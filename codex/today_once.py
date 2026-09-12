"""One specific exception explicitly requested by the owner in the active chat.

This is not a Telegram approval and cannot authorize any other content/day.
"""
import json
from datetime import datetime

ITEM_ID='cx001-free-shipping'
APPROVED_HASH='e5c025fad781643bead00095272dddab31239b029c8d9c0151601c17d96bbddd'
APPROVAL_DATE='2026-09-12'
EXPIRES_AT='2026-09-12T19:00:00+09:00'


def authorized_now(item,record,now):
    return (item['id']==ITEM_ID and record.get('hash')==APPROVED_HASH
            and record.get('decision')=='approved'
            and record.get('approval_source')=='owner_explicit_chat_exception_2026_09_12'
            and now.date().isoformat()==APPROVAL_DATE
            and now<datetime.fromisoformat(EXPIRES_AT))


def main():
    from codex.engine import Engine,KST,ROOT,fingerprint,commit
    engine=Engine(); now=datetime.now(KST)
    if now.date().isoformat()!=APPROVAL_DATE or now>=datetime.fromisoformat(EXPIRES_AT):
        print('TODAY_EXCEPTION_EXPIRED'); return
    item=next(i for i in engine.items if i['id']==ITEM_ID)
    record=engine.state['records'][ITEM_ID]
    if record.get('closed'):
        print('TODAY_EXCEPTION_ALREADY_COMPLETE'); return
    if fingerprint(item,record['manifest'])!=APPROVED_HASH or record.get('hash')!=APPROVED_HASH:
        raise RuntimeError('The reviewed content has changed')
    if engine.tg('getMe').get('username','').lower()!='donvalue_approval_bot': raise RuntimeError('Wrong approval bot')
    engine.callbacks()
    if record.get('decision') in ('held','edit_requested'):
        raise RuntimeError('A Telegram hold or edit request needs resolution')
    if not record.get('operations'):
        record.update({'decision':'approved','review_kind':'owner_chat_once',
                       'approval_source':'owner_explicit_chat_exception_2026_09_12',
                       'approved_at':now.isoformat(),'exception_expires_at':EXPIRES_AT})
        engine.save()
        engine.tell('오늘 채팅에서 요청한 1회 예외를 기록했어. 무료배송 콘텐츠 1편을 인스타 릴스와 별도 Threads 글로 게시합니다. 다음 콘텐츠는 전날 승인 규칙을 유지해요.')
    engine.publish(item,record,now)
    operations=record.get('operations',{})
    print('TODAY_DELIVERY: '+json.dumps({k:v['status'] for k,v in operations.items()},sort_keys=True))
    expected=['instagram','threads','ig_first_comment','th_reply_0','th_reply_1']
    for platform,key in [('ig','instagram'),('th','threads')]:
        op=operations.get(key,{})
        if op.get('status')=='done':
            try:
                result=engine.meta(platform,'GET',op['id'],fields='id,permalink')
                link=result.get('permalink','')
                if link:
                    record.setdefault('permalinks',{})[platform]=link
                    print('TODAY_PUBLISHED_LINK: '+platform+' '+link)
            except RuntimeError: pass
    if all(operations.get(key,{}).get('status')=='done' for key in expected):
        record['closed']=True; engine.save()
        path=ROOT/'codex/content.json'; data=json.loads(path.read_text())
        next(i for i in data['items'] if i['id']==ITEM_ID)['posted_early_on']=APPROVAL_DATE
        path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
        commit([path],'Mark today exception as delivered; original Monday slot needs new content')
        engine.tell('오늘 예외 게시 완료: 인스타 릴스, Threads 본문, 첫 댓글과 후속 답글.\n'+'\n'.join(record.get('permalinks',{}).values()))
    else:
        engine.save()
        raise RuntimeError('Some delivery stages need review; automatic duplication is blocked')


if __name__=='__main__': main()
