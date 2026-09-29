"""플랫폼별 해시태그 — 사람들이 실제로 찾는 태그만 붙인다.

왜 따로 뺐나 (2026-09-29 소유자 지적)
  예전에는 편마다 손으로 적은 태그와 코드에 박힌 태그(#분기점 #비교분석 #돈값하나)가
  그대로 나갔다. 인스타에서 게시물 수를 조회해 보니 #분기점 641개, #돈값하나 40개,
  #몰라서내는돈 0개 — 아무도 검색하지 않는 태그였다. 태그는 '검색되는 자리'에
  글을 세우는 도구라, 검색량이 없는 태그는 자리만 차지한다.

규칙
  1. 인스타는 게시물당 해시태그 5개까지만 쓴다(인스타그램의 게시물·릴스당 5개 제한,
     Social Media Today 'Instagram Implements New Limits on Hashtag Use').
  2. 주제 태그(편마다 다름) 최대 3개 + 공통 태그로 5개를 채운다.
  3. BLOCKED 에 있는 태그는 어디서 들어와도 빠진다(옛 편·GPT 트랙 캡션 포함).
  4. 게시물 수가 너무 큰 태그(#직장인 941만, #스타벅스 832만)는 새 글이 몇 분 만에
     묻힌다. 공통 태그는 수만~수십만 규모에서 고른다.

게시물 수 기준: 2026-09-29 인스타 검색(topsearch) 조회값. 몇 달마다 다시 볼 것.
"""
from __future__ import annotations

import re

# 게시물 수가 거의 없거나, 이 계정 안에서만 쓰는 말이라 검색되지 않는 태그
BLOCKED = {
    "분기점",        # 641
    "돈값하나",      # 40 — 계정 이름은 핸들로 충분하다
    "돈값하나?",
    "몰라서내는돈",  # 0 (검색 결과 없음)
    "비교분석",      # 1.2만이지만 주제와 무관한 게시물이 대부분
    "분기점계산",
    "쇼츠",          # 유튜브 쪽은 #Shorts 를 따로 붙인다
    "shorts",
}

# 공통 태그 — 편 주제와 상관없이 '생활 속 돈 계산'을 찾는 사람이 보는 자리
# (이름, 게시물 수) — 순서가 우선순위다.
CORE = [
    ("생활꿀팁", 218_229),
    ("돈모으기", 130_909),
    ("짠테크", 93_107),
    ("생활정보", 87_889),
    ("자취꿀팁", 39_376),
]

IG_MAX = 5
YT_DESC_MAX = 5          # 설명란 해시태그. 많이 달면 유튜브가 전부 무시한다(15개 초과 시)
TOPIC_MAX = 3


def clean(tag) -> str:
    """'#짠 테크 ' → '짠테크'. 해시태그에는 공백·특수문자가 들어갈 수 없다."""
    t = str(tag or "").strip().lstrip("#")
    t = re.sub(r"[\s.,!?·/&()\[\]'\"#]+", "", t)
    return t


def is_blocked(tag) -> bool:
    return clean(tag).lower() in {b.lower() for b in BLOCKED}


def topic_tags(item: dict) -> list[str]:
    """편마다 고른 주제 태그(차단 태그·중복 제거, 최대 3개)."""
    out: list[str] = []
    for t in item.get("hashtags") or []:
        c = clean(t)
        if c and not is_blocked(c) and c not in out:
            out.append(c)
    return out[:TOPIC_MAX]


def _fill(topic: list[str], limit: int) -> list[str]:
    out = list(topic)
    for name, _ in CORE:
        if len(out) >= limit:
            break
        if name not in out:
            out.append(name)
    return out[:limit]


def instagram(item: dict) -> list[str]:
    return _fill(topic_tags(item), IG_MAX)


def instagram_line(item: dict) -> str:
    return " ".join(f"#{t}" for t in instagram(item))


def youtube_description(item: dict) -> list[str]:
    """설명란 해시태그. 앞의 3개가 제목 위에 뜨므로 주제 태그가 먼저 온다."""
    return ["Shorts"] + _fill(topic_tags(item), YT_DESC_MAX - 1)


def youtube_keywords(item: dict) -> list[str]:
    """업로드 메타데이터의 tags(검색 키워드). 화면에는 안 보인다."""
    out = _fill(topic_tags(item), IG_MAX)
    for extra in ("생활비", "절약", "돈 아끼는 법"):
        if extra not in out:
            out.append(extra)
    return out


def strip_blocked(text: str) -> str:
    """이미 써 둔 캡션(GPT 트랙 등)에서 차단 태그만 걷어낸다."""
    def repl(m: re.Match) -> str:
        return "" if is_blocked(m.group(1)) else m.group(0)
    out = re.sub(r"#([^\s#]+)", repl, text or "")
    out = re.sub(r"[ \t]{2,}", " ", out)
    return "\n".join(ln.rstrip() for ln in out.splitlines()).strip()


def strip_all(text: str) -> str:
    """본문에 섞인 해시태그를 전부 걷어낸다.

    인스타는 5개 제한이라 본문에 태그가 하나라도 남아 있으면 끝의 태그 줄과 합쳐
    5개를 넘거나, 우리가 고른 태그 대신 본문 태그가 먼저 잡힌다.
    """
    out = re.sub(r"(?<!\S)#[^\s#]+", "", text or "")
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = "\n".join(ln.strip() if not ln.strip() else ln.rstrip() for ln in out.splitlines())
    return re.sub(r"\n{3,}", "\n\n", out).strip()
