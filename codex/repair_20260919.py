"""Read-only audit for the owner's 2026-09-19 missing-publication request."""
import json
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


if __name__ == '__main__':
    main()
