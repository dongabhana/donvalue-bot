"""Audit and explicitly authorized recovery of missing publications."""
import json
import argparse
import copy
from datetime import datetime

from codex.engine import Engine, ROOT, KST


def feed(engine, platform):
    user = engine.account_check(platform)
    endpoint = user + ('/media' if platform == 'ig' else '/threads')
    fields = 'id,caption,permalink,timestamp' if platform == 'ig' else 'id,text,permalink,timestamp'
    posts = []
    after = None
    for _ in range(20):
        params = {'fields': fields, 'limit': 100}
        if after:
            params['after'] = after
        result = engine.meta(platform, 'GET', endpoint, **params)
        posts.extend(result.get('data', []))
        if not result.get('paging', {}).get('next'):
            return posts
        after = result.get('paging', {}).get('cursors', {}).get('after')
        if not after:
            raise RuntimeError('Incomplete account feed; cannot establish duplicates')
    raise RuntimeError('Account feed exceeds audit limit')


def main():
    engine = Engine()
    now = datetime.now(KST)
    for platform in ('ig', 'th'):
        try:
            posts = feed(engine, platform)
            print('LIVE_FEED: ' + json.dumps({'platform': platform, 'count': len(posts),
                'posts': [{'id': p['id'], 'link': p.get('permalink'), 'at': p.get('timestamp'),
                           'text': p.get('caption', p.get('text', ''))[:160]} for p in posts]}, ensure_ascii=False))
        except RuntimeError:
            print('LIVE_FEED_UNAVAILABLE: ' + platform)
    for item in engine.items:
        if datetime.fromisoformat(item['publish_at']) > now:
            continue
        rec = engine.state['records'].get(item['id'], {})
        print('GPT_AUDIT: ' + json.dumps({'id': item['id'], 'title': item['topic'],
            'due': item['publish_at'], 'early': item.get('posted_early_on'),
            'decision': rec.get('decision'), 'closed': rec.get('closed'),
            'hash': rec.get('hash'), 'manifest': rec.get('manifest'),
            'operations': rec.get('operations', {}), 'links': rec.get('permalinks', {})}, ensure_ascii=False))
    import yaml
    queue = yaml.safe_load((ROOT / 'content/queue.yaml').read_text())
    posted = json.loads((ROOT / 'content/posted.json').read_text())
    delivered = json.loads((ROOT / 'content/delivery.json').read_text())
    approvals = json.loads((ROOT / 'content/approval.json').read_text())
    for item in queue['items']:
        records = [p for p in posted if p['id'] == item['id']]
        prepared = (ROOT / 'images' / item['id']).exists()
        if records or prepared or item['id'] in approvals:
            print('CLAUDE_AUDIT: ' + json.dumps({'id': item['id'], 'title': item['product'],
                'prepared': prepared, 'records': records, 'delivery': delivered.get(item['id'], {}),
                'approval': approvals.get(item['id'])}, ensure_ascii=False))


def reconcile_taxi(engine):
    """Adopt the replacement posts observed in the full live feed; never repost."""
    from codex.approvals import verify_posts
    rec = engine.state['records']['cx054-taxi-vs-driver']
    ids = {'instagram': '18115441163097434', 'threads': '18174467671445822'}
    links = verify_posts(engine, ids['instagram'], ids['threads'])
    for platform, key, field in [('ig', 'instagram', 'caption'), ('th', 'threads', 'text')]:
        post = engine.meta(platform, 'GET', ids[key], fields='id,' + field + ',timestamp')
        if not all(token in post.get(field, '') for token in ('택시', '대리', '500')):
            raise RuntimeError('Replacement taxi post identity did not match')
        if rec['operations'][key]['id'] != ids[key]:
            rec.setdefault('reconciled_history', []).append({
                'key': key, 'old': copy.deepcopy(rec['operations'][key]),
                'reason': 'Replacement post confirmed in live account feed on 2026-09-19'})
            rec['operations'][key] = {'id': ids[key], 'status': 'done',
                'at': datetime.fromisoformat(post['timestamp']).astimezone(KST).isoformat()}
    rec['permalinks'] = links
    rec['closed'] = True
    engine.save()
    print('TAXI_RECONCILED_WITHOUT_REPOST', flush=True)


def publish_recovery():
    from codex.approvals import digest, verify_posts
    from codex.engine import fingerprint, commit, git
    from codex.media import render
    engine = Engine()
    now = datetime.now(KST)
    plan = json.loads((ROOT / 'codex/recovery_20260919_plan.json').read_text())
    if plan['authorization'] != 'owner_chat_2026-09-19_publish_missing' or now >= datetime.fromisoformat(plan['expires_at']):
        raise RuntimeError('The explicit backlog authorization has expired')
    posts = {p: feed(engine, p) for p in ('ig', 'th')}
    reconcile_taxi(engine)
    for entry in plan['items']:
        item = next(i for i in engine.items if i['id'] == entry['id'])
        if (digest(item) != entry['source_hash'] or
                datetime.fromisoformat(item['publish_at']) > datetime.fromisoformat(plan['cutoff'])):
            raise RuntimeError('Backlog content or scheduled date changed')
        rec = engine.state['records'].get(item['id'], {})
        if rec.get('closed'):
            print('RECOVERY_ALREADY_COMPLETE: ' + item['id'])
            continue
        ops = rec.get('operations', {})
        if ops:
            if all(ops.get(k, {}).get('status') == 'done' for k in ('instagram', 'threads')):
                links = verify_posts(engine, ops['instagram']['id'], ops['threads']['id'])
                rec.update(closed=True, permalinks=links)
                engine.save()
                continue
            raise RuntimeError('Partial or ambiguous earlier publication requires review; no automatic retry')
        keywords = {'cx006-vacation-app': ('항공권', '얼리버드'),
                    'cx101-installment-cash': ('무이자', '일시불')}[item['id']]
        for platform in ('ig', 'th'):
            field = 'caption' if platform == 'ig' else 'text'
            if any(any(word in p.get(field, '') for word in keywords) for p in posts[platform]):
                raise RuntimeError('A matching recovery topic exists; review it rather than duplicate it')
        manifest = render(item, ROOT)
        commit([ROOT / 'codex/assets' / item['id']], 'Render reviewed missing comparison')
        old = copy.deepcopy(rec)
        rec = {'hash': fingerprint(item, manifest), 'manifest': manifest,
               'asset_commit': git('rev-parse', 'HEAD'), 'review_kind': 'real',
               'decision': 'approved', 'approval_policy': 'unified-v2',
               'approved_at': now.isoformat(), 'scheduled_at': now.isoformat(),
               'approval_source': plan['authorization'], 'operations': {},
               'recovery_prior_record': old}
        engine.state['records'][item['id']] = rec
        engine.save()
        engine.tell('승인됐어요. 오늘 채팅에서 요청한 누락분 발행 승인을 저장했습니다.\n'
                    + item['topic'] + '\n가정과 계산 조건을 보완한 1편을 인스타·스레드에 게시합니다.')
        engine.publish(item, rec, now)
        ops = rec['operations']
        if not all(ops.get(k, {}).get('status') == 'done' for k in ('instagram', 'threads')):
            raise RuntimeError('Recovery has incomplete publication stages')
        rec['permalinks'] = verify_posts(engine, ops['instagram']['id'], ops['threads']['id'])
        rec['closed'] = True
        engine.save()
        engine.tell('누락분 게시 확인 완료\n' + item['topic'] + '\n' + '\n'.join(rec['permalinks'].values()))
        print('RECOVERY_COMPLETE: ' + item['id'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    publish_recovery() if args.publish else main()
