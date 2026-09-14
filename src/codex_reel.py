"""
GPT(codex) 편은 codex 자신의 화면으로 영상을 만든다.

왜 이 파일이 생겼나
  처음엔 codex 편도 이쪽 장면 렌더러(src/reel_scenes.py)로 다시 그렸다.
  '채널 톤을 하나로 통일하는 게 낫다'는 판단이었는데, 그건 물어보지 않고
  내린 결정이었고 실제로 표지가 더 나빠졌다. codex 에는 사진 표지,
  versus/cart 픽토그램, 팔레트(coral 등) 같은 자기 디자인이 이미 있다.

무엇을 바꾸고 무엇을 지키나
  화면은 codex 것 그대로 쓴다(codex/media.py 의 카드 페인터를 직접 호출).
  대신 **길이와 소리는 이쪽 규칙**을 따른다.
    · 장면 길이 = max(codex 가 정한 seconds, 나레이션 길이 + 여백)
    · 나레이션 + 배경음 더킹은 src/tts.py, src/audio.py 그대로

슬라이드와 대본 칸의 대응
  codex 슬라이드는 [표지, 본문…, 결론, 참여유도] 순서로 고정돼 있다.
    슬라이드 0        ← hook (+ stake 를 붙여 표지를 조금 더 붙든다)
    슬라이드 1..n-3   ← beats
    슬라이드 n-2      ← verdict
    슬라이드 n-1      ← loop
"""
from __future__ import annotations

import shutil
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
W, H = 1080, 1920
FPS = 30

# 화질/용량 손잡이. 숫자가 클수록 파일이 작아진다(화질은 조금 내려간다).
# 회사망처럼 업로드 용량 제한이 있는 곳에서 손으로 올려야 할 때 쓴다.
#   20 = 기본(편당 10MB 안팎) / 28 = 가벼움(편당 3MB 안팎)
# 유튜브는 어차피 받아서 다시 인코딩하므로 28 정도까지는 체감 차이가 작다.
CRF = os.getenv("REEL_CRF", "21")

# codex 카드가 1080x1350 으로 나오는 스타일은 세로로 채워야 한다.
PAD_TOP = 250
PAD_BG = {"checkout_pop": "0xFFF5E8"}
PAD_BG_DEFAULT = "0x101820"


class CodexReelError(RuntimeError):
    pass


def raw_item(item_id: str) -> dict | None:
    """codex/content.json 원본(변환 전)을 찾는다. 렌더러가 원본을 먹는다."""
    import json
    path = ROOT / "codex" / "content.json"
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("items", raw) if isinstance(raw, dict) else raw
    return next((x for x in items if x.get("id") == item_id), None)


def _painter(cx: dict):
    """(슬라이드 그리는 함수, 세로 채움 색). 스타일별로 갈린다."""
    from codex import media

    style = cx.get("visual_style")
    if style == "money_editorial_v2":
        # 이 경로는 이미 1080x1920 을 그린다(사진 표지 포함)
        return lambda s, i: media.editorial_card(cx, s, i, reel=True), None
    if style == "checkout_pop":
        return lambda s, i: media.pop_card(cx, s, i), PAD_BG["checkout_pop"]
    raise CodexReelError(f"모르는 visual_style: {style}")


def narration_lines(cx: dict, script: dict | None) -> list[str]:
    """슬라이드 수와 같은 길이의 대사 목록. 대본이 없으면 전부 빈 문자열."""
    n = len(cx.get("slides") or [])
    if not script or n == 0:
        return [""] * n

    from src import tts as tts_mod

    hook = str(script.get("hook") or "").strip()
    stake = str(script.get("stake") or "").strip()
    beats = [str(b) for b in (script.get("beats") or [])]
    verdict = str(script.get("verdict") or "").strip()
    loop = str(script.get("loop") or "").strip()

    lines = [""] * n
    # 표지에서 훅과 stake 를 이어 말한다. codex 표지는 원래 1~2초로 짧지만,
    # 말이 길면 장면이 늘어나므로 첫 화면을 더 붙들게 된다. 훅이라 그게 낫다.
    lines[0] = " ".join(x for x in (hook, stake) if x)
    if n >= 4:
        for k in range(1, n - 2):
            idx = k - 1
            lines[k] = beats[idx] if idx < len(beats) else ""
        lines[n - 2] = verdict
        lines[n - 1] = loop
    elif n >= 2:
        lines[n - 1] = verdict or loop

    return [tts_mod.speakable(x, tts_mod.SCRIPT_LINE) for x in lines]


def _encode(png: Path, seconds: float, out: Path, pad_bg: str | None) -> Path:
    n = max(2, int(round(seconds * FPS)))
    motion = (f"zoompan=z='1+0.03*on/{n}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2'"
              f":d={n}:fps={FPS}")
    if pad_bg:                      # 1080x1350 카드를 세로로 채운다
        vf = (f"{motion}:s=1080x1350,"
              f"pad={W}:{H}:0:{PAD_TOP}:color={pad_bg},format=yuv420p")
    else:
        vf = f"{motion}:s={W}x{H},format=yuv420p"
    r = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(png), "-vf", vf,
         "-frames:v", str(n), "-c:v", "libx264", "-preset", "medium",
         "-crf", CRF, "-pix_fmt", "yuv420p", "-r", str(FPS), str(out)],
        capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        raise CodexReelError(f"ffmpeg(codex 장면) 실패: {r.stderr[:300]}")
    return out


def build(cx: dict, outfile: Path) -> tuple[Path, str]:
    """codex 원본 한 편을 세로영상으로. (파일, 설명문구) 를 돌려준다."""
    from src import audio as audio_mod
    from src import tts as tts_mod

    slides = list(cx.get("slides") or [])
    if not slides:
        raise CodexReelError("슬라이드가 없습니다")

    paint, pad_bg = _painter(cx)
    script = tts_mod.scripts().get(cx["id"])
    lines = narration_lines(cx, script)

    work = Path(tempfile.mkdtemp(prefix=f"cxreel_{cx['id']}_"))
    narration_fail = ""
    try:
        # 1) 나레이션 먼저 — 말이 길면 장면을 늘려야 하므로
        voices: list[Path | None] = [None] * len(slides)
        if tts_mod.enabled() and any(lines):
            if not tts_mod.available():
                narration_fail = "edge-tts 미설치"
                print("[tts] ⚠ edge-tts 가 없어 나레이션 없이 진행합니다")
            else:
                try:
                    for i, text in enumerate(lines):
                        if text:
                            voices[i] = tts_mod.synth_line(
                                text, work / f"v{i:02d}.mp3")
                except Exception as e:                            # noqa: BLE001
                    print(f"[tts] ⚠ 나레이션 실패 → 무음으로 진행합니다: {e}")
                    narration_fail = str(e)[:120]
                    voices = [None] * len(slides)

        # 2) 장면 길이 — codex 가 정한 시간과 말 길이 중 긴 쪽
        plan: list[dict] = []
        for i, slide in enumerate(slides):
            base = float(slide.get("seconds") or 3.5)
            if voices[i] is not None:
                import math
                need = (tts_mod._duration(voices[i])
                        + tts_mod.LEAD + tts_mod.TAIL)
                base = max(base, math.ceil(need * 100) / 100)
            plan.append({"kind": "slide", "dur": base})

        # 3) codex 화면 그대로 그려서 인코딩
        segs = []
        for i, slide in enumerate(slides):
            png = work / f"s{i:02d}.jpg"
            paint(slide, i).save(png, quality=95)
            segs.append(_encode(png, plan[i]["dur"], work / f"s{i:02d}.mp4", pad_bg))

        lst = work / "_scenes.txt"
        lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in segs),
                       encoding="utf-8")
        silent = work / "silent.mp4"
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", str(lst), "-c", "copy", str(silent)],
            capture_output=True, text=True)
        if r.returncode != 0 or not silent.exists():
            raise CodexReelError(f"이어붙이기 실패: {r.stderr[:300]}")

        # 4) 소리 — 나레이션 + 배경음 더킹 (이쪽 규칙 그대로)
        seconds = audio_mod.probe_duration(silent)
        track, source = audio_mod.pick_track(cx["id"], seconds, work, "focus")
        outfile.parent.mkdir(parents=True, exist_ok=True)
        spoken = sum(1 for v in voices if v is not None)
        if spoken:
            vtrack = tts_mod.build_track(plan, voices, work)
            audio_mod.mux_with_voice(silent, track, vtrack, outfile)
        else:
            audio_mod.mux(silent, track, outfile)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    tail = (f" / ⚠ 목소리 없음({narration_fail})" if narration_fail
            else f" / 나레이션 {spoken}컷")
    note = (f"codex 화면({cx.get('visual_style')}) · {len(slides)}장 / "
            f"{audio_mod.probe_duration(outfile):.1f}초 / 음원 {source}{tail}")
    return outfile, note
