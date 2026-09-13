import json
import subprocess
import wave
from pathlib import Path

from src import voice, youtube


ITEM = {
    "product": "노트북 총비용",
    "hook": "70만원이 90만원 되는 순간",
    "caption": "본체 가격만 보면 안 됩니다.",
    "hashtags": ["노트북", "가성비"],
    "cards": [{"title": "추가 비용", "body": "허브와 저장장치를 더하세요."}],
    "verdict_text": "본체가 아니라 사용 구성을 비교하세요",
    "reel": {
        "big": ["70만원", "노트북이", "90만원 된다"],
        "stake": "주변기기 가격을 빼먹었기 때문입니다",
        "beats": ["허브와 저장장치까지 더해야 합니다"],
    },
}


def test_narration_and_metadata():
    script = voice.narration_text(ITEM)
    assert "70만원" in script
    assert "결론은" in script
    title, description = youtube.metadata(ITEM)
    assert len(title) <= 100
    assert "#Shorts" in description


def _tone(path: Path, seconds: float):
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
        f"color=c=black:s=1080x1920:r=10:d={seconds}", "-f", "lavfi", "-i",
        f"sine=frequency=220:duration={seconds}", "-shortest", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
    ], check=True)


def _speech(path: Path, seconds: float):
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
        f"sine=frequency=440:duration={seconds}", "-c:a", "libmp3lame", str(path),
    ], check=True)


def test_voice_mix_extends_video(tmp_path):
    video, speech, out = tmp_path / "v.mp4", tmp_path / "s.mp3", tmp_path / "out.mp4"
    _tone(video, 1.0)
    _speech(speech, 1.5)
    voice.mix_into_video(video, speech, out)
    assert out.exists() and out.stat().st_size > 0
