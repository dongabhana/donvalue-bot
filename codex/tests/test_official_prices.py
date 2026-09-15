import copy
import json
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import requests
from codex.official_prices import matches_official_page,check_prices
from codex.engine import Engine

# 가격 출처가 없는 편이 금액을 쓸 때 반드시 들어가야 하는 표현.
ASSUMPTION_MARKERS=('비교를 위한 가정','비교용 가정','가정해볼게요','이렇게 가정','가정입니다')
# 조건이 뒤집히는 지점(손익분기)을 밝혔는지 확인하는 표현.
BREAKEVEN_MARKERS=('넘는 순간','넘으면','부터는','이상이면','뒤집','기준을 넘')

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
        self.assertEqual(len(revised),47)   # cx102(해외직구) 삭제로 48 → 47
        for item in revised:
            self.assertNotIn('가상 조건·창작 상황',item['caption'])
            self.assertTrue(item['slides'][3]['body'])
            self.assertEqual(item['verification']['real_world_price_claim'],bool(item['verification']['sources']))
            if not item['verification']['real_world_price_claim']:
                import re
                money=re.search(r'\d[\d,.]*\s*만?원',item['caption'])
                if money:
                    # 출처 없는 금액이라고 무조건 막으면, 가정임을 밝히고 손익분기점까지
                    # 제시하는 계산편을 낼 수 없다. 규칙의 목적은 '확인 안 된 가격을
                    # 사실처럼 쓰지 않는 것'이므로, 아래 셋을 모두 갖춘 편만 허용한다.
                    #   ① 캡션에 가정임을 명시  ② 쓰레드 본문에도 명시  ③ 조건이 뒤집히는 지점 제시
                    where=f"{item['id']} 캡션의 '{money.group()}'"
                    self.assertTrue(any(m in item['caption'] for m in ASSUMPTION_MARKERS),
                                    where+': 출처 없는 금액은 가정임을 캡션에 명시해야 합니다')
                    self.assertTrue(any(m in item['threads_text'] for m in ASSUMPTION_MARKERS),
                                    where+': 쓰레드 본문에도 가정임을 명시해야 합니다')
                    self.assertTrue(any(m in item['caption'] for m in BREAKEVEN_MARKERS),
                                    where+': 가정을 쓰면 조건이 뒤집히는 지점을 함께 적어야 합니다')
