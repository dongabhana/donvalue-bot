"""
카드 PNG 를 인스타 릴스용 세로 영상(mp4)으로 합친다.

왜 릴스인가
  팔로워가 적은 계정에서 캐러셀은 비팔로워에게 거의 도달하지 않는다.
  릴스는 팔로워 수와 무관하게 배포되므로 콜드스타트를 뚫는 통로가 된다.

만드는 영상
  1080x1920 (9:16) · 카드당 SEC_PER_CARD 초 · H.264 + 무음 AAC
  카드(1080x1350)는 세로 화면 가운데에 얹고 배경은 카드와 같은 어두운 톤.
  인스타가 오디오 스트림 없는 영상을 거부하는 경우가 있어 무음 트랙을 넣는다.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

W, H = 1080, 1920
SEC_PER_CARD = 2.6          # 표지는 아래에서 따로 늘린다
COVER_EXTRA = 1.2           # 첫 장은 훅을 읽을 시간이 더 필요하다
BG = "#101217"
FPS = 30


class ReelError(RuntimeError):
    pass


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def build_reel(card_paths: list[Path], outfile: Path) -> Path:
    """카드 이미지들을 이어붙여 세로 영상을 만든다."""
    if not ffmpeg_available():
        raise ReelError("ffmpeg 가 없습니다. (GitHub Actions 러너에는 기본 설치되어 있습니다)")
    if not card_paths:
        raise ReelError("카드 이미지가 없습니다.")

    outfile.parent.mkdir(parents=True, exist_ok=True)
    concat = outfile.parent / "_concat.txt"

    lines = []
    for i, p in enumerate(card_paths):
        dur = SEC_PER_CARD + (COVER_EXTRA if i == 0 else 0)
        lines.append(f"file '{p.resolve()}'")
        lines.append(f"duration {dur:.2f}")
    # concat demuxer 는 마지막 파일을 한 번 더 적어야 길이가 반영된다
    lines.append(f"file '{card_paths[-1].resolve()}'")
    concat.write_text("\n".join(lines), encoding="utf-8")

    vf = (
        f"scale={W}:-2:flags=lanczos,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={BG},"
        f"format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(concat),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-vf", vf,
        "-r", str(FPS),
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "96k",
        "-shortest",
        str(outfile),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    concat.unlink(missing_ok=True)
    if r.returncode != 0 or not outfile.exists():
        raise ReelError(f"ffmpeg 실패: {r.stderr[:400]}")
    return outfile


def duration_of(card_count: int) -> float:
    return card_count * SEC_PER_CARD + COVER_EXTRA


if __name__ == "__main__":
    import sys
    cards = sorted(Path(sys.argv[1]).glob("*.png"))
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "reel.mp4")
    p = build_reel(cards, out)
    print(p, f"{p.stat().st_size/1024/1024:.2f}MB", f"{duration_of(len(cards)):.1f}s")
