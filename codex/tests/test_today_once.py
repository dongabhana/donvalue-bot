import unittest
from datetime import datetime
from codex.engine import eligible,KST
from codex.today_once import APPROVED_HASH,ITEM_ID


class TodayTests(unittest.TestCase):
    def test_exception_is_bound_to_one_item_day_and_version(self):
        item={'id':ITEM_ID}
        rec={'hash':APPROVED_HASH,'decision':'approved','review_kind':'owner_chat_once','approval_source':'owner_explicit_chat_exception_2026_09_12'}
        now=datetime(2026,9,12,16,tzinfo=KST)
        self.assertTrue(eligible(item,rec,now))
        self.assertFalse(eligible({'id':'cx002-countdown'},rec,now))
        self.assertFalse(eligible(item,{**rec,'hash':'different'},now))
        self.assertFalse(eligible(item,{**rec,'decision':'held'},now))
        self.assertFalse(eligible(item,rec,datetime(2026,9,13,16,tzinfo=KST)))
        self.assertFalse(eligible(item,rec,datetime(2026,9,12,19,tzinfo=KST)))
        self.assertFalse(eligible(item,{**rec,'closed':True},now))


if __name__=='__main__': unittest.main()
