"""
나레이션(음성) 모듈 — 릴스/쇼츠에 사람 목소리를 얹는다.

왜 목소리인가
  글자만 있는 세로영상은 '읽어야 하는 것'이라 스크롤을 못 잡는다.
  쇼츠·릴스는 소리를 켜둔 상태로 넘기는 사람이 많고, 첫 1초에 말소리가
  들리면 손가락이 멈춘다. 유튜브 쇼츠는 특히 무음 영상 완주율이 낮다.

무엇으로 만드나
  edge-tts (Microsoft Edge 읽어주기 엔진). 선택 이유:
    · API 키·과금 없음 → 발행 편수가 늘어도 비용 0
    · 한국어 뉴럴 보이스 품질이 무료 중에서 가장 낫다
    · GitHub Actions 러너에서 그대로 돈다 (pip 한 줄)
  대신 비공식 클라이언트라 마이크로소프트가 막으면 죽을 수 있다.
  그래서 **실패해도 발행은 멈추지 않는다** — 나레이션 없이 예전처럼 나간다.
  유료로 갈아탈 자리는 synth_line() 하나뿐이다(구글 Cloud TTS 등).

싱크를 어떻게 맞추나
  영상 장면은 프레임 단위로 잘린다(n = round(초*30) 프레임).
  그래서 오디오도 **같은 프레임 수로 환산한 길이**로 만든다. 장면마다
  '앞 여백 + 말소리 + 뒤 여백'을 정확히 장면 길이에 맞춰 잘라 이어붙이면
  누적 오차 없이 끝까지 입이 맞는다.

장면 길이는 나레이션에 맞춰 늘어난다
  원래 계획된 노출 시간보다 말이 길면 장면을 늘린다. 반대는 하지 않는다
  (읽을 시간은 남겨둬야 한다). 그래서 전체 길이가 25~30초 → 35~50초쯤 된다.
  쇼츠 상한은 3분이라 여유가 있고, 릴스도 문제없다.

환경변수
  REEL_TTS        1(기본) | 0    나레이션 자체를 끈다
  TTS_VOICE       ko-KR-YuJinNeural (기본, 여성·또렷)
                  ko-KR-JiMinNeural(여성·가벼움) / ko-KR-SunHiNeural(여성·표준)
                  ko-KR-BongJinNeural(남성·활기) / ko-KR-InJoonNeural(남성·뉴스)
                  ko-KR-HyunsuMultilingualNeural(남성·차분)
  TTS_RATE        +22% (기본)    쇼츠는 빠른 편이 완주율이 낫다
  TTS_PITCH       +0Hz (기본)
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "tts"

FPS = 30                 # src.reel.FPS 와 반드시 같아야 한다
SR = 44100

LEAD = 0.28              # 장면이 바뀌고 말이 시작되기까지
TAIL = 0.42              # 말이 끝나고 다음 장면까지 (숨 쉴 틈)
MAX_LINE = 90            # 화면 문구를 읽을 때의 상한
SCRIPT_LINE = 150        # 손으로 쓴 대본은 더 길어도 된다(장면이 늘어난다)

# 쇼츠는 또렷하고 빠른 편이 귀에 박힌다. 차분한 남성 톤은 설명이 늘어진다.
DEFAULT_VOICE = "ko-KR-YuJinNeural"
DEFAULT_RATE = "+22%"


class TTSError(RuntimeError):
    pass


# ---------------------------------------------------------------- 켜짐/가능
def enabled() -> bool:
    return os.getenv("REEL_TTS", "1").lower() not in ("0", "false", "no", "off")


def available() -> bool:
    try:
        import edge_tts  # noqa: F401
    except Exception:                                             # noqa: BLE001
        return False
    return True


# ---------------------------------------------------------------- 읽을 문장
_NUM = re.compile(r"(\d),(\d)")


def speakable(text: str, limit: int = 0) -> str:
    """화면용 글자를 '읽었을 때 자연스러운' 문장으로 손본다.

    · 1,000 의 천단위 쉼표는 빼야 한다. 안 그러면 '일 쉼표 영영영'으로 읽는다.
    · 화면에서만 통하는 기호(· → / ~)는 말로 바꾼다.
    · 괄호 안 부연은 통째로 뺀다. 소리로 들으면 흐름만 끊는다.
    """
    t = (text or "").strip()
    t = re.sub(r"\([^)]*\)", " ", t)
    while _NUM.search(t):
        t = _NUM.sub(r"\1\2", t)
    t = t.replace("→", ", ").replace("↑", " 오름 ").replace("↓", " 내림 ")
    # 계산식 기호 — 화면에선 읽히지만 소리로는 전부 말로 풀어야 한다
    t = t.replace("×", " 곱하기 ").replace("÷", " 나누기 ")
    # '=' 는 조사('은/는')를 붙이면 받침에 따라 틀린다. 쉼표로 끊는 편이 자연스럽다.
    t = t.replace("=", ", ")
    # '+' 는 계산식일 때만 '더하기'다. '디즈니+' 같은 상품명은 건드리지 않는다.
    t = re.sub(r"(?<=[\d\s])\+(?=[\d\s])", " 더하기 ", t)
    t = t.replace("원/월", "원").replace("/월", " 월").replace("/", " ")
    t = re.sub(r"\bvs\.?\b", " 대 ", t, flags=re.I)
    t = t.replace("·", ", ").replace("~", " 에서 ")
    t = t.replace("%", "퍼센트").replace("₩", "")
    t = re.sub(r"#\S+", " ", t)
    t = re.sub(r"\s+([,.])", r"\1", t)          # ' ,' → ','
    t = re.sub(r"[,]{2,}", ",", t)
    t = re.sub(r"[.…]{2,}", ".", t)             # '합계는 33800원..' 같은 겹침
    t = re.sub(r"\.\s*,", ".", t)
    limit = limit or MAX_LINE
    t = re.sub(r"\s+", " ", t).strip(" ,.…")
    if len(t) <= limit:
        return t
    # 길면 자른다. 다만 어절 한가운데서 끊으면 '…를 더하는' 처럼 말이 끊긴다.
    # 문장 경계 → 쉼표 → 어절 순으로 물러나며 자연스러운 지점을 찾는다.
    cut = t[:limit]
    for sep in (". ", "? ", "! ", ", ", " "):
        at = cut.rfind(sep)
        if at >= limit // 2:
            return cut[:at].rstrip(" ,.…")
    return cut.rstrip(" ,.…")


SCRIPTS = ROOT / "content" / "narration.yaml"
_scripts_cache: dict | None = None


def scripts() -> dict:
    """편별 손으로 쓴 나레이션 대본. 없으면 빈 dict."""
    global _scripts_cache
    if _scripts_cache is None:
        if SCRIPTS.exists():
            import yaml
            _scripts_cache = yaml.safe_load(SCRIPTS.read_text(encoding="utf-8")) or {}
        else:
            _scripts_cache = {}
    return _scripts_cache


def _from_script(plan: list[dict], sc: dict) -> list[str]:
    """대본(narration.yaml)에서 장면별 문장을 뽑는다.

    beats 는 **카드 번호 순서 그대로** 적는다. 길이 때문에 중간 카드가
    빠져도 남은 카드가 자기 대사를 그대로 들고 간다.
    """
    beats = list(sc.get("beats") or [])
    hook_last = max((i for i, s in enumerate(plan) if s["kind"] == "hook"), default=-1)
    out: list[str] = []
    for i, s in enumerate(plan):
        k = s["kind"]
        if k == "hook":
            out.append(str(sc.get("hook") or "") if i == hook_last else "")
        elif k == "stake":
            out.append(str(sc.get("stake") or ""))
        elif k == "beat":
            n = s["card"] - 1
            out.append(str(beats[n]) if 0 <= n < len(beats) else "")
        elif k == "verdict":
            out.append(str(sc.get("verdict") or ""))
        else:
            out.append(str(sc.get("loop") or ""))
    return out


def script_for(plan: list[dict], item: dict, h: dict) -> list[str]:
    """장면 계획과 같은 길이의 '장면별 읽을 문장' 목록을 만든다.

    1순위는 content/narration.yaml 의 손으로 쓴 대본이다.
    **화면 글자를 그대로 읽지 않는 게 핵심** — 화면은 숫자를 보여주고
    목소리는 그 숫자가 왜 중요한지를 말해야 한다. 대본이 없는 편만
    아래 폴백으로 화면 문구를 읽는다(있는 것보단 낫지만 딱딱하다).

    빈 문자열이면 그 장면은 말 없이 지나간다(훅 리빌 중간 컷 등).
    """
    sc = scripts().get(item.get("id"))
    if sc:
        # 손으로 쓴 대본은 화면 글자수 제한과 무관하다. 조금 더 길어도 된다.
        return [speakable(x, SCRIPT_LINE) for x in _from_script(plan, sc)]

    cards = item.get("cards", [])
    lines: list[str] = []
    hook_last = max((i for i, s in enumerate(plan) if s["kind"] == "hook"), default=-1)

    for i, s in enumerate(plan):
        kind = s["kind"]
        if kind == "hook":
            # 리빌 중간 컷(0.4초)에는 말을 얹지 않는다. 마지막 훅에서 한 번에 읽는다.
            lines.append(" ".join(h["big"]) if i == hook_last else "")
        elif kind == "stake":
            lines.append(h["stake"])
        elif kind == "beat":
            c = cards[s["card"] - 1]
            beat = h["beats"][s["card"] - 1] if s["card"] - 1 < len(h["beats"]) \
                else c.get("body", "")
            # 화면용 문구는 글자수 제한에 걸려 '…' 로 잘려 있다. 소리에는 그
            # 제한이 없으니 원문(body)이 더 길면 원문을 읽는다.
            body = str(c.get("body", "")).strip()
            if beat.rstrip().endswith("…") and len(body) > len(beat):
                beat = body
            title = str(c.get("title", "")).strip()
            # 제목과 본문이 사실상 같은 말이면 두 번 읽지 않는다
            if not title or title in beat:
                lines.append(beat)
            else:
                # 제목이 이미 ?/!/. 로 끝나면 마침표를 더 붙이지 않는다('부품?. 추가')
                joiner = "" if title[-1] in "?!." else "."
                lines.append(f"{title}{joiner} {beat}")
        elif kind == "verdict":
            v = str(item.get("verdict_text", "")).strip()
            lines.append(v)
        else:                                   # loop
            lines.append(h["loop"])

    return [speakable(x) for x in lines]


# ---------------------------------------------------------------- 합성
def _cache_path(text: str, voice: str, rate: str, pitch: str) -> Path:
    key = hashlib.sha1(f"{voice}|{rate}|{pitch}|{text}".encode()).hexdigest()[:16]
    return CACHE / f"{key}.mp3"


def synth_line(text: str, out: Path, voice: str = "", rate: str = "",
               pitch: str = "", tries: int = 3) -> Path:
    """한 문장을 mp3 로 만든다. 여기만 갈아끼우면 다른 TTS 로 옮길 수 있다."""
    import edge_tts

    # 워크플로가 빈 문자열을 넘길 수 있어 getenv 기본값이 아니라 or 로 받는다
    voice = voice or os.getenv("TTS_VOICE") or DEFAULT_VOICE
    rate = rate or os.getenv("TTS_RATE") or DEFAULT_RATE
    pitch = pitch or os.getenv("TTS_PITCH") or "+0Hz"

    cached = _cache_path(text, voice, rate, pitch)
    if cached.exists() and cached.stat().st_size > 512:
        out.write_bytes(cached.read_bytes())
        return out

    last = ""
    for n in range(1, tries + 1):
        try:
            async def go() -> bytes:
                buf = b""
                comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
                async for chunk in comm.stream():
                    if chunk["type"] == "audio":
                        buf += chunk["data"]
                return buf

            data = asyncio.run(go())
            if len(data) < 512:
                raise TTSError("빈 응답")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            CACHE.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(data)
            return out
        except Exception as e:                                    # noqa: BLE001
            last = str(e)[:200]
            if n < tries:
                import time
                time.sleep(1.5 * n)
    raise TTSError(f"음성 합성 실패({tries}회): {last}")


def _duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True)
    return float(r.stdout.strip())


def frames(seconds: float) -> int:
    """영상 인코더와 똑같은 규칙으로 프레임 수를 센다."""
    return max(2, int(round(seconds * FPS)))


# ---------------------------------------------------------------- 장면 맞추기
def plan_with_narration(plan: list[dict], lines: list[str], workdir: Path,
                        synth=None) -> tuple[list[dict], list[Path | None]]:
    """장면마다 말소리를 만들고, 말이 길면 장면을 늘린다.

    장면을 줄이지는 않는다. 읽을 시간은 남겨둬야 하기 때문이다.
    synth 를 넘기면 그걸로 합성한다(테스트에서 망을 타지 않으려고).

    반환: (길이가 조정된 plan, 장면별 mp3 경로[없으면 None])
    """
    synth = synth or synth_line
    workdir.mkdir(parents=True, exist_ok=True)
    voices: list[Path | None] = []
    out_plan: list[dict] = []

    for i, (s, text) in enumerate(zip(plan, lines)):
        s = dict(s)
        if not text:
            voices.append(None)
            out_plan.append(s)
            continue
        mp3 = synth(text, workdir / f"v{i:02d}.mp3")
        need = _duration(mp3) + LEAD + TAIL
        if need > s["dur"]:
            # 내림하면 말 끝이 몇 ms 잘린다. 항상 올림한다.
            s["dur"] = math.ceil(need * 100) / 100
        voices.append(mp3)
        out_plan.append(s)

    return out_plan, voices


def build_track(plan: list[dict], voices: list[Path | None],
                workdir: Path) -> Path:
    """장면 길이에 정확히 맞춘 나레이션 트랙 하나를 만든다(무음 구간 포함)."""
    segs: list[Path] = []
    for i, (s, v) in enumerate(zip(plan, voices)):
        dur = frames(s["dur"]) / FPS          # 영상과 같은 길이로 맞춘다
        seg = workdir / f"a{i:02d}.wav"
        if v is None:
            cmd = ["ffmpeg", "-y", "-loglevel", "error",
                   "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=stereo",
                   "-t", f"{dur:.4f}", str(seg)]
        else:
            af = (f"adelay={int(LEAD*1000)}|{int(LEAD*1000)},"
                  f"aformat=sample_rates={SR}:channel_layouts=stereo,"
                  f"apad,atrim=0:{dur:.4f},asetpts=N/SR/TB")
            cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(v),
                   "-af", af, "-ar", str(SR), "-ac", "2", str(seg)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not seg.exists():
            raise TTSError(f"나레이션 구간 생성 실패: {r.stderr[:200]}")
        segs.append(seg)

    lst = workdir / "_voice.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in segs), encoding="utf-8")
    out = workdir / "voice.wav"
    r = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(lst), "-c", "copy", str(out)], capture_output=True, text=True)
    lst.unlink(missing_ok=True)
    if r.returncode != 0 or not out.exists():
        raise TTSError(f"나레이션 이어붙이기 실패: {r.stderr[:200]}")
    return out


if __name__ == "__main__":                     # 목소리 들어보기
    import sys
    text = sys.argv[1] if len(sys.argv) > 1 else "쿠팡 와우 월 7,890원, 이거 진짜 돈값하나?"
    out = Path("out") / "tts_preview.mp3"
    out.parent.mkdir(exist_ok=True)
    synth_line(speakable(text), out)
    print("→", out, f"{_duration(out):.2f}초")
