"""「0년」 컷툰 → 인스타 릴스 자동 게시 (2026-11-09 소유자 결정).

돈값하나 인스타 계정을 「0년」 컷툰 계정으로 바꾸면서 만든 경로다.
돈값하나 본편(src/run.py)은 유튜브에만 나가고, 인스타에는 이 모듈만 올린다.

왜 캐러셀이 아니라 릴스인가
  인스타 공식 게시 API 는 캐러셀을 10장까지만 받는다(앱은 20장).
  한 화가 15장이라, 소유자가 '15장을 이어 붙인 릴스로 자동 게시'를 골랐다.

한 화 = 폴더 하나
  toon/ep01/
    01.png ~ 15.png   GPT 가 그린 그림. 파일 이름 앞 숫자 순서대로 쓴다(png/jpg/jpeg/webp).
    caption.txt       인스타 캡션 그대로.
    timing.yaml       (선택) 장별 초 수와 효과음. 없으면 장마다 3초.

  timing.yaml 예:
    durations: [3, 2, 3, 4, 3, 3, 3, 3, 4, 4, 4, 3, 4, 2, 3]
    sfx:
      11: [click, click]
      13: [shutter]

발행
  · 다음 화 = toon/posted.json 에 없는 가장 앞 번호 폴더. 그림이 없으면 텔레그램으로 알리고 끝.
  · 하루에 한 화만. 오늘 이미 올렸으면 건너뛴다(보조 실행·시계 재시도 대비).
  · 외부 게시는 src/run.py 의 deliver_once 원장(content/delivery.json)을 거친다.
    키는 'toon-ep01' / 'instagram_reel'. 결과를 모르는 시도가 있으면 다시 올리지 않고 멈춘다.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
TOON = ROOT / "toon"
LEDGER = TOON / "posted.json"
OUT = ROOT / "images" / "toon"
KST = timezone(timedelta(hours=9))

W, H = 1080, 1920
FG_MAX_H = 1500            # 아래쪽 캡션·버튼에 그림이 가리지 않게 세로를 제한
FG_SHIFT_UP = 60           # 화면 가운데보다 살짝 위
FPS = 30
SR = 44100
DEFAULT_SEC = 3.0
MIN_SEC, MAX_SEC = 1.0, 10.0
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
EP_RE = re.compile(r"^ep(\d{2,3})$")
SFX_KINDS = ("click", "shutter", "crack", "hiss")

# 월·수·금 21:20 KST (tools/publish_clock.py 의 TOON_SLOTS 와 같아야 한다)
SLOTS = {0: (21, 20), 2: (21, 20), 4: (21, 20)}
EARLY_SKIP_MIN = 60


class ToonError(RuntimeError):
    pass


# ------------------------------------------------------------------ 폴더 읽기
def episodes() -> list[Path]:
    if not TOON.exists():
        return []
    eps = [p for p in TOON.iterdir() if p.is_dir() and EP_RE.match(p.name)]
    return sorted(eps, key=lambda p: int(EP_RE.match(p.name).group(1)))


def images_of(ep: Path) -> list[Path]:
    """앞 숫자 순서. 숫자가 없거나 겹치면 순서를 장담 못 하므로 멈춘다."""
    files = [p for p in ep.iterdir() if p.is_file() and p.suffix.lower() in IMG_EXT]
    numbered = []
    for p in files:
        m = re.match(r"^\D*?(\d+)", p.stem)
        if not m:
            raise ToonError(f"{ep.name}/{p.name}: 파일 이름에 장 번호가 없습니다 (예: 01.png)")
        numbered.append((int(m.group(1)), p))
    nums = [n for n, _ in numbered]
    dup = sorted({n for n in nums if nums.count(n) > 1})
    if dup:
        raise ToonError(f"{ep.name}: 같은 장 번호가 두 번 있습니다 {dup}")
    return [p for _, p in sorted(numbered)]


def caption_of(ep: Path) -> str:
    f = ep / "caption.txt"
    text = f.read_text(encoding="utf-8").strip() if f.exists() else ""
    if not text:
        raise ToonError(f"{ep.name}: caption.txt 가 없거나 비어 있습니다")
    if len(text) > 2200:
        raise ToonError(f"{ep.name}: 캡션이 2,200자를 넘습니다({len(text)}자)")
    if text.count("#") > 30:
        raise ToonError(f"{ep.name}: 해시태그가 30개를 넘습니다")
    return text


def timing_of(ep: Path, n: int) -> tuple[list[float], dict[int, list[str]]]:
    f = ep / "timing.yaml"
    cfg = yaml.safe_load(f.read_text(encoding="utf-8")) if f.exists() else {}
    cfg = cfg or {}
    durs = cfg.get("durations") or [DEFAULT_SEC] * n
    if len(durs) != n:
        raise ToonError(f"{ep.name}: 그림은 {n}장인데 durations 는 {len(durs)}개입니다")
    durs = [float(d) for d in durs]
    bad = [i + 1 for i, d in enumerate(durs) if not MIN_SEC <= d <= MAX_SEC]
    if bad:
        raise ToonError(f"{ep.name}: {MIN_SEC:g}~{MAX_SEC:g}초 밖인 장 {bad}")
    sfx: dict[int, list[str]] = {}
    for k, v in (cfg.get("sfx") or {}).items():
        idx = int(k)
        kinds = [v] if isinstance(v, str) else list(v)
        if not 1 <= idx <= n:
            raise ToonError(f"{ep.name}: 효과음 장 번호 {idx} 가 1~{n} 밖입니다")
        unknown = [x for x in kinds if x not in SFX_KINDS]
        if unknown:
            raise ToonError(f"{ep.name}: 모르는 효과음 {unknown} (가능: {SFX_KINDS})")
        sfx[idx] = kinds
    return durs, sfx


def load_ledger() -> list[dict]:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    return []


def next_episode(ledger: list[dict], only: str = "") -> tuple[Path | None, str]:
    """(다음 화 폴더, 사유). 폴더가 없거나 그림이 비면 None 과 사람에게 보낼 사유."""
    done = {r["episode"] for r in ledger if not r.get("skipped")}
    for ep in episodes():
        if only and ep.name != only:
            continue
        if ep.name in done and not only:
            continue
        if ep.name in done and only:
            return None, f"{ep.name} 은 이미 게시했습니다"
        if not images_of(ep):
            return None, f"{ep.name} 폴더에 그림이 아직 없습니다"
        return ep, ""
    if only:
        return None, f"{only} 폴더가 없습니다"
    return None, "올릴 다음 화 폴더가 없습니다(toon/epNN 를 만들어 주세요)"


def posted_today(ledger: list[dict], now: datetime) -> str:
    """오늘 올린 화(쉰 날은 '(쉼)'). 쉰 기록도 남기는 이유: 시계·보조 실행이 그날 다시 돌며
    '그림 없음' 알림을 여러 번 보내지 않게 한다. 그림을 늦게 넣었으면 --episode 로 손으로 올린다."""
    today = now.date().isoformat()
    for r in ledger:
        if str(r.get("posted_at", "")).startswith(today):
            return "(쉼)" if r.get("skipped") else r["episode"]
    return ""


def schedule_skip(now: datetime, event: str) -> str:
    """예약 실행인데 게시 요일이 아니거나 슬롯보다 너무 이르면 사유를 돌려준다."""
    if event != "schedule":
        return ""
    if now.weekday() not in SLOTS:
        return "오늘은 컷툰 게시 요일(월·수·금)이 아닙니다"
    h, m = SLOTS[now.weekday()]
    slot = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if now < slot - timedelta(minutes=EARLY_SKIP_MIN):
        return f"슬롯({h:02d}:{m:02d})보다 {EARLY_SKIP_MIN}분 넘게 이릅니다"
    return ""


# ------------------------------------------------------------------ 화면
def frame(src: Path, out: Path) -> Path:
    """세로 1080×1920. 뒤는 같은 그림을 흐리고 어둡게, 앞은 그림 전체가 보이게."""
    im = Image.open(src).convert("RGB")
    w, h = im.size
    s_bg = max(W / w, H / h)
    bg = im.resize((math.ceil(w * s_bg), math.ceil(h * s_bg)), Image.LANCZOS)
    left, top = (bg.width - W) // 2, (bg.height - H) // 2
    bg = bg.crop((left, top, left + W, top + H)).filter(ImageFilter.GaussianBlur(40))
    bg = ImageEnhance.Brightness(bg).enhance(0.40)
    s_fg = min(W / w, FG_MAX_H / h)
    fg = im.resize((round(w * s_fg), round(h * s_fg)), Image.LANCZOS)
    x = (W - fg.width) // 2
    y = max(0, (H - fg.height) // 2 - FG_SHIFT_UP)
    bg.paste(fg, (x, y))
    out.parent.mkdir(parents=True, exist_ok=True)
    bg.save(out, "JPEG", quality=92)
    return out


# ------------------------------------------------------------------ 소리
def _click(rng: np.random.Generator) -> np.ndarray:
    n = int(0.045 * SR)
    noise = rng.standard_normal(n).astype(np.float32)
    noise = np.diff(noise, prepend=0.0)                    # 고음만 남겨 '딸깍'
    env = np.exp(-np.arange(n) / (0.006 * SR)).astype(np.float32)
    return noise * env * 0.35


def _shutter(rng: np.random.Generator) -> np.ndarray:
    a, b = _click(rng), _click(rng) * 0.8
    out = np.zeros(int(0.12 * SR) + b.size, dtype=np.float32)
    out[: a.size] += a
    out[int(0.07 * SR): int(0.07 * SR) + b.size] += b
    return out


def _crack(rng: np.random.Generator) -> np.ndarray:
    """돌이 터지거나 끈이 끊어지는 '딱'. 딸깍보다 낮고 크다."""
    n = int(0.14 * SR)
    noise = np.cumsum(rng.standard_normal(n).astype(np.float32))
    noise -= np.linspace(noise[0], noise[-1], n, dtype=np.float32)
    noise /= (np.max(np.abs(noise)) or 1.0)
    env = np.exp(-np.arange(n) / (0.02 * SR)).astype(np.float32)
    out = noise * env * 1.4
    c = _click(rng)
    out[: c.size] += c
    return out


def _hiss(rng: np.random.Generator) -> np.ndarray:
    """달군 돌이 물에 들어가는 '치익'."""
    n = int(0.9 * SR)
    noise = np.diff(rng.standard_normal(n + 1).astype(np.float32))
    t = np.arange(n) / SR
    env = (np.minimum(1.0, t / 0.04) * np.exp(-t / 0.35)).astype(np.float32)
    return noise * env * 0.12


SFX = {"click": _click, "shutter": _shutter, "crack": _crack, "hiss": _hiss}


def soundtrack(durs: list[float], sfx: dict[int, list[str]], seed: int = 0) -> np.ndarray:
    """저작권이 생기지 않는 합성음: 낮은 드론 + 바람 소리 + 효과음."""
    rng = np.random.default_rng(seed)
    total = sum(durs)
    n = int(total * SR)
    t = np.arange(n, dtype=np.float32) / SR
    # 55·82Hz 는 폰 스피커로 거의 안 들려서 위 배음(165·220Hz)을 조금 섞는다.
    drone = sum(g * np.sin(2 * np.pi * f * t)
                for f, g in ((55.0, 0.30), (82.41, 0.18), (110.0, 0.12), (164.81, 0.07), (220.0, 0.05)))
    drone *= 0.6 + 0.4 * np.sin(2 * np.pi * 0.07 * t)          # 아주 느린 숨
    wind = np.cumsum(rng.standard_normal(n).astype(np.float32))  # 갈색 잡음
    k = 2048                                                  # 이동평균을 빼서 낮은 쏠림 제거
    c = np.concatenate([[0.0], np.cumsum(wind, dtype=np.float64)])
    lo = np.clip(np.arange(n) - k // 2, 0, n)
    hi = np.clip(np.arange(n) + k // 2, 0, n)
    wind = (wind - (c[hi] - c[lo]) / np.maximum(hi - lo, 1)).astype(np.float32)
    wind /= (np.max(np.abs(wind)) or 1.0)
    wind *= 0.12 * (0.5 + 0.5 * np.sin(2 * np.pi * 0.05 * t + 1.3))
    mix = (drone + wind).astype(np.float32)
    starts = np.concatenate([[0.0], np.cumsum(durs)[:-1]])
    for idx, kinds in sfx.items():
        for j, kind in enumerate(kinds):
            buf = SFX[kind](rng)
            at = int((starts[idx - 1] + 0.6 + 0.9 * j) * SR)
            end = min(n, at + buf.size)
            if at < n:
                mix[at:end] += buf[: end - at] * 1.2
    fade = int(1.2 * SR)
    mix[:int(0.6 * SR)] *= np.linspace(0, 1, int(0.6 * SR), dtype=np.float32)
    mix[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
    peak = float(np.max(np.abs(mix))) or 1.0
    return (mix / peak * 0.8).astype(np.float32)


def write_wav(path: Path, mono: np.ndarray) -> Path:
    pcm = (np.clip(mono, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(np.repeat(pcm[:, None], 2, axis=1).tobytes())
    return path


# ------------------------------------------------------------------ 영상
def build(ep: Path, outdir: Path | None = None) -> dict:
    imgs = images_of(ep)
    if not imgs:
        raise ToonError(f"{ep.name}: 그림이 없습니다")
    durs, sfx = timing_of(ep, len(imgs))
    outdir = outdir or OUT / ep.name
    outdir.mkdir(parents=True, exist_ok=True)
    frames = [frame(p, outdir / f"f{i:02d}.jpg") for i, p in enumerate(imgs, 1)]

    concat = outdir / "_concat.txt"
    lines = []
    for p, d in zip(frames, durs):
        lines += [f"file '{p.resolve()}'", f"duration {d:.3f}"]
    lines.append(f"file '{frames[-1].resolve()}'")
    concat.write_text("\n".join(lines) + "\n", encoding="utf-8")
    wav = write_wav(outdir / "_sound.wav", soundtrack(durs, sfx, seed=int(EP_RE.match(ep.name).group(1))))
    mp4 = outdir / "reel.mp4"
    total = sum(durs)
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "concat", "-safe", "0", "-i", str(concat), "-i", str(wav),
           "-vf", f"fps={FPS},format=yuv420p", "-t", f"{total:.3f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-c:a", "aac", "-b:a", "160k", "-ar", str(SR),
           "-movflags", "+faststart", str(mp4)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    concat.unlink(missing_ok=True)
    wav.unlink(missing_ok=True)
    if r.returncode or not mp4.exists():
        raise ToonError(f"ffmpeg 실패: {r.stderr[:400]}")
    cover = outdir / "cover.jpg"
    frames[0].replace(cover)
    for p in frames[1:]:
        p.unlink(missing_ok=True)
    return {"mp4": mp4, "cover": cover, "slides": len(imgs), "seconds": round(total, 2)}


# ------------------------------------------------------------------ 게시
def _tell(text: str) -> None:
    from src import notify
    if not notify.enabled():
        return
    try:
        notify.send_message(text)
    except Exception as e:                                        # noqa: BLE001
        print(f"[telegram] 전송 실패: {e}")


def record_skip(ledger: list[dict], why: str) -> None:
    from src.run import push, sh
    ledger.append({"episode": "", "skipped": why,
                   "posted_at": datetime.now(KST).isoformat(timespec="seconds")})
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        sh("git", "add", str(LEDGER))
        sh("git", "-c", "user.name=donvalue-bot", "-c", "user.email=bot@users.noreply.github.com",
           "commit", "-m", "toon: 오늘은 쉼")
        push()
    except Exception as e:                                        # noqa: BLE001 — 기록 실패해도 알림은 보낸다
        print(f"[toon] 쉼 기록 커밋 실패: {e}")


def run(only: str = "", dry_run: bool = False, now: datetime | None = None) -> int:
    now = now or datetime.now(KST)
    event = os.getenv("GITHUB_EVENT_NAME", "")
    skip = schedule_skip(now, event)
    if skip:
        print(f"[toon] {skip} → 건너뜀")
        return 0
    ledger = load_ledger()
    already = posted_today(ledger, now)
    if already and not only and not dry_run:
        print(f"[toon] 오늘 이미 {already} 를 올렸습니다 → 건너뜀")
        return 0
    ep, why = next_episode(ledger, only)
    if ep is None:
        print(f"[toon] {why}")
        if not dry_run and not only:
            record_skip(ledger, why)
            _tell(f"🟠 0년 컷툰 · ⛔ 오늘 게시 못 함\n사유: {why}\n"
                  "그림을 넣은 뒤 오늘 올리려면 Actions → 0년 컷툰 릴스 → episode 에 화 번호를 넣고 실행하세요.")
        return 0

    caption = caption_of(ep)
    built = build(ep)
    print(f"[toon] {ep.name}: {built['slides']}장 · {built['seconds']}초 → {built['mp4']}")
    if dry_run:
        print("[toon] 드라이런 — 게시하지 않습니다")
        print("--- 캡션 ---\n" + caption)
        return 0

    from src import notify, publish
    from src.run import deliver_once, push, sh
    ig_id, ig_tok = os.getenv("IG_USER_ID"), os.getenv("IG_ACCESS_TOKEN")
    if not (ig_id and ig_tok):
        print("[toon] 인스타 토큰 없음 → 게시하지 않습니다")
        return 1

    outdir = OUT / ep.name
    sh("git", "add", str(outdir))
    if sh("git", "status", "--porcelain", str(outdir)):
        sh("git", "-c", "user.name=donvalue-bot", "-c", "user.email=bot@users.noreply.github.com",
           "commit", "-m", f"toon: {ep.name} 릴스")
        push()
    sha = sh("git", "rev-parse", "HEAD")
    repo = os.environ["GITHUB_REPOSITORY"]
    base = f"https://raw.githubusercontent.com/{repo}/{sha}/images/toon/{ep.name}"
    key_id = f"toon-{ep.name}"
    results: dict[str, str] = {}
    errors: list[str] = []
    try:
        results["instagram_reel"] = deliver_once(key_id, "instagram_reel", lambda: publish.publish_instagram_reel(
            ig_id, ig_tok, f"{base}/reel.mp4", caption, f"{base}/cover.jpg"))
        print(f"[toon] 릴스 게시 완료 media_id={results['instagram_reel']}")
    except Exception as e:                                        # noqa: BLE001
        errors.append(f"instagram_reel: {e}")
        print(f"[toon] 실패: {e}")
        notify.done(key_id, f"0년 {ep.name}", results, errors)
        return 1

    ledger.append({"episode": ep.name, "posted_at": datetime.now(KST).isoformat(timespec="seconds"),
                   "media_id": results["instagram_reel"], "slides": built["slides"],
                   "seconds": built["seconds"]})
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    notify.done(key_id, f"0년 {ep.name}", results, errors)
    sh("git", "add", str(LEDGER))
    sh("git", "-c", "user.name=donvalue-bot", "-c", "user.email=bot@users.noreply.github.com",
       "commit", "-m", f"toon posted: {ep.name}")
    push()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="0년 컷툰 릴스 게시")
    ap.add_argument("--episode", default="", help="특정 화만 (예: ep01)")
    ap.add_argument("--dry-run", action="store_true", help="영상만 만들고 게시하지 않음")
    a = ap.parse_args()
    try:
        return run(a.episode.strip(), a.dry_run)
    except ToonError as e:
        print(f"[toon] 멈춤: {e}")
        if not a.dry_run:
            _tell(f"🟠 0년 컷툰 · ⛔ 게시 멈춤\n{e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
