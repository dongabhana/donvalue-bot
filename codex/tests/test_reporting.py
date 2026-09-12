import unittest
from codex.reporting import metric_value


class MetricTests(unittest.TestCase):
    def test_zero_is_valid_but_missing_is_not_zero(self):
        self.assertEqual(metric_value({'data':[{'values':[{'value':0}]}]}),0)
        self.assertIsNone(metric_value({'data':[]}))
        self.assertIsNone(metric_value({'data':[{'values':[]}]}))

    def test_supported_shapes(self):
        self.assertEqual(metric_value({'data':[{'total_value':{'value':12}}]}),12)
        self.assertEqual(metric_value({'data':[{'values':[{'value':13}]}]}),13)


if __name__=='__main__': unittest.main()
