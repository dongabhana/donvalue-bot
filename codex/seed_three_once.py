"""The owner's three-card profile exception; no authority for other posts or days."""
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ITEM_IDS = ('cx005-coupon-minimum','cx004-laptop-total','cx008-robot-prep')
DATE = '2026-09-12'
SOURCE = 'owner_explicit_chat_seed_three_2026_09_12'
CONFIG = json.loads((ROOT/'codex/seed-three.json').read_text())
if CONFIG['date'] != DATE or tuple(CONFIG['item_ids']) != ITEM_IDS or set(CONFIG['content_hashes']) != set(ITEM_IDS):
    raise RuntimeError('Unexpected seed exception configuration')
HASHES = CONFIG['content_hashes']


def content_hash(item):
    from codex.engine import canonical
    return hashlib.sha256(canonical({k:v for k,v in item.items() if k!='posted_early_on'})).hexdigest()


def authorized_now(item, record, now):
    return (item['id'] in ITEM_IDS and now.date().isoformat()==DATE
            and now < datetime.fromisoformat(DATE+'T23:59:00+09:00')
            and record.get('decision')=='approved' and record.get('approval_source')==SOURCE
            and record.get('seed_content_hash')==HASHES[item['id']]
            and content_hash(item)==HASHES[item['id']])


def last_instagram_time(engine):
    times=[]
    path=ROOT/'content/delivery.json'
    if path.exists():
        for operations in json.loads(path.read_text()).values():
            for key in ('instagram','instagram_reel'):
                operation=operations.get(key,{})
                if operation.get('status')=='done' and operation.get('at'):
                    times.append(datetime.fromisoformat(operation['at']))
    for record in engine.state['records'].values():
        operation=record.get('operations',{}).get('instagram',{})
        if operation.get('status')=='done' and operation.get('at'):
            times.append(datetime.fromisoformat(operation['at']))
    return max(times) if times else None


def mark_delivered(engine,item,record):
    from codex.engine import commit
    record['closed']=True
    engine.save()
    path=ROOT/'codex/content.json'
    data=json.loads(path.read_text())
    actual=next(i for i in data['items'] if i['id']==item['id'])
    if actual.get('posted_early_on')!=DATE:
        actual['posted_early_on']=DATE
        path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
        commit([path],'Mark profile seed card delivered; block its original scheduled slot')
    for platform,key in [('ig','instagram'),('th','threads')]:
        operation=record['operations'][key]
        try:
            result=engine.meta(platform,'GET',operation['id'],fields='id,permalink')
            if result.get('permalink'):
                record.setdefault('permalinks',{})[platform]=result['permalink']
                print('SEED_PUBLISHED_LINK: '+item['id']+' '+platform+' '+result['permalink'],flush=True)
        except RuntimeError:
            pass
    engine.save()


def main():
    from codex.engine import Engine, KST, fingerprint, commit
    from codex.media import render
    now=datetime.now(KST)
    if now.date().isoformat()!=DATE or now>=datetime.fromisoformat(DATE+'T23:59:00+09:00'):
        print('SEED_EXCEPTION_EXPIRED'); return
    engine=Engine()
    if engine.tg('getMe').get('username','').lower()!='donvalue_approval_bot':
        raise RuntimeError('Wrong approval bot')
    for item_id in ITEM_IDS:
        item=next(i for i in engine.items if i['id']==item_id)
        old=engine.state['records'].get(item_id,{})
        if old.get('closed'):
            print('SEED_ALREADY_COMPLETE: '+item_id,flush=True); continue
        if content_hash(item)!=HASHES[item_id] or item['format']!='carousel' or item.get('threads_media')!='carousel':
            raise RuntimeError('The specifically authorized cards changed')
        if old.get('decision') in ('held','edit_requested'):
            raise RuntimeError('An unresolved owner hold/edit blocks this version')
        if not old.get('operations'):
            latest=last_instagram_time(engine)
            if latest:
                remaining=max(0,40*60-(datetime.now(KST)-latest).total_seconds())
                print(f'SEED_NEXT: {item_id} in {remaining/60:.1f} minutes',flush=True)
                time.sleep(remaining)
            now=datetime.now(KST)
            if now.date().isoformat()!=DATE or now>=datetime.fromisoformat(DATE+'T23:59:00+09:00'):
                raise RuntimeError('Seed publication window expired')
            manifest=render(item,ROOT)
            commit([ROOT/'codex/assets'/item_id],'Render immutable owner-requested profile card '+item_id)
            from codex.engine import git
            record={'hash':fingerprint(item,manifest),'manifest':manifest,'asset_commit':git('rev-parse','HEAD'),
                    'review_kind':'owner_seed_three','decision':'approved','approval_source':SOURCE,
                    'seed_content_hash':HASHES[item_id],'approved_at':now.isoformat(),'operations':{}}
            engine.state['records'][item_id]=record
            engine.save()
            engine.tell('오늘 채팅 요청의 3편 예외 · '+item['topic']+'\nInstagram과 Threads 모두 6장 카드뉴스로 발행합니다. 이후 정기 예약의 승인은 유지해요.')
        else:
            record=old
            if record.get('review_kind')!='owner_seed_three' or not authorized_now(item,record,datetime.now(KST)):
                raise RuntimeError('An unrelated/ambiguous prior operation blocks automatic replacement')
        print('SEED_START: '+item_id,flush=True)
        engine.publish(item,record,datetime.now(KST))
        statuses={k:v['status'] for k,v in record.get('operations',{}).items()}
        print('SEED_DELIVERY: '+item_id+' '+json.dumps(statuses,sort_keys=True),flush=True)
        if not all(record.get('operations',{}).get(k,{}).get('status')=='done' for k in ('instagram','threads')):
            raise RuntimeError('Seed needs delivery review; automatic duplication is blocked')
        mark_delivered(engine,item,record)
        engine.tell('프로필 카드뉴스 발행 완료 · '+item['topic']+'\n'+'\n'.join(record.get('permalinks',{}).values()))
    print('SEED_THREE_COMPLETE',flush=True)


if __name__=='__main__': main()
