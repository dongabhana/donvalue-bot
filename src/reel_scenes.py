"""
릴스 9:16 화면 그리기.

구성 의도
  표지는 '멈추게 하는 화면', 본문부터는 '읽는 화면'이다. 둘은 규칙이 달라야 한다.

    표지   어두운 히어로 배경 + 화면 밖으로 흘러넘치는 거대한 숫자 + 흰 대문짝 훅
           (assets/covers/<id>.jpg 를 넣으면 그 사진이 배경이 된다)
    본문~  밝은 종이 바탕으로 확 전환. 왼쪽 인덱스 레일, 하드 오프셋 패널, 얇은 괘선.

  어두운 화면 → 밝은 화면으로 넘어가는 순간 자체가 '전환'이라 시선이 한 번 더 붙는다.
  그리고 본문은 밝은 바탕이라 글자가 훨씬 잘 읽힌다.

영상 조립·길이 계산·발행은 src/reel.py 가 맡고, 이 파일은 '한 장면 그리기'만 한다.
출력 한 장: 1458x2592 PNG (인코딩 때 1080x1920 으로 축소된다)
"""
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
def scene_stake(h: dict, brand: str, handle: str,
                item: dict | None = None) -> Image.Image:
    th = T.get_theme((item or {}).get("theme"))
    img, d = _paper(brand, handle, 0.10, th)
    f = fit(d, h["stake"], BLACK, TEXT_W, _s(760), _s(112), _s(62), 1.18)
    hgt = block_h(d, h["stake"], f, TEXT_W, 1.18)
    y = TOP_SAFE + (BOT_SAFE - TOP_SAFE - hgt) // 2
    _label(d, "결론부터", PAD, y - _s(104), th, _s(34), th.accent)
    d.rectangle((PAD, y - _s(52), PAD + _s(96), y - _s(44)), fill=th.accent)
    block(d, h["stake"], f, PAD, y, TEXT_W, th.ink, 1.18)
    return img


def scene_beat(idx: int, total: int, title: str, text: str, brand: str,
               handle: str, ratio: float, card: dict | None = None,
               item: dict | None = None) -> Image.Image:
    th = T.get_theme((item or {}).get("theme"))
    img, d = _paper(brand, handle, ratio, th)
    card = card or {}
    figure = str(card.get("figure") or "").strip()
    fig_label = str(card.get("figure_label") or "").strip()

    tf = fit(d, title, BLACK, TEXT_W, _s(300), _s(100), _s(58), 1.14)
    bf = fit(d, text, MED, TEXT_W, _s(560), _s(62), _s(42), 1.5)

    fig_h = 0
    if figure:
        ff = fit(d, figure, BLACK, TEXT_W - _s(96), _s(190), _s(120), _s(56), 1.05)
        fig_h = _s(56) + (_s(44) if fig_label else 0) + int(ff.size * 1.1) + _s(56)

    hgt = _s(92) + block_h(d, title, tf, TEXT_W, 1.14) + _s(46) + fig_h \
        + (_s(40) if figure else 0) + block_h(d, text, bf, TEXT_W, 1.5)
    y = TOP_SAFE + max(0, (BOT_SAFE - TOP_SAFE - hgt) // 2)

    nf = font(BLACK, _s(44))
    d.text((PAD, y), f"{idx:02d}", font=nf, fill=th.accent)
    nw = d.textlength(f"{idx:02d}", font=nf)
    d.text((PAD + nw + _s(10), y + _s(6)), f"/{total:02d}", font=font(BOLD, _s(32)),
           fill=th.ink_faint)
    y += _s(92)

    y = block(d, title, tf, PAD, y, TEXT_W, th.ink, 1.14) + _s(46)

    if figure:
        box = (PAD, y, PAD + TEXT_W, y + fig_h)
        T.panel(d, box, th, radius=_s(22), offset=_s(12), width=_s(3))
        yy = y + _s(30)
        if fig_label:
            _label(d, fig_label, PAD + _s(44), yy, th, _s(26), th.ink_faint)
            yy += _s(44)
        d.text((PAD + _s(44), yy), figure, font=ff, fill=th.accent)
        y += fig_h + _s(40)

    block(d, text, bf, PAD, y, TEXT_W, th.ink_soft, 1.5)
    return img


def scene_verdict(item: dict, brand: str, handle: str, voice: str = "") -> Image.Image:
    th = T.get_theme(item.get("theme"))
    img, d = _paper(brand, handle, 0.94, th)
    score = max(0, min(5, int(item.get("verdict", 3))))
    text = str(item.get("verdict_text", ""))

    vf = fit(d, text, MED, TEXT_W, _s(620), _s(62), _s(42), 1.45)
    v_h = block_h(d, text, vf, TEXT_W, 1.45)
    voice_h = _s(80) if voice else 0
    hgt = _s(150) + _s(130) + _s(70) + v_h + voice_h
    y = TOP_SAFE + max(0, (BOT_SAFE - TOP_SAFE - hgt) // 2)

    _label(d, "결론", PAD, y, th, _s(34), th.accent)
    y += _s(70)

    # 점수 — 큰 숫자 + 칸. 숫자를 크게 둬야 한눈에 읽힌다
    sf = font(BLACK, _s(130))
    d.text((PAD, y - _s(26)), str(score), font=sf, fill=th.ink)
    sw = d.textlength(str(score), font=sf)
    d.text((PAD + sw + _s(10), y + _s(52)), "/5", font=font(BOLD, _s(48)),
           fill=th.ink_faint)
    bx = PAD + sw + _s(130)
    bw = (TEXT_W - (bx - PAD) - _s(4 * 14)) // 5
    for i in range(5):
        x = bx + i * (bw + _s(14))
        d.rounded_rectangle((x, y + _s(24), x + bw, y + _s(62)), radius=_s(8),
                            fill=th.accent if i < score else th.rule)
    y += _s(150)

    y = block(d, text, vf, PAD, y, TEXT_W, th.ink, 1.45)

    if voice:
        y += _s(44)
        d.line((PAD, y, PAD + _s(52), y), fill=th.accent, width=_s(4))
        block(d, voice, font(REG, _s(42)), PAD + _s(72), y - _s(26),
              TEXT_W - _s(72), th.ink_faint, 1.3)
    return img


def scene_loop(h: dict, brand: str, handle: str,
               item: dict | None = None) -> Image.Image:
    """마지막 화면. 표지와 같은 어두운 톤으로 돌아가 자연스럽게 루프된다."""
    th = T.get_theme((item or {}).get("theme"))
    item = item or {}
    img = T.load_cover(".", item.get("id", "cover"), RW, RH,
                       item.get("id", "cover"), T.motif_from(item, h))
    img = T.scrim(img, start=0.10, strength=0.94)
    d = ImageDraw.Draw(img)
    white, faint = "#FFFFFF", "#C9C9CE"

    d.rectangle((PAD, TOP_SAFE - _s(96), PAD + _s(26), TOP_SAFE - _s(70)),
                fill=th.accent)
    _label(d, brand, PAD + _s(42), TOP_SAFE - _s(98), th, _s(30), white)
    _label(d, handle, PAD, BOT_SAFE + _s(58), th, _s(28), faint)

    y = TOP_SAFE + _s(180)
    f = font(BLACK, _s(150))
    d.text((PAD, y), "저장", font=f, fill=th.accent)
    aw = d.textlength("저장", font=f)
    d.text((PAD + aw + _s(30), y + _s(48)), "· 공유", font=font(BLACK, _s(86)),
           fill=white)
    y += _s(250)
    block(d, "필요한 사람한테 그냥 보내주세요.\n주 3회, 같은 계산으로 돌아옵니다.",
          font(MED, _s(52)), PAD, y, TEXT_W, faint, 1.45)

    lf = fit(d, h["loop"], BLACK, TEXT_W, _s(300), _s(112), _s(62), 1.14)
    ly = BOT_SAFE - block_h(d, h["loop"], lf, TEXT_W, 1.14) - _s(20)
    tw = max(d.textlength(ln, font=lf) for ln in wrap(d, h["loop"], lf, TEXT_W))
    T.marker(d, PAD - _s(14), ly + int(lf.size * 0.16), int(tw) + _s(42),
             int(lf.size * 1.02), th, slant=_s(6))
    block(d, h["loop"], lf, PAD, ly, TEXT_W, th.marker_on, 1.14)
    return img
