"""
카드 데이터를 인스타 릴스용 세로 영상(mp4)으로 만든다.

왜 릴스인가
  팔로워가 적은 계정에서 캐러셀은 비팔로워에게 거의 도달하지 않는다.
  릴스는 팔로워 수와 무관하게 배포되므로 콜드스타트를 뚫는 통로가 된다.

v2 에서 바뀐 것 (2026-09)
  이전에는 카드 PNG(1080x1350)를 9:16 화면 가운데에 얹었다. 만들기는 쉬운데
  위아래가 비고, 첫 화면이 정지 이미지라 1초 안에 넘어간다. 그래서 두 가지를 바꿨다.

  1) 릴스 전용 세로 화면을 새로 그린다 (src/reel_scenes.py)
     · 훅을 한 줄씩 띄우는 3단 리빌 — 첫 1.5초에 '화면이 움직인다'는 신호를 준다
     · 상단에 남은 분량 진행바 — 완주율이 1순위 지표라 '얼마 안 남았다'를 보여준다
     · 마지막 장을 첫 장과 맞물리게 끝내 자연스럽게 한 번 더 재생되게 한다
     · 모든 장에 느린 줌/팬 — 정지 이미지는 알고리즘이 밀어주지 않는다
  2) 배경음을 넣는다 (src/audio.py)
     무음 릴스는 소리를 켜둔 사람에게 '빈 영상'으로 느껴진다.
     저작권 문제를 피하려고 assets/audio 의 실제 음원 → 없으면 자체 합성 순으로 쓴다.

  화면 그리기가 어떤 이유로든 실패하면 **예전 방식(카드 얹기)으로 조용히 내려간다.**
  릴스가 안 나가는 것보다 예전 모양으로라도 나가는 게 낫다.

길이를 어떻게 정하나
  장마다 글자 수에 비례해 노출 시간을 주고(MIN_SEC~MAX_SEC),
  합이 TARGET_SEC 를 넘으면 '덜어낼 수 있는 장'만 뒤에서부터 뺀다.
  숫자(figure)가 박힌 장과 표지·결론은 알맹이라 빼지 않는다.
  큐에서 `reel_cards: [1, 2, 4]` 로 직접 지정할 수도 있다.

만드는 영상
  1080x1920 (9:16) · H.264 + AAC(배경음) · 보통 25~30초 / 3~6MB
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
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

# 훅 리빌 타이밍 — 장면이 아니라 '한 줄이 더 떠오르는' 단위라 따로 둔다
D_HOOK_STEP = 0.42
D_HOOK_HOLD = 1.25
D_STAKE_MIN, D_STAKE_MAX = 2.4, 4.0
D_LOOP = 2.0


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
    """(예전 방식용) 릴스에 넣을 카드와 각 장의 노출 시간을 정한다."""
    n_cards = len(item.get("cards", []))
    if len(paths) != n_cards + 2:          # 표지 + 본문 + 결론
        return list(paths), [_dur("", i == 0) + 1.0 for i in range(len(paths))]

    texts = card_texts(item)
    durs = [_dur(t, i == 0) for i, t in enumerate(texts)]
    last = len(paths) - 1

    override = item.get("reel_cards")
    if override:
        sel = [0] + [int(i) for i in override if 1 <= int(i) <= n_cards] + [last]
    else:
        sel = list(range(len(paths)))
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


def plan_scenes(item: dict, target: float = TARGET_SEC) -> list[dict]:
    """릴스 전용 화면의 장면 목록과 각 장의 길이를 정한다.

    반환: [{kind, dur, motion, ...}] — kind 는 hook/stake/beat/verdict/loop
    """
    from src import hooks as hooks_mod

    h = hooks_mod.resolve(item)
    cards = item.get("cards", [])
    beats = h["beats"]

    # 본문 후보 (카드 인덱스는 1부터)
    idxs = list(range(1, len(cards) + 1))
    override = item.get("reel_cards")
    if override:
        idxs = [int(i) for i in override if 1 <= int(i) <= len(cards)]

    def beat_dur(i: int) -> float:
        card = cards[i - 1]
        text = f"{card.get('title', '')} {beats[i - 1] if i - 1 < len(beats) else ''}"
        return _dur(text)

    hook_lines = max(1, len(h["big"]))
    fixed = (hook_lines - 1) * D_HOOK_STEP + D_HOOK_HOLD + D_HOOK_STEP
    stake_d = round(max(D_STAKE_MIN, min(D_STAKE_MAX, len(h["stake"]) / CPS)), 2)
    verdict_d = _dur(str(item.get("verdict_text", "")))
    fixed += stake_d + verdict_d + D_LOOP

    # 길면 덜어낸다. 숫자(figure)가 박힌 장은 알맹이라 남긴다.
    essential = {i for i in idxs if cards[i - 1].get("figure")}
    while (fixed + sum(beat_dur(i) for i in idxs)) > target and len(idxs) > MIN_BODY_CARDS:
        droppable = [i for i in reversed(idxs) if i not in essential]
        if not droppable:
            break
        idxs.remove(droppable[0])

    plan: list[dict] = []
    for r in range(1, hook_lines):
        plan.append({"kind": "hook", "reveal": r, "dur": D_HOOK_STEP, "motion": "still"})
    plan.append({"kind": "hook", "reveal": hook_lines,
                 "dur": D_HOOK_HOLD + D_HOOK_STEP, "motion": "in"})
    plan.append({"kind": "stake", "dur": stake_d, "motion": "out"})

    motions = ["in", "up", "out", "down"]
    for n, i in enumerate(idxs):
        ratio = 0.18 + (0.70 - 0.18) * (n + 1) / len(idxs)
        plan.append({"kind": "beat", "card": i, "n": n + 1, "total": len(idxs),
                     "ratio": ratio, "dur": beat_dur(i), "motion": motions[n % 4]})
    plan.append({"kind": "verdict", "dur": verdict_d, "motion": "in"})
    plan.append({"kind": "loop", "dur": D_LOOP, "motion": "out"})
    return plan


def plan_summary(item: dict, paths: list[Path]) -> str:
    try:
        plan = plan_scenes(item)
        beats = [s for s in plan if s["kind"] == "beat"]
        total = sum(s["dur"] for s in plan)
        dropped = len(item.get("cards", [])) - len(beats)
        return (f"본문 {len(beats)}장 / 전체 {total:.1f}초 / 장면 {len(plan)}개"
                + (f" (본문 {dropped}장 축약)" if dropped > 0 else ""))
    except Exception:                                             # noqa: BLE001
        sel, durs = plan_reel(item, paths)
        return (f"{len(sel)}장 / {sum(durs):.1f}초 "
                f"(원본 {len(paths)}장, 장당 {min(durs):.1f}~{max(durs):.1f}초)")


# ------------------------------------------------------------------ 인코딩
def _encode_scene(png: Path, seconds: float, motion: str, out: Path) -> Path:
    """정지 이미지 한 장을 '느리게 움직이는' 구간 영상으로 만든다."""
    n = max(2, int(round(seconds * FPS)))
    zmax = 1.06
    if motion == "in":
        z, x, y = f"1+{zmax-1:.4f}*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif motion == "out":
        z, x, y = f"{zmax:.4f}-{zmax-1:.4f}*on/{n}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif motion == "up":
        z, x, y = "1.04", "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*(1-on/{n})"
    elif motion == "down":
        z, x, y = "1.04", "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*on/{n}"
    else:
        z, x, y = "1", "0", "0"

    vf = f"zoompan=z='{z}':x='{x}':y='{y}':d={n}:s={W}x{H}:fps={FPS},format=yuv420p"
    r = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(png),
         "-vf", vf, "-frames:v", str(n),
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-pix_fmt", "yuv420p", "-r", str(FPS), str(out)],
        capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        raise ReelError(f"ffmpeg(장면) 실패: {r.stderr[:300]}")
    return out


def _concat(segments: list[Path], out: Path) -> Path:
    lst = out.parent / "_scenes.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in segments), encoding="utf-8")
    r = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(lst), "-c", "copy", str(out)], capture_output=True, text=True)
    lst.unlink(missing_ok=True)
    if r.returncode != 0 or not out.exists():
        raise ReelError(f"ffmpeg(이어붙이기) 실패: {r.stderr[:300]}")
    return out


def _build_scene_reel(item: dict, outfile: Path, brand: str, handle: str) -> tuple[Path, str]:
    """릴스 전용 세로 화면을 그려서 배경음까지 입힌다."""
    from src import audio as audio_mod
    from src import hooks as hooks_mod
    from src import reel_scenes as sc

    h = hooks_mod.resolve(item)
    cards = item.get("cards", [])
    plan = plan_scenes(item)

    work = Path(tempfile.mkdtemp(prefix=f"reel_{item['id']}_"))
    try:
        segs: list[Path] = []
        for i, s in enumerate(plan):
            if s["kind"] == "hook":
                img = sc.scene_hook(h, brand, handle, s["reveal"], item, str(Path.cwd()))
            elif s["kind"] == "stake":
                img = sc.scene_stake(h, brand, handle, item)
            elif s["kind"] == "beat":
                c = cards[s["card"] - 1]
                text = h["beats"][s["card"] - 1] if s["card"] - 1 < len(h["beats"]) \
                    else c.get("body", "")
                img = sc.scene_beat(s["n"], s["total"], c.get("title", ""), text,
                                    brand, handle, s["ratio"], c, item)
            elif s["kind"] == "verdict":
                img = sc.scene_verdict(item, brand, handle, h["voice"])
            else:
                img = sc.scene_loop(h, brand, handle, item)

            png = work / f"s{i:02d}.png"
            img.save(png, "PNG")
            segs.append(_encode_scene(png, s["dur"], s["motion"], work / f"s{i:02d}.mp4"))

        silent = _concat(segs, work / "silent.mp4")
        seconds = audio_mod.probe_duration(silent)
        track, source = audio_mod.pick_track(item["id"], seconds, work, h["mood"])
        outfile.parent.mkdir(parents=True, exist_ok=True)
        audio_mod.mux(silent, track, outfile)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    n_beats = sum(1 for s in plan if s["kind"] == "beat")
    note = (f"전용화면 · 본문 {n_beats}장 / "
            f"{audio_mod.probe_duration(outfile):.1f}초 / 음원 {source}")
    return outfile, note


# ------------------------------------------------------------------ 예전 방식(폴백)
INTRO_FADE = 0.45
INTRO_RISE = 0.85
INTRO_SHIFT = 40


def _build_reel_motion(card_paths: list[Path], durations: list[float],
                       outfile: Path) -> Path:
    """카드 PNG 를 9:16 에 얹는 예전 방식. 첫 장에 페이드인 + 밀려 올라오기."""
    args: list[str] = ["ffmpeg", "-y", "-loglevel", "error"]
    args += ["-f", "lavfi", "-t", f"{durations[0]:.2f}",
             "-i", f"color=c=0x101217:s={W}x{H}:r={FPS}"]
    for p, d in zip(card_paths, durations):
        args += ["-loop", "1", "-framerate", str(FPS), "-t", f"{d:.2f}", "-i", str(p)]
    args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]

    y_expr = (f"(H-h)/2-{INTRO_SHIFT}*max(0\\,1-t/{INTRO_RISE})")
    parts = [
        f"[1:v]scale={W}:-2,setsar=1[cov];",
        f"[0:v][cov]overlay=x=(W-w)/2:y='{y_expr}':shortest=1,"
        f"fade=t=in:st=0:d={INTRO_FADE},fps={FPS},format=yuv420p,setsar=1[v0];",
    ]
    for i in range(1, len(card_paths)):
        parts.append(
            f"[{i+1}:v]scale={W}:-2,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x101217,"
            f"fps={FPS},format=yuv420p,setsar=1[v{i}];")
    parts.append("".join(f"[v{i}]" for i in range(len(card_paths)))
                 + f"concat=n={len(card_paths)}:v=1:a=0[v]")

    args += ["-filter_complex", "".join(parts),
             "-map", "[v]", "-map", f"{len(card_paths)+1}:a",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart",
             "-c:a", "aac", "-b:a", "96k", "-shortest", str(outfile)]

    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0 or not outfile.exists():
        raise ReelError(f"ffmpeg(모션) 실패: {r.stderr[:400]}")
    return outfile


def build_reel(card_paths: list[Path], outfile: Path,
               durations: list[float] | None = None,
               motion: bool = True) -> Path:
    """카드 이미지들을 이어붙여 세로 영상을 만든다 (예전 방식)."""
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

    if motion:
        try:
            return _build_reel_motion(card_paths, durations, outfile)
        except ReelError as e:
            print(f"[reel] 모션 인코딩 실패 → 기본 방식으로 진행: {e}")
    concat = outfile.parent / "_concat.txt"

    lines = []
    for p, d in zip(card_paths, durations):
        lines.append(f"file '{p.resolve()}'")
        lines.append(f"duration {d:.2f}")
    lines.append(f"file '{card_paths[-1].resolve()}'")
    concat.write_text("\n".join(lines), encoding="utf-8")

    vf = (f"scale={W}:-2:flags=lanczos,"
          f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={BG},format=yuv420p")
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "concat", "-safe", "0", "-i", str(concat),
           "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
           "-vf", vf, "-r", str(FPS),
           "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart",
           "-c:a", "aac", "-b:a", "96k", "-shortest", str(outfile)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    concat.unlink(missing_ok=True)
    if r.returncode != 0 or not outfile.exists():
        raise ReelError(f"ffmpeg 실패: {r.stderr[:400]}")
    return outfile


# ------------------------------------------------------------------ 진입점
def build_reel_for(item: dict, paths: list[Path], outfile: Path,
                   brand: str = "돈값하나?", handle: str = "@dongabhana",
                   style: str | None = None) -> tuple[Path, str]:
    """항목에 맞춰 릴스를 만든다.

    style: "scene"(기본, 전용 화면+배경음) | "cards"(예전 방식)
           환경변수 REEL_STYLE 로도 바꿀 수 있다.
    """
    import os

    if not ffmpeg_available():
        raise ReelError("ffmpeg 가 없습니다. 워크플로에서 apt-get install ffmpeg 를 확인하세요.")

    style = (style or os.getenv("REEL_STYLE") or "scene").lower()
    if style == "scene":
        try:
            return _build_scene_reel(item, outfile, brand, handle)
        except Exception as e:                                    # noqa: BLE001
            # 전용 화면은 '있으면 좋은 것'이다. 실패해도 릴스 자체는 나가야 한다.
            print(f"[reel] 전용 화면 실패 → 예전 방식(카드 얹기)으로 진행: {e}")

    sel, durs = plan_reel(item, paths)
    mp4 = build_reel(sel, outfile, durs)
    note = (f"카드 {len(sel)}장 / {sum(durs):.1f}초"
            + ("" if len(sel) == len(paths) else f" (원본 {len(paths)}장에서 축약)"))
    return mp4, note


if __name__ == "__main__":
    import sys, yaml
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src import hooks as hooks_mod

    queue = hooks_mod.attach(
        yaml.safe_load(Path("content/queue.yaml").read_text(encoding="utf-8")))
    want = sys.argv[1] if len(sys.argv) > 1 else None
    for it in queue["items"]:
        if want and it["id"] != want:
            print(f"{it['id']:24} {plan_summary(it, [])}")
            continue
        out = Path(".preview") / it["id"] / f"{it['id']}.mp4"
        mp4, note = build_reel_for(it, [], out,
                                   it.get("brand") or queue.get("brand", "돈값하나?"),
                                   queue.get("handle", "@dongabhana"))
        print(it["id"], "→", note, f"{mp4.stat().st_size/1024/1024:.2f}MB")
    if not want:
        print("\n특정 편을 실제로 만들려면: python -m src.reel <id>")
