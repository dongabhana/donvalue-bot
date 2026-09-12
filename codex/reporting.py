"""Compare labelled cohorts at a similar post age; never treat missing data as zero."""
import hashlib
import json
from datetime import datetime, timedelta
from statistics import mean


def metric_value(payload):
    rows=payload.get('data',[])
    if not rows: return None
    row=rows[0]
    value=row.get('total_value',{}).get('value')
    if value is None and row.get('values'): value=row['values'][0].get('value')
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) else None


def collect_and_report(engine, root, now):
    candidates=[]
    path=root/'content/posted.json'
    legacy=json.loads(path.read_text()) if path.exists() else []
    for item in legacy:
        for key,mid in item.get('results',{}).items():
            if key not in ('instagram','instagram_reel','threads') or not mid: continue
            candidates.append({'source':'Claude','platform':'th' if key=='threads' else 'ig','format':'text' if key=='threads' else ('reel' if key=='instagram_reel' else 'feed'), 'media_id':str(mid),'at':item['posted_at']})
    for item in engine.items:
        record=engine.state['records'].get(item['id'],{})
        for platform,key in [('ig','instagram'),('th','threads')]:
            op=record.get('operations',{}).get(key,{})
            if op.get('status')=='done':
                candidates.append({'source':'Codex','platform':platform,'format':'text' if platform=='th' else ('reel' if item['format']=='reel' else 'feed'),'media_id':op['id'],'at':op['at']})
    samples=engine.state.setdefault('comparison_samples',{})
    for row in candidates:
        age=(now-datetime.fromisoformat(row['at'])).total_seconds()/3600
        # If this window was missed, do not mix a much older cumulative count into the cohort.
        if not 24<=age<27: continue
        identity=hashlib.sha256((row['platform']+row['media_id']).encode()).hexdigest()[:20]
        if identity in samples: continue
        metrics=['views','reach','saved','shares'] if row['platform']=='ig' else ['views','likes','replies','reposts']
        row.update({'sampled_at':now.isoformat(),'age_hours':round(age,2),'metrics':{},'unavailable':[]})
        for metric in metrics:
            try:
                value=metric_value(engine.meta(row['platform'],'GET',row['media_id']+'/insights',metric=metric))
                if value is None: row['unavailable'].append(metric)
                else: row['metrics'][metric]=value
            except RuntimeError: row['unavailable'].append(metric)
        samples[identity]=row
    if now.weekday()!=6 or now.hour<19 or engine.state.get('comparison_report_date')==now.date().isoformat(): return
    recent=[r for r in samples.values() if now-timedelta(days=7)<=datetime.fromisoformat(r['sampled_at'])<=now]
    if not recent: return
    groups={}
    for row in recent: groups.setdefault((row['source'],row['platform'],row['format']),[]).append(row)
    lines=['돈값하나 주간 비교 · 게시 24~27시간 시점','수집 시각 기준 최근 7일. 형식별로 분리했습니다.']
    for (source,platform,fmt),rows in sorted(groups.items()):
        values=[]
        for metric in ('views','reach','saved','shares','likes','replies','reposts'):
            counts=[r['metrics'][metric] for r in rows if metric in r['metrics']]
            if counts: values.append(f'{metric} 평균 {mean(counts):.1f} (조회 성공 {len(counts)}편)')
        lines.append(f'{source} / {platform} / {fmt} / {len(rows)}편\n'+(', '.join(values) or '지표 조회 불가'))
    lines.append('표본·주제·요일이 달라 인과관계나 승자를 확정할 수 없습니다. 조회 실패는 0으로 계산하지 않았습니다.')
    engine.tell('\n\n'.join(lines))
    engine.state['comparison_report_date']=now.date().isoformat()
