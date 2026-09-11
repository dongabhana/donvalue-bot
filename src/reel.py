"""
카드 PNG 를 인스타 릴스용 세로 영상(mp4)으로 합친다.

왜 릴스인가
  팔로워가 적은 계정에서 캐러셀은 비팔로워에게 거의 도달하지 않는다.
  릴스는 팔로워 수와 무관하게 배포되므로 콜드스타트를 뚫는 통로가 된다.

길이를 어떻게 정하나
  고정 4.2초는 틀린 기준이었다. 카드마다 글자 수가 61자에서 147자까지 벌어지는데
  같은 시간을 주면 어떤 장은 못 읽고 어떤 장은 지루해진다.
  그래서 두 단계로 정한다.

  1) 장마다 글자 수에 비례해 노출 시간을 준다 (MIN_SEC ~ MAX_SEC 사이).
  2) 그렇게 합친 길이가 TARGET_SEC 를 넘으면 '덜어낼 수 있는 장'만 뒤에서부터 뺀다.

  덜어낼 수 없는 장 = 표지, 결론, 그리고 숫자(figure)가 박힌 장.
  숫자가 이 콘텐츠의 알맹이라 그건 길어지더라도 남긴다.
  즉 내용이 빽빽한 편은 안 줄고, 설명이 늘어진 편만 줄어든다.

  큐에서 `reel_cards: [1, 2, 4]` (cards 기준 1부터) 로 직접 지정할 수도 있다.

만드는 영상
  1080x1920 (9:16) · H.264 + 무음 AAC
  카드(1080x1350)는 세로 화면 가운데에 얹고 배경은 카드와 같은 어두운 톤.
  인스타가 오디오 스트림 없는 영상을 거부하는 경우가 있어 무음 트랙을 넣는다.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

W, H = 1080, 1920
BG = "#101217"
FPS = 30

CPS = 17.5          # 초당 읽는 글자 수. 릴스는 정독이 아니라 훑는 속도다.
MIN_SEC = 3.2       # 이보다 짧으면 무슨 장이었는지도 남지 않는다
MAX_SEC = 6.5       # 이보다 길면 읽기 전에 손가락이 먼저 올라간다
COVER_EXTRA = 1.8   # 첫 장은 훅을 읽고 '볼지 말지' 판단할 시간이 더 필요하다
TARGET_SEC = 28.0   # 이 길이를 넘으면 덜어낼 장을 찾는다
MIN_BODY_CARDS = 2  # 본문을 이보다 더 줄이면 계산 과정이 사라진다


class ReelError(RuntimeError):
    pass


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


# ------------------------------------------------------------------ 길이 계획
def card_texts(item: dict) -> list[str]:
    """render_item 과 같은 순서(표지 → 본문 → 결론)로 각 장의 텍스트를 만든다."""
    texts = [f"{item.get('product', '')} {item.get('hook', '')}"]
    for c in item.get("cards", []):
        parts = [str(c.get(k, "")) for k in
                 ("title", "figure", "figure_label", "body", "note")]
        texts.append(" ".join(p for p in parts if p))
    texts.append(str(item.get("verdict_text", "")))
    return texts


def _dur(text: str, is_cover: bool = False) -> float:
    base = len(text) / CPS
    base = max(MIN_SEC, min(MAX_SEC, base))
    return round(base + (COVER_EXTRA if is_cover else 0.0), 2)


def plan_reel(item: dict, paths: list[Path],
              target: float = TARGET_SEC) -> tuple[list[Path], list[float]]:
    """릴스에 넣을 장과 각 장의 노출 시간을 정한다."""
    n_cards = len(item.get("cards", []))
    if len(paths) != n_cards + 2:          # 표지 + 본문 + 결론
        # 구조가 예상과 다르면 균등 분배로 안전하게 처리한다
        return list(paths), [_dur("", i == 0) + 1.0 for i in range(len(paths))]

    texts = card_texts(item)
    durs = [_dur(t, i == 0) for i, t in enumerate(texts)]
    last = len(paths) - 1

    override = item.get("reel_cards")
    if override:
        sel = [0] + [int(i) for i in override if 1 <= int(i) <= n_cards] + [last]
    else:
        sel = list(range(len(paths)))
        # 숫자가 박힌 장은 알맹이라 후보에서 뺀다
        essential = {i + 1 for i, c in enumerate(item["cards"]) if c.get("figure")}
        droppable = [i for i in range(n_cards, 0, -1) if i not in essential]
        for d in droppable:
            if sum(durs[i] for i in sel) <= target:
                break
            if sum(1 for i in sel if 1 <= i <= n_cards) <= MIN_BODY_CARDS:
                break
            sel.remove(d)

    sel = sorted(set(sel))
    return [paths[i] for i in sel], [durs[i] for i in sel]


def plan_summary(item: dict, paths: list[Path]) -> str:
    sel, durs = plan_reel(item, paths)
    return (f"{len(sel)}장 / {sum(durs):.1f}초 "
            f"(원본 {len(paths)}장, 장당 {min(durs):.1f}~{max(durs):.1f}초)")


# ------------------------------------------------------------------ 인코딩
def build_reel(card_paths: list[Path], outfile: Path,
               durations: list[float] | None = None) -> Path:
    """카드 이미지들을 이어붙여 세로 영상을 만든다."""
    if not ffmpeg_available():
        raise ReelError("ffmpeg 가 없습니다. 워크플로에서 apt-get install ffmpeg 를 확인하세요.")
    if not card_paths:
        raise ReelError("카드 이미지가 없습니다.")
    if durations is None:
        durations = [4.2 + (COVER_EXTRA if i == 0 else 0)
                     for i in range(len(card_paths))]
    if len(durations) != len(card_paths):
        raise ReelError("카드 수와 노출 시간 수가 다릅니다.")

    outfile.parent.mkdir(parents=True, exist_ok=True)
    concat = outfile.parent / "_concat.txt"

    lines = []
    for p, d in zip(card_paths, durations):
        lines.append(f"file '{p.resolve()}'")
        lines.append(f"duration {d:.2f}")
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


def build_reel_for(item: dict, paths: list[Path], outfile: Path) -> tuple[Path, str]:
    """항목에 맞춰 장을 고르고 길이를 정해 영상을 만든다."""
    sel, durs = plan_reel(item, paths)
    mp4 = build_reel(sel, outfile, durs)
    note = (f"{len(sel)}장 / {sum(durs):.1f}초"
            + ("" if len(sel) == len(paths) else f" (원본 {len(paths)}장에서 축약)"))
    return mp4, note


if __name__ == "__main__":
    import sys, yaml

    queue = yaml.safe_load(Path("content/queue.yaml").read_text(encoding="utf-8"))
    for it in queue["items"]:
        fake = [Path(f"{it['id']}_{i:02d}.png") for i in range(1, len(it["cards"]) + 3)]
        sel, durs = plan_reel(it, fake)
        mark = "" if len(sel) == len(fake) else "  ← 축약"
        print(f"{it['id']:24} {len(sel)}장 {sum(durs):5.1f}초  "
              f"[{' '.join(f'{d:.1f}' for d in durs)}]{mark}")
    if len(sys.argv) > 1:
        cards = sorted(Path(sys.argv[1]).glob("*.png"))
        out = Path(sys.argv[2] if len(sys.argv) > 2 else "reel.mp4")
        p = build_reel(cards, out)
        print(p, f"{p.stat().st_size/1024/1024:.2f}MB")
