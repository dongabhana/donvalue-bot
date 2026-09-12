"""Owner-approved immutable previews, separate publishing and encrypted audit state."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from codex.media import render
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


def eligible(item, record, now):
    due = datetime.fromisoformat(item['publish_at'])
    return (record.get('decision') == 'approved' and record.get('review_kind') == 'real'
            and due <= now < due + timedelta(hours=2)
            and datetime.fromisoformat(record['approved_at']).date() == (due-timedelta(days=1)).date())


def git(*args):
    result = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Git operation failed; no external action will follow')
    return result.stdout.strip()


def commit(paths, message):
    for path in paths:
        git('add', str(path))
    if git('diff', '--cached', '--name-only'):
        git('-c', 'user.name=donvalue-bot', '-c', 'user.email=bot@users.noreply.github.com', 'commit', '-m', message)
        git('push')


class Engine:
    def __init__(self):
        self.token = os.environ['TELEGRAM_BOT_TOKEN']
        self.crypt = cipher(self.token)
        self.owner = json.loads(self.crypt.decrypt((ROOT/'content/telegram_owner.enc').read_bytes()))
        self.state = json.loads(self.crypt.decrypt(STATE.read_bytes())) if STATE.exists() else {'offset': 0, 'records': {}, 'comments': {}}
        self.items = json.loads((ROOT/'codex/content.json').read_text())['items']
        for item in self.items:
            validate(item)
        if len({i['id'] for i in self.items}) != len(self.items):
            raise ValueError('Duplicate content ID')

    def save(self):
        STATE.write_bytes(self.crypt.encrypt(canonical(self.state)))
        commit([STATE], 'Update encrypted Codex approval and delivery state')

    def tg(self, method, files=None, **params):
        try:
            url='https://api.telegram.org/bot'+self.token+'/'+method
            response = requests.post(url, data=params, files=files, timeout=60) if files else requests.post(url, json=params, timeout=40)
            result=response.json()
            if not response.ok or not result.get('ok'):
                raise RuntimeError()
            return result['result']
        except Exception:
            raise RuntimeError('Telegram '+method+' failed; sensitive details suppressed') from None

    def tell(self, text, **kwargs):
        return self.tg('sendMessage', chat_id=self.owner['chat_id'], text=text, **kwargs)

    def upload(self, path, video=False):
        kind='video' if video else 'photo'
        with (ROOT/path).open('rb') as f:
            return self.tg('sendVideo' if video else 'sendPhoto', files={kind:f}, chat_id=str(self.owner['chat_id']))

    def preview(self, item, real=False):
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
        self.tell(('내일 게시 최종 승인 요청' if real else '사전 미리보기 · 테스트 버튼은 SNS에 게시하지 않습니다')+
                  '\n주제: '+item['topic']+'\n예정: '+item['publish_at']+'\nInstagram '+item['format']+' / Threads 별도 글\n음원: 직접 합성한 88 BPM 리듬, 외부 샘플 없음')
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
                        if valid and action in ('a','e','h'):
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
            if not response.ok or 'error' in data: raise RuntimeError()
            return data
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

    def operation(self, rec, key, action):
        op=rec.setdefault('operations',{}).get(key)
        if op:
            if op['status']=='done': return op['id']
            raise RuntimeError('Ambiguous prior operation requires review: '+key)
        rec['operations'][key]={'status':'in_flight'}; self.save()
        try:
            result=action()
        except Exception:
            rec['operations'][key]={'status':'needs_review'}; self.save()
            self.tell('게시 단계 '+key+'의 성공 여부를 확정하지 못했어. 중복 게시를 막기 위해 자동 재시도를 멈췄어.')
            raise RuntimeError('Operation stopped safely') from None
        rec['operations'][key]={'status':'done','id':str(result),'at':datetime.now(KST).isoformat()}; self.save()
        return str(result)

    def thread(self, text, parent=None):
        user=self.account_check('th')
        args={'media_type':'TEXT','text':text}
        if parent: args['reply_to_id']=parent
        cid=self.meta('th','POST',user+'/threads',**args)['id']
        self.wait_ready('th',cid)
        return self.meta('th','POST',user+'/threads_publish',creation_id=cid)['id']

    def publish(self,item,rec,now):
        if not eligible(item,rec,now): return
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
        for key,action in [('instagram',instagram),('threads',lambda:self.thread(item['threads_text']))]:
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
        self.save()

    def run(self,mode):
        if self.tg('getMe').get('username','').lower()!='donvalue_approval_bot': raise RuntimeError('Wrong bot')
        if self.tg('getWebhookInfo').get('url'): raise RuntimeError('Existing webhook left unchanged')
        self.callbacks()
        now=datetime.now(KST)
        if mode=='preview':
            self.preflight()
            pending=[i for i in self.items if datetime.fromisoformat(i['publish_at'])>now]
            if pending:
                item=pending[0]
                due=datetime.fromisoformat(item['publish_at'])
                real=now.date()==(due-timedelta(days=1)).date() and now.hour>=20
                self.preview(item,real=real)
            return
        for item in self.items:
            due=datetime.fromisoformat(item['publish_at'])
            if now.date()==(due-timedelta(days=1)).date() and now.hour>=20:
                self.preview(item,real=True)
            rec=self.state['records'].get(item['id'])
            if rec: self.publish(item,rec,now)
        self.observations()


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('mode',choices=['preview','tick']); args=parser.parse_args()
    try: Engine().run(args.mode)
    except Exception as e:
        print('CODEX_STOPPED: '+type(e).__name__+'; inspect encrypted state, no sensitive values logged')
        raise SystemExit(1)
    print('CODEX_OK: '+args.mode)


if __name__=='__main__': main()
