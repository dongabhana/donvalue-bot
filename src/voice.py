"""무료 한국어 TTS 내레이션 생성과 영상 믹싱."""
from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

from src import hooks


DEFAULT_VOICE = "ko-KR-InJoonNeural"


def narration_text(item: dict) -> str:
    """릴스 훅 데이터를 짧은 구어체 내레이션으로 바꾼다."""
    h = hooks.resolve(item)
    parts = [". ".join(str(x).strip() for x in h.get("big", []) if str(x).strip())]
    parts.append(str(h.get("stake", "")).strip())
    parts.extend(str(x).strip() for x in h.get("beats", []) if str(x).strip())
    verdict = str(item.get("verdict_text", "")).strip()
    if verdict:
        parts.append(f"결론은, {verdict}")
    return ". ".join(p.rstrip(". ") for p in parts if p).strip() + "."


async def _save(text: str, path: Path, voice: str) -> None:
    import edge_tts
    communicate = edge_tts.Communicate(text=text, voice=voice,
                                       rate=os.getenv("TTS_RATE", "+8%"),
                                       pitch=os.getenv("TTS_PITCH", "-2Hz"))
    await communicate.save(str(path))


def synthesize(item: dict, path: Path) -> tuple[Path, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = narration_text(item)
    asyncio.run(_save(text, path, os.getenv("TTS_VOICE", DEFAULT_VOICE)))
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError("TTS 음성 파일이 생성되지 않았습니다")
    return path, text


def mix_into_video(video: Path, speech: Path, out: Path) -> Path:
    """기존 배경음은 낮추고 내레이션을 앞에 둔다. 음성이 길면 마지막 화면을 연장한다."""
    from src.audio import probe_duration

    vd, sd = probe_duration(video), probe_duration(speech)
    extend = max(0.0, sd + 0.5 - vd)
    vf = f"tpad=stop_mode=clone:stop_duration={extend:.3f},format=yuv420p"
    af = ("[0:a]volume=-18dB[bg];"
          "[1:a]highpass=f=80,lowpass=f=12000,volume=1.25[voice];"
          "[bg][voice]amix=inputs=2:duration=longest:dropout_transition=2,"
          "loudnorm=I=-14:TP=-1.5:LRA=9[a]")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(speech),
        "-filter_complex", f"[0:v]{vf}[v];{af}", "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest", str(out),
    ], check=True, capture_output=True, text=True)
    return out
