"""Publish the reviewed coupon container once, then resume the two remaining seed cards."""
from datetime import datetime
import hashlib
from codex.engine import Engine, KST, ROOT, fingerprint
from codex.seed_three_once import DATE, authorized_now, mark_delivered, main as resume
from codex.seed_recovery_review import matching_posts


def main():
    e=Engine();now=datetime.now(KST)
    item=next(x for x in e.items if x['id']=='cx005-coupon-minimum');rec=e.state['records'][item['id']]
    if rec.get('closed'):
        print('RECOVERY_COUPON_ALREADY_COMPLETE',flush=True);resume();return
    assert now.date().isoformat()==DATE and authorized_now(item,rec,now)
    assert rec['operations']['instagram']['status']=='done'
    assert fingerprint(item,rec['manifest'])==rec['hash']
    for path,sha in rec['manifest']['sha256'].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==sha
    if rec['operations']['threads']['status']!='done':
        prepared=rec['recovery_prepared']
        assert prepared['source_hash']==rec['hash'] and prepared['cards']==6
        assert prepared['review_run']=='34680023274-attempt-2'
        prior=rec['operations'].get('threads_recovery_publish')
        if prior and prior['status']!='done':
            raise RuntimeError('Ambiguous recovery publication; no retry')
        if not prior:
            posts=matching_posts(e,item,rec)
            print('RECOVERY_FINAL_MATCHING_POSTS: '+str(len(posts)),flush=True)
            if posts: raise RuntimeError('Matching published post requires adoption review; no duplicate publication')
            e.wait_ready('th',prepared['id'])
            rec.setdefault('recovery_audit',[]).append({'original_threads_operation':dict(rec['operations']['threads']),
                'reviewed_at':now.isoformat(),'review_run':'34686190512','action':'publish reviewed six-card container; preserve completed Instagram'})
            e.save()
        user=e.account_check('th')
        post_id=e.operation(rec,'threads_recovery_publish',lambda:e.meta('th','POST',user+'/threads_publish',creation_id=prepared['id'])['id'])
        recovered=rec['operations']['threads_recovery_publish']
        rec['operations']['threads']={'status':'done','id':post_id,'at':recovered['at'],'recovered_by':'threads_recovery_publish'}
        e.save()
        print('RECOVERY_THREADS_PUBLISHED: coupon; Instagram not called',flush=True)
    mark_delivered(e,item,rec)
    e.tell('쿠폰 카드뉴스 복구 완료 · Instagram 재발행 없이 Threads 6장 발행 완료\n'+'\n'.join(rec.get('permalinks',{}).values()))
    print('RECOVERY_COUPON_COMPLETE',flush=True)
    resume()

if __name__=='__main__':main()
