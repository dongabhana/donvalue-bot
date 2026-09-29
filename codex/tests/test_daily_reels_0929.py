"""2026-09-29 소유자 요청 회귀 테스트.

  · 인스타는 릴스만, 해시태그는 검색되는 것만 5개까지(#분기점·#돈값하나 금지)
  · 인스타·유튜브·영상 끝에 좋아요·팔로우(유튜브는 구독) 유도
  · 쓰레드는 본편 글 + 스하리 글만(단문 콘텐츠 끔, 하루 1번)
  · 새 일상 주제를 앞에, 예전 미발행 편은 보관(hold)
  · 표지 없는 편은 내지 않고 알린다
  · GPT 트랙 자동 발행은 기본 꺼짐(한 파이프라인)
"""
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from src import hooks, microposts, run, tags, tts, youtube

ROOT = Path(__file__).resolve().parents[2]
NEW = ['d001-snooze-taxi', 'd002-kpass-offpeak', 'd003-lotto-weekly', 'd004-one-plus-one',
       'd005-tumbler-400', 'd006-late-night-delivery', 'd007-vinyl-umbrella']


def queue():
    return hooks.attach(yaml.safe_load((ROOT / 'content/queue.yaml').read_text(encoding='utf-8')))


def hashtags_in(text):
    return re.findall(r'(?<!\S)#([^\s#]+)', text)


class TagTests(unittest.TestCase):
    def test_blocked_tags_never_reach_instagram(self):
        item = {'hashtags': ['돈값하나', '분기점', '비교분석', '몰라서내는돈', '택시']}
        out = tags.instagram(item)
        self.assertEqual(out[0], '택시')
        for bad in ('돈값하나', '분기점', '비교분석', '몰라서내는돈'):
            self.assertNotIn(bad, out)
        self.assertLessEqual(len(out), 5)

    def test_strip_all_removes_inline_tags(self):
        self.assertEqual(tags.strip_all('본문 #돈값하나 #택시\n\n#분기점'), '본문')


class CaptionTests(unittest.TestCase):
    def setUp(self):
        self.items = {i['id']: i for i in queue()['items']}

    def test_instagram_caption_asks_like_and_follow_with_five_tags(self):
        for iid in NEW:
            with self.subTest(iid):
                cap = run.build_caption(self.items[iid], queue().get('cta') or {})
                self.assertIn('좋아요', cap)
                self.assertIn('팔로우', cap)
                found = hashtags_in(cap)
                self.assertLessEqual(len(found), 5)
                self.assertFalse(set(found) & tags.BLOCKED)
                self.assertLessEqual(len(cap), 2200)

    def test_youtube_description_asks_subscribe_not_instagram_cta(self):
        for iid in NEW:
            with self.subTest(iid):
                item = self.items[iid]
                desc = youtube.build_description(item, run.build_caption(item, queue().get('cta')))
                self.assertIn('구독', desc)
                self.assertNotIn(hooks.IG_CTA, desc)
                found = hashtags_in(desc)
                self.assertEqual(found[0], 'Shorts')
                self.assertLessEqual(len(found), 5)
                self.assertFalse(set(found) & tags.BLOCKED)

    def test_youtube_title_uses_written_title(self):
        item = self.items['d003-lotto-weekly']
        title = youtube.build_title(item, hooks.resolve(item))
        self.assertTrue(title.startswith(item['yt_title']))
        self.assertLessEqual(len(title), youtube.TITLE_MAX)


class NarrationTests(unittest.TestCase):
    def test_last_line_asks_like_and_follow(self):
        self.assertIn('팔로우', tts._with_cta('지금 현관에 우산 몇 개야?'))
        # 이미 말했으면 두 번 말하지 않는다
        self.assertEqual(tts._with_cta('팔로우 해 둬'), '팔로우 해 둬')


class QueueTests(unittest.TestCase):
    def test_new_daily_items_come_first_and_old_unposted_are_held(self):
        q = queue()
        posted = {p['id'] for p in json.loads((ROOT / 'content/posted.json').read_text())}
        self.assertEqual([i['id'] for i in q['items'][:len(NEW)]], NEW)
        for item in q['items'][len(NEW):]:
            if item['id'] not in posted:
                self.assertTrue(item.get('hold'), item['id'])

    def test_new_items_are_complete(self):
        q = queue()
        scripts = yaml.safe_load((ROOT / 'content/narration.yaml').read_text(encoding='utf-8'))
        for item in q['items'][:len(NEW)]:
            with self.subTest(item['id']):
                self.assertTrue(item['verified'])
                self.assertIn(item['id'], scripts)
                h = hooks.resolve(item)
                self.assertEqual(hooks.validate(item), [])
                self.assertFalse(h['loop'].endswith('…'), '마지막 질문이 잘리면 안 된다')
                self.assertEqual(item.get('threads_chain'), [])
                # 가정값을 쓴 편은 캡션·쓰레드에 가정이라고 밝힌다(AGENTS.md 규칙)
                if '가정' in str(item.get('sources', '')):
                    self.assertIn('가정', item['caption'])
                    self.assertIn('가정', item['threads_text'])


class PickTests(unittest.TestCase):
    def q(self):
        return {'items': [{'id': 'a', 'verified': True, 'hold': True},
                          {'id': 'b', 'verified': True},
                          {'id': 'c', 'verified': True}]}

    def test_hold_is_skipped_and_missing_cover_is_skipped_with_notice(self):
        with patch.object(run, 'has_cover', side_effect=lambda i: i['id'] == 'c'), \
             patch.object(run, '_tell_cover_missing') as tell, \
             patch.dict(os.environ, {'REQUIRE_COVER': '1'}):
            item = run.pick_next(self.q(), set())
        self.assertEqual(item['id'], 'c')
        tell.assert_called_once_with(['b'], picked='c')

    def test_nothing_ready_returns_none_and_notifies(self):
        with patch.object(run, 'has_cover', return_value=False), \
             patch.object(run, '_tell_cover_missing') as tell, \
             patch.dict(os.environ, {'REQUIRE_COVER': '1'}):
            self.assertIsNone(run.pick_next(self.q(), set()))
        tell.assert_called_once_with(['b', 'c'], picked='')


class ThreadsTests(unittest.TestCase):
    def test_only_soft_track_is_allowed(self):
        pool = microposts.load_pool()
        self.assertEqual(pool.get('tracks'), ['soft'])
        with patch.dict(os.environ, {'TH_USER_ID': '', 'TH_ACCESS_TOKEN': ''}):
            self.assertEqual(microposts.run(1, dry_run=True, track='content'), 0)

    def test_skipped_duplicates_are_not_picked(self):
        pool = microposts.load_pool()
        picks = microposts.pick(pool, set(), 100, 'soft')
        self.assertNotIn('sp009-printer', [p['id'] for p in picks])

    def test_micro_workflow_runs_once_a_day(self):
        src = (ROOT / '.github/workflows/threads-micro.yml').read_text(encoding='utf-8')
        self.assertEqual(re.findall(r'cron: "([^"]+)"', src), ['40 12 * * *'])


class ScheduleTests(unittest.TestCase):
    def test_post_runs_every_day(self):
        src = (ROOT / '.github/workflows/post.yml').read_text(encoding='utf-8')
        days = set()
        for spec in re.findall(r'cron: "[^"]* \* \* ([^"]+)"', src):
            for part in spec.split(','):
                if '-' in part:
                    a, b = map(int, part.split('-'))
                    days.update(range(a, b + 1))
                else:
                    days.add(int(part))
        self.assertEqual(days, set(range(7)))


if __name__ == '__main__':
    unittest.main()
