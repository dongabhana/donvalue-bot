"""2026-10-05 유튜브 썸네일을 표지로 맞추는 재시도(src/thumbs.py)."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src import run, thumbs  # noqa: E402

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 5, 22, 0, tzinfo=KST)


def _ops(at='2026-10-05T21:50:00+09:00', th=None):
    ops = {'youtube': {'status': 'done', 'id': 'VID', 'at': at}}
    if th:
        ops['youtube_thumbnail'] = th
    return ops


class DueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'images' / 'p07').mkdir(parents=True)
        (self.root / 'images' / 'p07' / 'cover.jpg').write_bytes(b'jpg')

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_upload_without_record_is_due(self):
        self.assertTrue(thumbs.due('p07', _ops(), self.root, NOW))

    def test_done_is_not_due(self):
        self.assertFalse(thumbs.due('p07', _ops(th={'status': 'done'}), self.root, NOW))

    def test_recent_failure_waits_six_hours(self):
        th = {'status': 'error', 'at': '2026-10-05T21:55:00+09:00', 'tries': 1}
        self.assertFalse(thumbs.due('p07', _ops(th=th), self.root, NOW))
        self.assertTrue(thumbs.due('p07', _ops(th=th), self.root, NOW + timedelta(hours=6)))

    def test_gives_up_after_max_tries(self):
        th = {'status': 'error', 'at': '2026-10-01T00:00:00+09:00', 'tries': thumbs.MAX_TRIES}
        self.assertFalse(thumbs.due('p07', _ops(th=th), self.root, NOW))

    def test_no_cover_file_or_old_video_is_skipped(self):
        self.assertFalse(thumbs.due('p99', _ops(), self.root, NOW))
        self.assertFalse(thumbs.due('p07', _ops(at='2026-08-01T00:00:00+09:00'), self.root, NOW))

    def test_not_uploaded_is_skipped(self):
        self.assertFalse(thumbs.due('p07', {'youtube': {'status': 'in_flight'}}, self.root, NOW))


class ApplyTests(unittest.TestCase):
    def test_success_and_failure_are_recorded(self):
        ledger = {'p07': _ops()}
        row = thumbs.apply('p07', 'VID', Path('x.jpg'), ledger, NOW, setter=lambda v, c: {})
        self.assertEqual(row['status'], 'done')

        def boom(v, c):
            raise RuntimeError('썸네일 적용 실패 403')
        ledger = {'p08': _ops()}
        row = thumbs.apply('p08', 'VID', Path('x.jpg'), ledger, NOW, setter=boom)
        self.assertEqual((row['status'], row['tries']), ('error', 1))
        self.assertIn('403', ledger['p08']['youtube_thumbnail']['error'])
        row = thumbs.apply('p08', 'VID', Path('x.jpg'), ledger, NOW, setter=boom)
        self.assertEqual(row['tries'], 2)


class CatchUpTests(unittest.TestCase):
    def test_catch_up_sets_due_items_and_commits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'images' / 'p07').mkdir(parents=True)
            (root / 'images' / 'p07' / 'cover.jpg').write_bytes(b'jpg')
            now = datetime.now(KST).isoformat(timespec='seconds')
            ledger = root / 'delivery.json'
            ledger.write_text(json.dumps({'p07': _ops(at=now), 'p06': _ops(at=now, th={'status': 'done'})}))
            calls, git = [], []
            with patch.object(run, 'DELIVERY', ledger), patch.object(run, 'ROOT', root), \
                 patch.object(run, 'sh', lambda *a: git.append(a) or ''), \
                 patch.object(run, 'push', lambda *a, **k: None):
                n = thumbs.catch_up(setter=lambda v, c: calls.append((v, Path(c).name)))
            self.assertEqual(n, 1)
            self.assertEqual(calls, [('VID', 'cover.jpg')])
            saved = json.loads(ledger.read_text())
            self.assertEqual(saved['p07']['youtube_thumbnail']['status'], 'done')
            self.assertTrue(any('commit' in a for a in git))

    def test_shorts_workflow_runs_catch_up(self):
        src = (ROOT / '.github/workflows/youtube-shorts.yml').read_text(encoding='utf-8')
        self.assertIn('python -m src.thumbs', src)


class CampaignPublishTests(unittest.TestCase):
    """발행 직후 썸네일 결과가 원장(youtube_thumbnail)에 남는지 — 성공·실패 둘 다."""
    yt_thumb = '1'

    def test_switch_off_skips_api(self):
        """2026-10-06: YT_THUMBNAIL 이 꺼져 있으면 API 를 부르지 않고 오류도 남기지 않는다."""
        self.yt_thumb = '0'
        def boom(v, c):
            raise AssertionError('썸네일 API 를 부르면 안 됨')
        led, posted, _ = self._publish(boom)
        self.assertNotIn('youtube_thumbnail', led['p07-car-fixed'])
        self.assertEqual(posted['errors'], [])
        self.assertIn('youtube', posted['results'])
    def _publish(self, set_thumbnail):
        from src import campaign
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        folder = root / 'render'
        folder.mkdir()
        for name in campaign.PUBLIC_FILES + ('youtube.mp4',):
            (folder / name).write_bytes(b'x')
        for name in ('instagram-caption.txt', 'youtube-description.txt', 'threads.txt'):
            (folder / name).write_text('t', encoding='utf-8')
        delivery = root / 'delivery.json'
        delivery.write_text('{}', encoding='utf-8')

        def deliver_once(item_id, key, action):
            led = json.loads(delivery.read_text(encoding='utf-8'))
            res = action()
            led.setdefault(item_id, {})[key] = {'status': 'done', 'id': res}
            delivery.write_text(json.dumps(led), encoding='utf-8')
            return res

        class YT:
            hold_reason = staticmethod(lambda: '')
            configured = staticmethod(lambda: True)
            upload_short = staticmethod(lambda *a, **k: 'VID')
            watch_url = staticmethod(lambda v: v)
            video_status = staticmethod(lambda v: {'privacyStatus': 'public'})
            resolve_privacy = staticmethod(lambda: 'public')

        YT.set_thumbnail = staticmethod(set_thumbnail)

        class Notify:
            enabled = staticmethod(lambda: False)
            done = staticmethod(lambda *a, **k: None)

        git = []
        ctx = dict(sh=lambda *a: git.append(a) or 'sha', push=lambda *a, **k: None,
                   deliver_once=deliver_once, POSTED=root / 'posted.json', IMAGES=root / 'images',
                   PREVIEW=root / 'preview', KST=KST, notify=Notify, youtube=YT, publish=None,
                   DELIVERY=delivery)
        item = {'id': 'p07-car-fixed', 'order': 7, 'product': '차', 'yt_title': '제목'}
        env = {'GITHUB_REPOSITORY': 'o/r', 'APPROVAL_REQUIRED': '0', 'IG_USER_ID': '', 'YT_THUMBNAIL': self.yt_thumb,
               'IG_ACCESS_TOKEN': '', 'TH_USER_ID': '', 'TH_ACCESS_TOKEN': ''}
        with patch.object(campaign, 'render', lambda it: folder), patch.dict('os.environ', env):
            self.assertEqual(campaign.publish(item, ctx), 0)
        posted = json.loads((root / 'posted.json').read_text(encoding='utf-8'))[-1]
        return json.loads(delivery.read_text(encoding='utf-8')), posted, git

    def test_success_recorded(self):
        led, posted, git = self._publish(lambda v, c: {})
        self.assertEqual(led['p07-car-fixed']['youtube_thumbnail']['status'], 'done')
        self.assertEqual(posted['errors'], [])
        self.assertTrue(any(str(a[-1]).endswith('delivery.json') for a in git if a[:2] == ('git', 'add')))

    def test_failure_recorded_for_retry(self):
        def boom(v, c):
            raise RuntimeError('썸네일 적용 실패 403')
        led, posted, _ = self._publish(boom)
        row = led['p07-car-fixed']['youtube_thumbnail']
        self.assertEqual((row['status'], row['tries']), ('error', 1))
        self.assertTrue(any(e.startswith('youtube_thumbnail:') for e in posted['errors']))
        self.assertIn('youtube', posted['results'])


class MakeCoverTests(unittest.TestCase):
    """2026-10-05: 영상 장면이 아니라 표지 이미지를 올린다 — 예전 편도 표지를 만든다."""
    def test_real_older_items_get_vertical_cover(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            # 실제 저장소 파일을 그대로 쓰되 결과물만 임시 폴더로
            root = Path(tmp)
            for rel in ('codex/content.json', 'images/001-coupang-wow/001-coupang-wow_01.png'):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_bytes((ROOT / rel).read_bytes())
            data = json.loads((ROOT / 'codex/content.json').read_text(encoding='utf-8'))
            items = data.get('items', data) if isinstance(data, dict) else data
            photo = next(i for i in items if i['id'] == 'cx107-filter-service')['cover_photo']['path']
            (root / photo).parent.mkdir(parents=True, exist_ok=True)
            (root / photo).write_bytes((ROOT / photo).read_bytes())
            for item_id in ('001-coupang-wow', 'cx107-filter-service'):
                out = thumbs.make_cover(root, item_id)
                self.assertIsNotNone(out, item_id)
                with Image.open(out) as im:
                    self.assertEqual(im.size, (1080, 1920))
                self.assertLess(out.stat().st_size, 2 * 1024 * 1024)
            self.assertIsNone(thumbs.make_cover(root, 'zz-none'))
            self.assertFalse(thumbs.has_cover_source(root, 'zz-none'))

    def test_campaign_cover_file_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'images' / 'p07').mkdir(parents=True)
            (root / 'images' / 'p07' / 'cover.jpg').write_bytes(b'jpg')
            self.assertEqual(thumbs.make_cover(root, 'p07'), root / 'images' / 'p07' / 'cover.jpg')


if __name__ == '__main__':
    unittest.main()
