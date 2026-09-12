import argparse
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from codex import engine
from src import run


class GitDeliveryTests(unittest.TestCase):
    def test_codex_rebases_before_retrying_push(self):
        calls = []

        def git(*args):
            calls.append(args)
            if args == ('push',) and calls.count(args) == 1:
                raise RuntimeError('non-fast-forward')
            return ''

        with patch.object(engine, 'git', side_effect=git), patch.object(engine.time, 'sleep'):
            engine.push()
        self.assertEqual(calls[1], ('fetch', 'origin', 'main'))
        self.assertEqual(calls[2][-2:], ('rebase', 'origin/main'))
        self.assertEqual(calls[-1], ('push',))

    def test_conflicting_state_aborts_without_another_push(self):
        def git(*args):
            if args == ('push',) or 'origin/main' in args:
                raise RuntimeError('conflict')
            return ''

        with patch.object(engine, 'git', side_effect=git) as mocked:
            with self.assertRaises(RuntimeError):
                engine.push()
        self.assertEqual(mocked.call_args_list[-1].args, ('rebase', '--abort'))
        self.assertEqual(sum(c.args == ('push',) for c in mocked.call_args_list), 1)

    def test_unchanged_state_does_not_encrypt_or_commit(self):
        instance = object.__new__(engine.Engine)
        instance.state = {'offset': 10, 'records': {}}
        instance._saved_state = engine.canonical(instance.state)
        instance.crypt = Mock()
        with patch.object(engine, 'commit') as commit:
            instance.save()
        instance.crypt.encrypt.assert_not_called()
        commit.assert_not_called()

    def test_reel_already_committed_with_images_still_publishes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            queue = root / 'queue.yaml'
            queue.write_text('items: [{id: test-reel, product: Test, verified: true, ig_format: reel}]')
            posted = root / 'posted.json'

            def render(item, folder, *args):
                folder.mkdir(parents=True)
                paths = [folder / '01.png', folder / '02.png']
                for path in paths:
                    path.write_bytes(b'card')
                return paths

            def reel(item, paths, mp4, *args):
                mp4.write_bytes(b'video')
                return None, 'test'

            def sh(*args):
                if args[1] == 'status':
                    return 'new files'
                if args[1] == 'diff':
                    return ''  # The whole media folder was committed earlier.
                if args[1] == 'rev-parse':
                    return 'test-sha'
                if 'commit' in args and 'reel: test-reel' in args:
                    raise subprocess.CalledProcessError(1, args, stderr='nothing to commit')
                return ''

            args = argparse.Namespace(id=None, pick='', tomorrow=False, dry_run=False)
            with patch.multiple(run, QUEUE=queue, POSTED=posted, IMAGES=root / 'images',
                                render_item=Mock(side_effect=render), build_reel_for=Mock(side_effect=reel),
                                sh=Mock(side_effect=sh), push=Mock(), build_caption=Mock(return_value='caption'),
                                build_first_comment=Mock(return_value='')):
                with patch.object(run.hooks, 'attach', side_effect=lambda q: q), \
                     patch.object(run.hooks, 'validate', return_value=[]), \
                     patch.object(run.notify, 'enabled', return_value=False), \
                     patch.object(run.notify, 'done'), \
                     patch.object(run.publish, 'publish_instagram_reel', return_value='reel-id') as publish_reel, \
                     patch.dict(run.os.environ, {'GITHUB_REPOSITORY': 'test/repo', 'IG_USER_ID': 'test-id',
                                                 'IG_ACCESS_TOKEN': 'test-token', 'SKIP_THREADS': 'true'}, clear=True):
                    self.assertEqual(run.run_once(args), 0)
                publish_reel.assert_called_once()
