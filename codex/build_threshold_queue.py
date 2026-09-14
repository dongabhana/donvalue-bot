from __future__ import annotations
import json,re
from datetime import datetime,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
SRC=ROOT/'codex/threshold_specs.json'; DST=ROOT/'codex/content.json'
CUTOFF=datetime.fromisoformat('2026-09-16T00:00:00+09:00')
SCHEDULE=['2026-09-16T20:00:00+09:00','2026-09-19T20:00:00+09:00','2026-09-21T20:00:00+09:00','2026-09-23T20:00:00+09:00','2026-09-26T20:00:00+09:00','2026-09-28T20:00:00+09:00','2026-09-30T20:00:00+09:00','2026-10-03T20:00:00+09:00','2026-10-05T20:00:00+09:00','2026-10-07T20:00:00+09:00','2026-10-10T20:00:00+09:00','2026-10-12T20:00:00+09:00']

def slide(title,body,note,value,seconds):
    return {'title':title,'body':body,'note':note,'seconds':seconds,'visual':{'kind':'metric','value':value,'label':'분기점'}}

def item(row,due):
    ident,cat,topic,hook,thr,a,b,calc,verdict,note,fmt,photo,sha=row
    slides=[slide(hook,f'{a} vs {b}. 답은 조건 하나에서 갈린다.',note,thr,1.8),slide('A를 같은 단위로',calc,'가격표가 아니라 실제 지출 기준.',a,3.4),slide('B도 똑같이 계산',f'{b}도 같은 기간·횟수·인원 기준으로 맞춰 비교한다.','단위를 맞추지 않으면 비교가 왜곡된다.',b,3.4),slide('여기서 답이 뒤집힌다',verdict,note,thr,3.8),slide('한쪽이 무조건 답은 아니다',verdict,'내 숫자를 넣으면 답이 바뀔 수 있다.',f'{a} ↔ {b}',3.4),slide('당신 숫자는 어디쯤?','본인 조건을 넣어 같은 공식으로 계산해보자.','돈값하나? · 느낌 말고 분기점',thr,3.0)]
    return {'id':ident,'publish_at':due,'format':fmt,'verified':True,'content_version':2,'category':cat,'series':'분기점 계산','threads_tag':'비교분석','topic_key':ident[2:],'topic':topic,'hook':hook,'hook_candidates':[hook,f'{thr}에서 답이 갈린다',f'{a} vs {b}, 어디서 뒤집힐까'],'hook_reason':'두 선택 모두 가능한 상황에서 판단을 바꾸는 분기점 숫자를 첫 화면에 제시.','slides':slides,'caption':f'{hook}\n\n{calc}\n\n{verdict}\n\n{note}\n#돈값하나 #비교분석 #분기점','first_comment':f'계산 기준: {calc}\n{note}','threads_text':f'{a} vs {b}.\n\n핵심 분기점은 {thr}. 같은 단위로 계산하면 어느 지점에서 답이 바뀌는지 보인다.','threads_chain':[],'faq':[],'evidence':calc+' '+note,'music':'original-playful-112bpm','visual_style':'money_editorial_v2','accent':'#E6F34A','threads_media':'carousel','cover_photo':{'path':'assets/covers/'+photo,'sha256':sha,'kind':'ai_staged_editorial'},'track':'threshold-v1'}

def validate(x):
    assert re.fullmatch(r'cx[0-9]{3}-[a-z0-9-]+',x['id']) and x['verified'] is True
    d=datetime.fromisoformat(x['publish_at']); assert d.utcoffset()==timedelta(hours=9) and d.weekday() in (0,2,5) and d.hour==20 and d.minute==0
    assert x['format'] in ('reel','carousel') and len(x['slides'])==6 and x['slides'][0]['title']==x['hook']
    assert len(x['caption'])<=2200 and 0<len(x['threads_text'])<=500 and x['threads_chain']==[]

def main():
    rows=json.loads(SRC.read_text(encoding='utf-8'))['items']; assert len(rows)==12
    new=[item(r,SCHEDULE[i]) for i,r in enumerate(rows)]
    for x in new: validate(x)
    assert len({x['id'] for x in new})==12 and len({x['cover_photo']['path'] for x in new})==12
    old=json.loads(DST.read_text(encoding='utf-8'))['items'] if DST.exists() else []
    keep=[x for x in old if x.get('posted_early_on') or datetime.fromisoformat(x['publish_at'])<CUTOFF]
    out={'items':keep+new}; DST.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('THRESHOLD_QUEUE_OK',len(keep),len(new),new[0]['publish_at'],new[-1]['publish_at'])
if __name__=='__main__': main()
