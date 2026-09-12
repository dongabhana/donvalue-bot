"""Owner-approved immutable previews, separate publishing and encrypted audit state."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import traceback
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from codex.media import render
from codex.official_prices import check_prices
from codex.reporting import collect_and_report
from tools.pair_telegram import cipher

ROOT = Path(__file__).resolve().parent.parent
KST = ZoneInfo('Asia/Seoul')
STATE = ROOT / 'codex/state.enc'


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


def fingerprint(item, manifest):
    return hashlib.sha256(canonical({'item': item, 'assets': manifest})).hexdigest()


def validate(item):
    assert re.fullmatch(r'cx[0-9]{3}-[a-z0-9-]+', item['id'])
    assert item['verified'] is True
    assert item['format'] in ('reel', 'carousel')
    due = datetime.fromisoformat(item['publish_at'])
    assert due.utcoffset() == timedelta(hours=9)
    assert due.weekday() in (0, 2, 5) and due.hour == 20 and due.minute == 0
    assert 2 <= len(item['slides']) <= 10
    assert len(item['caption']) <= 2200
    assert all(0 < len(t) <= 500 for t in [item['threads_text'], *item['threads_chain']])
    assert item['threads_text'].strip() != item['caption'].strip()
    if item.get('content_version') == 2:
        assert item['threads_chain'] == []
        assert item['category'] and item['series']
        tag = item['threads_tag']
        assert 1 <= len(tag) <= 50 and not any(c in tag for c in '.&')
        assert item['slides'][0]['title'] == item['hook']
        assert 1 <= float(item['slides'][0]['seconds']) <= 2
    if item.get('editorial_revision') == 'official-comparison-2026-09-12':
        verification=item['verification']
        assert verification['real_world_price_claim'] == bool(verification['sources'])
        assert item['slides'][0]['title'] == item['hook']
        assert verification['checked_at']
        if verification['real_world_price_claim']:
            assert all(s['url'].startswith('https://') and s['offers'] and s['required_tokens'] for s in verification['sources'])


def eligible(item, record, now):
    if record.get('closed'): return False
    if record.get('review_kind')=='owner_seed_three':
        from codex.seed_three_once import authorized_now
        return authorized_now(item,record,now)
    if record.get('review_kind')=='owner_chat_once':
        from codex.today_once import authorized_now
        return authorized_now(item,record,now)
    due = datetime.fromisoformat(item['publish_at'])
    return (record.get('decision') == 'approved' and record.get('review_kind') == 'real'
            and due <= now < due + timedelta(hours=2)
            and datetime.fromisoformat(record['approved_at']).date() == (due-timedelta(days=1)).date())


def regular_item(item, now):
    if item.get('posted_early_on'): return False
    from codex.seed_three_once import DATE, ITEM_IDS
    return not (now.date().isoformat()==DATE and item['id'] in ITEM_IDS)


def git(*args):
    result = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        print('CODEX_GIT_FAILED: '+args[0])
        raise RuntimeError('Git operation failed; no external action will follow')
    return result.stdout.strip()


def commit(paths, message):
    for path in paths:
        git('add', str(path))
    if git('diff', '--cached', '--name-only'):
        git('-c', 'user.name=donvalue-bot', '-c', 'user.email=bot@users.noreply.github.com', 'commit', '-m', message)
        push()


def push(tries=5):
    """Rebase concurrent changes; conflicting approval state must stop publishing."""
    for attempt in range(tries):
        try:
            git('push')
            return
        except RuntimeError:
            if attempt == tries - 1:
                raise
        git('fetch', 'origin', 'main')
        try:
            git('-c', 'user.name=donvalue-bot', '-c', 'user.email=bot@users.noreply.github.com',
                'rebase', 'origin/main')
        except RuntimeError:
            git('rebase', '--abort')
            raise RuntimeError('Concurrent changes conflict; publishing stopped') from None
        time.sleep(3 * (attempt + 1))


class MetaFailure(RuntimeError):
    def __init__(self, platform, method, stage, status, code, subcode):
        super().__init__('Meta rejected '+platform+' '+stage)
        self.failure={'platform':platform,'method':method,'stage':stage,'http':status,'code':code,'subcode':subcode}


class Engine:
    def __init__(self):
        self.token = os.environ['TELEGRAM_BOT_TOKEN']
        self.crypt = cipher(self.token)
        self.owner = json.loads(self.crypt.decrypt((ROOT/'content/telegram_owner.enc').read_bytes()))
        self.state = json.loads(self.crypt.decrypt(STATE.read_bytes())) if STATE.exists() else {'offset': 0, 'records': {}, 'comments': {}}
        self._saved_state = canonical(self.state) if STATE.exists() else None
        self.items = json.loads((ROOT/'codex/content.json').read_text())['items']
        for item in self.items:
            validate(item)
        if len({i['id'] for i in self.items}) != len(self.items):
            raise ValueError('Duplicate content ID')

    def save(self):
        payload = canonical(self.state)
        if payload == getattr(self, '_saved_state', None):
            return
        STATE.write_bytes(self.crypt.encrypt(payload))
        commit([STATE], 'Update encrypted Codex approval and delivery state')
        self._saved_state = payload

    def tg(self, method, files=None, **params):
        try:
            url='https://api.telegram.org/bot'+self.token+'/'+method
            for attempt in range(3):
                if method.startswith('send'):
                    gap=1.1-(time.monotonic()-getattr(self,'_last_tg_send',0))
                    if gap>0: time.sleep(gap)
                    self._last_tg_send=time.monotonic()
                if files:
                    for handle in files.values(): handle.seek(0)
                response = requests.post(url, data=params, files=files, timeout=60) if files else requests.post(url, json=params, timeout=40)
                result=response.json()
                if response.ok and result.get('ok'): return result['result']
                print('CODEX_TG_ERROR: '+method+' http='+str(response.status_code)+' code='+str(result.get('error_code')))
                if result.get('error_code')==429 and attempt<2:
                    delay=int(result.get('parameters',{}).get('retry_after',5))
                    if 0<delay<=60:
                        time.sleep(delay+1); continue
                raise RuntimeError()
        except Exception:
            print('CODEX_TG_FAILED_METHOD: '+method)
            raise RuntimeError('Telegram '+method+' failed; sensitive details suppressed') from None

    def tell(self, text, **kwargs):
        return self.tg('sendMessage', chat_id=self.owner['chat_id'], text=text, **kwargs)

    def upload(self, path, video=False):
        kind='video' if video else 'photo'
        with (ROOT/path).open('rb') as f:
            return self.tg('sendVideo' if video else 'sendPhoto', files={kind:f}, chat_id=str(self.owner['chat_id']))

    def price_check(self, item):
        if item.get('editorial_revision') != 'official-comparison-2026-09-12': return True
        key=item['id']
        if key in getattr(self, '_price_checks', {}): return self._price_checks[key]
        self._price_checks=getattr(self, '_price_checks', {})
        try:
            check_prices(item)
            self._price_checks[key]=True
            return True
        except RuntimeError:
            self._price_checks[key]=False
            alerts=self.state.setdefault('price_alerts', {})
            if alerts.get(key)!=item['evidence']:
                self.tell(item['topic']+'\n공식 가격이 변경됐거나 현재 페이지에서 확인되지 않아 미리보기·자동 발행을 멈췄어요. 공식 상품·요금과 조건을 재확인하고 수정 원고로 다시 승인해야 합니다.')
                alerts[key]=item['evidence']; self.save()
            return False

    def preview(self, item, real=False):
        # Telegram is for actual previous-day approvals only.
        if not real: return
        if not self.price_check(item): return
        manifest=render(item,ROOT)
        digest=fingerprint(item,manifest)
        key=item['id']
        old=self.state['records'].get(key,{})
        kind='real' if real else 'test'
        # A code push must never replace an existing real approval with a test.
        if not real and old.get('review_kind') == 'real':
            return
        if old.get('hash') == digest and old.get('review_kind') == kind and old.get('message_id'):
            return
        if old.get('operations'):
            raise RuntimeError('Published/in-flight content cannot be silently replaced')
        commit([ROOT/'codex/assets'/key], 'Render immutable Codex media '+key)
        rec={'hash':digest,'manifest':manifest,'asset_commit':git('rev-parse','HEAD'),'review_kind':kind,'decision':'pending','operations':{}}
        self.state['records'][key]=rec; self.save()
        music=('직접 합성한 '+('112' if item.get('music')=='original-playful-112bpm' else '88')+' BPM 리듬, 외부 샘플 없음') if 'video' in manifest else '정지 이미지 캐러셀 · 음원 없음'
        self.tell(('내일 게시 최종 승인 요청' if real else '사전 미리보기 · 테스트 버튼은 SNS에 게시하지 않습니다')+
                  '\n주제: '+item['topic']+'\n예정: '+item['publish_at']+'\nInstagram '+item['format']+' / Threads 별도 글\n음원: '+music)
        for path in manifest['cards']:
            self.upload(path)
        if 'video' in manifest:
            self.upload(manifest['video'],True)
        for label, body in [('Instagram 캡션',item['caption']),('Instagram 첫 댓글',item['first_comment']),('Threads 본문',item['threads_text']), *[(f'Threads 후속 답글 {i+1}',t) for i,t in enumerate(item['threads_chain'])], ('계산 근거',item['evidence'])]:
            self.tell(label+'\n\n'+body)
        buttons=[{'text':'예약 승인' if real else '미리보기 테스트 확인','callback_data':f'a|{key}|{digest[:12]}'},
                 {'text':'수정 요청','callback_data':f'e|{key}|{digest[:12]}'},
                 {'text':'보류','callback_data':f'h|{key}|{digest[:12]}'}]
        msg=self.tell('위 이미지·음원·본문·댓글 전체에 대한 선택입니다.\n버튼은 약 15분 간격으로 처리되며 GitHub 실행 지연이 있을 수 있어요.\n수정 요청을 누르고 이 방에 변경 내용을 보내주세요.',reply_markup={'inline_keyboard':[[b] for b in buttons]})
        rec['message_id']=msg['message_id']; self.save()

    def callbacks(self):
        updates=self.tg('getUpdates',offset=self.state['offset'],timeout=0,limit=100,allowed_updates=['message','callback_query'])
        for update in updates:
            cb=update.get('callback_query')
            if cb:
                msg=cb.get('message',{})
                if cb.get('from',{}).get('id')==self.owner['user_id'] and msg.get('chat',{}).get('id')==self.owner['chat_id']:
                    parts=cb.get('data','').split('|')
                    if len(parts)==3:
                        action,key,short=parts
                        rec=self.state['records'].get(key,{})
                        item=next((i for i in self.items if i['id']==key),None)
                        valid=(item and rec.get('message_id')==msg.get('message_id') and rec.get('hash','')[:12]==short
                               and fingerprint(item,rec['manifest'])==rec['hash'] and not rec.get('operations'))
                        if valid and rec.get('review_kind') == 'real' and action in ('a','e','h'):
                            now=datetime.now(KST); due=datetime.fromisoformat(item['publish_at'])
                            if action=='a' and rec['review_kind']=='real' and now.date()!=(due-timedelta(days=1)).date():
                                self.tell('승인은 게시 전날만 가능해요. 이 예약은 승인되지 않았습니다.')
                            else:
                                rec['decision']={'a':'approved' if rec['review_kind']=='real' else 'test_confirmed','e':'edit_requested','h':'held'}[action]
                                if action=='a': rec['approved_at']=now.isoformat()
                                self.state['offset']=update['update_id']+1; self.save()
                                text={'a':'예약 승인 저장 완료' if rec['review_kind']=='real' else '테스트 확인 완료. SNS 게시 승인은 아닙니다.', 'e':'수정 요청을 저장했어. 변경할 내용을 이 대화방에 보내줘. 수정본은 다시 승인받을게.', 'h':'보류했어. 이 상태에서는 게시하지 않아.'}[action]
                                self.tell(text)
                        elif parts[0] in ('r','x'):
                            self.reply_callback(parts,msg)
                        elif action in ('a','e','h') and rec.get('review_kind') == 'real':
                            self.tell('이 미리보기는 수정되었거나 더 이상 유효하지 않아. 가장 최근에 받은 콘텐츠 아래 버튼을 사용해줘.')
                    try: self.tg('answerCallbackQuery',callback_query_id=cb['id'])
                    except RuntimeError: pass  # Old callbacks can no longer be acknowledged.
            message=update.get('message',{})
            if (message.get('chat',{}).get('id')==self.owner['chat_id'] and message.get('from',{}).get('id')==self.owner['user_id'] and message.get('text')):
                text=message['text']
                if text=='/status':
                    self.tell('Codex 상태\n'+'\n'.join(k+': '+r['decision'] for k,r in self.state['records'].items()))
                elif not text.startswith('/') and not text.startswith('돈값하나 연결'):
                    self.state.setdefault('feedback',[]).append({'at':message['date'],'text':text[:4000]})
                    self.state['feedback']=self.state['feedback'][-30:]
                    # Feedback pauses all unposted content until a revised preview is approved.
                    for rec in self.state['records'].values():
                        if not rec.get('operations'): rec['decision']='edit_requested'
                    self.tell('수정 의견을 기록했어. 미게시 콘텐츠는 보류했으며 수정본을 다시 승인받아야 게시돼요.')
            self.state['offset']=update['update_id']+1
        if updates: self.save()

    def meta(self, platform, method, endpoint, **params):
        token=os.environ.get('IG_ACCESS_TOKEN' if platform=='ig' else 'TH_ACCESS_TOKEN')
        if not token: raise RuntimeError('Missing platform token')
        base='https://graph.instagram.com' if platform=='ig' else 'https://graph.threads.net/v1.0'
        try:
            response=requests.request(method,base+'/'+endpoint,params={**params,'access_token':token} if method=='GET' else None,
                                      data={**params,'access_token':token} if method=='POST' else None,timeout=60)
            data=response.json()
            if not response.ok or 'error' in data:
                error=data.get('error',{})
                print('CODEX_META_ERROR: '+platform+' http='+str(response.status_code)+' code='+str(error.get('code'))+' subcode='+str(error.get('error_subcode')))
                detail=' '.join(str(error.get(k,'')) for k in ('message','error_user_title','error_user_msg'))
                for name in ('IG_ACCESS_TOKEN','TH_ACCESS_TOKEN','TELEGRAM_BOT_TOKEN','IG_USER_ID','TH_USER_ID'):
                    value=os.environ.get(name,'')
                    if len(value)>4: detail=detail.replace(value,'[redacted]')
                detail=re.sub(r'https?://\S+','[url]',detail)
                detail=re.sub(r'[A-Za-z0-9_\-]{40,}','[redacted]',detail)
                detail=re.sub(r'\b\d{8,}\b','[id]',detail)
                print('CODEX_META_REASON: '+platform+' '+detail[:350])
                stage=('publish' if endpoint.endswith('threads_publish') else 'parent_create' if params.get('media_type')=='CAROUSEL' else 'child_create' if params.get('is_carousel_item') else 'other')
                print('CODEX_META_STAGE: '+stage,flush=True)
                raise MetaFailure(platform,method,stage,response.status_code,error.get('code'),error.get('error_subcode'))
            return data
        except MetaFailure:
            raise
        except Exception:
            raise RuntimeError('Meta request failed; platform='+platform) from None

    def wait_ready(self, platform, cid):
        for _ in range(40):
            field='status_code' if platform=='ig' else 'status'
            result=self.meta(platform,'GET',cid,fields=field)
            if result.get(field)=='FINISHED': return
            if result.get(field) in ('ERROR','EXPIRED'): raise RuntimeError('Media processing rejected')
            time.sleep(5)
        raise RuntimeError('Media processing timeout')

    def account_check(self, platform):
        user=os.environ['IG_USER_ID' if platform=='ig' else 'TH_USER_ID']
        info=self.meta(platform,'GET',user,fields='id,username')
        if info.get('username','').lower()!='dongabhana':
            print('CODEX_ACCOUNT_MISMATCH: '+platform+' username='+str(info.get('username','missing')))
            raise RuntimeError('Unexpected publishing account')
        return user

    def preflight(self):
        """Read-only checks, including existing media; never creates a post."""
        report={}
        for platform in ('ig','th'):
            checks={}
            try:
                user=self.account_check(platform); checks['account']='ok'
                feed=self.meta(platform,'GET',user+('/media' if platform=='ig' else '/threads'),fields='id',limit=1).get('data',[])
                checks['media_read']='ok'
                if feed:
                    mid=feed[0]['id']
                    for label,endpoint,args in [('comments_read',mid+('/comments' if platform=='ig' else '/replies'),{'fields':'id','limit':1}),('insights_read',mid+'/insights',{'metric':'views'})]:
                        try: self.meta(platform,'GET',endpoint,**args); checks[label]='ok'
                        except RuntimeError: checks[label]='unavailable'
                else: checks['existing_post_checks']='no_media'
            except (RuntimeError,KeyError): checks['account_or_media']='unavailable'
            report[platform]=checks
        if report!=self.state.get('preflight'):
            self.state['preflight']=report; self.save()
            labels={'account':'계정 확인','media_read':'게시물 조회','comments_read':'댓글 조회','insights_read':'조회수 조회','existing_post_checks':'기존 게시물 검사','account_or_media':'계정 또는 게시물 조회'}
            status={'ok':'성공','unavailable':'확인 실패','no_media':'검사할 게시물 없음'}
            self.tell('게시 없는 연결 점검\n'+'\n'.join(p+': '+', '.join(labels[k]+' '+status[v] for k,v in checks.items()) for p,checks in report.items())+'\n실제 쓰기 권한은 승인 게시가 성공해야 검증됩니다.')
        print('CODEX_CONNECTION_CHECK: '+json.dumps(report,sort_keys=True))

    def operation(self, rec, key, action):
        op=rec.setdefault('operations',{}).get(key)
        if op:
            if op['status']=='done': return op['id']
            raise RuntimeError('Ambiguous prior operation requires review: '+key)
        rec['operations'][key]={'status':'in_flight'}; self.save()
        try:
            result=action()
        except Exception as error:
            rec['operations'][key]={'status':'needs_review'}
            if isinstance(error,MetaFailure): rec['operations'][key]['failure']=error.failure
            self.save()
            self.tell('게시 단계 '+key+'의 성공 여부를 확정하지 못했어. 중복 게시를 막기 위해 자동 재시도를 멈췄어.')
            raise RuntimeError('Operation stopped safely') from None
        rec['operations'][key]={'status':'done','id':str(result),'at':datetime.now(KST).isoformat()}; self.save()
        return str(result)

    def prepare_thread(self, text, parent=None, topic_tag=None, image_urls=None):
        user=self.account_check('th')
        args={'media_type':'TEXT','text':text}
        if parent: args['reply_to_id']=parent
        if topic_tag: args['topic_tag']=topic_tag
        if image_urls:
            if not 2 <= len(image_urls) <= 20: raise ValueError('Threads carousel needs 2..20 images')
            children=[]
            for image_url in image_urls:
                child=self.meta('th','POST',user+'/threads',media_type='IMAGE',image_url=image_url,is_carousel_item='true')['id']
                children.append(child)
            if len(set(children)) != len(children): raise RuntimeError('Duplicate Threads child containers')
            for child in children: self.wait_ready('th',child)
            args.update(media_type='CAROUSEL',children=','.join(children))
        cid=self.meta('th','POST',user+'/threads',**args)['id']
        # Allow the freshly created parent to become visible before checking
        # readiness and making the single publish call; never retry a write.
        time.sleep(20)
        self.wait_ready('th',cid)
        return cid

    def thread(self, text, parent=None, topic_tag=None, image_urls=None):
        cid=self.prepare_thread(text,parent,topic_tag,image_urls)
        user=self.account_check('th')
        return self.meta('th','POST',user+'/threads_publish',creation_id=cid)['id']

    def publish(self,item,rec,now):
        if not eligible(item,rec,now): return
        if not self.price_check(item): return
        manifest=rec['manifest']
        if fingerprint(item,manifest)!=rec['hash']: raise RuntimeError('Content changed after approval')
        for path,sha in manifest['sha256'].items():
            if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=sha: raise RuntimeError('Media changed after approval')
        repo=os.environ['GITHUB_REPOSITORY']; commit_sha=rec['asset_commit']
        def url(path): return f'https://raw.githubusercontent.com/{repo}/{commit_sha}/{path}'
        def instagram():
            user=self.account_check('ig')
            if item['format']=='reel':
                cid=self.meta('ig','POST',user+'/media',media_type='REELS',video_url=url(manifest['video']),caption=item['caption'])['id']
            else:
                children=[]
                for p in manifest['cards']:
                    child=self.meta('ig','POST',user+'/media',image_url=url(p),is_carousel_item='true')['id']
                    self.wait_ready('ig',child); children.append(child)
                cid=self.meta('ig','POST',user+'/media',media_type='CAROUSEL',children=','.join(children),caption=item['caption'])['id']
            self.wait_ready('ig',cid)
            return self.meta('ig','POST',user+'/media_publish',creation_id=cid)['id']
        failures=[]
        for key,action in [('instagram',instagram),('threads',lambda:self.thread(item['threads_text'], topic_tag=item.get('threads_tag'),
                              image_urls=[url(p) for p in manifest['cards']] if item.get('threads_media')=='carousel' else None))]:
            try: self.operation(rec,key,action)
            except RuntimeError: failures.append(key)
        if rec['operations'].get('instagram',{}).get('status')=='done' and item['first_comment']:
            mid=rec['operations']['instagram']['id']
            try: self.operation(rec,'ig_first_comment',lambda:self.meta('ig','POST',mid+'/comments',message=item['first_comment'])['id'])
            except RuntimeError: failures.append('ig_first_comment')
        if rec['operations'].get('threads',{}).get('status')=='done':
            parent=rec['operations']['threads']['id']
            for i,text in enumerate(item['threads_chain']):
                try: parent=self.operation(rec,'th_reply_'+str(i),lambda t=text,p=parent:self.thread(t,p))
                except RuntimeError: failures.append('th_reply_'+str(i)); break
        if not rec.get('reported'):
            self.tell(item['topic']+' 게시 결과\n'+'\n'.join(k+': '+v['status'] for k,v in rec['operations'].items()))
            rec['reported']=True; self.save()

    def reply_callback(self,parts,msg):
        action,key,short=parts; rec=self.state['comments'].get(key)
        if not rec or rec.get('message_id')!=msg.get('message_id') or rec['hash'][:12]!=short or rec.get('operations'): return
        if action=='x': rec['decision']='held'; self.save(); return
        if rec.get('decision')=='held': return
        p=rec['platform']; cid=rec['comment_id']; text=rec['reply']
        self.operation(rec,'reply',lambda:self.meta('ig','POST',cid+'/replies',message=text)['id'] if p=='ig' else self.thread(text,cid))
        self.tell('승인한 방문자 답글을 게시했어.')

    def observations(self):
        now=datetime.now(KST)
        if self.state.get('observed_at') and (now-datetime.fromisoformat(self.state['observed_at'])).total_seconds()<3600: return
        self.state['observed_at']=now.isoformat()
        for item in self.items:
            rec=self.state['records'].get(item['id'],{})
            for platform,key in [('ig','instagram'),('th','threads')]:
                op=rec.get('operations',{}).get(key,{})
                if op.get('status')!='done': continue
                if (now-datetime.fromisoformat(op['at'])).days>7: continue
                try:
                    endpoint=op['id']+('/comments' if platform=='ig' else '/replies')
                    fields='id,text,username'
                    comments=self.meta(platform,'GET',endpoint,fields=fields,limit=50).get('data',[])
                    for c in comments:
                        if c.get('username','').lower()=='dongabhana': continue
                        identity=hashlib.sha256((platform+str(c['id'])).encode()).hexdigest()[:16]
                        if identity in self.state['comments']: continue
                        text=c.get('text','')[:2000]
                        matches=[f['reply'] for f in item.get('faq',[]) if any(w in text for w in f['keywords'])]
                        reply=matches[0] if len(matches)==1 else ''
                        cr={'platform':platform,'comment_id':str(c['id']),'text':text,'reply':reply,'decision':'pending'}
                        cr['hash']=hashlib.sha256(canonical(cr)).hexdigest()
                        self.state['comments'][identity]=cr
                        if not reply:
                            self.tell('새 방문자 댓글 · 자동 답변 후보 없음\n'+text+'\n\n내용 판단이 필요해서 자동 게시하지 않았어.')
                        else:
                            buttons=[[{'text':'이 답글 게시 승인','callback_data':f'r|{identity}|{cr["hash"][:12]}'},{'text':'보류','callback_data':f'x|{identity}|{cr["hash"][:12]}'}]]
                            message=self.tell('방문자 댓글\n'+text+'\n\n답글 초안\n'+reply,reply_markup={'inline_keyboard':buttons})
                            cr['message_id']=message['message_id']
                        self.save()
                except RuntimeError:
                    tag=platform+'_comments_unavailable'
                    if tag not in self.state:
                        self.state[tag]=True; self.tell(platform+' 댓글 조회가 실패했어. 댓글 읽기 권한 확인이 필요해.'); self.save()
                metrics=['views','reach','likes','comments','saved','shares'] if platform=='ig' else ['views','likes','replies','reposts','quotes']
                snapshot={'at':now.isoformat(),'metrics':{},'unavailable':[]}
                for metric in metrics:
                    try: snapshot['metrics'][metric]=self.meta(platform,'GET',op['id']+'/insights',metric=metric).get('data',[])
                    except RuntimeError: snapshot['unavailable'].append(metric)
                rec.setdefault('insights',{})[platform]=snapshot
        collect_and_report(self,ROOT,now)
        self.save()

    def run(self,mode):
        if self.tg('getMe').get('username','').lower()!='donvalue_approval_bot': raise RuntimeError('Wrong bot')
        if self.tg('getWebhookInfo').get('url'): raise RuntimeError('Existing webhook left unchanged')
        current_ids={i['id'] for i in self.items}
        retired=False
        for key,record in self.state['records'].items():
            if key not in current_ids and not record.get('operations') and record.get('decision')!='superseded':
                record['decision']='superseded'; retired=True
        if retired: self.save()
        self.callbacks()
        print('CODEX_REVIEW_COUNTS: '+json.dumps(dict(Counter(r.get('decision','pending') for r in self.state['records'].values())),sort_keys=True))
        now=datetime.now(KST)
        if mode=='preview':
            self.preflight()
            pending=sorted([i for i in self.items if datetime.fromisoformat(i['publish_at'])>now and regular_item(i,now)
                            and not self.state['records'].get(i['id'],{}).get('operations')],key=lambda i:i['publish_at'])
            if pending:
                item=pending[0]
                due=datetime.fromisoformat(item['publish_at'])
                real=now.date()==(due-timedelta(days=1)).date() and now.hour>=20
                self.preview(item,real=real)
            self.observations()
            return
        for item in self.items:
            if not regular_item(item,now): continue
            due=datetime.fromisoformat(item['publish_at'])
            if now.date()==(due-timedelta(days=1)).date() and now.hour>=20 and not self.state['records'].get(item['id'],{}).get('operations'):
                self.preview(item,real=True)
            rec=self.state['records'].get(item['id'])
            if rec: self.publish(item,rec,now)
        self.observations()


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('mode',choices=['preview','tick']); args=parser.parse_args()
    try: Engine().run(args.mode)
    except Exception as e:
        frame=traceback.extract_tb(e.__traceback__)[-1]
        print('CODEX_ERROR_LOCATION: '+Path(frame.filename).name+':'+str(frame.lineno)+' '+frame.name)
        print('CODEX_STOPPED: '+type(e).__name__+'; inspect encrypted state, no sensitive values logged')
        raise SystemExit(1)
    print('CODEX_OK: '+args.mode)


if __name__=='__main__': main()
