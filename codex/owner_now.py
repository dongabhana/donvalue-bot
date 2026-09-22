"""채팅에서 지용님이 직접 '지금 올려'라고 한 1편만 즉시 발행한다(2026-09-22).

텔레그램 승인을 대신하는 것은 이 편·이 날짜 하나뿐이다. 다른 편이나 다른 날에는
어떤 권한도 주지 않는다. 날짜가 지나면 아무것도 하지 않고 끝난다.
"""
import json
from datetime import datetime

ITEM_ID = 'cx103-taxi-transit'
APPROVAL_DATE = '2026-09-22'
EXPIRES_AT = '2026-09-22T23:59:00+09:00'
SOURCE = 'owner_explicit_chat_2026_09_22'


def authorized_now(item, record, now):
    return (item['id'] == ITEM_ID and record.get('decision') == 'approved'
            and record.get('review_kind') == 'owner_now'
            and record.get('approval_source') == SOURCE
            and now.date().isoformat() == APPROVAL_DATE
            and now < datetime.fromisoformat(EXPIRES_AT))


def main():
    from codex.engine import Engine, KST, ROOT, commit, fingerprint, git
    from codex.media import render
    engine = Engine()
    now = datetime.now(KST)
    if now.date().isoformat() != APPROVAL_DATE or now >= datetime.fromisoformat(EXPIRES_AT):
        print('OWNER_NOW_EXPIRED')
        return
    item = next(i for i in engine.items if i['id'] == ITEM_ID)
    rec = engine.state['records'].get(ITEM_ID, {})
    if rec.get('closed'):
        print('OWNER_NOW_ALREADY_COMPLETE')
        return
    if rec.get('review_kind') != 'owner_now':
        if rec.get('operations'):
            raise RuntimeError('This item already has publication attempts; review first')
        if not engine.price_check(item):
            raise RuntimeError('Official price check failed; not publishing')
        manifest = render(item, ROOT)
        commit([ROOT / 'codex/assets' / ITEM_ID], 'Render immutable Codex media ' + ITEM_ID)
        rec = {'hash': fingerprint(item, manifest), 'manifest': manifest,
               'asset_commit': git('rev-parse', 'HEAD'), 'review_kind': 'owner_now',
               'decision': 'approved', 'approval_source': SOURCE,
               'approved_at': now.isoformat(), 'operations': {}}
        engine.state['records'][ITEM_ID] = rec
        engine.save()
        engine.tell('채팅에서 요청하신 1회 즉시 발행을 시작해요.\n' + item['topic'])
    engine.publish(item, rec, now)
    ops = rec.get('operations', {})
    print('OWNER_NOW_DELIVERY: ' + json.dumps({k: v['status'] for k, v in ops.items()}, sort_keys=True))
    links = {}
    for platform, key in [('ig', 'instagram'), ('th', 'threads')]:
        op = ops.get(key, {})
        if op.get('status') == 'done':
            try:
                link = engine.meta(platform, 'GET', op['id'], fields='id,permalink').get('permalink', '')
            except RuntimeError:
                link = ''
            if link:
                links[platform] = link
                print('OWNER_NOW_LINK: ' + platform + ' ' + link)
    if all(ops.get(k, {}).get('status') == 'done' for k in ('instagram', 'threads')):
        rec['closed'] = True
        rec['permalinks'] = links
        engine.save()
        engine.tell('즉시 발행 확인 완료\n' + item['topic'] + '\n' + '\n'.join(links.values()))
    else:
        raise RuntimeError('Owner-now publication incomplete; see operations above')


if __name__ == '__main__':
    main()
