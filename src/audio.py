"""
릴스 배경음 모듈 — 저작권 걱정 없는 오디오만 사용한다.

우선순위
  1) assets/audio/ 에 사용자가 넣어둔 실제 음원(.mp3/.m4a/.wav)
     └ 여기에 넣는 파일은 반드시 CC0/퍼블릭도메인/상업적 사용 허용이어야 한다.
        (assets/audio/README.md 의 출처 목록 참고)
  2) 파일이 하나도 없으면 이 모듈이 직접 '생성'한다.
     └ 합성음이라 저작권 자체가 발생하지 않는다. 실패해도 발행이 멈추지 않는 최후 안전판.

왜 인스타 '트렌딩 오디오'를 API 로 못 붙이나
  Meta 의 Audio API(ig_audio / audio_configuration)는
  "Instagram API with Facebook Login" 전용이다.
  이 프로젝트는 graph.instagram.com(Instagram Login)을 쓰므로 해당 API 를 호출할 수 없다.
  → 페이스북 로그인 방식으로 재연동하면 publish.py 의 IG_AUDIO_ID 경로가 열린다.
"""
from __future__ import annotations

import hashlib
import math
import os
import subprocess
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
ASSET_DIR = ROOT / "assets" / "audio"
SR = 44100

AUDIO_EXT = (".mp3", ".m4a", ".wav", ".ogg", ".aac")

# ---------------------------------------------------------------- 무드 프리셋
# 카드뉴스/정보형 릴스에 어울리는 차분한 진행만 골랐다.
# (도수, 코드 구성음 반음 오프셋) — 루트는 A2 기준
MOODS: dict[str, dict] = {
    "calm": {      # Am7 - Fmaj7 - Cmaj7 - G6  : 기본값, 차분한 설명형
        "bpm": 84,
        "root": 57,                       # A3 (MIDI)
        "chords": [[0, 3, 7, 10], [-4, 0, 4, 7], [3, 7, 10, 14], [-2, 2, 5, 9]],
        "hat": 0.5,
    },
    "focus": {     # Dm9 - Bb - F - C : 조금 더 또렷, 숫자 얘기할 때
        "bpm": 92,
        "root": 62,
        "chords": [[0, 3, 7, 14], [-4, 0, 3, 7], [-9, -5, 0, 4], [-2, 2, 5, 9]],
        "hat": 0.7,
    },
    "warm": {      # Cmaj7 - Am7 - Dm7 - G7 : 결론/공감형
        "bpm": 78,
        "root": 60,
        "chords": [[0, 4, 7, 11], [-3, 0, 4, 7], [2, 5, 9, 12], [-5, -1, 2, 5]],
        "hat": 0.35,
    },
}


def _hz(midi: float) -> float:
    return 440.0 * (2 ** ((midi - 69) / 12))


def _env(n: int, attack: float, decay: float, sustain: float = 0.0) -> np.ndarray:
    """간단한 AD(+S) 엔벨로프."""
    a = max(1, int(attack * SR))
    d = max(1, int(decay * SR))
    out = np.zeros(n, dtype=np.float32)
    a = min(a, n)
    out[:a] = np.linspace(0, 1, a, dtype=np.float32)
    rest = n - a
    if rest > 0:
        d = min(d, rest)
        out[a:a + d] = np.linspace(1, sustain, d, dtype=np.float32)
        if rest > d:
            out[a + d:] = sustain
    return out


def _lowpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    """원폴 로우패스. 합성음 특유의 날카로움을 깎는다."""
    dt = 1.0 / SR
    rc = 1.0 / (2 * math.pi * cutoff)
    alpha = dt / (rc + dt)
    out = np.empty_like(x)
    acc = 0.0
    for i in range(x.size):          # 길이가 길지 않아 파이썬 루프로 충분
        acc += alpha * (x[i] - acc)
        out[i] = acc
    return out


def _pad(freqs: list[float], dur: float, gain: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float32) / SR
    buf = np.zeros(n, dtype=np.float32)
    for f in freqs:
        for detune, w in ((0.0, 1.0), (+0.15, 0.5), (-0.15, 0.5)):
            buf += w * np.sin(2 * np.pi * (f + detune) * t, dtype=np.float32)
        buf += 0.22 * np.sin(2 * np.pi * f * 2 * t, dtype=np.float32)   # 배음
    buf /= max(1.0, len(freqs) * 2.2)
    return buf * _env(n, dur * 0.28, dur * 0.5, 0.55) * gain


def _bass(f: float, dur: float, gain: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float32) / SR
    sig = np.sin(2 * np.pi * f * t, dtype=np.float32)
    sig += 0.25 * np.sin(2 * np.pi * f * 2 * t, dtype=np.float32)
    return sig * _env(n, 0.01, dur * 0.7, 0.05) * gain


def _kick(dur: float, gain: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n, dtype=np.float32) / SR
    f = 110 * np.exp(-t * 26) + 45
    sig = np.sin(2 * np.pi * np.cumsum(f) / SR, dtype=np.float32)
    return sig * _env(n, 0.002, dur * 0.55) * gain


def _hat(dur: float, gain: float, rng: np.random.Generator) -> np.ndarray:
    n = int(dur * SR)
    sig = rng.standard_normal(n).astype(np.float32)
    sig = sig - _lowpass(sig, 4000)          # 하이패스 근사
    return sig * _env(n, 0.001, dur * 0.35) * gain


def synth_loop(seed: str, seconds: float, mood: str = "calm") -> np.ndarray:
    """저작권이 존재하지 않는 배경음을 직접 합성한다."""
    cfg = MOODS.get(mood, MOODS["calm"])
    rng = np.random.default_rng(int(hashlib.sha1(seed.encode()).hexdigest()[:8], 16))

    beat = 60.0 / cfg["bpm"]
    bar = beat * 4
    total = int(math.ceil(seconds / bar)) * bar + 1.0
    out = np.zeros(int(total * SR) + SR, dtype=np.float32)

    def add(buf: np.ndarray, at: float):
        i = int(at * SR)
        out[i:i + buf.size] += buf[: max(0, out.size - i)]

    n_bars = int(total / bar)
    for b in range(n_bars):
        chord = cfg["chords"][b % len(cfg["chords"])]
        root = cfg["root"] + chord[0]
        freqs = [_hz(cfg["root"] + s) for s in chord]
        at = b * bar
        add(_pad(freqs, bar * 1.05, 0.30), at)
        add(_bass(_hz(root - 24), beat * 1.6, 0.34), at)
        add(_bass(_hz(root - 24), beat * 1.1, 0.22), at + beat * 2.5)
        add(_kick(0.30, 0.38), at)
        add(_kick(0.30, 0.30), at + beat * 2)
        for e in range(8):                       # 8분음표 하이햇
            if e % 2 == 1 or rng.random() < 0.35:
                add(_hat(0.06, 0.05 * cfg["hat"], rng), at + e * beat / 2)

    out = out[: int(seconds * SR)]
    out = np.tanh(out * 1.4) * 0.7               # 소프트 새추레이션
    peak = float(np.max(np.abs(out))) or 1.0
    return (out / peak * 0.72).astype(np.float32)


def _write_wav(path: Path, mono: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(mono, -1, 1)
    stereo = np.repeat((pcm * 32767).astype(np.int16)[:, None], 2, axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(stereo.tobytes())
    return path


def asset_tracks() -> list[Path]:
    if not ASSET_DIR.exists():
        return []
    return sorted(p for p in ASSET_DIR.iterdir()
                  if p.suffix.lower() in AUDIO_EXT and p.is_file())


def pick_track(seed: str, seconds: float, workdir: Path,
               mood: str = "calm") -> tuple[Path, str]:
    """(오디오 파일 경로, 출처설명) 을 돌려준다.

    assets/audio 에 실제 음원이 있으면 seed 로 결정론적으로 하나 고른다.
    (같은 편을 다시 렌더해도 같은 곡 → 재현 가능)
    """
    tracks = asset_tracks()
    if tracks:
        idx = int(hashlib.sha1(seed.encode()).hexdigest(), 16) % len(tracks)
        return tracks[idx], f"assets/audio/{tracks[idx].name}"
    wav = _write_wav(workdir / "bgm.wav", synth_loop(seed, seconds, mood))
    return wav, f"자체 합성 ({mood})"


def mux(video: Path, audio: Path, out: Path,
        music_db: float | None = None, fade_out: float = 1.2) -> Path:
    """영상에 배경음을 입힌다. 음원이 짧으면 루프로 채우고, 끝은 페이드아웃.

    내레이션이 없는 릴스라 음악이 유일한 소리다. loudnorm 으로 -16 LUFS 에 맞춘 뒤
    살짝만 낮춘다(-3dB). 나중에 보이스오버를 얹으면 REEL_MUSIC_DB 로 더 내리면 된다.
    """
    if music_db is None:
        music_db = float(os.getenv("REEL_MUSIC_DB", "-3"))
    dur = probe_duration(video)
    af = (f"aloop=loop=-1:size=2e9,atrim=0:{dur:.3f},"
          f"afade=t=in:st=0:d=0.6,"
          f"afade=t=out:st={max(0.0, dur - fade_out):.3f}:d={fade_out},"
          f"loudnorm=I=-16:TP=-1.5:LRA=11,"
          f"volume={music_db}dB,aformat=sample_rates=44100:channel_layouts=stereo")
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-i", str(video), "-i", str(audio),
         "-filter_complex", f"[1:a]{af}[a]",
         "-map", "0:v", "-map", "[a]",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
         "-shortest", "-movflags", "+faststart", str(out)],
        check=True, capture_output=True, text=True)
    return out


def probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True)
    return float(r.stdout.strip())


if __name__ == "__main__":                     # 미리듣기용
    import sys
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 28.0
    mood = sys.argv[2] if len(sys.argv) > 2 else "calm"
    p = _write_wav(Path("out") / f"preview_{mood}.wav", synth_loop("preview", secs, mood))
    print("→", p)
