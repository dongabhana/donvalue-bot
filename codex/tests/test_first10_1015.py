"""GPT '첫 10편'(codex/campaign_first10.py, 2026-10-15~) 회귀 테스트.

  · 10편 모두 표지 → 본문 4 → 결론 → 플랫폼별 마지막 장, 나레이션 6줄 + CTA
  · 발행 순서: 첫 10편 → 새 30편 → 27편 (2026-10-15 소유자 결정)
  · 훅: '단정 + 숫자', 다음 줄과 겹치지 않음, 말(한글 수사)과 글(숫자)의 숫자가 같음
  · 나레이션에 TTS 가 잘못 읽는 라틴 표기('E형')가 없음
  · 해시태그: 실측 1.5만~70만만
  · 다이소 두 제품은 공식몰 확인값(품번·가격) 그대로, 나머지 숫자는 '가정' 표기
"""
import importlib.util
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

from codex import campaign_first10 as F     # noqa: E402
from codex import campaign30 as C30         # noqa: E402
from src import campaign, tags              # noqa: E402


def design():
    spec = importlib.util.spec_from_file_location('df10', ROOT / 'tools/campaign27_design.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class First10PackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = F.package()['items']

    def test_ten_complete_episodes(self):
        self.assertEqual(len(self.items), 10)
        self.assertEqual([e['order'] for e in self.items], list(range(1, 11)))
        for e in self.items:
            with self.subTest(e=e['id']):
                self.assertTrue(re.fullmatch(r'f\d\d-[a-z-]+', e['id']))
                self.assertEqual(e['campaign'], 'campaign_first10')
                self.assertEqual(len(e['cards']), 4)
                self.assertEqual(len(e['screen']), 4)
                self.assertEqual(len(e['narration']), 6)
                self.assertTrue(all(x.strip() for x in e['narration']))
                self.assertTrue(e['key']['figure'])
                self.assertTrue(e['cover_ready'], e['cover_note'])
                self.assertFalse(e['hold'])
                self.assertIn('팔로우', e['cta']['instagram']['narration'])
                self.assertIn('구독', e['cta']['youtube']['narration'])
                self.assertNotIn('팔로우', e['cta']['youtube']['narration'])
                self.assertLessEqual(len(e['threads_text']), 500)
                self.assertLessEqual(len(e['yt_title']), 90)
                self.assertNotIn('\n', e['yt_title'])

    def test_covers_are_production_size(self):
        from PIL import Image
        pack = json.loads((ROOT / F.PACK / 'content.json').read_text(encoding='utf-8'))
        self.assertEqual(len(pack['episodes']), 10)
        for e in self.items:
            with self.subTest(e=e['id']):
                self.assertTrue((ROOT / F.PACK / e['pack_cover']).is_file())
                with Image.open(ROOT / e['cover_file']) as im:
                    self.assertEqual(im.size, (1080, 1920))
                    self.assertEqual(im.format, 'JPEG')

    def test_hook_is_assertive_and_not_repeated(self):
        """훅 = 단정형(물음표로 끝나지 않음). 바로 다음 줄이 훅을 되풀이하지 않는다(02·07·09 지적)."""
        for e in self.items:
            hook, nxt = e['narration'][0], e['narration'][1]
            with self.subTest(e=e['id']):
                self.assertFalse(hook.rstrip().endswith('?'), hook)
                words = lambda t: set(re.findall(r'[가-힣A-Za-z0-9]{2,}', t))
                overlap = words(hook) & words(nxt)
                self.assertLess(len(overlap) / max(1, len(words(nxt))), 0.5, (hook, nxt))

    def test_numeric_hooks_say_and_show_same_numbers(self):
        """말(나레이션 첫 줄, 한글 수사)과 글(캡션·제목 훅, 숫자)의 숫자가 같다."""
        expect = {
            'f01-door-gap': (['삼천 원'], ['3,000원']),
            'f04-delivery-vs-cook': (['이만 원', '삼만 원'], ['2만 원', '3만 원']),
            'f05-membership-saving': (['삼만 원', '칠천 원'], ['3만 원', '7천 원']),
            'f06-direct-buy-total': (['이만 원', '사분의 일'], ['2만 원', '5천 원']),
            'f07-ramen-bowl': (['삼천 원'], ['3,000원']),
            'f08-paid-ai-worth': (['오 초', '이십 분'], ['5초', '20분']),
            'f09-resale-net': (['만 원', '팔천 원'], ['1만 원', '8천 원']),
        }
        by = {e['id']: e for e in self.items}
        for i, (say, show) in expect.items():
            with self.subTest(e=i):
                for w in say:
                    self.assertIn(w, by[i]['narration'][0])
                for w in show:
                    self.assertIn(w, by[i]['hook'])
                    self.assertIn(w, by[i]['caption'])
        # 06: 2만 원 차이에서 배송비 1만5천 원 → 5천 원 = 4분의 1
        self.assertEqual(20000 - 15000, 5000)
        self.assertEqual(5000 * 4, 20000)
        # 05·09·04 계산
        self.assertEqual(12000 - 5000, 7000)
        self.assertEqual(10000 - 2000, 8000)
        self.assertEqual(30000 // 3, 10000)

    def test_narration_is_tts_safe(self):
        text = ' '.join(x for e in self.items for x in e['narration'] + [e['cta']['instagram']['narration'],
                                                                     e['cta']['youtube']['narration']])
        self.assertNotRegex(text, r'[A-Za-z]형')           # 'E형' 은 '이형'으로 읽힌다 → 한글로 적는다
        self.assertNotRegex(text, r'\d')                   # 숫자는 한글 수사로(장면 길이 = 말 길이)
        self.assertNotIn('품번', text)

    def test_hashtags_are_measured_mid_size(self):
        core = dict(tags.CORE)
        for e in self.items:
            with self.subTest(e=e['id']):
                self.assertEqual(len(e['ig_tags']), 5)
                self.assertLessEqual(len(e['hashtags']), 3)
                self.assertEqual(len(set(e['ig_tags'])), 5)
                for t in e['ig_tags']:
                    self.assertFalse(tags.is_blocked(t), t)
                    n = F.TAG_COUNTS.get(t, core.get(t))
                    self.assertIsNotNone(n, f'{t}: 게시물 수 기록 없음')
                    self.assertTrue(F.TAG_MIN <= n <= F.TAG_MAX, (t, n))
                self.assertEqual(e['threads_tag'], e['hashtags'][0])

    def test_daiso_facts_and_assumption_labels(self):
        by = {e['id']: e for e in self.items}
        self.assertIn('66327', by['f01-door-gap']['caption'])
        self.assertIn('3,000원', by['f01-door-gap']['caption'])
        self.assertIn('1059209', by['f07-ramen-bowl']['caption'])
        self.assertIn('1.4', by['f07-ramen-bowl']['caption'])
        for i in ('f04-delivery-vs-cook', 'f05-membership-saving', 'f06-direct-buy-total', 'f09-resale-net'):
            with self.subTest(e=i):
                self.assertIn('가정', by[i]['caption'])
                self.assertIn('가정', ' '.join(by[i]['narration']))
        for i in ('f04-delivery-vs-cook', 'f06-direct-buy-total', 'f09-resale-net'):
            self.assertIn('가정', by[i]['threads_text'], i)
        text = json.dumps(self.items, ensure_ascii=False)
        for bad in ('써봤는데', '직접 써보니', '내돈내산'):
            self.assertNotIn(bad, text)

    def test_caption_asks_question_once(self):
        for e in self.items:
            with self.subTest(e=e['id']):
                self.assertEqual(e['caption'].count(e['question']), 1)
                body = e['caption'].split('💬')[0]
                self.assertFalse(body.rstrip().endswith('?'), body[-80:])

    def test_compare_numbers_are_stated_in_caption(self):
        """화면 비교 막대의 숫자는 캡션(가정 명시 문단)에 적힌 숫자만. 첫 10편은 카드 본문이
        나레이션(한글 수사)이라 숫자는 캡션·화면 글자로 대조한다. 막대 크기는 값 비율과 같아야 한다."""
        num = lambda t: {x.replace(',', '').rstrip('.') for x in re.findall(r'\d[\d,.]*', t)}
        for e in self.items:
            have = num(e['caption'] + ' ' + ' '.join(e['screen']))
            for i, (_, _, a, b, va, vb) in (e['compare'] or {}).items():
                with self.subTest(e=e['id'], i=i):
                    self.assertTrue(num(a) <= have and num(b) <= have, (a, b))
                    self.assertGreater(float(va), 0)
                    self.assertGreater(float(vb), 0)
        by = {e['id']: e for e in self.items}
        self.assertEqual(by['f06-direct-buy-total']['compare'][0][4:], (115, 120))   # 100,000 + 15,000
        self.assertEqual(by['f08-paid-ai-worth']['compare'][0][4:], (5, 20 * 60))    # 초 단위

    def test_ids_do_not_collide(self):
        others = {e['id'] for e in campaign.load() if e['campaign'] != 'campaign_first10'}
        posted = {p['id'] for p in json.loads((ROOT / 'content/posted.json').read_text(encoding='utf-8'))}
        mine = {e['id'] for e in self.items}
        self.assertFalse(mine & others)
        self.assertFalse(mine & posted)


class First10RoutingTests(unittest.TestCase):
    def test_first10_goes_before_campaign30(self):
        self.assertEqual(campaign.CAMPAIGNS[:2], ('campaign_first10', 'campaign30'))
        first, _ = campaign.next_ready(set(), today=F.START)
        self.assertEqual(first['id'], F.EPISODES[0]['id'])
        nxt, _ = campaign.next_ready({first['id']}, today='2026-10-16')
        self.assertEqual(nxt['id'], F.EPISODES[1]['id'])
        # 10편을 다 내면 새 30편 n01 이 잇는다
        done = {e['id'] for e in F.EPISODES}
        after, _ = campaign.next_ready(done, today='2026-10-25')
        self.assertEqual(after['id'], C30.EPISODES[0]['id'])

    def test_forced_ids_are_known(self):
        ids = campaign.ids()
        for e in F.EPISODES:
            self.assertIn(e['id'], ids)


class First10RenderTests(unittest.TestCase):
    def test_every_scene_renders_and_endings_follow_owner_decisions(self):
        D = design()
        from PIL import Image, ImageChops
        for e in F.package()['items']:
            with self.subTest(e=e['id']):
                D.BOUNDS.clear()
                frames = dict((n, im) for n, im, _ in D.render_frames(e, ROOT))
                self.assertEqual(list(frames), ['01-cover', '02-body', '03-body', '04-body', '05-body',
                                                '06-conclusion', '07-instagram-cta', '07-youtube-cta'])
                self.assertTrue(all(im.size == (1080, 1920) for im in frames.values()))
                with Image.open(ROOT / e['cover_file']) as ref:
                    diff = ImageChops.difference(frames['01-cover'].convert('RGB'), ref.convert('RGB'))
                    self.assertLess(max(hi for _, hi in diff.getextrema()), 30)
                top = (0, 0, 1080, 1300)
                d2 = ImageChops.difference(frames['07-youtube-cta'].crop(top), frames['01-cover'].crop(top))
                self.assertIsNone(d2.getbbox())
                copy = ' '.join(x['text'] for x in D.BOUNDS)
                self.assertIn(e['key']['figure'], copy)          # 결론 = 핵심 숫자(2026-09-29)
                self.assertIn('좋아요 + 구독', copy)             # 유튜브 끝(2026-10-06 A안)
                for s in e['screen']:
                    self.assertIn(s.split('\n')[0][:6], copy)
        D.BOUNDS.clear()


if __name__ == '__main__':
    unittest.main()


class ProductPhotoSceneTests(unittest.TestCase):
    """2026-10-15: 추천템(01·07) '실제 후보' 장면 — 직접 찍은 사진이 있으면 사진 장면, 없으면 글자 장면."""

    def test_photo_scene_only_when_file_exists(self):
        import shutil
        import tempfile
        from PIL import Image
        D = design()
        for key, cid in (('01', 'f01-door-gap'), ('07', 'f07-ramen-bowl')):
            sp = F.PHOTOS[key]
            e = next(x for x in F.package()['items'] if x['id'] == cid)
            if not (ROOT / sp['file']).is_file():
                self.assertEqual(e['photos'], {})                   # 사진 없으면 기존 장면
            tmp = Path(tempfile.mkdtemp())
            try:
                Image.new('RGB', (1600, 1200), '#C8B89A').save(tmp / 'p.jpg')
                e = dict(e, photos={sp['card']: dict(sp, file=str(tmp / 'p.jpg'))})
                D.BOUNDS.clear()
                im = D.render_body(e, sp['card'])                   # 절대경로는 root / file 이 그대로 둔다
                self.assertEqual(im.size, (1080, 1920))
                copy = ' '.join(x['text'] for x in D.BOUNDS)
                self.assertIn(sp['price'], copy)
                self.assertIn(sp['meta'].split('·')[0].strip(), copy)
                for x in D.BOUNDS:                                   # 글자는 릴스 버튼 자리(오른쪽) 밖으로
                    if x['text'] != sp['price']:
                        self.assertLessEqual(x['bounds'][2], 958, x)
            finally:
                shutil.rmtree(tmp)
                D.BOUNDS.clear()

    def test_photo_specs_match_checked_facts(self):
        self.assertIn('66327', F.PHOTOS['01']['meta'])
        self.assertIn('1059209', F.PHOTOS['07']['meta'])
        self.assertEqual({p['price'] for p in F.PHOTOS.values()}, {'3,000원'})


class ProductPhotoCreditTests(unittest.TestCase):
    """2026-10-15 소유자 결정: 다이소몰 대표 이미지 사용 → 화면·캡션에 출처."""

    def test_credit_on_screen_and_caption_when_photo_used(self):
        for sp in F.PHOTOS.values():
            self.assertIn('다이소몰', sp['meta'])
            self.assertTrue(sp['source_url'].startswith('https://cdn.daisomall.co.kr/'))
            self.assertNotIn('/review/', sp['source_url'])           # 고객 리뷰 사진 금지
        for e in F.package()['items']:
            with self.subTest(e=e['id']):
                if e['photos']:
                    self.assertIn(F.PHOTO_CREDIT, e['caption'])
                    self.assertIn(F.PHOTO_CREDIT, e['youtube_description'])
                else:
                    self.assertNotIn(F.PHOTO_CREDIT, e['caption'])
