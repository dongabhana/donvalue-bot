"""2026-10-12 나레이션 합성 403 → 발행 3회 연속 실패 회귀 테스트.

예전 합성 주소(speech.platform.bing.com)는 403 을 돌려준다. 두 합성 경로(src/tts.py,
tools/build_campaign27.py)가 모두 새 주소로 바꾼 뒤 합성하는지 확인한다.
"""
import os
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


class TtsEndpointTest(unittest.TestCase):
    def setUp(self):
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            self.skipTest("edge-tts 미설치")

    def test_apply_moves_synthesis_off_legacy_host(self):
        import edge_tts.communicate as communicate
        import edge_tts.constants as constants
        from src import tts_endpoint

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EDGE_TTS_WSS_URL", None)
            url = tts_endpoint.apply()
        self.assertIn("api.msedgeservices.com", url)
        self.assertIn(f"Ocp-Apim-Subscription-Key={constants.TRUSTED_CLIENT_TOKEN}", url)
        self.assertNotIn("speech.platform.bing.com", communicate.WSS_URL)
        self.assertEqual(communicate.WSS_URL, url)
        # 목소리 목록 주소는 예전 호스트가 그대로 응답하므로 건드리지 않는다
        self.assertIn("speech.platform.bing.com", constants.VOICE_LIST)

    def test_env_override(self):
        import edge_tts.communicate as communicate
        from src import tts_endpoint

        with mock.patch.dict(os.environ, {"EDGE_TTS_WSS_URL": "wss://example.test/v1?k=1"}):
            tts_endpoint.apply()
            self.assertEqual(communicate.WSS_URL, "wss://example.test/v1?k=1")
        os.environ.pop("EDGE_TTS_WSS_URL", None)
        tts_endpoint.apply()  # 다른 테스트를 위해 기본값으로 되돌린다
        self.assertIn("api.msedgeservices.com", communicate.WSS_URL)

    def test_both_synth_paths_apply_before_synthesis(self):
        for rel, anchor in (("src/tts.py", "def synth_line"),
                            ("tools/build_campaign27.py", "def synth_one")):
            body = (ROOT / rel).read_text(encoding="utf-8").split(anchor, 1)[1]
            body = body.split("\ndef ", 1)[0]
            self.assertIn("tts_endpoint.apply()", body, rel)
            self.assertLess(body.index("tts_endpoint.apply()"), body.index("Communicate("), rel)


if __name__ == "__main__":
    unittest.main()
