"""2026-09-22 소유자 결정: 승인 없이 순번대로 매 슬롯 자동 발행(GPT 트랙)."""
import copy
import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from codex import engine as eng
from codex.engine import AUTO_SOURCE, Engine, KST, eligible, next_in_line

ROOT = Path(__file__).parents[1]


def items():
    return copy.deepcopy(json.loads((ROOT / 'content.json').read_text(encoding='utf-8'))['items'])


class AutoDailyTests(unittest.TestCase):
    def engine(self, records=None):
        e = object.__new__(Engine)
        e.items = items()
        e.state = {'offset': 0, 'records': records or {}}
        e.save = Mock(); e.tell = Mock(); e.publish = Mock()
        e.price_check = Mock(return_value=True)
        return e

    def run_auto(self, e, now):
        with patch.object(eng, 'render', return_value={'sha256': {}, 'cards': []}), \
             patch.object(eng, 'commit'), patch.object(eng, 'git', return_value='abc'):
            e.auto_publish(now)

    def test_queue_order_skips_posted_and_closed(self):
        its = items()
        first = next_in_line(its, {})[0]
        self.assertTrue(all(first['publish_at'] <= i['publish_at'] for i in next_in_line(its, {})))
        closed = {first['id']: {'closed': True}}
        self.assertNotEqual(next_in_line(its, closed)[0]['id'], first['id'])
        self.assertTrue(all(not i.get('posted_early_on') for i in next_in_line(its, {})))

    def test_wednesday_after_slot_publishes_next_in_line_once(self):
        e = self.engine()
        wed = datetime(2026, 9, 23, 21, 25, tzinfo=KST)
        self.run_auto(e, wed)
        e.publish.assert_called_once()
        item, rec, _ = e.publish.call_args[0]
        self.assertEqual(item['id'], next_in_line(items(), {})[0]['id'])
        self.assertEqual((rec['review_kind'], rec['auto_date'], rec['approval_source']),
                         ('auto', '2026-09-23', AUTO_SOURCE))
        self.run_auto(e, wed.replace(minute=45))     # 같은 날 두 번째 틱
        e.publish.assert_called_once()

    def test_nothing_before_slot_or_on_claude_days(self):
        for now in (datetime(2026, 9, 23, 21, 0, tzinfo=KST),    # 수 21:20 이전
                    datetime(2026, 9, 22, 22, 0, tzinfo=KST),    # 화 = Claude 트랙
                    datetime(2026, 9, 27, 16, 0, tzinfo=KST)):   # 일 = Claude 트랙
            e = self.engine()
            self.run_auto(e, now)
            e.publish.assert_not_called()

    def test_price_mismatch_skips_to_next_item(self):
        e = self.engine()
        line = next_in_line(items(), {})
        e.price_check = Mock(side_effect=lambda it: it['id'] != line[0]['id'])
        self.run_auto(e, datetime(2026, 9, 25, 15, 40, tzinfo=KST))
        self.assertEqual(e.publish.call_args[0][0]['id'], line[1]['id'])

    def test_already_posted_today_blocks_second_post(self):
        rec = {'closed': True, 'operations': {'instagram': {'status': 'done', 'at': '2026-09-23T10:00:00+09:00'}}}
        e = self.engine({'cx103-taxi-transit': rec})
        self.run_auto(e, datetime(2026, 9, 23, 21, 30, tzinfo=KST))
        e.publish.assert_not_called()

    def test_auto_authority_only_on_its_day(self):
        item = items()[0]
        rec = {'review_kind': 'auto', 'decision': 'approved', 'approval_source': AUTO_SOURCE,
               'auto_date': '2026-09-23'}
        self.assertTrue(eligible(item, rec, datetime(2026, 9, 23, 23, 0, tzinfo=KST)))
        self.assertFalse(eligible(item, rec, datetime(2026, 9, 24, 0, 5, tzinfo=KST)))
        self.assertFalse(eligible(item, dict(rec, approval_source='x'), datetime(2026, 9, 23, 23, 0, tzinfo=KST)))

    def test_tick_sends_no_approval_previews(self):
        e = self.engine()
        e.preview = Mock(); e.callbacks = Mock(); e.observations = Mock(); e.auto_publish = Mock()
        e.tg = Mock(side_effect=lambda m, **k: {'username': 'donvalue_approval_bot'} if m == 'getMe' else {})
        with patch('codex.approvals.publish_due'), patch('codex.approvals.migrate_buttons'):
            e.run('tick')
        e.preview.assert_not_called()
        e.auto_publish.assert_called_once()


if __name__ == '__main__':
    unittest.main()
