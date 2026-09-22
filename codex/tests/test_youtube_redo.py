"""잠긴 유튜브 영상 다시 올리기(--redo) 회귀 테스트.

왜 이 테스트가 있나
  구글 심사 통과 전에 API 로 올린 영상은 비공개로 잠기고, 채널 주인이 손으로도
  공개로 못 바꾼다. 그런데 content/delivery.json 에는 youtube: done 이 박혀 있어
  따라올리기가 영영 그 편을 건너뛴다 — 공개된 적 없는 편이 조용히 남는다.
  (실제: cx054-taxi-vs-driver, 2026-09-16 업로드분)

지키려는 것
  · --redo 는 이전 기록을 지우지 않고 youtube_superseded 로 옮긴다
    (옛 영상 id 가 사라지면 '왜 두 번 올라갔나'를 나중에 추적할 수 없다)
  · 옮긴 뒤에는 그 편이 다시 업로드 대상이 된다 (uploaded_ids 에서 빠진다)
  · --redo 는 --id 없이 못 쓴다 (무엇을 다시 올릴지 모르는 채로 돌면 안 된다)
  · --redo 는 정기 실행(--auto)에서 못 쓴다 (사람이 누르는 복구 경로다)
  · 옮길 기록이 없어도 오류로 죽지 않는다
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import youtube_run


class SupersedeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ledger = self.tmp / 'delivery.json'

    def _write(self, data):
        self.ledger.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

    def _run(self, item_id):
        with patch('src.run.DELIVERY', self.ledger), \
             patch('src.run.sh', return_value=''), \
             patch('src.run.push'):
            return youtube_run.supersede_youtube(item_id)

    def test_moves_record_instead_of_deleting(self):
        self._write({'cx054': {'youtube': {'status': 'done', 'id': 'OLD1',
                                           'at': '2026-09-16T11:05:01+09:00'}}})
        old = self._run('cx054')
        self.assertEqual(old['id'], 'OLD1')
        after = json.loads(self.ledger.read_text(encoding='utf-8'))
        self.assertNotIn('youtube', after['cx054'])
        self.assertEqual([r['id'] for r in after['cx054']['youtube_superseded']], ['OLD1'])

    def test_other_platforms_untouched(self):
        self._write({'cx054': {'youtube': {'status': 'done', 'id': 'OLD1'},
                               'instagram': {'status': 'done', 'id': 'IG1'}}})
        self._run('cx054')
        after = json.loads(self.ledger.read_text(encoding='utf-8'))
        self.assertEqual(after['cx054']['instagram'], {'status': 'done', 'id': 'IG1'})

    def test_becomes_uploadable_again(self):
        self._write({'cx054': {'youtube': {'status': 'done', 'id': 'OLD1'}}})
        with patch.object(youtube_run, 'DELIVERY', self.ledger):
            self.assertIn('cx054', youtube_run.uploaded_ids())
        self._run('cx054')
        with patch.object(youtube_run, 'DELIVERY', self.ledger):
            self.assertNotIn('cx054', youtube_run.uploaded_ids())

    def test_superseded_does_not_count_against_daily_cap(self):
        # 지난 기록은 '오늘 올린 편'이 아니다. 상한을 헛되이 깎으면 안 된다.
        self._write({'cx054': {'youtube_superseded': [{'status': 'done', 'id': 'OLD1'}]}})
        with patch.object(youtube_run, 'DELIVERY', self.ledger):
            self.assertEqual(youtube_run.uploaded_today(), (0, []))

    def test_missing_record_is_not_an_error(self):
        self._write({'cx054': {'instagram': {'status': 'done', 'id': 'IG1'}}})
        self.assertIsNone(self._run('cx054'))

    def test_unknown_item_is_not_an_error(self):
        self._write({})
        self.assertIsNone(self._run('없는편'))


class RedoGuardTests(unittest.TestCase):
    """--redo 를 잘못 쓰면 아무것도 올리지 않고 멈춘다."""

    def _main(self, argv):
        with patch.object(youtube_run, 'supersede_youtube') as sup, \
             patch('sys.argv', ['youtube_run'] + argv):
            code = youtube_run.main()
        return code, sup.called

    def test_redo_without_id_stops(self):
        code, called = self._main(['--redo'])
        self.assertEqual(code, 1)
        self.assertFalse(called)

    def test_redo_with_auto_stops(self):
        code, called = self._main(['--redo', '--id', 'cx054', '--auto'])
        self.assertEqual(code, 1)
        self.assertFalse(called)


if __name__ == '__main__':
    unittest.main()
