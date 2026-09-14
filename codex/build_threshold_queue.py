from __future__ import annotations
import hashlib,json,re
from datetime import datetime,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
SRC=ROOT/'codex/threshold_specs.json'; DST=ROOT/'codex/content.json'
CUSTOMS='https://www.customs.go.kr/kcs/ad/tax/BuyTaxCalculation.do'

def slide(title,body,note,value,seconds=3.4):
    return {'title':title,'body':body,'note':note,'seconds':seconds,
            'visual':{'kind':'metric','value':value,'label':'분기점'}}

def item(row,due,ident_override=None):
    ident=row['id']; cat=row['category']; topic=row['topic']; hook=row['hook']; thr=row['threshold']
    a=row['a']; b=row['b']; fmt=row['format']; photo=row['cover']; cards=row['cards']; note=row['note']
    ident=ident_override or ident
    slides=[slide(hook,f'{a} vs {b}. 이번 편은 {thr}에서 답이 갈린다.',note,thr,1.8)]
    slides += [slide(t,b,note,thr,3.4 if i<4 else 3.0) for i,(t,b) in enumerate(cards)]
    real='해외직구' in topic
    sources=[]
    if real:
        sources=[{
          'name':'관세청 해외직구물품 예상세액 조회',
          'url':CUSTOMS,
          'scope_start':'자가사용물품 면세기준(금액)',
          'scope_end':'자가사용물품 면세기준(물품가격 미화150달러) 국가별 환산금액',
          'required_tokens':['물품가격미화150달러이하','미국은200달러이하','미화150달러초과','공제없이총과세가격'],
          'offers':['자가사용물품 면세기준']
        }]
    asset=ROOT/'assets/covers'/photo
    sha=hashlib.sha256(asset.read_bytes()).hexdigest()
    caption=f'{hook}\n\n{cards[2][1]}\n\n{note}\n#돈값하나 #비교분석 #분기점'
    if not real:
        caption=re.sub(r'\d[\d,.]*\s*만?원','해당 금액',caption)
    evidence=' / '.join(c[1] for c in cards)+(' / 관세청: '+CUSTOMS if real else '')
    return {
      'id':ident,'publish_at':due,'format':fmt,'verified':True,'content_version':2,
      'category':cat,'series':'분기점 계산','threads_tag':'비교분석',
      'topic_key':ident[2:],'topic':topic,'hook':hook,
      'hook_candidates':[hook,f'{thr}에서 답이 갈린다',f'{a} vs {b}, 어디서 뒤집힐까'],
      'hook_reason':'변수명이 아니라 숫자 분기점을 첫 화면에 제시하고 각 카드가 다른 계산·조건을 설명한다.',
      'slides':slides,'caption':caption,
      'first_comment':'계산 기준: '+cards[0][1]+' '+note,
      'threads_text':f'{a} vs {b}.\n\n핵심 분기점은 {thr}. 그 숫자 위와 아래에서 승자가 바뀐다.',
      'threads_chain':[],'faq':[],'evidence':evidence,
      'verification':{
        'kind':'threshold_decision_model','checked_at':'2026-09-14',
        'real_world_price_claim':real,'sources':sources,
        'assumptions':note,'calculation':' / '.join(c[1] for c in cards[:3])
      },
      'music':'original-playful-112bpm','visual_style':'money_editorial_v2',
      'accent':'#E6F34A','threads_media':'carousel',
      'editorial_revision':'official-comparison-2026-09-12',
      'pricing_status':'official_rule_verified' if real else 'assumption_labeled',
      'cover_photo':{'path':'assets/covers/'+photo,'sha256':sha,'kind':'ai_staged_editorial'},
      'track':'threshold-v2'
    }

def validate(x):
    assert re.fullmatch(r'cx[0-9]{3}-[a-z0-9-]+',x['id']) and x['verified'] is True
    d=datetime.fromisoformat(x['publish_at'])
    assert d.utcoffset()==timedelta(hours=9) and d.weekday() in (0,2,5) and d.hour==20
    assert len(x['slides'])==6 and len({s['title'] for s in x['slides'][1:]})==5
    assert x['slides'][0]['title']==x['hook'] and x['threads_chain']==[]
    assert re.search(r'\d',x['slides'][0]['visual']['value'])
    assert x['slides'][3]['body'] != x['slides'][4]['body']
    assert x['verification']['real_world_price_claim']==bool(x['verification']['sources'])

def main():
    data=json.loads(SRC.read_text(encoding='utf-8'))
    rows=data['items']; schedule=data['schedule']
    assert len(rows)==len(schedule)==12 and len(set(schedule))==12
    old=json.loads(DST.read_text(encoding='utf-8'))['items']
    target=[x for x in old if x.get('track')=='threshold-v1']
    target_ids={x['id'] for x in target}
    keep=[x for x in old if x['id'] not in target_ids]
    new=[item(row,due,'cx006-vacation-app' if i==0 else None) for i,(row,due) in enumerate(zip(rows,schedule))]
    for x in new: validate(x)
    occupied={x['publish_at'] for x in keep if not x.get('posted_early_on')}
    assert not (occupied & set(schedule))
    assert all(not d.startswith(('2026-09-16','2026-09-23')) for d in schedule)
    assert len({x['cover_photo']['path'] for x in new})==12
    DST.write_text(json.dumps({'items':keep+new},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('THRESHOLD_V2_OK',[(x['id'],x['publish_at'],x['slides'][0]['visual']['value']) for x in new])

if __name__=='__main__': main()
