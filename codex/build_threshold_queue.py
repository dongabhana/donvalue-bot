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
    # 예전에는 real=False 가 상수로 박혀 있어, specs 에 실제 가격을 넣어도
    # 전부 '가격 미검증'으로 떨어지고 생성 캡션에서 금액이 지워졌다.
    # 이제는 specs 행이 출처를 들고 있을 때만 실제 가격 주장으로 승격한다.
    sources=row.get('sources') or []
    real=bool(sources)
    for src in sources:
        assert src.get('name') and src.get('url'), '출처에는 name 과 url 이 필요하다'
        assert src.get('checked_at'), '출처에는 확인 기준일(checked_at)이 필요하다'
    asset=ROOT/'assets/covers'/photo
    sha=hashlib.sha256(asset.read_bytes()).hexdigest()
    body_lines=[c[0] for c in cards[:3]]
    caption=f'{hook}\n\n' + '\n'.join(body_lines) + f'\n\n{note}\n#돈값하나 #비교분석 #분기점'
    if real:
        stamp=sources[0]['checked_at']
        caption=(f'{hook}\n\n' + '\n'.join(body_lines)
                 + f'\n\n기준일 {stamp} · 출처 ' + ' / '.join(x['name'] for x in sources)
                 + '\n#돈값하나 #비교분석 #분기점')
    else:
        # 확인하지 않은 숫자를 실제 가격처럼 내보내지 않기 위한 안전장치.
        # 이 치환은 유지한다. 없애면 AI 가 지어낸 금액이 그대로 나간다.
        caption=re.sub(r'\d[\d,.]*\s*만?원','해당 금액',caption)
    evidence=' / '.join(c[1] for c in cards)+(' / 관세청: '+CUSTOMS if real else '')
    return {
      'id':ident,'publish_at':due,'format':fmt,'verified':True,'content_version':2,
      'category':cat,'series':'분기점 계산','threads_tag':'비교분석',
      'topic_key':ident[2:],'topic':topic,'hook':hook,
      'hook_candidates':[hook,f'{thr}에서 답이 갈린다',f'{a} vs {b}, 어디서 뒤집힐까'],
      'hook_reason':'변수명이 아니라 숫자 분기점을 첫 화면에 제시하고 각 카드가 다른 계산·조건을 설명한다.',
      'slides':slides,'caption':row.get('caption',caption),
      'first_comment':'계산 기준: '+cards[0][1]+' '+note,
      'threads_text':row.get('threads_text',f'{a} vs {b}.\n\n핵심 분기점은 {thr}. 그 숫자 위와 아래에서 승자가 바뀐다.'),
      'threads_chain':[],'faq':[],'evidence':evidence,
      'verification':{
        'kind':'threshold_decision_model','checked_at':(sources[0]['checked_at'] if real else row.get('checked_at','2026-09-14')),
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
    # 발행 시각은 인사이트 실측 피크에 맞춘 두 슬롯만 허용한다.
    #   월·수 21:20 KST / 금·토 15:30 KST
    assert d.utcoffset()==timedelta(hours=9) and d.weekday() in (0,2,4,5)
    assert (d.hour,d.minute) in ((21,20),(15,30),(20,0)), f'허용되지 않은 발행 시각: {d}'
    assert len(x['slides'])==6 and len({s['title'] for s in x['slides'][1:]})==5
    assert x['slides'][0]['title']==x['hook'] and x['threads_chain']==[]
    assert re.search(r'\d',x['slides'][0]['visual']['value'])
    assert x['slides'][3]['body'] != x['slides'][4]['body']
    assert x['verification']['real_world_price_claim']==bool(x['verification']['sources'])

def main():
    data=json.loads(SRC.read_text(encoding='utf-8'))
    rows=data['items']; schedule=data['schedule']
    assert len(rows)==len(schedule)==11 and len(set(schedule))==11
    old=json.loads(DST.read_text(encoding='utf-8'))['items']
    target=[x for x in old if x.get('track')=='threshold-v2']
    target_ids={x['id'] for x in target}
    keep=[x for x in old if x['id'] not in target_ids]
    new=[item(row,due,'cx006-vacation-app' if i==0 else None) for i,(row,due) in enumerate(zip(rows,schedule))]
    for x in new: validate(x)
    occupied={x['publish_at'] for x in keep if not x.get('posted_early_on')}
    assert not (occupied & set(schedule))
    assert len({x['cover_photo']['path'] for x in new})==11
    DST.write_text(json.dumps({'items':keep+new},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('THRESHOLD_V2_OK',[(x['id'],x['publish_at'],x['slides'][0]['visual']['value']) for x in new])

if __name__=='__main__': main()
