"""Read published Threads and prepare six original cards; never publish or reset a journal."""
from datetime import datetime
from codex.engine import Engine, KST, ROOT, MetaFailure, fingerprint
from codex.seed_three_once import DATE, authorized_now
import hashlib


def matching_posts(engine,item,record):
    user=engine.account_check('th'); matches=[]; after=None
    for _ in range(5):
        args={'fields':'id,text,timestamp,media_type,children{id,media_type},permalink','limit':100}
        if after: args['after']=after
        data=engine.meta('th','GET',user+'/threads',**args)
        for post in data.get('data',[]):
            if post.get('text','').strip()==item['threads_text'].strip(): matches.append(post)
        if not data.get('paging',{}).get('next'): return matches
        after=data['paging']['cursors']['after']
        # All posts since the failed operation must be covered.
        timestamps=[datetime.fromisoformat(p['timestamp'].replace('Z','+00:00')) for p in data.get('data',[]) if p.get('timestamp')]
        if timestamps and min(timestamps)<datetime.fromisoformat(record['approved_at']): return matches
    raise RuntimeError('Feed review incomplete; no recovery permitted')


def main():
    e=Engine(); now=datetime.now(KST)
    item=next(x for x in e.items if x['id']=='cx005-coupon-minimum'); rec=e.state['records'][item['id']]
    assert now.date().isoformat()==DATE and authorized_now(item,rec,now)
    assert rec['operations']['instagram']['status']=='done'
    assert rec['operations']['threads']['status']=='needs_review'
    assert fingerprint(item,rec['manifest'])==rec['hash']
    for path,sha in rec['manifest']['sha256'].items(): assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==sha
    posts=matching_posts(e,item,rec)
    print('RECOVERY_MATCHING_PUBLISHED_THREADS: '+str(len(posts)),flush=True)
    for post in posts: print('RECOVERY_EXISTING_LINK: '+post.get('permalink',''),flush=True)
    if posts: return
    if rec.get('recovery_prepared'):
        print('RECOVERY_ALREADY_PREPARED; no new containers',flush=True);return
    repo=__import__('os').environ['GITHUB_REPOSITORY']; sha=rec['asset_commit']
    urls=[f'https://raw.githubusercontent.com/{repo}/{sha}/{p}' for p in rec['manifest']['cards']]
    try:
        cid=e.prepare_thread(item['threads_text'],topic_tag=item.get('threads_tag'),image_urls=urls)
    except MetaFailure as error:
        print('RECOVERY_PREPARATION_REJECTION: '+str(error.failure),flush=True)
        raise RuntimeError('Preparation rejected; original journal unchanged') from None
    rec['recovery_prepared']={'id':cid,'reviewed_at':now.isoformat(),'cards':len(urls),'source_hash':rec['hash'],'review_run':'34680023274-attempt-2'}
    e.save()
    print('RECOVERY_PREPARED_SUCCESS: six original cards; no publication attempted',flush=True)

if __name__=='__main__':main()
