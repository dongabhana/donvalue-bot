"""Prepare the three owner-requested profile cards and the next taxi comparison."""
import hashlib
import json
from pathlib import Path
from datetime import datetime, timedelta
from codex.engine import canonical, KST, validate

ROOT = Path(__file__).resolve().parents[1]
SEED_IDS = ['cx005-coupon-minimum', 'cx004-laptop-total', 'cx008-robot-prep']
TAGS = {
    'cx005-coupon-minimum': ['돈값하나', '쿠폰', '온라인쇼핑', '소비습관', '장바구니'],
    'cx004-laptop-total': ['돈값하나', '노트북', '노트북구매', '구매가이드', 'IT소비'],
    'cx008-robot-prep': ['돈값하나', '로봇청소기', '가전구매', '살림', '청소'],
}


def taxi_item():
    hook = '택시 2만 vs 대리 3만\n아직 싼 쪽은 모릅니다'
    source = '서울시 중형택시 요금 · 2026-09-12 확인'
    example = '귀가 총액은 가상 예시. 다른 추가비용은 0원으로 가정.'
    descriptions = [
        (hook, '차를 두고 가면 내일 찾는 비용이 남습니다. 귀가비는 오늘과 내일을 같이 봐요.',
         '총 귀가비', '오늘 + 내일', example),
        ('밤 11시를 넘기면\n할증도 달라져요', '서울 중형택시는 22~23시·02~04시 20%, 23~02시 40% 심야 할증입니다.',
         '심야 할증', '20% / 40%', source),
        ('5·10·20km\n같은 조건으로 비교', '같은 출발·도착지와 조회 시각으로 비교해요. 거리만으로 정체 시간·통행료를 알 수는 없어요.',
         '비교할 세 가지', '거리 · 시간 · 경로', '서울 중형 주간: 1.6km 4,800원, 이후 131m당 100원. 저속 시간요금 별도.'),
        ('택시 2만원이\n총 31,500원이 된다면', '택시 20,000원 + 밤샘 주차 10,000원 + 다음 날 차 찾으러 가는 교통비 1,500원.',
         '차를 두고 갈 때', '31,500원', example),
        ('대리 3만원이\n총 32,000원이 된다면', '대리 30,000원 + 통행료 2,000원. 예시의 총액 차이는 500원. 차 찾는 시간도 함께 봐요.',
         '차를 가져갈 때', '32,000원', example),
        ('호출 전 한 줄\n오늘 + 내일 + 내 차', '택시+주차+차 회수비와 대리+연료+통행료+주차를 각각 합쳐요. 대리비는 해당 시각 앱 견적을 확인해요.',
         '대리 요금 확인', '고정 할증표로 단정 X', '대리는 서비스·요금 방식에 따라 달라요. 서울 택시 기준을 전국에 적용하지 않아요.'),
    ]
    seconds = [1.8,3.6,3.6,3.8,3.2,2.6]
    slides = [{'title':t,'body':b,'note':n,'seconds':seconds[i],
               'visual':{'kind':'hero' if i==0 else 'check','label':l,'value':v}}
              for i,(t,b,l,v,n) in enumerate(descriptions)]
    slides[1]['visual']['rows'] = [['22~23시','20%'],['23~02시','40%'],['02~04시','20%']]
    slides[5]['body'] = '택시+주차+차 회수비와 대리+연료+통행료+주차를 합쳐요. 차 찾는 시간까지 보면 어떤 선택이 편했나요?'
    threads = ('택시 2만 vs 대리 3만. 아직 싼 쪽은 모릅니다.\n\n'
               '가상 예시: 택시 2만+밤샘 주차 1만+차 찾으러 가는 교통비 1,500=31,500원. 대리 3만+통행료 2천=32,000원. 다른 추가비는 0원 가정.\n\n'
               '서울 중형 심야 할증: 22~23시·02~04시 20%, 23~02시 40%.\n'
               '5·10·20km도 같은 출발·도착·조회 시각으로 비교하세요. 대리는 앱 견적과 연료·통행료·주차까지 확인.\n\n'
               '내일 차 찾는 시간까지 보면 어느 쪽이 편했나요?\n'
               '택시 기준 출처: https://news.seoul.go.kr/traffic/archives/1659')
    caption = (hook.replace('\n',' ')+'\n\n'+'\n\n'.join(b for _,b,_,_,_ in descriptions)+
               '\n\n※ 귀가 총액은 가상 예시이며 다른 추가비용은 0원 가정. 지역·택시 종류·대리 서비스에 따라 달라요.\n'
               '서울 택시 기준: https://news.seoul.go.kr/traffic/archives/1659\n'
               '대리 요금 방식: https://play.google.com/store/apps/details?id=com.kakao.wheel.driver\n'
               '#돈값하나 #택시비 #대리운전 #심야할증 #교통비')
    item = {'id':'cx054-taxi-vs-driver','publish_at':'2026-09-14T20:00:00+09:00','format':'reel',
            'verified':True,'content_version':2,'category':'이동','series':'이동의 영수증','threads_tag':'교통비',
            'topic_key':'taxi-vs-driver','topic':hook.replace('\n',' '),'hook':hook,'slides':slides,
            'caption':caption,'first_comment':'대리비는 서울 택시 심야 할증표를 적용하지 않아요. 같은 시각 앱 견적을 확인하고, 연료·통행료·주차·차 회수 비용을 합쳐 비교하세요.',
            'threads_text':threads,'threads_chain':[],'faq':[],
            'evidence':'서울 중형택시 요금 체계의 공식 공시와 카카오모빌리티 공식 앱 설명을 확인. 귀가 총액은 가상 예시: 20000+10000+1500=31500;30000+2000=32000;32000-31500=500.',
            'verification':{'kind':'official_tariff_and_illustrative_comparison','checked_at':'2026-09-12',
                            'real_world_price_claim':True,'region':'서울','taxi_type':'중형',
                            'sources':['https://news.seoul.go.kr/traffic/archives/1659','https://play.google.com/store/apps/details?id=com.kakao.wheel.driver'],
                            'live_driver_quote_obtained':False,'illustrative_totals':True,
                            'calculation':'20000+10000+1500=31500;30000+2000=32000;32000-31500=500'},
            'music':'original-playful-112bpm','visual_style':'money_editorial_v2','accent':'#69BCE8'}
    validate(item)
    return item


def main():
    path=ROOT/'codex/content.json'
    data=json.loads(path.read_text())
    selected={i['id']:i for i in data['items'] if i['id'] in SEED_IDS}
    if len(selected)!=3: raise RuntimeError('Missing seed manuscripts')
    for item_id,item in selected.items():
        if item.get('posted_early_on'): raise RuntimeError('Seed was already delivered; never replace it')
        item['format']='carousel'
        item['threads_media']='carousel'
        item['caption']=item['caption'].split('\n#')[0]+'\n'+' '.join('#'+t for t in TAGS[item_id])
        item['hashtags']=TAGS[item_id]
    coupon=selected['cx005-coupon-minimum']['slides']
    coupon[1]['title']='쿠폰 조건은 4만원\n원래 살 건 36,000원'
    coupon[1]['visual']['rows']=[['계획한 상품','36,000원'],['추가한 상품','9,000원'],['쿠폰 할인','−5,000원'],['최종 결제','40,000원']]
    coupon[2]['title']='할인은 5천원\n지출은 4천원 증가'
    coupon[3]['title']='필요한 물건이면\n결론은 달라져요'
    coupon[3]['visual']['value']='필요 vs 채움'
    coupon[4]['title']='쿠폰 말고\n결제 총액을 비교'
    coupon[4]['visual']['value']='36,000 vs 40,000'
    coupon[5]['title']='쿠폰 때문에\n뭘 더 담았나요?'
    coupon[5]['visual']['value']='계획 밖 구매'
    robot=selected['cx008-robot-prep']['slides']
    robot[0]['body']='편해지는 부분과 여전히 내가 하는 일을 나눠봐요.'
    robot[1]['title']='청소 버튼보다\n먼저 줍는 세 가지'
    robot[1]['visual']['rows']=[['케이블','먼저 정리'],['양말','바닥에서 치우기'],['장난감','이동 경로 확인']]
    robot[2]['title']='자동 청소여도\n준비는 남을 수 있어요'
    robot[2]['visual']['value']='준비 + 뒤처리'
    robot[3]['title']='좋은 가전인가보다\n우리 집에 맞는가'
    robot[3]['visual']['value']='구조 · 제품 · 생활'
    robot[4]['title']='제품 사진 말고\n우리 집 바닥부터'
    robot[4]['visual']['value']='바닥 사진 1장'
    robot[5]['title']='돌리기 전에\n제일 먼저 뭘 치워요?'
    robot[5]['visual']['value']='양말? 케이블?'
    for item in selected.values(): validate(item)
    new=taxi_item()
    if any(i['id']==new['id'] for i in data['items']): raise RuntimeError('Taxi draft already exists')
    data['items'].append(new)
    # Keep seed versions unchanged; their source hashes authorize these exact cards.
    remaining=[new]+[i for i in data['items'] if i['id'] not in SEED_IDS and i['id']!=new['id'] and not i.get('posted_early_on')]
    due=datetime(2026,9,14,20,tzinfo=KST)
    for item in remaining:
        while due.weekday() not in (0,2,5): due+=timedelta(days=1)
        item['publish_at']=due.isoformat()
        item['format']='carousel' if due.weekday()==2 else 'reel'
        due+=timedelta(days=1)
        validate(item)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    authorization={'date':'2026-09-12','expires_at':'2026-09-12T23:59:00+09:00',
                   'gap_minutes':40,'item_ids':SEED_IDS,
                   'content_hashes':{key:hashlib.sha256(canonical(selected[key])).hexdigest() for key in SEED_IDS}}
    (ROOT/'codex/seed-three.json').write_text(json.dumps(authorization,indent=2)+'\n')
    (ROOT/'codex/택시_대리_비교.md').write_text('# 다음 편 · 택시비와 대리비\n\n'+new['caption']+'\n\n## Threads\n\n'+new['threads_text']+'\n')
    print(json.dumps({'seed_cards':SEED_IDS,'next_regular':remaining[0]['id'],'next_publish_at':remaining[0]['publish_at'],
                      'remaining_manuscripts':len(remaining),'threads_characters':len(new['threads_text'])},ensure_ascii=False))


if __name__=='__main__': main()
