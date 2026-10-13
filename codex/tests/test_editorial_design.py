"""Render the real corpus to catch layout regressions before the daily job runs."""
import unittest
import importlib.util
from pathlib import Path
from src import editorial_design as D
from src import reel_scenes as S
from codex.campaign27 import package

ROOT=Path(__file__).resolve().parents[2]


class EditorialDesignTests(unittest.TestCase):
    def tearDown(self):
        D.BOUNDS.clear()

    def test_campaign_body_conclusion_and_both_ctas_fit(self):
        spec=importlib.util.spec_from_file_location('editorial_campaign',ROOT/'tools/campaign27_design.py')
        mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        for e in package()['items']:
            with self.subTest(episode=e['id']):
                images=[mod.render_body(e,i) for i in range(4)]
                images += [mod.conclusion(e),mod.cta(e,'instagram'),mod.cta(e,'youtube')]
                self.assertTrue(all(im.size==(1080,1920) for im in images))
                # All layouts keep the same dark background, including comparisons.
                self.assertEqual(len({im.getpixel((0,0)) for im in images}),1)
                self.assertLess(max(images[0].getpixel((0,0))),50)
        self.assertGreater(len(mod.BOUNDS),1000)

    def test_platform_action_and_question_are_present(self):
        for platform,action in [('instagram','팔로우'),('youtube','구독'),('both','팔로우')]:
            D.BOUNDS.clear()
            D.cta('직구하고 추가 비용 낸 적 있어?',platform)
            copy=' '.join(x['text'] for x in D.BOUNDS)
            self.assertIn('좋아요',copy)
            self.assertIn(action,copy)
            self.assertIn('직구하고 추가 비용 낸 적 있어?',copy)
            if platform=='youtube': self.assertNotIn('팔로우',copy)

    def test_regular_queue_without_figure_preserves_body(self):
        detail='배송비와 반품 조건을 먼저 확인하세요.'
        im=S.scene_beat(1,4,'결제 전 확인',detail,'돈값하나','@dongabhana',.3,{})
        self.assertEqual(im.size,(1458,2592))
        self.assertIn(detail,' '.join(x['text'] for x in D.BOUNDS))

    def test_long_copy_fails_explicitly_instead_of_clipping(self):
        with self.assertRaises(ValueError):
            D.cta('아주 긴 문장 '*500,'instagram')


if __name__=='__main__': unittest.main()
