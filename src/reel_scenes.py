"""릴스 화면: 표지는 기존 사진, 본문·결론·CTA는 공유 짙은 톤 디자인.
출력 크기와 기존 호출 규약은 그대로 유지한다."""
from __future__ import annotations

from PIL import Image, ImageDraw

from src import theme as T
from src.theme import BLACK, BOLD, DEMI, MED, REG, font

OUT_W, OUT_H = 1080, 1920
SCALE = 1.35
RW, RH = int(OUT_W * SCALE), int(OUT_H * SCALE)      # 1458 x 2592

PAD = int(104 * SCALE)
RAIL_X = int(52 * SCALE)
TOP_SAFE = int(RH * 0.140)
BOT_SAFE = int(RH * 0.772)
TEXT_W = RW - PAD * 2 - int(RW * 0.05)


def _s(v: float) -> int:
    return int(v * SCALE)


# ---------------------------------------------------------------- 텍스트 유틸
def wrap(d, text: str, f, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in str(text).split("\n"):
        cur = ""
        for word in para.split(" "):
            trial = f"{cur} {word}".strip()
            if d.textlength(trial, font=f) <= max_w:
                cur = trial
                continue
            if cur:
                lines.append(cur)
            if d.textlength(word, font=f) <= max_w:
                cur = word
            else:
                cur = ""
                for ch in word:
                    if d.textlength(cur + ch, font=f) <= max_w:
                        cur += ch
                    else:
                        lines.append(cur)
                        cur = ch
        lines.append(cur)
    return [ln for ln in lines if ln != ""] or [""]


def block(d, text, f, x, y, max_w, fill, gap=1.4) -> int:
    lh = int(f.size * gap)
    for ln in wrap(d, text, f, max_w):
        d.text((x, y), ln, font=f, fill=fill)
        y += lh
    return y


def block_h(d, text, f, max_w, gap=1.4) -> int:
    return len(wrap(d, text, f, max_w)) * int(f.size * gap)


def fit(d, text, weight, max_w, max_h, start, min_size, gap=1.2):
    size = start
    while size > min_size:
        f = font(weight, size)
        if len(wrap(d, text, f, max_w)) * int(size * gap) <= max_h:
            return f
        size -= 3
    return font(weight, min_size)


def fit_lines(d, lines: list[str], weight, max_w, max_h, start, min_size, gap=1.12):
    """줄바꿈을 직접 정한 텍스트용 — 가장 긴 줄의 실제 폭까지 본다."""
    size = start
    while size > min_size:
        f = font(weight, size)
        widest = max((d.textlength(ln, font=f) for ln in lines), default=0)
        if widest <= max_w and len(lines) * int(size * gap) <= max_h:
            return f
        size -= 3
    return font(weight, min_size)


# ---------------------------------------------------------------- 공통 껍데기
def _label(d, text, x, y, th, size, fill):
    T.letterspaced(d, text, x, y, font(BOLD, size), fill, space=size * 0.14)


def _paper(brand: str, handle: str, ratio: float, th):
    """본문 화면 공통 — 밝은 바탕 + 왼쪽 레일 + 상하 라벨."""
    img = T.background(RW, RH, th)
    d = ImageDraw.Draw(img)
    T.rail(d, RAIL_X, TOP_SAFE - _s(30), BOT_SAFE + _s(30), ratio, th, width=_s(5))
    d.rectangle((PAD, TOP_SAFE - _s(96), PAD + _s(26), TOP_SAFE - _s(70)),
                fill=th.accent)
    _label(d, brand, PAD + _s(42), TOP_SAFE - _s(98), th, _s(30), th.ink_soft)
    _label(d, handle, PAD, BOT_SAFE + _s(58), th, _s(28), th.ink_faint)
    return img, d


# ---------------------------------------------------------------- 표지(히어로)
def scene_hook(h: dict, brand: str, handle: str, reveal: int,
               item: dict | None = None, root: str = ".") -> Image.Image:
    """훅 화면. reveal = 띄울 줄 수(3단 리빌)."""
    from src import photo_covers
    if item and photo_covers.available(root, item):
        return photo_covers.render(item, brand, handle, root, reel=True,
                                   reveal=reveal).resize((RW, RH), Image.Resampling.LANCZOS)
    th = T.get_theme((item or {}).get("theme"))
    item = item or {}
    motif = T.motif_from(item, h)
    img = T.load_cover(root, item.get("id", "cover"), RW, RH,
                       item.get("id", "cover"), motif)
    img = T.scrim(img, start=0.30, strength=0.90)
    d = ImageDraw.Draw(img)

    white, faint = "#FFFFFF", "#C9C9CE"
    d.rectangle((PAD, TOP_SAFE - _s(96), PAD + _s(26), TOP_SAFE - _s(70)),
                fill=th.accent)
    _label(d, brand, PAD + _s(42), TOP_SAFE - _s(98), th, _s(30), white)
    _label(d, handle, PAD, BOT_SAFE + _s(58), th, _s(28), faint)

    big = h["big"]
    f_big = fit_lines(d, big, BLACK, TEXT_W, _s(1000), _s(176), _s(64), 1.1)
    lh = int(f_big.size * 1.1)
    f_sub = font(MED, _s(54))
    sub_h = block_h(d, h["sub"], f_sub, TEXT_W, 1.38) if h["sub"] else 0

    # 제품명 — 훅만 있으면 '무엇에 대한 얘기인지'를 알 수 없다.
    # 금액 알약 옆에 붙여서 한 줄로 "무엇 · 얼마"가 먼저 읽히게 한다.
    product = str(item.get("product", "")).strip()
    pf = font(BOLD, _s(46))
    head_h = _s(124) if (h["badge"] or product) else 0

    total = head_h + lh * len(big) + _s(66) + sub_h
    y = BOT_SAFE - total                      # 아래에서 쌓아 올린다(포스터 구도)

    if h["badge"] or product:
        x = PAD
        if h["badge"]:
            x = T.tag(d, h["badge"], PAD, y, th, _s(38), _s(32), _s(19))[0] + _s(26)
        if product:
            if x + d.textlength(product, font=pf) > PAD + TEXT_W:
                pf = fit(d, product, BOLD, TEXT_W - (x - PAD), _s(70), _s(46),
                         _s(30), 1.1)
            d.text((x, y + _s(12)), product, font=pf, fill=white)
        y += head_h

    # 마지막 줄에 마커를 깔아 시선을 고정한다
    hl = len(big) - 1
    for i, line in enumerate(big):
        if i >= reveal:
            break
        if i == hl and reveal > hl:
            tw = d.textlength(line, font=f_big)
            T.marker(d, PAD - _s(14), y + i * lh + int(f_big.size * 0.16),
                     int(tw) + _s(34), int(f_big.size * 1.02), th, slant=_s(6))
            d.text((PAD, y + i * lh), line, font=f_big, fill=th.marker_on)
        else:
            d.text((PAD, y + i * lh), line, font=f_big, fill=white)
    y += lh * len(big) + _s(66)

    if reveal >= len(big) and h["sub"]:
        block(d, h["sub"], f_sub, PAD, y, TEXT_W, faint, 1.38)
    return img


# ---------------------------------------------------------------- 본문 화면
def scene_stake(h, brand, handle, item=None):
    from src import editorial_design as D
    return D.stake(h['stake'],brand,handle).resize((RW,RH),Image.Resampling.LANCZOS)


def scene_beat(idx, total, title, text, brand, handle, ratio, card=None, item=None):
    from src import editorial_design as D
    card=card or {}
    detail='\n'.join(str(x) for x in (card.get('figure_label'),text) if x)
    im=D.body(title,card.get('figure',''),detail,idx-1,total,
              comparison=card.get('comparison'),note=card.get('note','상세 조건과 출처는 캡션'),brand=brand,handle=handle)
    return im.resize((RW,RH),Image.Resampling.LANCZOS)


def scene_verdict(item, brand, handle, voice=''):
    from src import editorial_design as D
    value=str(item.get('verdict_text',''))
    if voice: value+='\n'+voice
    return D.conclusion(value,brand,handle).resize((RW,RH),Image.Resampling.LANCZOS)


def scene_loop(h, brand, handle, item=None):
    from src import editorial_design as D
    item=item or {}
    return D.cta(h['loop'],item.get('platform','both'),brand,handle).resize((RW,RH),Image.Resampling.LANCZOS)
