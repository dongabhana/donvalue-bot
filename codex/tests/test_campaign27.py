import json
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

class Campaign27Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=json.loads((ROOT/'content/campaign27.json').read_text(encoding='utf8'))

    def test_full_packages_and_platform_separation(self):
        items=self.data['items']
        self.assertEqual(len(items),27)
        self.assertEqual(len({e['id'] for e in items}),27)
        for e in items:
            with self.subTest(e=e['id']):
                self.assertTrue(4<=len(e['cards'])<=6)
                self.assertEqual(len(e['narration']),len(e['cards'])+2)
                self.assertEqual(e['reel_cards'],list(range(1,len(e['cards'])+1)))
                self.assertTrue((ROOT/e['cover_file']).exists())
                for c in e['cards']:
                    self.assertTrue(all(c[k] for k in ['title','figure','body']))
                for key in ['caption','youtube_description','threads_text','assumptions']:
                    self.assertIn('가정',e[key])
                self.assertLessEqual(len(e['threads_text']),500)
                self.assertLessEqual(len(e['caption']),2200)
                self.assertLessEqual(len(e['yt_title']),100)
                self.assertNotIn('구독',e['cta']['instagram']['narration'])
                self.assertNotIn('팔로우',e['cta']['youtube']['narration'])
                self.assertTrue(e['hold'])

    def test_material_arithmetic_and_qualification(self):
        self.assertAlmostEqual(29000/15000*3600/22,316.36,places=2)
        self.assertEqual(4000000/(1800/12-1800/18),80000)
        self.assertEqual(1550*44*(.5-.2),20460)
        self.assertEqual((12000-1550)/5*60,125400)
        self.assertEqual((25000-5000)*52,1040000)
        items=self.data['items']
        self.assertIn('기대값',items[22]['cards'][1]['body'])
        self.assertIn('정액형',items[4]['cards'][3]['body'])
        self.assertIn('76',items[24]['cards'][1]['body'])

if __name__=='__main__': unittest.main()
