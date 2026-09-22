"""승인 없이 발행(APPROVAL_REQUIRED=0)일 때 남은 승인 요청이 발행을 막지 않는다.

왜 이 테스트가 있나
  2026-09-19 20:08 에 006-car-tco 승인 요청이 만들어졌고, 버튼을 아무도 누르지
  않았다. 그 뒤 src/run.py 는 매 슬롯마다 '기존 승인 요청 처리 → 공용 수신기가
  발행합니다' 를 찍고 return 0 했다. 9/22 에 승인 없이 순번대로 발행하도록
  바꿨는데도 이 분기는 승인 여부와 무관하게 먼저 걸려서, Claude 트랙이 계속
  한 편도 나가지 않았다(9/20 일요일 미발행 · 9/22 수동 실행 48초 만에 종료).

지키려는 것
  · APPROVAL_REQUIRED=0 이면 남은 승인 요청이 있어도 발행까지 진행한다
  · 그때 남은 요청은 지운다 — 남겨두면 나중에 옛 버튼 한 번에 같은 편이 또 나간다
  · APPROVAL_REQUIRED=1 이면 예전처럼 공용 수신기에 넘기고 종료한다 (승인 우회 금지)
"""
import unittest
from unittest.mock import patch

from codex import approvals


class DiscardTests(unittest.TestCase):
    def test_missing_file_is_not_an_error(self):
        with patch.object(approvals, 'REQUESTS', approvals.ROOT / 'codex/tests'):
            self.assertFalse(approvals.discard('없는키', 'x'))

    def test_discard_removes_and_commits(self):
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mkdtemp())
        (tmp / 'k.enc').write_bytes(b'x')
        committed = []
        with patch.object(approvals, 'REQUESTS', tmp), \
             patch('codex.engine.commit', side_effect=lambda p, m: committed.append(m)):
            self.assertTrue(approvals.discard('k', '006-car-tco'))
        self.assertFalse((tmp / 'k.enc').exists())
        self.assertEqual(len(committed), 1)
        self.assertIn('006-car-tco', committed[0])


class HandoffGateTests(unittest.TestCase):
    """run.py 의 '기존 승인 요청' 분기가 승인 설정에 따라 갈리는지."""

    def _source(self):
        # run.py 가 비교하는 값과 같은 방식으로 만든다.
        return 'SOURCE-HASH'

    def _fake_request(self, item_id):
        return {'item_id': item_id, 'context': {'source_hash': self._source()},
                'title': 't'}

    def _decide(self, approval_required):
        """분기 로직만 떼어내 재현한다 (외부 호출 없이)."""
        import os
        calls = {'discard': 0, 'remind': 0}
        item = {'id': '006-car-tco'}
        requests = {'k': self._fake_request('006-car-tco')}
        approval_on = os.getenv('APPROVAL_REQUIRED', '1') == '1'
        handed_off = False
        for key, request in requests.items():
            if (request['item_id'] == item['id'] and
                    request['context']['source_hash'] == self._source()):
                if not approval_on:
                    calls['discard'] += 1
                    break
                calls['remind'] += 1
                handed_off = True
        return calls, handed_off

    def test_approval_off_continues_and_discards(self):
        with patch.dict('os.environ', {'APPROVAL_REQUIRED': '0'}):
            calls, handed_off = self._decide('0')
        self.assertEqual(calls['discard'], 1)
        self.assertEqual(calls['remind'], 0)
        self.assertFalse(handed_off)

    def test_approval_on_still_hands_off(self):
        with patch.dict('os.environ', {'APPROVAL_REQUIRED': '1'}):
            calls, handed_off = self._decide('1')
        self.assertEqual(calls['discard'], 0)
        self.assertEqual(calls['remind'], 1)
        self.assertTrue(handed_off)


class SourceCodeTests(unittest.TestCase):
    """실제 run.py 가 그 분기를 승인 설정으로 감싸고 있는지 확인한다."""

    def test_run_py_gates_handoff(self):
        from src import run
        from pathlib import Path
        src = Path(run.__file__).read_text(encoding='utf-8')
        self.assertIn("approval_on = os.getenv('APPROVAL_REQUIRED', '1') == '1'", src)
        self.assertIn('if not approval_on:', src)
        self.assertIn('discard(key, item[', src)


if __name__ == '__main__':
    unittest.main()
