import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex import media, build_threshold_queue
from src import photo_covers

ROOT = Path(__file__).resolve().parents[2]


class PhotoCoverTests(unittest.TestCase):
    def test_opt_in_requires_matching_asset(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertFalse(photo_covers.available(temp, {'id': 'example'}))
            target = photo_covers.asset_path(temp, {'id': 'example'})
            target.parent.mkdir(parents=True)
            target.touch()
            self.assertTrue(photo_covers.available(temp, {'id': 'example'}))
            self.assertFalse(photo_covers.available(temp, {'id': 'different'}))

    def test_pop_first_card_uses_explicit_photo_only(self):
        item = {'cover_photo': {'path': 'example'}}
        with patch.object(media, 'photographic_cover', return_value='photo') as renderer:
            self.assertEqual(media.pop_card(item, {}, 0), 'photo')
            renderer.assert_called_once_with(item, {})

    def test_generated_cover_hashes_match_files(self):
        items = json.loads((ROOT / 'codex/content.json').read_text())['items']
        for item in items:
            cover = item.get('cover_photo', {})
            if '.editorial-v3.' in cover.get('path', ''):
                with self.subTest(id=item['id']):
                    self.assertEqual(hashlib.sha256((ROOT / cover['path']).read_bytes()).hexdigest(), cover['sha256'])

    def test_threshold_source_preserves_generated_cover(self):
        specs = json.loads((ROOT / 'codex/threshold_specs.json').read_text())
        current = {x['id']: x for x in json.loads((ROOT / 'codex/content.json').read_text())['items']}
        for row, due in zip(specs['items'], specs['schedule']):
            ident = 'cx006-vacation-app' if row['id'] == 'cx100-earlybird-flex' else row['id']
            rebuilt = build_threshold_queue.item(row, due, ident)
            self.assertEqual(rebuilt['cover_photo'], current[ident]['cover_photo'])
