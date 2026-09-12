import copy
import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from codex.engine import Engine, eligible, fingerprint, validate, KST


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.item=json.loads((Path(__file__).resolve().parents[1]/'content.json').read_text())['items'][0]
        self.record={'decision':'approved','review_kind':'real','approved_at':'2026-09-13T20:15:00+09:00'}

    def test_data(self):
        validate(self.item)
        self.assertEqual((27900+5900)-(27900+3000),2900)
        self.assertEqual(27900+2100,30000)

    def test_time_and_previous_day(self):
        self.assertTrue(eligible(self.item,self.record,datetime(2026,9,14,20,15,tzinfo=KST)))
        for at in [datetime(2026,9,14,19,59,tzinfo=KST),datetime(2026,9,14,22,tzinfo=KST),datetime(2026,9,15,20,tzinfo=KST)]:
            self.assertFalse(eligible(self.item,self.record,at))
        self.record['approved_at']='2026-09-12T20:00:00+09:00'
        self.assertFalse(eligible(self.item,self.record,datetime(2026,9,14,20,tzinfo=KST)))

    def test_test_button_never_publishes(self):
        self.record['review_kind']='test'
        self.assertFalse(eligible(self.item,self.record,datetime(2026,9,14,20,tzinfo=KST)))

    def test_revision_bound(self):
        manifest={'sha256':{'card':'original'}}
        orig=fingerprint(self.item,manifest)
        new=copy.deepcopy(self.item); new['caption']+=' changed'
        self.assertNotEqual(orig,fingerprint(new,manifest))
        self.assertNotEqual(orig,fingerprint(self.item,{'sha256':{'card':'changed'}}))

    def test_idempotent_and_ambiguous_operations(self):
        engine=object.__new__(Engine); engine.save=Mock(); engine.tell=Mock()
        action=Mock(return_value='123'); record={'operations':{}}
        self.assertEqual(engine.operation(record,'ig',action),'123')
        self.assertEqual(engine.operation(record,'ig',action),'123'); action.assert_called_once()
        record['operations']['th']={'status':'in_flight'}
        with self.assertRaises(RuntimeError): engine.operation(record,'th',action)
        action.assert_called_once()

    def test_commit_failure_prevents_external_write(self):
        engine=object.__new__(Engine); engine.save=Mock(side_effect=RuntimeError('push failed')); engine.tell=Mock()
        action=Mock()
        with self.assertRaises(RuntimeError): engine.operation({'operations':{}},'ig',action)
        action.assert_not_called()

    def test_unapproved_never_calls_meta(self):
        engine=object.__new__(Engine); engine.meta=Mock()
        engine.publish(self.item,{'decision':'pending'},datetime(2026,9,14,20,tzinfo=KST))
        engine.meta.assert_not_called()

    def test_foreign_sender_cannot_approve(self):
        engine=object.__new__(Engine)
        engine.owner={'user_id':1,'chat_id':1}
        engine.items=[self.item]
        manifest={'sha256':{}}
        digest=fingerprint(self.item,manifest)
        rec={'decision':'pending','review_kind':'test','hash':digest,'manifest':manifest,'message_id':4,'operations':{}}
        engine.state={'offset':0,'records':{self.item['id']:rec}}
        engine.save=Mock(); engine.tell=Mock()
        update={'update_id':1,'callback_query':{'id':'cb','from':{'id':2},'message':{'message_id':4,'chat':{'id':1}},'data':'a|'+self.item['id']+'|'+digest[:12]}}
        engine.tg=Mock(return_value=[update])
        engine.callbacks()
        self.assertEqual(rec['decision'],'pending')
        engine.tell.assert_not_called()

    def test_preview_does_not_downgrade_real_approval(self):
        engine=object.__new__(Engine)
        rec={'review_kind':'real','decision':'approved'}
        engine.state={'records':{self.item['id']:rec}}
        engine.save=Mock(); engine.tell=Mock()
        with patch('codex.engine.render',return_value={}): engine.preview(self.item,real=False)
        self.assertEqual(rec['decision'],'approved')
        engine.save.assert_not_called()


if __name__=='__main__': unittest.main()
