"""돈값하나 '첫 10편'(2026-10-15 GPT 제작 패키지) — 새 30편보다 먼저 발행한다.

원본: assets/cover-packs/2026-10-15_first10/ (content.json · 표지 10장 · 대본 · 표지 프롬프트)
GPT 패키지는 독립 인계 형식이라(README) 운영 형식으로 옮기면서 아래를 바꿨다(2026-10-15 Claude 검증).

  · 훅(첫 나레이션): 질문형 → '단정 + 숫자' 형으로. 지난 실측에서 계속 시청 30%대 편(700~970회)과
    10%대 편(100~220회)을 가른 게 이 차이였다. 표지 글자는 그대로(이미지에 박힌 완성본).
  · 해시태그: GPT 태그 30개 중 #쇼핑습관 176 · #구독관리 445 · #자동결제 1,362 · #문풍지 3,671 ·
    #라면 211만 처럼 찾는 사람이 없거나 묻히는 태그가 많아 1.5만~70만 실측 태그로 교체(TAG_COUNTS).
  · 화면: 본문 4장마다 큰 숫자/핵심어(figure)와 짧은 설명(screen)을 따로 둔다. 나레이션 문장을 화면에
    그대로 다시 적지 않는다(PR #4 편집 메모와 같은 원칙).
  · 사실 확인(2026-10-15): 다이소몰 66327 'E형 문틈막이 2줄(2.5m×5m)' 3,000원,
    1059209 '일본제 전자레인지 라면 용기 1.4 L' 3,000원 — 공식몰 상품 페이지 제목·가격으로 확인.
    나머지 편의 숫자는 전부 '설명용 가정'이며 화면 하단·캡션에 그렇게 적는다.
  · 체험담·후기 표현 없음(구매 전 소개 / 판단 가이드). 01·07 캡션의 '연출 이미지' 고지 유지.
"""
from pathlib import Path
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
PACK = 'assets/cover-packs/2026-10-15_first10'
DATE = '2026-10-15'
START = '2026-10-15'
SERIES = '돈값하나 첫 10편'

# 해시태그 게시물 수(인스타 태그 조회, 2026-10-15). 1.5만~70만만 쓴다.
TAG_COUNTS_AS_OF = '2026-10-15'
TAG_COUNTS = {
    '겨울준비': 242268, '단열': 31768, '자취방': 251631, '구독': 503535, '구독서비스': 26592,
    '생활비': 64292, '중고폰': 66962, '중고폰판매': 22676, '중고거래': 70386, '배달음식': 540481,
    '자취밥': 24491, '식비절약': 24405, '멤버십': 34238, '현명한소비': 33572, '해외직구': 393692,
    '직구': 283348, '가격비교': 16613, '다이소꿀템': 87333, '다이소추천': 31537, '챗GPT': 167633,
    'AI활용': 34721, '인공지능': 327171, '당근마켓': 143178, '비우기': 59751, '소비': 54021,
    '집정리': 92597,
}
TAG_MIN, TAG_MAX = 15_000, 700_000

# id 접미어, 훅(첫 나레이션), 해시태그 3개(첫 번째 = 쓰레드 주제),
# 본문 4장 [(카드 제목, 큰 글자, 화면 설명)], 비교 막대 {장 번호: (라벨A, 라벨B, 값A, 값B, 수A, 수B)},
# 결론(두 줄), 결론 위 핵심 숫자(라벨, 값), 화면 하단 고지
EDIT = {
 '01': dict(slug='door-gap',
   fix={1: '다이소몰에서 확인한 건 삼천 원짜리 이형 문틈막이야. 문틀 틈을 채우는 후보지, 문 아래 큰 틈을 뭐든 막는 만능템은 아니야.'},
   hook='춥다고 문풍지부터 사면, 삼천 원 그냥 날릴 수 있어. 바람 들어오는 자리부터 봐.',
   tags='겨울준비 단열 자취방',
   cards=[('바람은 어디서?', '아래 vs 옆', '문 아래 틈과 문틀 옆 틈은 막는 방식이 다름'),
          ('실제 후보', '3,000원', '다이소몰 E형 문틈막이 · 품번 66327 · 10/15 조회'),
          ('두꺼우면 더 좋을까?', '문이 안 닫히면 끝', '틈보다 두꺼우면 오히려 문 닫힘을 방해'),
          ('사기 전 딱 세 가지', '틈 크기·붙일 면·문 닫힘', '제품 안내와 이 세 가지부터 맞추기')],
   verdict='난방 올리기 전에\n바람 자리부터.', key=('사기 전 확인', '틈 · 면 · 닫힘'),
   note='구매 전 소개 · 사용 후기 아님 · 가격 10/15 조회'),
 '02': dict(slug='cancel-offer',
   fix={0: '그러니까 할인받겠다고 마지막 해지 버튼까지 무작정 누르지는 마. 그대로 해지될 수도 있어.'},
   hook='구독 해지 누르면 할인 뜬다는 거, 모든 계정에 뜨는 건 아니야.',
   tags='구독 구독서비스 생활비',
   cards=[('할인 보장 버튼은 아님', '계정마다 다름', '해지 화면의 할인 제안은 보장되지 않음'),
          ('제안이 뜨면?', '할인율보다 기간', '몇 달만 싼지 · 그 뒤 요금은 얼마인지'),
          ('월 결제 ≠ 월 약정', '연간 약정 분할?', '매달 내도 연간 약정일 수 있음 · 해지 조건 확인'),
          ('안 쓸 거였는데?', '다음 달에 쓸까?', '안 쓸 구독이면 할인받아도 지출')],
   verdict='싸게 유지하는 것과\n끝내는 건 다른 선택.', key=('해지 전 질문', '다음 달에 쓸까?'),
   note='판단 가이드 · 할인 제안은 서비스·계정마다 다름'),
 '03': dict(slug='used-phone',
   hook='중고폰 최고가 검색해 봤지? 그 숫자는 진단 전 가격이야. 아직 네 돈 아니야.',
   tags='중고폰 중고폰판매 중고거래',
   cards=[('같은 이름, 다른 조건', '모델명·용량', '비슷한 이름의 다른 기기 가격을 보고 있을 수 있음'),
          ('최고가의 조건', '상태 등급', '최고가가 어떤 상태 기준인지부터 확인'),
          ('진단 후 가격 확인', '검색가 ≠ 진단가', '민팃처럼 기기를 진단한 뒤 가격을 제안하는 방식'),
          ('견적만 볼까, 팔까?', '반송 조건', '가격이 마음에 안 들 때 돌려받는 방법부터')],
   verdict='제일 큰 숫자 말고\n내 폰 상태의 가격.', key=('비교할 숫자', '같은 상태 기준가'),
   note='판단 가이드 · 실제 매입 견적 아님'),
 '04': dict(slug='delivery-vs-cook',
   hook='배달 이만 원 대신 장보기 삼만 원. 이게 꼭 손해는 아니야. 조건이 하나 있어.',
   tags='배달음식 자취밥 식비절약',
   cards=[('오늘 결제만 보면', '', '설명용 가정 · 장보기가 1만원 더 큼'),
          ('한 끼로 나누면', '', '재료 30,000원을 세 끼에 다 쓴다는 가정'),
          ('냉장고에 남은 돈', '다음 끼니 재료', '남은 재료는 버린 돈도, 아낀 돈도 아직 아님'),
          ('퇴근 후의 나를 기준으로', '내일 메뉴 하나', '피곤한 내가 정말 만들 수 있는 걸로')],
   compare={0: ('배달 한 번', '장보기 한 번', '20,000원', '30,000원', 2, 3),
            1: ('배달 한 끼', '장보기 ÷ 세 끼', '20,000원', '10,000원', 2, 1)},
   verdict='배달을 끊기보다\n대신 먹을 걸 정해두자.', key=('세 끼 다 먹으면', '한 끼 1만원'),
   note='설명용 가정 · 실제 실험 결과 아님'),
 '05': dict(slug='membership-saving',
   hook='멤버십 앱이 삼만 원 아꼈다는데, 진짜 남은 돈은 칠천 원일 수도 있어.',
   tags='멤버십 현명한소비 생활비',
   cards=[('혜택 3만원 ≠ 현금 3만원', '혜택 ≠ 현금', '할인·배송 혜택이 한데 합쳐진 숫자'),
          ('원래 할 주문이었나', '원래 살 물건만', '혜택 쓰려고 만든 주문은 빼고 계산'),
          ('얼마가 남았나', '', '12,000원 − 5,000원 = 7,000원 (가정)'),
          ('쿠폰 쓰려고 더 샀다면', '', '필요 없던 지출이 남은 돈보다 커짐')],
   compare={2: ('원래 살 물건에서 아낀 돈', '회비', '12,000원', '5,000원', 12, 5),
            3: ('남은 돈', '쿠폰 때문에 더 쓴 돈', '7,000원', '10,000원', 7, 10)},
   verdict='혜택 합계보다\n생활에서 남은 돈.', key=('이 예시에서 남은 돈', '7,000원'),
   note='가상 멤버십 예시 · 실제 서비스 수치 아님'),
 '06': dict(slug='direct-buy-total',
   hook='직구가 이만 원 싸 보여도, 배송비 하나 붙이면 그 차이가 사분의 일로 줄어.',
   tags='해외직구 직구 가격비교',
   cards=[('가격표는 첫 장면', '', '설명용 가정 · 배송비 15,000원을 더하면 차이 5,000원'),
          ('추가 비용은 조건마다', '세금·수수료', '모든 직구에 똑같이 붙지 않음 · 관세청 예상세액 조회'),
          ('같은 물건 맞아?', '정확한 모델명', '구성품·보증 조건이 다를 수 있음'),
          ('반품할 때도 비교', '반품 주소·비용', '작은 가격 차이면 반품 조건이 더 크게 느껴짐')],
   compare={0: ('직구 + 배송비', '국내 판매가', '115,000원', '120,000원', 115, 120)},
   verdict='최저가보다\n받고 되돌리는 비용.', key=('이 예시의 진짜 차이', '5,000원'),
   note='설명용 가정 · 세금은 상품·국가·통관 방식별로 다름'),
 '07': dict(slug='ramen-bowl',
   fix={0: '다이소몰에서 직접 확인한 제품이야. 이름은 전자레인지 라면 용기, 용량은 일 점 사 리터.'},
   hook='라면 하나 끓이려고 냄비까지 씻기 싫다면, 다이소에 삼천 원짜리 전자레인지 용기가 있어.',
   tags='다이소꿀템 다이소추천 자취밥',
   cards=[('실제 후보', '3,000원', '다이소몰 전자레인지 라면 용기 1.4L · 품번 1059209'),
          ('전자레인지가 냄비 대신', '봉지라면 조리용', '가스레인지 앞에 서기 귀찮은 날 후보'),
          ('설거지 0개는 아니야', '용기 + 뚜껑', '냄비째 먹는 사람이면 설거지가 크게 줄진 않음'),
          ('몇 분인지는 포장을 봐', '조리시간·물 양·출력', '제품 설명과 전자레인지 출력 확인')],
   verdict='내 귀찮음을\n덜어줄지 보고 사자.', key=('가격 · 용량', '3,000원 · 1.4L'),
   note='구매 전 소개 · 사용 후기 아님 · 가격 10/15 조회'),
 '08': dict(slug='paid-ai-worth',
   hook='AI가 오 초 만에 써줘도, 고치는 데 이십 분이면 시간을 아낀 게 아니야.',
   tags='챗GPT AI활용 인공지능',
   cards=[('답 나온 시간은 끝이 아냐', '', '설명용 예시 · 제출할 수 있을 때까지 재기'),
          ('멋진 질문보다 내 일 하나', '자주 하는 일 1개', '같은 회의 메모로 결정·담당·마감 뽑기'),
          ('없는 마감 만들었나?', '세 가지 기록', '빠뜨린 것 · 지어낸 것 · 내가 고친 양'),
          ('한 번 잘했다고 끝?', '여러 번 반복', '무료로 충분하면 그걸로도 괜찮음')],
   compare={0: ('답이 뜬 시간', '고친 시간', '5초', '20분', 5, 1200)},
   verdict='화려한 답보다\n덜 남는 내 일.', key=('유료의 돈값', '덜 남는 내 일'),
   note='설명용 예시 · 특정 서비스 성능·요금 주장 아님'),
 '09': dict(slug='resale-net',
   fix={0: '가정으로 포장비랑 이동비에 이천 원이 들었다고 쳐. 입금된 만 원이 다 남는 돈은 아니지.'},
   hook='중고로 만 원에 팔아도, 손에 남는 건 팔천 원일 수 있어. 시간은 따로고.',
   tags='중고거래 당근마켓 비우기',
   cards=[('입금액과 남는 돈', '', '포장·이동 2,000원 (가정)'),
          ('시간은 별도로', '사진·답장·대기', '시급으로 바꿀 필요는 없음 · 감당할 만했나'),
          ('작은 건 묶어볼까', '묶음 판매', '거래 시간·장소를 먼저 써두기'),
          ('비우는 것도 목적이라면', '나눔도 선택지', '나눔도 연락·전달 수고는 있음')],
   compare={0: ('판매가', '손에 남은 돈', '10,000원', '8,000원', 10, 8)},
   verdict='최고가보다\n돈과 수고의 균형.', key=('이 예시에서 남은 돈', '8,000원'),
   note='설명용 가정 · 가상 상황'),
 '10': dict(slug='cheap-vs-daily',
   hook='싸게 사서 안 쓰는 물건보다, 비싸게 사서 매일 쓰는 물건이 더 싼 경우가 있어.',
   tags='현명한소비 소비 집정리',
   cards=[('물건보다 생활을 산 건가', '꺼내기·조립·세척', '안 쓰는 이유는 쓰는 과정일 때가 많음'),
          ('매일 쓰는 이유', '손 닿는 자리', '준비가 적고 자주 겪는 불편을 줄여줌'),
          ('비싸면 오래 쓴다?', '가격 ≠ 사용', '싼 것도 매일 쓰면 돈값, 비싼 것도 방치하면 똑같음'),
          ('내일 어디서 쓸 건데?', '내일 언제·어디서?', '답이 없으면 잠깐 보류')],
   verdict='가격표보다\n닳은 자리에 답이 있다.', key=('사기 전 질문', '내일 어디서 쓸까?'),
   note='판단 가이드'),
}

# 글로 나가는 훅(캡션·유튜브 제목·쓰레드 첫 줄 자리) — 숫자는 아라비아 숫자로.
# 말로 나가는 훅(EDIT[..]['hook'], 나레이션 첫 줄)은 TTS 가 또박또박 읽도록 한글 수사로 둔다.
# (campaign30 의 hook / narration[0] 분리와 같은 방식) 내용·숫자는 두 쪽이 같아야 한다(테스트로 확인).
HOOK_TEXT = {
    '01': '춥다고 문풍지부터 사면, 3,000원 그냥 날릴 수 있어. 바람 들어오는 자리부터 봐.',
    '04': '배달 2만 원 대신 장보기 3만 원. 이게 꼭 손해는 아니야. 조건이 하나 있어.',
    '05': '멤버십 앱이 3만 원 아꼈다는데, 진짜 남은 돈은 7천 원일 수도 있어.',
    '06': '직구가 2만 원 싸 보여도, 배송비 하나 붙이면 그 차이가 5천 원으로 줄어.',
    '07': '라면 하나 끓이려고 냄비까지 씻기 싫다면, 다이소에 3,000원짜리 전자레인지 용기가 있어.',
    '08': 'AI가 5초 만에 써줘도, 고치는 데 20분이면 시간을 아낀 게 아니야.',
    '09': '중고로 1만 원에 팔아도, 손에 남는 건 8천 원일 수 있어. 시간은 따로고.',
}

# 유튜브 제목에서 GPT 제목 두 덩어리를 잇는 말(표지에선 두 줄이라 붙여 쓰면 어색함)
YT_TITLE_TEXT = {'10': '싸게 사고 방치 vs 비싸게 사고 매일'}

EPISODES = []


def _load():
    pack = json.loads((ROOT / PACK / 'content.json').read_text(encoding='utf-8'))
    for src in pack['episodes']:
        x = EDIT[src['id']]
        n = int(src['id'])
        beats = src['beats']
        assert len(beats) == 4 and len(x['cards']) == 4, src['id']
        cards = [dict(title=t, figure=f, body=x.get('fix', {}).get(i, b[1]))
                 for i, ((t, f, _), b) in enumerate(zip(x['cards'], beats))]
        EPISODES.append(dict(
            id=f"f{n:02d}-{x['slug']}", order=n, campaign='campaign_first10', series=SERIES,
            product=src['topic'], title=src['title'], hook=HOOK_TEXT.get(src['id'], x['hook']),
            spoken_hook=x['hook'], yt_title_text=YT_TITLE_TEXT.get(src['id'], src['title']),
            cards=cards, screen=[s for _, _, s in x['cards']], compare=dict(x.get('compare') or {}),
            verdict_text=x['verdict'], key=dict(label=x['key'][0], figure=x['key'][1]),
            question=src['question'],
            hashtags=x['tags'].split(), note=x['note'],
            # 첫 줄 = 훅(단정형), 본문 4장 = GPT 대본(훅과 겹치는 문장·발음만 fix 로 고침), 결론 = GPT 대본
            narration=[x['hook']] + [x.get('fix', {}).get(i, b[1]) for i, b in enumerate(beats)] + [src['ending']],
            body_caption=src['caption'], threads_body=src['threads_text'],
            disclosure=src['disclosure'], gpt_hook=src['hook'],
            sources=[s['url'] for s in src.get('sources') or []],
            source_labels=[s['label'] for s in src.get('sources') or []],
            assumptions=src['disclosure'], as_of=DATE, pack_cover=src['cover']['file']))


_load()
assert len(EPISODES) == 10, len(EPISODES)


def cover_status(e):
    own = ROOT / f"assets/covers/{e['id']}.editorial-v3.jpg"
    if not own.is_file():
        return False, f'표지 필요: {own.relative_to(ROOT)}'
    return True, 'ok'


def one_line(t):
    return t.replace('\n', ' ')


def first_sentence(t):
    # 마침표 뒤에 공백이 올 때만 자른다('1.4 L' 같은 소수점·'봐 봤지?' 같은 물음은 이어 둔다)
    return re.split(r'(?<=\.)\s', one_line(t).strip(), maxsplit=1)[0].rstrip('.')


def caption_body(t):
    # GPT 캡션 마지막 문단이 질문이면 아래 '💬 질문' 줄과 겹치므로 뺀다(f10)
    lines = t.strip().split('\n')
    if len(lines) > 1 and lines[-1].rstrip().endswith('?'):
        lines = lines[:-1]
    return '\n'.join(lines).strip()


def package():
    from codex.campaign27 import IG_CTA, YT_CTA
    from src.tags import CORE
    for e in EPISODES:
        e['cover_file'] = f"assets/covers/{e['id']}.editorial-v3.jpg"
        e['cover_complete'] = True
        ready, why = cover_status(e)
        e['cover_ready'], e['cover_note'], e['hold'] = ready, why, not ready
        e['reel_cards'] = [1, 2, 3, 4]
        e['reel'] = {'big': [e['title']], 'badge': e['product'], 'sub': e['series'], 'stake': '',
                     'beats': [c['body'] for c in e['cards']], 'loop': e['question']}
        e['yt_title'] = f"{first_sentence(e['hook'])} | {e['yt_title_text']}"[:90]
        tags = e['hashtags'] + [t for t, _ in CORE if t not in e['hashtags']]
        e['ig_tags'] = tags[:5]
        ig_tags = ' '.join('#' + t for t in e['ig_tags'])
        yt_tags = ' '.join('#' + t for t in (['Shorts'] + e['ig_tags'][:4]))
        refs = '\n'.join(f"{l}: {u}" for l, u in zip(e['source_labels'], e['sources']))
        core = f"{one_line(e['hook'])}\n\n{caption_body(e['body_caption'])}"
        e['caption'] = f"{core}\n\n💬 {e['question']}\n{IG_CTA}\n\n{ig_tags}"
        e['youtube_description'] = (f"{core}" + (f"\n\n출처(확인일 {DATE}):\n{refs}" if refs else '')
                                    + f"\n\n💬 {e['question']}\n{YT_CTA}\n\n{yt_tags}")
        e['youtube_tags'] = e['ig_tags'] + ['생활비', '절약', '돈 아끼는 법']
        e['threads_tag'] = e['hashtags'][0]
        th = e['threads_body'].strip()
        tail = '\n\n좋아요·팔로우하면 매일 하나씩 돈 계산 볼 수 있어.'
        if len(th) + len(tail) > 500:
            th = th[:500 - len(tail) - 1].rstrip() + '…'
        e['threads_text'] = th + tail
        e['threads_chain'] = []
        e['cta'] = {
            'instagram': dict(screen='좋아요 + 팔로우',
                              narration=f"{e['question']} 도움 됐으면 좋아요 누르고, 매일 올라오는 돈 계산 받아 보려면 팔로우 해 둬."),
            'youtube': dict(screen='좋아요 + 구독',
                            narration=f"{e['question']} 도움 됐으면 좋아요 누르고, 매일 올라오는 돈 계산 받아 보려면 구독 해 둬."),
        }
    return {'schema_version': 2, 'brand': '돈값하나', 'handle': '@dongabhana', 'as_of': DATE,
            'start': START, 'items': EPISODES}


if __name__ == '__main__':
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'build' / 'campaign_first10.json'
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(package(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{len(EPISODES)} episodes -> {dest}')
