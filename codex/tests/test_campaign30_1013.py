"""새 30편(codex/campaign30.py, 2026-10-15~) 회귀 테스트.

  · 30편 모두 표지 → 본문 4 → 결론 → 플랫폼별 마지막 장, 나레이션 6줄 + CTA
  · 표지 30장: GPT 원본(대응표 SHA-256 일치) ↔ 운영 표지(assets/covers/<id>.editorial-v3.jpg) ↔ 원고 ID 연결
  · 발행 순서: START 전에는 27편 남은 편, START 부터는 새 30편이 번호 순서대로
  · 화면 비교 막대의 숫자는 카드 본문에 있는 숫자만
  · 유튜브 마지막 장 = 표지 위 '좋아요 + 구독'(2026-10-06 A안), 결론 = 핵심 숫자 포함(2026-09-29)
  · 계산값 검산
"""
import hashlib
import importlib.util
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

from codex import campaign30 as C          # noqa: E402
from src import campaign, tags             # noqa: E402


def design():
    spec = importlib.util.spec_from_file_location('d30', ROOT / 'tools/campaign27_design.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Campaign30PackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = C.package()['items']

    def test_thirty_complete_episodes(self):
        self.assertEqual(len(self.items), 30)
        self.assertEqual(len({e['id'] for e in self.items}), 30)
        self.assertEqual([e['order'] for e in self.items], list(range(1, 31)))
        for e in self.items:
            with self.subTest(e=e['id']):
                self.assertTrue(e['id'].startswith('n'))
                self.assertEqual(len(e['cards']), 4)
                self.assertEqual(len(e['screen']), 4)
                self.assertEqual(len(e['narration']), 6)
                self.assertTrue(e['hook'].strip())
                self.assertTrue(e['key']['figure'])
                self.assertTrue(e['sources'])
                self.assertEqual(e['cover_file'], f"assets/covers/{e['id']}.editorial-v3.jpg")
                self.assertTrue(e['cover_ready'], e['cover_note'])
                self.assertIn('팔로우', e['cta']['instagram']['narration'])
                self.assertIn('구독', e['cta']['youtube']['narration'])
                self.assertNotIn('팔로우', e['cta']['youtube']['narration'])
                self.assertLessEqual(len(e['threads_text']), 500)
                self.assertLessEqual(len(e['ig_tags']), 5)
                for t in e['ig_tags']:
                    self.assertFalse(tags.is_blocked(t), t)

    def test_hashtags_are_measured_mid_size(self):
        """2026-10-15 소유자 지적: 아무도 안 찾는 태그 금지. 실측 게시물 수 1.5만~70만만."""
        from src.tags import CORE
        core = dict(CORE)
        for e in self.items:
            with self.subTest(e=e['id']):
                self.assertEqual(len(e['ig_tags']), 5)
                self.assertLessEqual(len(e['hashtags']), 3)
                for t in e['ig_tags']:
                    n = C.TAG_COUNTS.get(t, core.get(t))
                    self.assertIsNotNone(n, f'{t}: 게시물 수 기록 없음 — 조회 후 TAG_COUNTS 에 적을 것')
                    self.assertTrue(C.TAG_MIN <= n <= C.TAG_MAX, (t, n))
                self.assertEqual(e['threads_tag'], e['hashtags'][0])

    def test_ids_do_not_collide_with_other_tracks(self):
        others = {e['id'] for e in campaign.load() if e['campaign'] != 'campaign30'}
        posted = {p['id'] for p in json.loads((ROOT / 'content/posted.json').read_text(encoding='utf-8'))}
        mine = {e['id'] for e in self.items}
        self.assertFalse(mine & others)
        self.assertFalse(mine & posted)

    def test_cover_pack_is_linked_to_scripts(self):
        pack = ROOT / C.PACK
        manifest = json.loads((pack / 'manifest.json').read_text(encoding='utf-8'))
        by_order = {e['order']: e for e in self.items}
        self.assertEqual(len(manifest), 30)
        for row in manifest:
            e = by_order[row['sequence']]
            with self.subTest(seq=row['sequence']):
                self.assertEqual(row['content_id'], e['id'])
                self.assertTrue(e['product'].startswith(row['title'].split(':')[0]))
                src = pack / row['file']
                self.assertEqual(hashlib.sha256(src.read_bytes()).hexdigest(), row['sha256'])
                from PIL import Image
                with Image.open(ROOT / e['cover_file']) as im:
                    self.assertEqual(im.size, (1080, 1920))
                    self.assertEqual(im.format, 'JPEG')

    def test_compare_numbers_come_from_card_text(self):
        num = lambda t: {x.replace(',', '') for x in re.findall(r'\d[\d,.]*', t)}
        for e in self.items:
            for i, (_, _, a, b, va, vb) in (e['compare'] or {}).items():
                card = e['cards'][i]
                have = num(card['title'] + ' ' + card['figure'] + ' ' + card['body'])
                with self.subTest(e=e['id'], i=i):
                    self.assertTrue(num(a) <= have and num(b) <= have, (a, b, card))
                    self.assertGreater(float(va), 0)
                    self.assertGreater(float(vb), 0)

    def test_arithmetic(self):
        self.assertEqual(round(59800 * 0.5), 29900)                         # n03
        self.assertEqual(round(24780 * 24, -4), 590000)                     # n02 약 59만원
        self.assertEqual(5150 * 4, 20600)                                   # n05 약 2만원
        self.assertEqual(10300 + 6830 + 5230 + 5150, 27510)                 # n21 약 2만7천원
        self.assertEqual(round(7_200_000 * 0.17), 1_224_000)                # n22
        self.assertEqual(round(7_200_000 * 0.15), 1_080_000)
        self.assertEqual(round(9_000_000 * (0.165 - 0.132)), 297_000)
        self.assertEqual(round(10_000_000 * 0.17), 1_700_000)               # n23
        self.assertEqual(100_000 + round(100_000 * 0.44) + 60_000 - 200_000, 4_000)   # n24
        self.assertEqual(round(9_000_000 * 0.165), 1_485_000)               # n28
        self.assertEqual(round(40_000_000 * 0.03), 1_200_000)               # n26
        self.assertEqual(200 * 5, 1000)                                     # n19

    def test_known_corrections_stay(self):
        text = json.dumps(self.items, ensure_ascii=False)
        # 숨은 보험금은 금융위 2025년 말 수치(10조3천억)로 — 2차 인용 '12조'를 쓰지 않는다
        self.assertIn('10조3천억', text)
        self.assertNotIn('12조원', text)
        # 경차 환급은 종료일을 '현재 기준'으로만 말한다
        kcar = next(e for e in self.items if e['id'].endswith('kcar-refund'))
        self.assertIn('현재', kcar['note'])


class Campaign30RoutingTests(unittest.TestCase):
    def test_start_gate_then_sequence(self):
        # 2026-10-15: GPT '첫 10편'(campaign_first10)이 새 30편보다 먼저 나간다.
        # 이 테스트는 새 30편의 순서만 보므로 첫 10편은 '이미 나감'으로 둔다.
        from codex import campaign_first10 as F
        f10 = {e['id'] for e in F.EPISODES}
        before, _ = campaign.next_ready(set(f10), today='2026-10-14')
        self.assertEqual(before['campaign'], 'campaign27')
        first, _ = campaign.next_ready(set(f10), today=C.START)
        self.assertEqual(first['id'], C.EPISODES[0]['id'])
        second, _ = campaign.next_ready(f10 | {first['id']}, today='2026-10-15')
        self.assertEqual(second['id'], C.EPISODES[1]['id'])
        # 날짜 고정이 아니다: 하루 밀려도 다음 편이 이어서 나간다
        later, _ = campaign.next_ready(f10 | {C.EPISODES[0]['id']}, today='2026-11-30')
        self.assertEqual(later['id'], C.EPISODES[1]['id'])
        # 30편을 다 내면 27편 남은 편으로 넘어간다
        done = f10 | {e['id'] for e in C.EPISODES}
        after, _ = campaign.next_ready(done, today='2026-11-30')
        self.assertEqual(after['campaign'], 'campaign27')

    def test_forced_id_is_known(self):
        self.assertIn(C.EPISODES[0]['id'], campaign.ids())


class Campaign30RenderTests(unittest.TestCase):
    def test_every_scene_renders_and_endings_follow_owner_decisions(self):
        D = design()
        from PIL import ImageChops
        for e in C.package()['items']:
            with self.subTest(e=e['id']):
                frames = dict((n, im) for n, im, _ in D.render_frames(e, ROOT))
                self.assertEqual(list(frames), ['01-cover', '02-body', '03-body', '04-body', '05-body',
                                                '06-conclusion', '07-instagram-cta', '07-youtube-cta'])
                self.assertTrue(all(im.size == (1080, 1920) for im in frames.values()))
                # 완성 표지는 글자를 다시 얹지 않는다 → 운영 표지 그대로
                from PIL import Image
                with Image.open(ROOT / e['cover_file']) as ref:
                    diff = ImageChops.difference(frames['01-cover'].convert('RGB'), ref.convert('RGB'))
                    self.assertLess(max(hi for _, hi in diff.getextrema()), 30)
                # 유튜브 마지막 장 = 표지 윗부분 그대로 + 아래 '좋아요 + 구독'
                top = (0, 0, 1080, 1300)
                d2 = ImageChops.difference(frames['07-youtube-cta'].crop(top), frames['01-cover'].crop(top))
                self.assertIsNone(d2.getbbox())
        copy = ' '.join(x['text'] for x in D.BOUNDS)
        self.assertIn('좋아요 + 구독', copy)
        D.BOUNDS.clear()

    def test_conclusion_shows_key_figure(self):
        D = design()
        e = C.package()['items'][0]
        D.BOUNDS.clear()
        D.conclusion(e)
        copy = ' '.join(x['text'] for x in D.BOUNDS)
        self.assertIn(e['key']['figure'], copy)
        self.assertIn('그래서, 돈값하나?', copy)
        D.BOUNDS.clear()


if __name__ == '__main__':
    unittest.main()
