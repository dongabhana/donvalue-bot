"""
훅(hook) 엔진.

릴스는 1.5~3초 안에 스크롤을 멈추게 하지 못하면 그 뒤 내용이 아무리 좋아도 소용이 없다.
그래서 훅을 '작가의 감'이 아니라 '패턴 + 검증 규칙'으로 관리한다.

큐(queue.yaml)의 각 항목은 아래를 가질 수 있다.

    reel:
      pattern: loss            # 아래 PATTERNS 중 하나 (기록·분석용)
      big:  ["매달 7,890원", "그냥 나가는 중"]   # 1~3줄, 화면을 꽉 채우는 대문짝
      sub:  "본전 넘기는 사람은 절반도 안 된다"   # 한 줄 부연
      stake: "이 숫자 하나만 세면 5초 만에 갈린다" # 2번째 씬 — 열린 고리
      loop:  "그래서, 돈값하나?"                 # 마지막 → 처음으로 되감는 문장

reel 블록이 없으면 product/price/hook 에서 자동 생성한다(품질은 수동 작성이 더 좋다).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

HOOK_SHEET = Path(__file__).resolve().parent.parent / "content" / "hooks.yaml"


def attach(queue: dict) -> dict:
    """content/hooks.yaml 을 읽어 각 항목의 reel 블록으로 합친다.

    queue.yaml 안에 직접 쓴 reel 블록이 있으면 그쪽이 우선한다(편별 예외 처리용).
    """
    if not HOOK_SHEET.exists():
        return queue
    sheet = yaml.safe_load(HOOK_SHEET.read_text(encoding="utf-8")) or {}
    for item in queue.get("items", []):
        base = sheet.get(item["id"])
        if not base:
            continue
        merged = dict(base)
        merged.update(item.get("reel") or {})
        item["reel"] = merged
    return queue

# ---------------------------------------------------------------- 패턴 정의
# 각 패턴은 '왜 멈추게 되는가'가 서로 다르다. 한 패턴만 반복하면 계정이 빨리 질린다.
PATTERNS: dict[str, str] = {
    "loss":      "손실 프레이밍 — '이미 새고 있는 돈'을 먼저 보여준다",
    "number":    "구체 숫자 — 금액·횟수를 첫 줄에 박아 신뢰와 궁금증을 동시에 산다",
    "contrarian": "통념 반박 — '다들 이렇게 아는데 아니다'로 예측을 깬다",
    "threshold": "기준선 제시 — '이 숫자를 넘느냐'로 시청자를 둘로 가른다",
    "callout":   "대상 지목 — '~한 사람은 지금 손해 중' 으로 나를 부른 것처럼 만든다",
    "reveal":    "순서 뒤집기 — 결론을 먼저 던지고 근거를 뒤에 푼다",
}

# 화면에 들어가는 글자 수 상한. 넘으면 폰트가 줄어 '대문짝' 효과가 죽는다.
MAX_BIG_LINE = 13        # 한 줄
MAX_BIG_LINES = 3
MAX_SUB = 34
MAX_STAKE = 40
MAX_BEAT = 46
MAX_VOICE = 30

# 인스타 캡션은 약 125자에서 '... 더 보기'로 잘린다. 첫 줄이 두 번째 훅이다.
CAPTION_CUT = 125


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _shorten(s: str, limit: int) -> str:
    s = _clean(s)
    if len(s) <= limit:
        return s
    cut = s[:limit]
    # 어절 경계에서 자른다
    if " " in cut[limit // 2:]:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,.·") + "…"


def _auto_big(item: dict) -> list[str]:
    """reel.big 이 없을 때의 폴백. product 를 2줄로 쪼개고 물음표를 붙인다."""
    name = _clean(item.get("product", ""))
    parts = name.split(" ")
    if len(parts) >= 2:
        mid = len(parts) // 2 + len(parts) % 2
        lines = [" ".join(parts[:mid]), " ".join(parts[mid:])]
    else:
        lines = [name]
    lines.append("돈값하나?")
    return [_shorten(x, MAX_BIG_LINE) for x in lines if x][:MAX_BIG_LINES]


def resolve(item: dict) -> dict:
    """항목 하나에서 릴스용 훅 데이터를 만들어 낸다. 항상 유효한 값을 돌려준다."""
    reel = item.get("reel") or {}
    big = [ln for ln in (reel.get("big") or []) if _clean(ln)]
    big = [_shorten(ln, MAX_BIG_LINE) for ln in big][:MAX_BIG_LINES] or _auto_big(item)

    sub = _shorten(reel.get("sub") or item.get("hook", ""), MAX_SUB)
    stake = _shorten(reel.get("stake") or item.get("hook", ""), MAX_STAKE)
    loop = _shorten(reel.get("loop") or "그래서, 돈값하나?", MAX_BIG_LINE + 6)
    pattern = reel.get("pattern") or "reveal"

    beats = [_shorten(b, MAX_BEAT) for b in (reel.get("beats") or []) if _clean(b)]
    if not beats:
        beats = [_shorten(c.get("body", ""), MAX_BEAT) for c in item.get("cards", [])]

    # 화자 — 이 계정이 '교과서'가 아니라 '사람'으로 읽히게 하는 한 줄.
    # 결론 카드 아래 서명처럼 붙는다. 없으면 아예 그리지 않는다.
    voice = _shorten(reel.get("voice") or "", MAX_VOICE)

    fmt = (reel.get("format") or "both").lower()
    if fmt not in ("both", "reel", "card"):
        fmt = "both"

    return {
        "pattern": pattern if pattern in PATTERNS else "reveal",
        "big": big,
        "sub": sub,
        "stake": stake,
        "loop": loop,
        "beats": beats,
        "voice": voice,
        "format": fmt,
        "badge": _clean(reel.get("badge") or item.get("price", "")),
        "mood": reel.get("mood", "calm"),
    }


def item_format(item: dict) -> str:
    """이 편을 어떤 포맷으로 낼지. both | reel | card"""
    return resolve(item)["format"]


def caption_first_line(item: dict) -> str:
    """캡션 맨 앞에 세울 한 줄. 릴스 훅과 다른 각도로 써야 두 번 걸린다."""
    reel = item.get("reel") or {}
    line = _clean(reel.get("caption_hook") or item.get("hook", ""))
    return _shorten(line, CAPTION_CUT - 20)


def build_caption(item: dict, cta: str = "") -> str:
    """첫 줄(훅) → 본문 → CTA → 해시태그 순서로 조립한다.

    해시태그를 본문 바로 뒤에 붙이면 첫 줄 미리보기에서 태그가 먼저 보여 신뢰를 깎는다.
    줄바꿈 두 번으로 확실히 떼어 놓는다.
    """
    head = caption_first_line(item)
    body = _clean_block(item.get("caption", ""))
    # 캡션 본문이 이미 훅으로 시작하면 중복 제거
    if body.startswith(head[:12]):
        head = ""
    cta = cta or default_cta(item)
    tags = " ".join(f"#{str(t).lstrip('#')}" for t in (item.get("hashtags") or []))

    chunks = [c for c in (head, body, cta, tags) if c]
    return "\n\n".join(chunks).strip()


def _clean_block(s: str) -> str:
    return "\n".join(ln.rstrip() for ln in (s or "").strip().splitlines()).strip()


def default_cta(item: dict) -> str:
    """저장·공유를 직접 요구한다. 알고리즘상 DM 공유 > 저장 > 댓글 순으로 신호가 세다."""
    name = _clean(item.get("product", "이거"))
    return (f"이 계산 필요한 사람한테 그냥 보내주세요.\n"
            f"나중에 {name} 고민될 때 꺼내보려면 저장.")


def validate(item: dict) -> list[str]:
    """발행 전에 훅 품질을 기계적으로 점검한다. 경고 문자열 리스트를 돌려준다."""
    warn: list[str] = []
    h = resolve(item)
    if not (item.get("reel") or {}).get("big"):
        warn.append("reel.big 이 없어 자동 생성됨 — 훅 힘이 약해질 수 있음")
    if len("".join(h["big"])) < 8:
        warn.append("훅 문구가 너무 짧음")
    if h["big"] and h["big"][0].endswith("?") and h["pattern"] == "number":
        warn.append("pattern=number 인데 첫 줄이 질문형")
    if not h["badge"]:
        warn.append("badge(금액/단위)가 비어 있음 — 숫자가 있으면 멈춤률이 올라감")
    if len(h["beats"]) < 3:
        warn.append("본문 비트가 3개 미만 — 릴스가 너무 짧아짐")
    if not item.get("hashtags"):
        warn.append("해시태그 없음")
    elif len(item["hashtags"]) > 8:
        warn.append("해시태그가 8개 초과 — 주제가 흐려짐")
    return warn
