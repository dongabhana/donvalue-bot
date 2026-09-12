import copy
import json
import re
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from codex.engine import Engine, KST, eligible, validate, regular_item
from codex.seed_three_once import ITEM_IDS, HASHES, SOURCE, content_hash

ROOT=Path(__file__).resolve().parents[2]


class SeedThreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items=json.loads((ROOT/'codex/content.json').read_text())['items']
        cls.selected={i['id']:i for i in cls.items if i['id'] in ITEM_IDS}

    def test_three_exception_versions_are_complete_carousels_on_both_platforms(self):
        self.assertEqual(set(self.selected),set(ITEM_IDS))
        for item_id,item in self.selected.items():
            validate(item)
            self.assertEqual(content_hash(item),HASHES[item_id])
            self.assertEqual(item['format'],'carousel')
            self.assertEqual(item['threads_media'],'carousel')
            self.assertEqual(len(item['slides']),6)
            tags=re.findall(r'#([^\s#]+)',item['caption'])
            self.assertEqual(len(tags),5)
            self.assertEqual(len(set(tags)),5)
            self.assertEqual(item['threads_chain'],[])

    def test_exception_cannot_authorize_another_version_item_or_day(self):
        item=self.selected[ITEM_IDS[0]]
        record={'review_kind':'owner_seed_three','decision':'approved','approval_source':SOURCE,
                'seed_content_hash':HASHES[item['id']]}
        now=datetime(2026,9,12,19,tzinfo=KST)
        self.assertTrue(eligible(item,record,now))
        modified=copy.deepcopy(item); modified['caption']+=' changed'
        self.assertFalse(eligible(modified,record,now))
        other=next(i for i in self.items if i['id']=='cx006-vacation-app')
        self.assertFalse(eligible(other,record,now))
        for change in ({'closed':True},{'decision':'held'},{'approval_source':'unrelated'},{'seed_content_hash':'wrong'}):
            self.assertFalse(eligible(item,{**record,**change},now))
        self.assertFalse(eligible(item,record,datetime(2026,9,12,23,59,tzinfo=KST)))
        self.assertFalse(eligible(item,record,datetime(2026,9,13,19,tzinfo=KST)))

    def test_completed_marker_does_not_change_the_original_source_hash(self):
        item=self.selected[ITEM_IDS[0]]
        self.assertEqual(content_hash(item),content_hash({**item,'posted_early_on':'2026-09-12'}))

    def test_threads_waits_for_every_child_then_parent_and_keeps_actual_topic_tag(self):
        instance=object.__new__(Engine)
        instance.account_check=Mock(return_value='user')
        instance.meta=Mock(side_effect=[{'id':'one'},{'id':'two'},{'id':'parent'},{'id':'post'}])
        instance.wait_ready=Mock()
        self.assertEqual(instance.thread('complete text',topic_tag='살림',image_urls=['image1','image2']),'post')
        self.assertEqual([c.args for c in instance.wait_ready.call_args_list],[('th','one'),('th','two'),('th','parent')])
        parent=instance.meta.call_args_list[2].kwargs
        self.assertEqual(parent['media_type'],'CAROUSEL')
        self.assertEqual(parent['children'],'one,two')
        self.assertEqual(parent['topic_tag'],'살림')

    def test_regular_queue_has_no_empty_seed_slots_and_keeps_approval(self):
        remaining=[i for i in self.items if i['id'] not in ITEM_IDS and not i.get('posted_early_on')]
        dates=[datetime.fromisoformat(i['publish_at']) for i in remaining]
        self.assertEqual(len(dates),48)
        self.assertEqual(len(set(dates)),len(dates))
        taxi=next(i for i in remaining if i['id']=='cx054-taxi-vs-driver')
        self.assertEqual(taxi['publish_at'],'2026-09-14T20:00:00+09:00')
        self.assertFalse(taxi['verification']['live_driver_quote_obtained'])
        self.assertFalse(eligible(taxi,{'decision':'pending'},datetime(2026,9,14,20,tzinfo=KST)))

    def test_today_seed_cards_are_excluded_only_from_todays_regular_queue(self):
        today=datetime(2026,9,12,19,tzinfo=KST)
        tomorrow=datetime(2026,9,13,19,tzinfo=KST)
        for item in self.selected.values():
            unposted={k:v for k,v in item.items() if k!='posted_early_on'}
            self.assertFalse(regular_item(unposted,today))
            self.assertTrue(regular_item(unposted,tomorrow))
        archived=next(i for i in self.items if i.get('posted_early_on'))
        self.assertFalse(regular_item(archived,today))

    def test_regular_preview_picks_the_earliest_actual_slot_without_seed_test_buttons(self):
        instance=object.__new__(Engine)
        instance.items=self.items
        instance.state={'records':{}}
        instance.tg=Mock(side_effect=lambda method:{'username':'donvalue_approval_bot'} if method=='getMe' else {'url':''})
        instance.callbacks=Mock(); instance.preflight=Mock(); instance.preview=Mock(); instance.observations=Mock()
        with patch('codex.engine.datetime',wraps=datetime) as clock:
            clock.now.return_value=datetime(2026,9,12,19,tzinfo=KST)
            instance.run('preview')
        self.assertEqual(instance.preview.call_args.args[0]['id'],'cx054-taxi-vs-driver')
        self.assertFalse(instance.preview.call_args.kwargs['real'])


if __name__=='__main__': unittest.main()
