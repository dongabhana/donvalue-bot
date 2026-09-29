"""27편 캠페인 회귀 테스트 (2026-09-29 최종본).

  · 27편 모두 표지 → 본문 4 → 결론 → 플랫폼별 마지막 장, 나레이션은 화면을 읽지 않는 설명형
  · 인스타=좋아요+팔로우, 유튜브=좋아요+구독이 섞이지 않는다
  · 해시태그 5개(주제 3 + 공통 2), 검색되지 않는 태그 금지
  · 표지 재제작 대상 12편은 새 표지 파일이 들어오기 전까지 발행 대상이 아니다
  · 계산값 검산
"""
import hashlib
import json
import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]

from codex import campaign27 as C          # noqa: E402
from src import campaign, tags             # noqa: E402


def hashtags_in(text):
    return re.findall(r'(?<!\S)#([^\s#]+)', text)


class Campaign27Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(json.dumps(C.package(), ensure_ascii=False))
        cls.items = cls.data['items']

    def test_full_packages_and_platform_separation(self):
        self.assertEqual(len(self.items), 27)
        self.assertEqual(len({e['id'] for e in self.items}), 27)
        for e in self.items:
            with self.subTest(e=e['id']):
                self.assertEqual(len(e['cards']), 4)
                self.assertEqual(len(e['narration']), len(e['cards']) + 2)
                self.assertTrue((ROOT / e['cover_file']).exists())
                for c in e['cards']:
                    self.assertTrue(all(c[k] for k in ['title', 'figure', 'body']))
                # 가정값을 쓴 편은 캡션·설명·쓰레드에 가정이라고 밝힌다(AGENTS.md)
                if '가정' in e['assumptions']:
                    for key in ['caption', 'youtube_description', 'threads_text']:
                        self.assertIn('가정', e[key])
                self.assertLessEqual(len(e['threads_text']), 500)
                self.assertLessEqual(len(e['caption']), 2200)
                self.assertLessEqual(len(e['yt_title'] + ' #Shorts'), 100)
                ig, yt = e['cta']['instagram'], e['cta']['youtube']
                self.assertIn('좋아요', ig['narration']); self.assertIn('팔로우', ig['narration'])
                self.assertNotIn('구독', ig['narration'])
                self.assertIn('좋아요', yt['narration']); self.assertIn('구독', yt['narration'])
                self.assertNotIn('팔로우', yt['narration'])
                self.assertIn(C.IG_CTA, e['caption']); self.assertNotIn(C.YT_CTA, e['caption'])
                self.assertIn(C.YT_CTA, e['youtube_description']); self.assertNotIn(C.IG_CTA, e['youtube_description'])
                self.assertTrue(e['key']['figure'])

    def test_narration_explains_instead_of_reading_screen(self):
        for e in self.items:
            with self.subTest(e=e['id']):
                for line in e['narration']:
                    self.assertNotIn('?.', line)
                    for sym in ('~', '×', '→', '%p', 'km/L'):
                        self.assertNotIn(sym, line)
                # 본문 카드 문장을 그대로 읽는 편이 없어야 한다
                for card, line in zip(e['cards'], e['narration'][1:5]):
                    self.assertNotEqual(card['body'], line)

    def test_hashtags_five_searched_tags(self):
        for e in self.items:
            with self.subTest(e=e['id']):
                ig = hashtags_in(e['caption'])
                self.assertEqual(len(ig), 5)
                self.assertFalse({t.lower() for t in ig} & {b.lower() for b in tags.BLOCKED})
                for mega in ('AI', '쇼핑', '비오는날', '살림', '자동차', '유튜브', '야식'):
                    self.assertNotIn(mega, ig)
                yt = hashtags_in(e['youtube_description'])
                self.assertEqual(yt[0], 'Shorts')
                self.assertLessEqual(len(yt), 5)

    def test_cover_gate_for_twelve_reused_covers(self):
        waiting = {e['order'] for e in self.items if not e['cover_ready']}
        for n in C.NEW_COVER_NEEDED:
            e = self.items[n - 1]
            own = ROOT / f"assets/covers/{e['id']}.editorial-v3.jpg"
            ok = own.is_file() and hashlib.sha256(own.read_bytes()).hexdigest() not in C.REJECTED_COVER_SHA
            self.assertEqual(e['cover_ready'], ok, e['id'])
            self.assertEqual(e['hold'], not ok, e['id'])
        self.assertTrue(waiting <= C.NEW_COVER_NEEDED)

    def test_next_ready_follows_order_and_skips_waiting_covers(self):
        item, waiting = campaign.next_ready(set())
        first = next(e for e in self.items if e['cover_ready'])
        self.assertEqual(item['id'], first['id'])
        posted = {e['id'] for e in self.items if e['cover_ready']}
        item, waiting = campaign.next_ready(posted)
        self.assertIsNone(item)
        self.assertEqual(set(waiting), {e['id'] for e in self.items if not e['cover_ready']})

    def test_material_arithmetic_and_qualification(self):
        self.assertAlmostEqual(29000 / 15000 * 3600 / 22, 316.36, places=2)   # 5분 16초
        self.assertEqual(1550 * 44 * (.5 - .2), 20460)
        self.assertEqual((12000 - 1550) / 5 * 60, 125400)
        self.assertEqual((12000 - 1550) * 2 * 12, 250800)
        self.assertEqual((25000 - 5000) * 52, 1040000)
        self.assertEqual(round(1600000 / 730), 2192)
        self.assertEqual(round(1750000 / 1460), 1199)
        diff = 1700 / 15 - 1700 / 21.1
        self.assertAlmostEqual(diff, 32.76, places=2)
        self.assertEqual(round(3000000 / diff / 1000), 92)                     # 약 9만 2천km
        self.assertEqual(round(100 * 60 / 104), 58)
        self.assertEqual((14900 - 8500) * 12, 76800)
        self.assertEqual(round(1000000 / 1825), 548)
        self.assertEqual(round(1500000 / 1560 + 300), 1262)
        self.assertEqual(round(8145060 / 260), 31327)
        items = self.items
        self.assertIn('기대값', items[22]['cards'][1]['body'])
        self.assertIn('정액형', items[4]['cards'][3]['body'])
        self.assertIn('76', items[24]['cards'][1]['body'])
        self.assertIn('8,500', items[9]['cards'][0]['figure'])


class CampaignRoutingTests(unittest.TestCase):
    """정기 발행(run_once)이 캠페인 편을 먼저 고르는지 — 외부 호출 없이."""

    def test_run_once_publishes_campaign_first(self):
        from src import run
        import argparse
        args = argparse.Namespace(dry_run=False, id=None, tomorrow=False, ask_tomorrow=False,
                                  pick='', count=1)
        with patch.object(run, 'load_posted', return_value=[]), \
             patch('src.campaign.publish', return_value=0) as pub:
            self.assertEqual(run.run_once(args), 0)
        item = pub.call_args.args[0]
        self.assertTrue(item['id'].startswith('p'))
        self.assertTrue(item['cover_ready'])

    def test_waiting_cover_episode_cannot_be_forced(self):
        from src import run
        import argparse
        waiting = next((e for e in campaign.load() if not e['cover_ready']), None)
        if waiting is None:
            self.skipTest('표지 대기 편이 없음')
        args = argparse.Namespace(dry_run=False, id=waiting['id'], tomorrow=False,
                                  ask_tomorrow=False, pick='', count=1)
        with patch.object(run, 'load_posted', return_value=[]), \
             patch('src.campaign.publish') as pub:
            self.assertEqual(run.run_once(args), 1)
        pub.assert_not_called()


if __name__ == '__main__':
    unittest.main()
