import copy
import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from codex.engine import Engine, KST, eligible, fingerprint
from codex import approvals
from src import notify


class UnifiedApprovalTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 19, 20, 30, tzinfo=KST)
        self.item = json.loads((Path(__file__).parents[1] / 'content.json').read_text())['items'][0]
        self.item = copy.deepcopy(self.item)
        self.item['publish_at'] = '2026-09-19T20:00:00+09:00'
        manifest = {'sha256': {}}
        self.rec = {'decision': 'pending', 'review_kind': 'real', 'manifest': manifest,
                    'hash': fingerprint(self.item, manifest), 'message_id': 4, 'operations': {}}
        self.e = object.__new__(Engine)
        self.e.items = [self.item]
        self.e.owner = {'user_id': 1, 'chat_id': 1}
        self.e.state = {'offset': 0, 'records': {self.item['id']: self.rec}}
        self.e.save = Mock()
        self.e.tell = Mock()

    def click(self, data, message_id=4, sender=1):
        update = {'update_id': 22, 'callback_query': {'id': 'test', 'from': {'id': sender},
                  'message': {'message_id': message_id, 'chat': {'id': 1}}, 'data': data}}
        self.e.tg = Mock(side_effect=lambda method, **kw: [update] if method == 'getUpdates' else True)
        with patch('codex.engine.datetime') as clock:
            clock.now.return_value = self.now
            self.e.callbacks()

    def test_gpt_same_day_click_saves_and_confirms(self):
        order = []
        self.e.save.side_effect = lambda: order.append('save')
        self.e.tell.side_effect = lambda text: order.append(text)
        self.click('a|' + self.item['id'] + '|' + self.rec['hash'][:12])
        self.assertEqual(self.rec['decision'], 'approved')
        self.assertEqual(order[0], 'save')
        self.assertTrue(any('승인됐어요' in value for value in order))
        self.assertFalse(eligible(self.item, self.rec, self.now))
        self.assertTrue(eligible(self.item, self.rec, self.now + timedelta(minutes=2)))

    def test_gpt_defer_never_publishes_and_can_be_approved_later(self):
        self.click('h|' + self.item['id'] + '|' + self.rec['hash'][:12])
        self.assertEqual(self.rec['decision'], 'deferred')
        self.assertFalse(eligible(self.item, self.rec, self.now + timedelta(days=3)))
        self.now += timedelta(days=2)
        self.click('a|' + self.item['id'] + '|' + self.rec['hash'][:12])
        self.assertTrue(eligible(self.item, self.rec, self.now + timedelta(minutes=2)))

    def test_claude_click_is_not_swallowed_by_gpt_receiver(self):
        request = {'message_id': 4, 'title': 'Claude example', 'context': {'scheduled_at': self.item['publish_at']}}
        with patch.object(approvals, 'load_requests', return_value={'abc': request}), \
             patch.object(approvals, 'validate_request'):
            self.click('v|abc|a')
        self.assertEqual(self.e.state['shared_reviews']['abc']['decision'], 'approved')
        self.assertTrue(any('승인됐어요' in call.args[0] for call in self.e.tell.call_args_list))

    def test_foreign_sender_cannot_approve_either_track(self):
        self.click('v|abc|a', sender=2)
        self.assertNotIn('shared_reviews', self.e.state)
        self.e.tell.assert_not_called()

    def test_wrong_message_cannot_approve_claude(self):
        with patch.object(approvals, 'load_requests', return_value={'abc': {'message_id': 99}}):
            self.click('v|abc|a')
        self.assertNotIn('shared_reviews', self.e.state)

    def test_failed_persistence_never_says_approved(self):
        self.e.save.side_effect = RuntimeError('storage unavailable')
        with self.assertRaises(RuntimeError):
            self.click('a|' + self.item['id'] + '|' + self.rec['hash'][:12])
        self.e.tell.assert_not_called()

    def test_confirmation_survives_sender_failure(self):
        self.e.tell.side_effect = RuntimeError('network')
        with self.assertRaises(RuntimeError):
            self.click('a|' + self.item['id'] + '|' + self.rec['hash'][:12])
        self.assertIn('notice_pending', self.rec)
        self.e.tell = Mock()
        approvals.flush_notices(self.e)
        self.assertNotIn('notice_pending', self.rec)
        self.e.tell.assert_called_once()

    def test_legacy_sender_does_not_poll_or_drain_telegram(self):
        with patch.object(notify, 'enabled', return_value=True), \
             patch.object(approvals, 'register', return_value=None) as register, \
             patch.object(notify, '_call') as api:
            self.assertIsNone(notify.ask('x', 'Title', 'Body', approval_context={'version': 'test'}))
        register.assert_called_once()
        api.assert_not_called()

    def test_deferred_claude_request_never_invokes_publisher(self):
        self.e.state['shared_reviews'] = {'abc': {'decision': 'deferred'}}
        with patch.object(approvals, 'load_requests', return_value={'abc': {'item_id': 'x'}}), \
             patch('src.run.run_once') as publish:
            approvals.publish_due(self.e, self.now)
        publish.assert_not_called()

    def test_changed_media_cannot_be_approved(self):
        req = {'message_id': 4, 'title': 'Test', 'context': {}}
        with patch.object(approvals, 'load_requests', return_value={'abc': req}), \
             patch.object(approvals, 'validate_request', side_effect=RuntimeError('changed')):
            with self.assertRaises(RuntimeError): self.click('v|abc|a')
        self.assertNotEqual(self.e.state['shared_reviews']['abc'].get('decision'), 'approved')
        self.e.tell.assert_not_called()


if __name__ == '__main__':
    unittest.main()
