"""2026-09-22 회귀: 발행이 조용히 멈추던 경로들."""
import argparse
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from codex import approvals, owner_now
from src import run

KST = timezone(timedelta(hours=9))


class SlotTests(unittest.TestCase):
    def test_slots_follow_peak_schedule(self):
        cases = {datetime(2026, 9, 22, 9, 0, tzinfo=KST): '21:20',   # 화
                 datetime(2026, 9, 24, 9, 0, tzinfo=KST): '21:20',   # 목
                 datetime(2026, 9, 25, 9, 0, tzinfo=KST): '15:30',   # 금
                 datetime(2026, 9, 27, 9, 0, tzinfo=KST): '15:30'}   # 일
        for day, hm in cases.items():
            with self.subTest(day=day):
                self.assertEqual(run.slot_for(day).strftime('%H:%M'), hm)

    def test_matches_post_cron(self):
        # post.yml: 화·목 12:20 UTC(21:20 KST), 일 06:30 UTC(15:30 KST)
        src = (Path(run.__file__).parents[1] / '.github/workflows/post.yml').read_text(encoding='utf-8')
        self.assertIn('"20 12 * * 2,4"', src)
        self.assertIn('"30 6 * * 0"', src)
        self.assertEqual(run.SLOTS[1], (21, 20))
        self.assertEqual(run.SLOTS[6], (15, 30))


class RemindTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': 'test-token'})
        self.env.start()
        self.request = {'item_id': '009-certificate', 'title': '자격증 (reel)', 'message_id': 10,
                        'context': {'scheduled_at': '2026-09-20T20:00:00+09:00'}}

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def call(self, decision_rec):
        send = Mock(return_value={'message_id': 99})
        with patch.object(approvals, 'REQUESTS', Path(self.tmp.name)), \
             patch.object(approvals, 'state', return_value={'shared_reviews': {'k1': decision_rec}}), \
             patch('src.notify.send_message', send), patch('codex.engine.commit') as commit:
            result = approvals.remind('k1', self.request, '2026-09-24T21:20:00+09:00')
        return result, send, commit

    def test_undecided_request_gets_fresh_buttons_and_new_slot(self):
        result, send, commit = self.call({})
        self.assertEqual(result, 'reminded')
        send.assert_called_once()
        self.assertEqual(self.request['message_id'], 99)
        self.assertEqual(self.request['context']['scheduled_at'], '2026-09-24T21:20:00+09:00')
        commit.assert_called_once()
        saved = approvals.cipher('test-token').decrypt((Path(self.tmp.name) / 'k1.enc').read_bytes())
        self.assertEqual(json.loads(saved)['message_id'], 99)

    def test_deferred_request_is_also_resent(self):
        result, send, _ = self.call({'decision': 'deferred'})
        self.assertEqual(result, 'reminded')
        self.assertIn('미뤄 둔', send.call_args[0][0])

    def test_approved_or_done_is_left_alone(self):
        for rec in ({'decision': 'approved', 'scheduled_at': 'x'}, {'done': True}, {'started': 'x'}):
            with self.subTest(rec=rec):
                _, send, commit = self.call(rec)
                send.assert_not_called(); commit.assert_not_called()

    def test_earlier_slot_never_moves_schedule_backwards(self):
        self.request['context']['scheduled_at'] = '2026-09-27T15:30:00+09:00'
        self.call({})
        self.assertEqual(self.request['context']['scheduled_at'], '2026-09-27T15:30:00+09:00')


class DailyGuardTests(unittest.TestCase):
    def test_slot_run_does_nothing_after_todays_post(self):
        today = datetime.now(KST).isoformat()
        args = argparse.Namespace(id=None, pick='', tomorrow=False, dry_run=False, ask_tomorrow=False)
        with patch.object(run, 'load_posted', return_value=[{'id': '006-car-tco', 'posted_at': today}]), \
             patch.object(run, 'pick_next') as pick:
            self.assertEqual(run.run_once(args), 0)
        pick.assert_not_called()

    def test_eve_approval_still_runs_after_todays_post(self):
        today = datetime.now(KST).isoformat()
        args = argparse.Namespace(id=None, pick='', tomorrow=True, dry_run=False, ask_tomorrow=True)
        with patch.object(run, 'load_posted', return_value=[{'id': '006-car-tco', 'posted_at': today}]), \
             patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': ''}), \
             patch.object(run, 'pick_next', return_value=None) as pick:
            self.assertEqual(run.run_once(args), 0)
        pick.assert_called_once()


class OwnerNowTests(unittest.TestCase):
    def rec(self, **kw):
        base = {'decision': 'approved', 'review_kind': 'owner_now', 'approval_source': owner_now.SOURCE}
        base.update(kw); return base

    def test_only_that_item_on_that_day(self):
        item = {'id': owner_now.ITEM_ID}
        ok = datetime(2026, 9, 22, 10, 0, tzinfo=KST)
        self.assertTrue(owner_now.authorized_now(item, self.rec(), ok))
        self.assertFalse(owner_now.authorized_now(item, self.rec(), ok + timedelta(days=1)))
        self.assertFalse(owner_now.authorized_now({'id': 'cx104-self-full-gas'}, self.rec(), ok))
        self.assertFalse(owner_now.authorized_now(item, self.rec(approval_source='other'), ok))
        self.assertFalse(owner_now.authorized_now(item, self.rec(decision='pending'), ok))


if __name__ == '__main__':
    unittest.main()
