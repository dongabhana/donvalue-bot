"""
GPT(codex) 트랙 콘텐츠를 릴스/쇼츠 파이프라인이 먹을 수 있는 모양으로 바꾼다.

왜 필요한가
  이 저장소에는 콘텐츠가 두 군데 있다.
    content/queue.yaml   — cards/verdict_text/reel 스키마 (이쪽 파이프라인)
    codex/content.json   — slides/topic/hook_candidates 스키마 (GPT 트랙)
  인스타에는 둘 다 나가는데, 유튜브 백필이 queue.yaml 만 보면 GPT 편들이
  통째로 빠진다. '빠짐없이 올린다'가 목표라 여기서 스키마를 맞춰준다.

무엇을 어떻게 옮기나
  slides[].title/body/note  →  cards[].title/body/note
  hook_candidates[0]        →  훅 대문짝(3줄로 쪼갬)
  hook_candidates[1]        →  stake(두 번째 훅)
  마지막 slide              →  결론(verdict_text)
  caption 끝의 #태그        →  hashtags

  codex 쪽 visual(versus/cart/question 같은 그림 지시)은 옮기지 않는다.
  그건 codex/media.py 전용 렌더러가 그리는 것이고, 쇼츠는 이 저장소의
  장면 렌더러로 한 가지 톤으로 통일하는 편이 채널이 정돈돼 보인다.

언제 유튜브에 올릴 수 있다고 보나
  codex 의 발행 상태는 암호화돼 있어(codex/state.enc) 여기서 읽지 않는다.
  대신 publish_at 이 지났거나 posted_early_on 이 찍힌 편을 '인스타에 이미
  나간 편'으로 본다. 조금 보수적이지만, 안 나간 편을 유튜브에 먼저
  올려버리는 사고는 막는다.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODEX = ROOT / "codex" / "content.json"
KST = timezone(timedelta(hours=9))

MAX_BIG_LINE = 13        # src.hooks 와 같은 기준
MAX_BIG_LINES = 3
LABEL_MAX = 14


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip())


BRAND_TAGS = {"돈값하나", "몰라서내는돈", "짠테크", "생활비절약", "소비습관", "가성비"}


def _label(topic: str, tags: list[str] | None = None) -> str:
    """표지 알약과 유튜브 제목 앞에 붙을 '무슨 편인가' 한 마디.

    codex 의 topic 은 문장이라("무료배송을 채우는 순간") 그대로 쓰면
    제목이 늘어진다. 캡션 해시태그의 첫 주제어가 사실상 제품명이라
    (#무료배송, #노트북 …) 그걸 먼저 쓴다. 없으면 topic 을 잘라 쓴다.
    """
    for t in tags or []:
        if t not in BRAND_TAGS and 2 <= len(t) <= LABEL_MAX:
            return t
    t = _clean(topic)
    if len(t) <= LABEL_MAX:
        return t
    cut = t[:LABEL_MAX]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,.·")


def _split_big(hook: str) -> list[str]:
    """훅 한 문장을 대문짝 3줄로 쪼갠다. 어절 경계에서만 자른다."""
    words = _clean(hook).split(" ")
    lines, cur = [], ""
    for w in words:
        nxt = f"{cur} {w}".strip()
        if len(nxt) <= MAX_BIG_LINE:
            cur = nxt
            continue
        if cur:
            lines.append(cur)
        cur = w[:MAX_BIG_LINE]
        if len(lines) == MAX_BIG_LINES - 1:
            break
    if cur and len(lines) < MAX_BIG_LINES:
        lines.append(cur)
    return lines[:MAX_BIG_LINES] or [_clean(hook)[:MAX_BIG_LINE]]


def _hashtags(caption: str) -> list[str]:
    return [t.lstrip("#") for t in re.findall(r"#\S+", caption or "")]


def _flat(s: str) -> str:
    """codex 제목은 줄바꿈으로 두 줄이다. 한 줄로 합친다.

    첫 줄만 쓰면 '장바구니에 / 27,900원' 에서 금액이 날아간다.
    """
    return _clean(str(s or "").replace("\n", " "))


def to_queue_item(cx: dict) -> dict:
    """codex 편 하나를 queue.yaml 스키마로 바꾼다.

    codex 슬라이드 순서는 [표지, 본문…, 결론, 참여유도] 로 굳어 있다.
      표지    → 훅 장면이 이미 담당하므로 카드로 넣지 않는다(같은 말 두 번)
      결론    → verdict_text
      참여유도 → 마지막 루프 장면 문구
    """
    slides = list(cx.get("slides") or [])
    hooks_ = [h for h in (cx.get("hook_candidates") or []) if _clean(h)]
    caption = str(cx.get("caption") or "")
    tags = _hashtags(caption)

    if len(slides) >= 4:
        body_slides = slides[1:-2]
        conclusion, cta = slides[-2], slides[-1]
    elif len(slides) >= 2:
        body_slides, conclusion, cta = slides[1:-1], slides[-1], {}
    else:
        body_slides, conclusion, cta = slides, {}, {}

    cards = []
    for s in body_slides:
        cards.append({
            "title": _flat(s.get("title"))[:22],
            "body": _flat(s.get("body")),
            "note": _flat(s.get("note")),
        })

    parts = [_flat(conclusion.get("title")), _flat(conclusion.get("body"))]
    verdict = ". ".join(p.rstrip(".") for p in parts if p)
    loop = _flat(cta.get("title")) or "그래서, 돈값하나?"

    return {
        "id": cx["id"],
        "product": _label(cx.get("topic"), tags),
        "hook": _clean(hooks_[0]) if hooks_ else _clean(cx.get("topic")),
        "cards": cards,
        "verdict_text": verdict,
        "caption": caption,
        "hashtags": tags,
        "first_comment": _clean(cx.get("first_comment")),
        "verified": bool(cx.get("verified")),
        # 어느 트랙에서 왔는지 표시하는 내부 값. 사람에게 보여줄 출처가 아니므로
        # 유튜브 설명란 등에 새어나가면 안 된다 (예전 이름은 "source" 였다).
        "track": "codex",
        "reel": {
            "big": _split_big(hooks_[0] if hooks_ else cx.get("topic", "")),
            "sub": _clean(hooks_[1]) if len(hooks_) > 1 else "",
            "stake": _clean(hooks_[1]) if len(hooks_) > 1 else _clean(cx.get("hook_reason")),
            "beats": [_flat(s.get("body")) for s in body_slides],
            "loop": loop,
            "mood": "focus",
        },
    }


def already_on_instagram(cx: dict, now: datetime | None = None) -> bool:
    """인스타에 이미 나갔다고 볼 수 있는가.

    codex 발행 상태는 암호화돼 있어 읽지 않는다. 예정 시각이 지났거나
    조기 발행 기록이 있으면 나간 것으로 본다(보수적으로 판단).
    """
    if cx.get("posted_early_on"):
        return True
    at = cx.get("publish_at")
    if not at:
        return False
    try:
        due = datetime.fromisoformat(str(at))
    except ValueError:
        return False
    return due <= (now or datetime.now(KST))


def load_items(only_published: bool = True) -> list[dict]:
    """codex 편들을 queue 스키마로. 예정 시각 순서로 돌려준다."""
    if not CODEX.exists():
        return []
    raw = json.loads(CODEX.read_text(encoding="utf-8"))
    items = raw.get("items", raw) if isinstance(raw, dict) else raw

    out = []
    for cx in items:
        if not cx.get("verified"):
            continue
        if only_published and not already_on_instagram(cx):
            continue
        out.append((str(cx.get("publish_at") or ""), to_queue_item(cx)))
    out.sort(key=lambda p: p[0])
    return [it for _, it in out]


if __name__ == "__main__":                     # 변환 결과 훑어보기
    import sys
    only = "--all" not in sys.argv
    items = load_items(only_published=only)
    print(f"{len(items)}편 ({'인스타에 이미 나간 것만' if only else '전체'})\n")
    for it in items:
        print(f"— {it['id']}  [{it['product']}]")
        print(f"   훅   {' / '.join(it['reel']['big'])}")
        print(f"   본문 {len(it['cards'])}장 · 결론 {it['verdict_text'][:40]}")
