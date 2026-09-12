import copy
import json
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import requests
from codex.official_prices import matches_official_page,check_prices
from codex.engine import Engine

class OfficialPriceTests(unittest.TestCase):
    def setUp(self):
        self.source={'scope_start':'대한민국(원)','scope_end':'싱가포르','required_tokens':['50GB','1,100','200GB','4,400','2TB','14,000']}
    def test_country_and_script_values_cannot_confirm_a_price(self):
        html='<h2>대한민국(원)</h2>50GB: 1,100 200GB: 4,400 2TB: 15,000<h2>싱가포르</h2>2TB: 14,000<script>14,000</script>'
        self.assertFalse(matches_official_page(self.source,html))
    def test_numeric_prefix_is_not_the_same_price(self):
        source={'scope_start':'Start','scope_end':'End','required_tokens':['12,500']}
        self.assertFalse(matches_official_page(source,'Start 12,5000 End'))
        self.assertTrue(matches_official_page(source,'Start ₩12,500/월 End'))
    def test_unavailable_source_fails_closed(self):
        item={'editorial_revision':'official-comparison-2026-09-12','verification':{'real_world_price_claim':True,'sources':[{**self.source,'url':'https://support.apple.com/ko-kr/108047'}]}}
        session=Mock();session.get.side_effect=requests.Timeout()
        with self.assertRaises(RuntimeError):check_prices(item,session)
    def test_price_failure_sends_one_alert_without_changing_approval(self):
        engine=Engine.__new__(Engine); engine.state={'records':{'cx012-storage-used':{'decision':'approved'}}};engine.tell=Mock();engine.save=Mock()
        item={'id':'cx012-storage-used','topic':'test','evidence':'v1','editorial_revision':'official-comparison-2026-09-12'}
        before=copy.deepcopy(engine.state['records'])
        with patch('codex.engine.check_prices',side_effect=RuntimeError('changed')):
            self.assertFalse(engine.price_check(item));self.assertFalse(engine.price_check(item))
        engine.tell.assert_called_once();self.assertEqual(before,engine.state['records'])
    def test_queue_has_no_fictional_money_and_has_explicit_decisions(self):
        queue=json.loads((Path(__file__).parents[1]/'content.json').read_text())['items']
        revised=[x for x in queue if x.get('editorial_revision')]
        self.assertEqual(len(revised),48)
        for item in revised:
            self.assertNotIn('가상 조건·창작 상황',item['caption'])
            self.assertTrue(item['slides'][3]['body'])
            self.assertEqual(item['verification']['real_world_price_claim'],bool(item['verification']['sources']))
            if not item['verification']['real_world_price_claim']:
                import re
                self.assertIsNone(re.search(r'\d[\d,.]*\s*만?원',item['caption']))
