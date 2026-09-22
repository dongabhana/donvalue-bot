"""2026-09-21 회귀: 발행 시각 변경 후 엔진이 매 실행 멈춰 월요일 편이 안 올라간 건."""
import copy
import json
import re
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from codex.engine import ALLOWED_SLOTS, Engine, KST, fingerprint, validate

ROOT = Path(__file__).parents[1]


def items():
    return json.loads((ROOT / 'content.json').read_text(encoding='utf-8'))['items']


class SlotTimeTests(unittest.TestCase):
    def test_every_queued_item_passes_engine_validate(self):
        # 빌더는 통과하고 엔진은 거부하던 불일치를 잡는다.
        for item in items():
            with self.subTest(item=item['id']):
                validate(item)

    def test_new_peak_slots_accepted_and_others_rejected(self):
        base = next(i for i in items() if i['publish_at'].endswith('21:20:00+09:00'))
        for stamp, ok in [('2026-09-28T21:20:00+09:00', True),   # 월
                          ('2026-10-02T15:30:00+09:00', True),   # 금
                          ('2026-09-23T20:00:00+09:00', True),   # 수(기존 편)
                          ('2026-09-28T20:05:00+09:00', False),
                          ('2026-09-29T21:20:00+09:00', False)]:  # 화 = Claude 트랙
            item = copy.deepcopy(base); item['publish_at'] = stamp
            with self.subTest(stamp=stamp):
                if ok: validate(item)
                else: self.assertRaises(AssertionError, validate, item)

    def test_engine_and_builder_allow_the_same_slots(self):
        src = (ROOT / 'build_threshold_queue.py').read_text(encoding='utf-8')
        line = next(l for l in src.splitlines() if '(d.hour,d.minute) in' in l)
        builder = {tuple(map(int, t)) for t in re.findall(r'\((\d+),(\d+)\)', line)}
        self.assertEqual(builder, set(ALLOWED_SLOTS))


class SourceFieldTests(unittest.TestCase):
    def official(self):
        return copy.deepcopy(next(i for i in items() if i['id'].startswith('cx103')))

    def test_source_without_offers_is_accepted(self):
        item = self.official()
        self.assertTrue(all('offers' not in s for s in item['verification']['sources']))
        validate(item)

    def test_source_missing_what_price_check_needs_is_rejected(self):
        for field in ('required_tokens', 'scope_start', 'scope_end'):
            item = self.official(); del item['verification']['sources'][0][field]
            with self.subTest(field=field):
                self.assertRaises(AssertionError, validate, item)

    def test_empty_offers_is_still_rejected(self):
        item = self.official(); item['verification']['sources'][0]['offers'] = {}
        self.assertRaises(AssertionError, validate, item)


class StaleApprovalTests(unittest.TestCase):
    def setUp(self):
        self.item = copy.deepcopy(items()[0])
        self.item['publish_at'] = '2026-09-21T21:20:00+09:00'
        manifest = {'sha256': {}}
        self.rec = {'decision': 'approved', 'review_kind': 'real', 'approval_policy': 'unified-v2',
                    'approved_at': '2026-09-20T21:00:00+09:00',
                    'scheduled_at': '2026-09-21T21:20:00+09:00',
                    'manifest': manifest, 'hash': 'stale-approval-hash', 'operations': {}}
        self.e = object.__new__(Engine)
        self.e.save = Mock(); self.e.tell = Mock()
        self.e.price_check = Mock(return_value=True)
        self.now = datetime(2026, 9, 21, 21, 30, tzinfo=KST)

    def test_content_changed_after_approval_skips_without_crashing(self):
        # 예전에는 RuntimeError 로 엔진 전체가 멈췄다.
        self.e.publish(self.item, self.rec, self.now)
        self.e.publish(self.item, self.rec, self.now)
        self.assertEqual(self.e.tell.call_count, 1)   # 알림은 한 번만
        self.assertEqual(self.rec['operations'], {})  # 게시 시도 없음


if __name__ == '__main__':
    unittest.main()
