"""심사 통과 전 유튜브 자동 업로드 보류 회귀 테스트.

왜 이 테스트가 있나
  구글 심사(audit) 전에 videos.insert 로 올린 영상은 비공개로 잠기고,
  채널 주인이 손으로도 공개로 못 바꾼다. 그런데 올라간 순간
  content/delivery.json 에 'youtube: done' 으로 남기 때문에,
  나중에 심사가 풀려 몰아 올릴 때 그 편들을 전부 건너뛴다.
  = 영영 공개 못 하는 편이 조용히 쌓인다.

지키려는 것
  · 보류 중에는 정기 발행이 유튜브를 아예 호출하지 않는다
  · 보류 중이어도 인스타·쓰레드 발행은 그대로 나간다
  · 보류 중에는 delivery.json 에 youtube 기록이 남지 않는다 (나중 백필이 건너뛰면 안 됨)
  · 설정 파일이 없거나 깨졌으면 '보류'로 간다 (조용히 올려버리면 안 된다)
  · hold=false 로 풀면 다시 올라간다
"""
import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src import run, youtube


def _sh(*args):
    if args[1] == 'status':
        return 'new files'
    if args[1] == 'diff':
        return ''
    if args[1] == 'rev-parse':
        return 'test-sha'
    return ''


class HoldReasonTests(unittest.TestCase):
    """content/youtube_hold.json 과 YT_AUTO 를 읽는 규칙."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.path = Path(self._temp.name) / 'youtube_hold.json'

    def tearDown(self):
        self._temp.cleanup()

    def reason(self, env=None):
        with patch.object(youtube, 'HOLD_FILE', self.path), \
             patch.dict(youtube.os.environ, env or {}, clear=True):
            return youtube.hold_reason()

    def test_hold_true_gives_a_reason(self):
        self.path.write_text(json.dumps({'hold': True, 'reason': '심사 대기'}),
                             encoding='utf-8')
        self.assertEqual(self.reason(), '심사 대기')

    def test_hold_false_releases(self):
        self.path.write_text(json.dumps({'hold': False}), encoding='utf-8')
        self.assertEqual(self.reason(), '', 'hold=false 면 올라가야 한다')

    def test_missing_file_defaults_to_hold(self):
        self.assertTrue(self.reason(),
                        '설정 파일이 없다고 조용히 올려버리면 안 된다')

    def test_broken_file_defaults_to_hold(self):
        self.path.write_text('{ 이건 json 이 아니다', encoding='utf-8')
        self.assertTrue(self.reason(),
                        '파일이 깨졌으면 보류 쪽으로 가야 안전하다')

    def test_env_overrides_the_file(self):
        self.path.write_text(json.dumps({'hold': True, 'reason': '심사 대기'}),
                             encoding='utf-8')
        self.assertEqual(self.reason({'YT_AUTO': '1'}), '',
                         'YT_AUTO=1 이면 파일보다 우선해서 올린다')
        self.path.write_text(json.dumps({'hold': False}), encoding='utf-8')
        self.assertTrue(self.reason({'YT_AUTO': '0'}),
                        'YT_AUTO=0 이면 파일이 풀려 있어도 막는다')

    def test_auto_enabled_is_the_inverse(self):
        self.path.write_text(json.dumps({'hold': False}), encoding='utf-8')
        with patch.object(youtube, 'HOLD_FILE', self.path), \
             patch.dict(youtube.os.environ, {}, clear=True):
            self.assertTrue(youtube.auto_enabled())


class PublishWithHoldTests(unittest.TestCase):
    """정기 발행(run_once)이 보류를 실제로 지키는지."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.queue = self.root / 'queue.yaml'
        self.queue.write_text(
            'items: [{id: test-reel, product: Test, verified: true, ig_format: reel}]')
        self.delivery = self.root / 'delivery.json'
        self.images = self.root / 'images'
        folder = self.images / 'test-reel'
        folder.mkdir(parents=True)
        self.cards = [folder / '01.png', folder / '02.png']
        for path in self.cards:
            path.write_bytes(b'card')
        self.mp4 = folder / 'test-reel.mp4'
        self.mp4.write_bytes(b'video')
        self.hold_file = self.root / 'youtube_hold.json'

    def tearDown(self):
        self._temp.cleanup()

    def publish(self):
        """(발행 성공한 인스타 릴스 수, 유튜브 업로드 호출 수)."""
        args = argparse.Namespace(id=None, pick='', tomorrow=False, dry_run=False,
                                  ask_tomorrow=False)
        with patch.multiple(run, QUEUE=self.queue, POSTED=self.root / 'posted.json',
                            DELIVERY=self.delivery, IMAGES=self.images,
                            render_item=Mock(side_effect=lambda i, f, *a: self.cards),
                            build_reel_for=Mock(return_value=(self.mp4, 'test')),
                            sh=Mock(side_effect=_sh), push=Mock(),
                            build_caption=Mock(return_value='caption'),
                            build_first_comment=Mock(return_value='')), \
             patch.object(youtube, 'HOLD_FILE', self.hold_file), \
             patch.object(run.hooks, 'attach', side_effect=lambda q: q), \
             patch.object(run.hooks, 'validate', return_value=[]), \
             patch.object(run.notify, 'enabled', return_value=False), \
             patch.object(run.youtube, 'configured', return_value=True), \
             patch.object(run.youtube, 'publish_short',
                          return_value='vid-id') as upload, \
             patch.object(run.publish, 'publish_instagram_reel',
                          return_value='reel-id') as publish_reel, \
             patch.object(run.publish, 'publish_instagram_comment',
                          return_value='c-id'), \
             patch.dict(run.os.environ,
                        {'GITHUB_REPOSITORY': 'test/repo', 'IG_USER_ID': 'x',
                         'IG_ACCESS_TOKEN': 'y', 'SKIP_THREADS': 'true'}, clear=True):
            run.run_once(args)
        return publish_reel.call_count, upload.call_count

    def ledger(self):
        if not self.delivery.exists():
            return {}
        return json.loads(self.delivery.read_text(encoding='utf-8'))

    def test_hold_skips_youtube_but_keeps_instagram(self):
        self.hold_file.write_text(json.dumps({'hold': True, 'reason': '심사 대기'}),
                                  encoding='utf-8')
        reels, uploads = self.publish()
        self.assertEqual(uploads, 0, '보류 중에는 유튜브를 호출하면 안 된다')
        self.assertEqual(reels, 1, '유튜브를 보류해도 인스타는 그대로 나가야 한다')

    def test_hold_leaves_no_youtube_record_in_the_ledger(self):
        self.hold_file.write_text(json.dumps({'hold': True}), encoding='utf-8')
        self.publish()
        record = self.ledger().get('test-reel', {})
        self.assertNotIn('youtube', record,
                         '보류인데 원장에 기록이 남으면 나중 백필이 이 편을 건너뛴다')
        self.assertIn('instagram_reel', record, '인스타 기록은 남아야 한다')

    def test_release_lets_the_upload_through(self):
        self.hold_file.write_text(json.dumps({'hold': False}), encoding='utf-8')
        _, uploads = self.publish()
        self.assertEqual(uploads, 1, 'hold=false 로 풀면 다시 올라가야 한다')
        self.assertEqual(self.ledger()['test-reel']['youtube']['id'], 'vid-id')


if __name__ == '__main__':
    unittest.main()
