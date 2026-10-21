"""2026-10-21: 10/20 정기 발행이 마이크로소프트 TTS 429(요청 과다)로 21:20·22:39 연달아 실패.

  · 저장소 음성 캐시(assets/tts-cache)가 있으면 TTS 를 부르지 않는다
  · 429 면 몇 분까지 기다렸다 다시 하고, 끝내 안 되면 멈춘다(무음 발행 금지)
  · 반쯤 받은 음성은 쓰지 않는다
  · 미리 만들기(prewarm)는 다음에 나갈 편을 고른다
"""
import importlib.util
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def builder():
    spec = importlib.util.spec_from_file_location('b1021', ROOT / 'tools/build_campaign27.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fake_tts(behaviour):
    """behaviour: 호출마다 'ok' | '429' | 'partial' 순서."""
    calls = []

    class Communicate:
        def __init__(self, text, voice, rate=None):
            self.text = text

        async def save(self, path):
            kind = behaviour[min(len(calls), len(behaviour) - 1)]
            calls.append(kind)
            if kind == '429':
                raise RuntimeError("429, message='Invalid response status'")
            if kind == 'partial':
                Path(path).write_bytes(b'x' * 4000)
                raise RuntimeError('connection reset')
            Path(path).write_bytes(b'ID3' + b'\0' * 4000)

    return types.SimpleNamespace(Communicate=Communicate), calls


class SynthTests(unittest.TestCase):
    def setUp(self):
        self.B = builder()
        self.tmp = Path(tempfile.mkdtemp())
        self.B.TTS_CACHE = self.tmp / 'cache'
        self.sleeps = []
        p1 = mock.patch('time.sleep', lambda s: self.sleeps.append(s))
        p2 = mock.patch.object(self.B, 'run', lambda args: None)          # ffmpeg 변환 생략
        p3 = mock.patch.object(self.B.wave, 'open')
        from src import tts_endpoint
        p4 = mock.patch.object(tts_endpoint, 'apply', lambda: None)       # 실제 주소 설정은 test_tts_endpoint 가 본다
        for p in (p1, p2, p3, p4):
            p.start()
            self.addCleanup(p.stop)
        w = self.B.wave.open.return_value.__enter__.return_value
        w.getnframes.return_value = 24000 * 3
        w.getframerate.return_value = 24000
        self.addCleanup(shutil.rmtree, self.tmp)

    def job(self, name='01-cover', text='춥다고 문풍지부터 사면, 삼천 원 그냥 날릴 수 있어.'):
        folder = self.tmp / 'ep'
        folder.mkdir(exist_ok=True)
        (folder / f'{name}.wav').touch()
        return (folder, {'name': name, 'narration': text})

    def synth(self, behaviour, job=None):
        mod, calls = fake_tts(behaviour)
        with mock.patch.dict(sys.modules, {'edge_tts': mod}):
            job = job or self.job()
            (job[0] / f"{job[1]['name']}.wav").touch()
            return self.B.synth_one(job), calls

    def test_429_waits_then_succeeds_and_fills_cache(self):
        res, calls = self.synth(['429', '429', 'ok'])
        self.assertEqual(calls, ['429', '429', 'ok'])
        self.assertEqual(self.sleeps, [15, 30])
        self.assertEqual(res['duration'], 3.0)
        self.assertEqual(len(list(self.B.TTS_CACHE.glob('*.mp3'))), 1)

    def test_cache_hit_skips_tts(self):
        self.synth(['ok'])
        job = self.job()
        for f in job[0].glob('*'):
            f.unlink()
        _, calls = self.synth(['429'], job)
        self.assertEqual(calls, [])                         # 캐시로 끝 — 서버를 부르지 않음

    def test_gives_up_after_waits(self):
        with self.assertRaises(RuntimeError) as cm:
            self.synth(['429'])
        self.assertIn('TTS 실패', str(cm.exception))
        self.assertEqual(self.sleeps, list(self.B.TTS_WAITS))
        self.assertLess(sum(self.B.TTS_WAITS), 300)         # 한 문장에 5분 넘게 붙잡지 않음
        self.assertEqual(list(self.B.TTS_CACHE.glob('*.mp3')) if self.B.TTS_CACHE.exists() else [], [])

    def test_partial_audio_is_not_used(self):
        with self.assertRaises(RuntimeError):
            self.synth(['partial'])
        self.assertFalse((self.tmp / 'ep' / '01-cover.mp3').exists())

    def test_synth_runs_one_at_a_time(self):
        src = (ROOT / 'tools/build_campaign27.py').read_text(encoding='utf-8')
        self.assertIn('ThreadPoolExecutor(max_workers=1) as pool:\n            audios=list(pool.map(synth_one,jobs))', src)


class PrewarmTests(unittest.TestCase):
    def test_upcoming_follows_publish_order(self):
        sys.path.insert(0, str(ROOT))
        spec = importlib.util.spec_from_file_location('pw', ROOT / 'tools/prewarm_tts.py')
        pw = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pw)
        from src import campaign
        import json
        posted = {p['id'] for p in json.loads((ROOT / 'content/posted.json').read_text(encoding='utf-8'))}
        first, _ = campaign.next_ready(posted)
        ups = pw.upcoming(2)
        self.assertEqual(ups[0]['id'], first['id'])
        self.assertEqual(len({u['id'] for u in ups}), len(ups))
        self.assertFalse({u['id'] for u in ups} & posted)


if __name__ == '__main__':
    unittest.main()
