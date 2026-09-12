import ast
import json
import operator
import unittest
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
import tempfile

from codex.engine import Engine, KST, validate
from src import run, publish


def arithmetic(text):
    operations={ast.Add:operator.add, ast.Sub:operator.sub, ast.Mult:operator.mul, ast.Div:operator.truediv}
    def walk(node):
        if isinstance(node,ast.Constant) and type(node.value) in (int,float): return node.value
        if isinstance(node,ast.BinOp) and type(node.op) in operations:
            return operations[type(node.op)](walk(node.left),walk(node.right))
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='min' and not node.keywords:
            return min(walk(v) for v in node.args)
        raise ValueError('Unsupported calculation')
    return walk(ast.parse(text,mode='eval').body)


class EditorialBankTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items=json.loads((Path(__file__).resolve().parents[1]/'editorial-bank.json').read_text())['items']

    def test_fifty_unique_complete_category_balanced_manuscripts(self):
        self.assertEqual(len(self.items),50)
        self.assertEqual(len({i['id'] for i in self.items}),50)
        self.assertEqual(len({i['topic_key'] for i in self.items}),50)
        self.assertEqual(sorted(Counter(i['category'] for i in self.items).values()),[6,6,6,6,6,6,7,7])
        previous=None
        for item in self.items:
            validate(item)
            due=datetime.fromisoformat(item['publish_at'])
            if previous is not None: self.assertGreater(due,previous)
            previous=due
            self.assertEqual(item['threads_chain'],[])
            self.assertIn(item['slides'][4]['body'],item['threads_text'])
            self.assertIn(item['slides'][5]['body'],item['threads_text'])
            self.assertTrue(item['threads_text'].startswith(item['hook'].replace('\n',' ')))
            self.assertEqual(item['verification']['real_world_price_claim'],False)

    def test_every_written_calculation_matches_its_result(self):
        checked=0
        for item in self.items:
            for equation in item['verification']['calculation'].split(';'):
                if not equation: continue
                left,right=equation.split('=')
                with self.subTest(topic=item['topic_key'],equation=equation):
                    self.assertAlmostEqual(arithmetic(left),arithmetic(right),delta=.01)
                checked+=1
        self.assertGreater(checked,35)

    def test_topic_tag_is_sent_on_root_post(self):
        instance=object.__new__(Engine)
        instance.account_check=Mock(return_value='test-user')
        instance.meta=Mock(side_effect=[{'id':'container'},{'id':'post'}])
        instance.wait_ready=Mock()
        self.assertEqual(instance.thread('complete text',topic_tag='IT소비'),'post')
        self.assertEqual(instance.meta.call_args_list[0].kwargs['topic_tag'],'IT소비')

    def test_failed_state_push_prevents_claude_external_write(self):
        with tempfile.TemporaryDirectory() as temp:
            action=Mock(return_value='post')
            with patch.object(run,'DELIVERY',Path(temp)/'delivery.json'), \
                 patch.object(run,'sh',return_value=''), \
                 patch.object(run,'push',side_effect=RuntimeError('failed push')):
                with self.assertRaises(RuntimeError): run.deliver_once('test','instagram',action)
            action.assert_not_called()

    def test_done_or_uncertain_claude_attempt_is_not_posted_again(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger=Path(temp)/'delivery.json'
            ledger.write_text(json.dumps({'test':{'instagram':{'status':'done','id':'old'},'threads':{'status':'in_flight'}}}))
            action=Mock()
            with patch.object(run,'DELIVERY',ledger):
                self.assertEqual(run.deliver_once('test','instagram',action),'old')
                with self.assertRaises(RuntimeError): run.deliver_once('test','threads',action)
            action.assert_not_called()

    def test_threads_children_are_ready_before_carousel_creation(self):
        events=[]
        def post(url, params, **options):
            events.append(params.get('media_type', 'PUBLISH'))
            return {'id': str(len(events))}
        def ready(container, token):
            events.append('READY')
        with patch.object(publish, '_post', side_effect=post) as writer, \
             patch.object(publish, '_th_wait_ready', side_effect=ready), \
             patch.object(publish.time, 'sleep'):
            publish.publish_threads('user', 'token', ['one','two'], 'complete text', topic_tag='생활비')
        self.assertEqual(events, ['IMAGE','IMAGE','READY','READY','CAROUSEL','READY','PUBLISH'])
        self.assertEqual(writer.call_args.kwargs, {'retry':False})

    def test_rejected_threads_child_prevents_parent_and_publication(self):
        with patch.object(publish, '_post', return_value={'id':'child'}) as writer, \
             patch.object(publish, '_th_wait_ready', side_effect=publish.PublishError('ERROR')):
            with self.assertRaises(publish.PublishError):
                publish.publish_threads('user','token',['one','two'],'complete text')
        self.assertEqual(writer.call_count,2)
