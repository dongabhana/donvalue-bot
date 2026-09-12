"""Owner-requested four-card backlog, no approval, 40 minutes between starts."""
import argparse
import json
import os
import time
from datetime import datetime

import yaml
from src import run, publish, notify

ITEM_IDS = ['004-ott-stack', '005-mvno', '007-dishwasher', '008-commute-vs-rent']


def recover_rejected_threads(item_id, prior):
    """Retry only the recorded pre-publication 400 rejection; never an ambiguous publish."""
    if prior.get('results', {}).get('threads'):
        return
    proven_rejection = any('threads: POST ' in e and '/me/threads → 400' in e
                          and 'Invalid Carousel Children' in e for e in prior.get('errors', []))
    if not proven_rejection:
        print('BURST_THREADS_REVIEW: ' + item_id, flush=True)
        return
    ledger = json.loads(run.DELIVERY.read_text())
    operation = ledger.get(item_id, {}).get('threads', {})
    if operation.get('status') == 'done':
        post_id = operation['id']
    else:
        if operation.get('status') != 'in_flight':
            raise RuntimeError('Unexpected recovery state')
        # The original request was rejected while creating the parent container.
        # It never reached threads_publish, so no existing post can be duplicated.
        del ledger[item_id]['threads']
        run.DELIVERY.write_text(json.dumps(ledger, ensure_ascii=False, indent=2))
        run.sh('git', 'add', str(run.DELIVERY))
        run.sh('git', '-c', 'user.name=donvalue-bot', '-c', 'user.email=bot@users.noreply.github.com',
               'commit', '-m', f'delivery: {item_id} confirmed Threads preparation rejection')
        run.push()
        queue = yaml.safe_load(run.QUEUE.read_text())
        item = next(i for i in queue['items'] if i['id'] == item_id)
        paths = sorted((run.IMAGES / item_id).glob('*.png'))
        if not paths:
            paths = sorted((run.IMAGES / item_id).glob('*.jpg'))
        if len(paths) < 2:
            raise RuntimeError('Original carousel images are missing')
        sha = run.sh('git', 'rev-parse', 'HEAD')
        base = f"https://raw.githubusercontent.com/{os.environ['GITHUB_REPOSITORY']}/{sha}/images/{item_id}"
        urls = [f'{base}/{p.name}' for p in run.threads_images(paths)]
        post_id = run.deliver_once(item_id, 'threads', lambda: publish.publish_threads(
            os.environ['TH_USER_ID'], os.environ['TH_ACCESS_TOKEN'], urls,
            run.build_threads_text(item, queue.get('cta') or {}, 'carousel'), topic_tag=item.get('threads_tag')))
    posted = run.load_posted()
    entry = next(p for p in posted if p['id'] == item_id)
    entry['results']['threads'] = post_id
    entry['errors'] = [e for e in entry['errors'] if not e.startswith('threads:')]
    run.POSTED.write_text(json.dumps(posted, ensure_ascii=False, indent=2))
    run.sh('git', 'add', str(run.POSTED))
    run.sh('git', '-c', 'user.name=donvalue-bot', '-c', 'user.email=bot@users.noreply.github.com',
           'commit', '-m', f'posted: {item_id} recovered Threads only')
    run.push()
    notify.done(item_id, entry['product'], entry['results'], entry['errors'])
    print('BURST_THREADS_RECOVERED: ' + item_id, flush=True)


def main():
    if datetime.now(run.KST).date().isoformat() != '2026-09-12':
        print('BURST_EXPIRED: no publication')
        return 0
    for item_id in ITEM_IDS:
        prior = next((p for p in run.load_posted() if p['id']==item_id),None)
        if prior and prior.get('results',{}).get('instagram'):
            recover_rejected_threads(item_id, prior)
            print('BURST_ALREADY_DELIVERED: ' + item_id)
            continue
        ledger=json.loads(run.DELIVERY.read_text()) if run.DELIVERY.exists() else {}
        last_times=[datetime.fromisoformat(ledger[k]['instagram']['at']) for k in ITEM_IDS
                    if k in ledger and ledger[k].get('instagram',{}).get('status')=='done' and k!=item_id]
        if last_times and not ledger.get(item_id,{}).get('instagram',{}).get('status')=='done':
            remaining=max(0, 40*60-(datetime.now(run.KST)-max(last_times)).total_seconds())
            print(f'BURST_NEXT: {item_id} in {remaining / 60:.1f} minutes', flush=True)
            time.sleep(remaining)
        print('BURST_START: ' + item_id, flush=True)
        args = argparse.Namespace(id=item_id, pick='carousel', tomorrow=False, dry_run=False)
        rc = run.run_once(args)
        if rc:
            return rc
        ledger=json.loads(run.DELIVERY.read_text()) if run.DELIVERY.exists() else {}
        if ledger.get(item_id,{}).get('instagram',{}).get('status')!='done':
            print('BURST_STOPPED: Instagram delivery needs review', flush=True)
            return 1
    print('BURST_COMPLETE: requested four items only', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
