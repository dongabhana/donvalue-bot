"""Owner-requested four-card backlog, no approval, 40 minutes between starts."""
import argparse
import time
from datetime import datetime

from src import run

ITEM_IDS = ['004-ott-stack', '005-mvno', '007-dishwasher', '008-commute-vs-rent']


def main():
    if datetime.now(run.KST).date().isoformat() != '2026-09-12':
        print('BURST_EXPIRED: no publication')
        return 0
    previous_start = None
    for item_id in ITEM_IDS:
        if any(p['id'] == item_id for p in run.load_posted()):
            print('BURST_ALREADY_DELIVERED: ' + item_id)
            continue
        if previous_start is not None:
            remaining = max(0, 40 * 60 - (time.monotonic() - previous_start))
            print(f'BURST_NEXT: {item_id} in {remaining / 60:.1f} minutes', flush=True)
            time.sleep(remaining)
        previous_start = time.monotonic()
        print('BURST_START: ' + item_id, flush=True)
        args = argparse.Namespace(id=item_id, pick='carousel', tomorrow=False, dry_run=False)
        rc = run.run_once(args)
        if rc:
            return rc
    print('BURST_COMPLETE: requested four items only', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
