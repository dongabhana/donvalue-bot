"""발행 전날 승인(Claude 트랙) 회귀 테스트.

지키려는 것
  · 전날 승인한 그대로만 나간다 (내용이 바뀌면 승인은 무효)
  · 승인은 그 다음 발행일 1회만 유효하다
  · '수정'을 누르면 그날은 발행하지 않는다
  · 쓴 승인은 원장에서 사라진다 (같은 승인으로 두 번 나가면 중복 발행)
"""
import argparse
import json

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from src import approval, run


def _sh(*args):
    if args[1] == 'status':
        return 'new files'
    if args[1] == 'diff':
        return ''
    if args[1] == 'rev-parse':
        return 'test-sha'
    return ''


class EveApprovalTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.queue = self.root / 'queue.yaml'
        self.queue.write_text(
            'items: [{id: test-reel, product: Test, verified: true, ig_format: reel}]')
        self.ledger = self.root / 'approval.json'
        self.images = self.root / 'images'
        # 전날 승인 때 커밋해 둔 결과물이 이미 있는 상태를 만든다.
        folder = self.images / 'test-reel'
        folder.mkdir(parents=True)
        self.cards = [folder / '01.png', folder / '02.png']
        for path in self.cards:
            path.write_bytes(b'card')
        self.mp4 = folder / 'test-reel.mp4'
        self.mp4.write_bytes(b'video')
        self.digest = approval.fingerprint('test-reel', 'reel', 'caption', '',
                                           self.cards + [self.mp4])
        self.today = datetime.now(approval.KST).date().isoformat()

    def tearDown(self):
        self._temp.cleanup()

    def write_ledger(self, decision, digest=None, publish_date=None, note=''):
        self.ledger.write_text(json.dumps({'test-reel': {
            'decision': decision,
            'ig_format': 'reel',
            'publish_date': publish_date or self.today,
            'fingerprint': digest if digest is not None else self.digest,
            'note': note,
        }}, ensure_ascii=False), encoding='utf-8')

    def publish(self, ask_return=True):
        """run_once 를 발행 모드로 돌리고 (반환값, ask 호출횟수, 렌더 호출횟수, 발행 호출횟수)."""
        args = argparse.Namespace(id=None, pick='', tomorrow=False, dry_run=False,
                                  ask_tomorrow=False)
        render = Mock(side_effect=lambda item, folder, *a: self.cards)
        ask = Mock(return_value=ask_return)
        with patch.multiple(run, QUEUE=self.queue, POSTED=self.root / 'posted.json',
                            DELIVERY=self.root / 'delivery.json', IMAGES=self.images,
                            render_item=render,
                            build_reel_for=Mock(return_value=(None, 'test')),
                            sh=Mock(side_effect=_sh), push=Mock(),
                            build_caption=Mock(return_value='caption'),
                            build_first_comment=Mock(return_value='')), \
             patch.object(approval, 'LEDGER', self.ledger), \
             patch.object(run.hooks, 'attach', side_effect=lambda q: q), \
             patch.object(run.hooks, 'validate', return_value=[]), \
             patch.object(run.notify, 'enabled', return_value=True), \
             patch.object(run.notify, 'ask', ask), \
             patch.object(run.notify, 'send_message'), \
             patch.object(run.notify, 'done'), \
             patch.object(run.publish, 'publish_instagram_reel',
                          return_value='reel-id') as publish_reel, \
             patch.object(run.publish, 'publish_instagram_comment',
                          return_value='c-id'), \
             patch.dict(run.os.environ,
                        {'GITHUB_REPOSITORY': 'test/repo', 'IG_USER_ID': 'x',
                         'IG_ACCESS_TOKEN': 'y', 'SKIP_THREADS': 'true'}, clear=True):
            rc = run.run_once(args)
        return rc, ask.call_count, render.call_count, publish_reel.call_count

    # ---------------------------------------------------------------- 승인
    def test_prior_approval_publishes_without_asking_again(self):
        self.write_ledger(approval.APPROVED)
        rc, asked, rendered, published = self.publish()
        self.assertEqual(rc, 0)
        self.assertEqual(asked, 0, '전날 승인이 있으면 당일에 다시 묻지 않는다')
        self.assertEqual(rendered, 0, '승인한 결과물을 다시 렌더하면 다른 게 나갈 수 있다')
        self.assertEqual(published, 1)

    def test_used_approval_is_removed_from_ledger(self):
        self.write_ledger(approval.APPROVED)
        self.publish()
        with patch.object(approval, 'LEDGER', self.ledger):
            self.assertIsNone(approval.load().get('test-reel'),
                              '쓴 승인이 남으면 같은 승인으로 또 나갈 수 있다')

    # ------------------------------------------------------ 승인이 무효인 경우
    def test_changed_content_invalidates_the_approval(self):
        self.write_ledger(approval.APPROVED, digest='다른지문')
        rc, asked, _, published = self.publish()
        self.assertEqual(rc, 0)
        self.assertEqual(asked, 1, '승인 후 내용이 바뀌면 그 자리에서 다시 물어야 한다')
        self.assertEqual(published, 1)

    def test_approval_expires_with_its_publish_date(self):
        yesterday = (datetime.now(approval.KST).date()
                     - timedelta(days=1)).isoformat()
        self.write_ledger(approval.APPROVED, publish_date=yesterday)
        _, asked, _, _ = self.publish()
        self.assertEqual(asked, 1, '지난 승인이 다음 회차를 통과시키면 안 된다')
        with patch.object(approval, 'LEDGER', self.ledger):
            self.assertIsNone(approval.lookup('test-reel'))

    def test_revise_decision_blocks_todays_publishing(self):
        self.write_ledger(approval.REVISE, note='금액 키워줘')
        rc, asked, _, published = self.publish()
        self.assertEqual(rc, 0)
        self.assertEqual(published, 0, "'수정'을 눌렀는데 발행되면 안 된다")
        self.assertEqual(asked, 0, "'수정'은 이미 결론이므로 다시 묻지 않는다")

    def test_no_approval_falls_back_to_asking_on_the_day(self):
        rc, asked, _, published = self.publish()
        self.assertEqual(rc, 0)
        self.assertEqual(asked, 1, '전날 승인이 없으면 기존처럼 당일에 묻는다')
        self.assertEqual(published, 1)

    def test_rejecting_on_the_day_keeps_the_queue(self):
        rc, _, _, published = self.publish(ask_return=False)
        self.assertEqual(rc, 0)
        self.assertEqual(published, 0)
        self.assertFalse((self.root / 'posted.json').exists(),
                         '반려된 편은 발행 이력에 남으면 안 된다')

    # ---------------------------------------------------------------- 원장
    def test_broken_ledger_is_loud_not_silent(self):
        self.ledger.write_text('{ 깨진 json', encoding='utf-8')
        with patch.object(approval, 'LEDGER', self.ledger):
            with self.assertRaises(RuntimeError):
                approval.load()

    def test_record_keeps_the_first_asked_time(self):
        with patch.object(approval, 'LEDGER', self.ledger):
            first = approval.record('a', approval.PENDING, 'reel', 'd', self.today)
            second = approval.record('a', approval.APPROVED, 'reel', 'd', self.today)
        self.assertEqual(first['asked_at'], second['asked_at'])
        self.assertIn('decided_at', second)
        self.assertNotIn('decided_at', first)


if __name__ == '__main__':
    unittest.main()
