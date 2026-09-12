"""
'돈값하나?' 카드뉴스 렌더러 v3 — 1080x1350 (4:5) PNG.

릴스(src/reel_scenes.py)와 같은 디자인 규칙을 쓴다. 계정에 들어왔을 때
릴스와 카드뉴스가 한 덩어리로 보여야 '운영되는 계정'으로 읽힌다.

  1장   표지 — 어두운 히어로 + 화면 밖으로 흘러넘치는 거대한 숫자 + 대문짝 훅
  2~n   본문 — 밝은 종이 바탕, 왼쪽 인덱스 레일, 숫자는 하드 오프셋 패널 안에
  마지막 결론 — 돈값 지수 + 화자 한 줄 + 댓글 유도

테마는 src/theme.py 에서 바꾼다 (THEME=paper | midnight).
"""
from __future__ import annotations

from pathlib import Path

from PIL import ImageDraw

from src import theme as T
from src.hooks import resolve as _hook
from src.theme import BLACK, BOLD, MED, REG, font

W, H = 1080, 1350
PAD = 96
RAIL_X = 48
TOP_SAFE = int(H * 0.125)
BOT_SAFE = H - 150
TEXT_W = W - PAD * 2

# 하위 호환 — 예전 코드가 import 하던 이름들
THEME = T.get_theme()


def wrap(d, text, f, max_w):
    lines = []
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


def block(d, text, f, x, y, max_w, fill, gap=1.42):
    lh = int(f.size * gap)
    for ln in wrap(d, text, f, max_w):
        d.text((x, y), ln, font=f, fill=fill)
        y += lh
    return y


def block_h(d, text, f, max_w, gap=1.42):
    return len(wrap(d, text, f, max_w)) * int(f.size * gap)


def fit(d, text, weight, max_w, max_h, start, min_size, gap=1.2):
    size = start
    while size > min_size:
        f = font(weight, size)
        if len(wrap(d, text, f, max_w)) * int(size * gap) <= max_h:
            return f
        size -= 3
    return font(weight, min_size)


def fit_lines(d, lines, weight, max_w, max_h, start, min_size, gap=1.12):
    size = start
    while size > min_size:
        f = font(weight, size)
        widest = max((d.textlength(ln, font=f) for ln in lines), default=0)
        if widest <= max_w and len(lines) * int(size * gap) <= max_h:
            return f
        size -= 3
    return font(weight, min_size)


def _label(d, text, x, y, size, fill):
    T.letterspaced(d, text, x, y, font(BOLD, size), fill, space=size * 0.14)


def _paper(brand, handle, ratio, th, page=None):
    img = T.background(W, H, th)
    d = ImageDraw.Draw(img)
    T.rail(d, RAIL_X, TOP_SAFE - 24, BOT_SAFE + 24, ratio, th, width=4)
    d.rectangle((PAD, TOP_SAFE - 72, PAD + 20, TOP_SAFE - 52), fill=th.accent)
    _label(d, brand, PAD + 32, TOP_SAFE - 74, 24, th.ink_soft)
    _label(d, handle, PAD, BOT_SAFE + 44, 22, th.ink_faint)
    if page:
        f = font(BOLD, 22)
        d.text((W - PAD - d.textlength(page, font=f), BOT_SAFE + 44), page,
               font=f, fill=th.ink_faint)
    return img, d


# ---------------------------------------------------------------- 표지
def cover(item, brand, handle, total, root="."):
    th = T.get_theme(item.get("theme"))
    h = _hook(item)
    img = T.load_cover(root, item.get("id", "cover"), W, H,
                       item.get("id", "cover"), T.motif_from(item, h))
    img = T.scrim(img, start=0.28, strength=0.90)
    d = ImageDraw.Draw(img)
    white, faint = "#FFFFFF", "#C9C9CE"

    d.rectangle((PAD, TOP_SAFE - 72, PAD + 20, TOP_SAFE - 52), fill=th.accent)
    _label(d, brand, PAD + 32, TOP_SAFE - 74, 24, white)
    _label(d, handle, PAD, BOT_SAFE + 44, 22, faint)

    badge = h["badge"] or item.get("price", "")
    big = h["big"] if (item.get("reel") or {}).get("big") else \
        wrap(d, item.get("hook") or item["product"], font(BLACK, 92), TEXT_W)
    sub = h["sub"] or item.get("hook", "")

    f_big = fit_lines(d, big, BLACK, TEXT_W, 620, 116, 52, 1.12)
    lh = int(f_big.size * 1.12)
    f_sub = font(MED, 38)
    sub_h = block_h(d, sub, f_sub, TEXT_W, 1.38) if sub else 0

    # 제품명 — 훅만 있으면 무엇에 대한 얘기인지 알 수 없다
    product = str(item.get("product", "")).strip()
    pf = font(BOLD, 34)
    head_h = 88 if (badge or product) else 0

    total_h = head_h + lh * len(big) + 46 + sub_h
    y = BOT_SAFE - total_h

    if badge or product:
        x = PAD
        if badge:
            x = T.tag(d, badge, PAD, y, th, 28, 24, 14)[0] + 18
        if product:
            if x + d.textlength(product, font=pf) > PAD + TEXT_W:
                pf = fit(d, product, BOLD, TEXT_W - (x - PAD), 52, 34, 22, 1.1)
            d.text((x, y + 9), product, font=pf, fill=white)
        y += head_h

    hl = len(big) - 1
    for i, line in enumerate(big):
        if i == hl:
            tw = d.textlength(line, font=f_big)
            T.marker(d, PAD - 10, y + i * lh + int(f_big.size * 0.16),
                     int(tw) + 26, int(f_big.size * 1.02), th, slant=4)
            d.text((PAD, y + i * lh), line, font=f_big, fill=th.marker_on)
        else:
            d.text((PAD, y + i * lh), line, font=f_big, fill=white)
    y += lh * len(big) + 46
    if sub:
        block(d, sub, f_sub, PAD, y, TEXT_W, faint, 1.38)
    return img


# ---------------------------------------------------------------- 본문
def body(card, brand, handle, idx, total, item=None):
    th = T.get_theme((item or {}).get("theme"))
    ratio = 0.12 + 0.76 * (idx - 1) / max(1, total - 1)
    img, d = _paper(brand, handle, ratio, th, f"{idx}/{total}")

    figure = str(card.get("figure") or "").strip()
    fig_label = str(card.get("figure_label") or "").strip()
    note = str(card.get("note") or "").strip()

    tf = fit(d, card["title"], BLACK, TEXT_W, 200, 78, 46, 1.14)
    bf = fit(d, card["body"], MED, TEXT_W, 420, 44, 32, 1.52)
    nf = font(REG, 30)

    fig_h = 0
    if figure:
        ff = fit(d, figure, BLACK, TEXT_W - 72, 130, 92, 42, 1.05)
        fig_h = 36 + (32 if fig_label else 0) + int(ff.size * 1.1) + 36

    note_lines = wrap(d, note, nf, TEXT_W - 76) if note else []
    note_h = (len(note_lines) * 44 + 48 + 28) if note else 0

    total_h = (64 + block_h(d, card["title"], tf, TEXT_W, 1.14) + 34
               + (fig_h + 30 if figure else 0)
               + block_h(d, card["body"], bf, TEXT_W, 1.52) + note_h)
    y = TOP_SAFE + max(0, (BOT_SAFE - TOP_SAFE - total_h) // 2)

    num = f"{idx - 1:02d}"
    numf = font(BLACK, 34)
    d.text((PAD, y), num, font=numf, fill=th.accent)
    nw = d.textlength(num, font=numf)
    d.text((PAD + nw + 8, y + 5), f"/{total - 2:02d}", font=font(BOLD, 24),
           fill=th.ink_faint)
    y += 64

    y = block(d, card["title"], tf, PAD, y, TEXT_W, th.ink, 1.14) + 34

    if figure:
        T.panel(d, (PAD, y, PAD + TEXT_W, y + fig_h), th, radius=16, offset=9, width=2)
        yy = y + 22
        if fig_label:
            _label(d, fig_label, PAD + 34, yy, 20, th.ink_faint)
            yy += 32
        d.text((PAD + 34, yy), figure, font=ff, fill=th.accent)
        y += fig_h + 30

    y = block(d, card["body"], bf, PAD, y, TEXT_W, th.ink_soft, 1.52)

    if note:
        y += 28
        box_h = len(note_lines) * 44 + 48
        d.rounded_rectangle((PAD, y, PAD + TEXT_W, y + box_h), radius=14,
                            fill=th.panel, outline=th.rule, width=2)
        d.rectangle((PAD, y + 14, PAD + 5, y + box_h - 14), fill=th.accent)
        yy = y + 24
        for ln in note_lines:
            d.text((PAD + 34, yy), ln, font=nf, fill=th.ink_faint)
            yy += 44
    return img


# ---------------------------------------------------------------- 결론
def verdict(item, brand, handle, total, cta=None):
    th = T.get_theme(item.get("theme"))
    img, d = _paper(brand, handle, 1.0, th, f"{total}/{total}")
    cta = cta or {}
    score = max(0, min(5, int(item.get("verdict", 3))))
    text = str(item.get("verdict_text", ""))
    voice = _hook(item)["voice"]

    vf = fit(d, text, MED, TEXT_W, 400, 44, 32, 1.48)
    v_h = block_h(d, text, vf, TEXT_W, 1.48)
    total_h = 52 + 108 + 40 + v_h + (60 if voice else 0) + 150
    y = TOP_SAFE + max(0, (BOT_SAFE - TOP_SAFE - total_h) // 2)

    _label(d, "결론", PAD, y, 26, th.accent)
    y += 52

    sf = font(BLACK, 96)
    d.text((PAD, y - 18), str(score), font=sf, fill=th.ink)
    sw = d.textlength(str(score), font=sf)
    d.text((PAD + sw + 8, y + 38), "/5", font=font(BOLD, 34), fill=th.ink_faint)
    bx = PAD + int(sw) + 96
    bw = (TEXT_W - (bx - PAD) - 4 * 10) // 5
    for i in range(5):
        x = bx + i * (bw + 10)
        d.rounded_rectangle((x, y + 16, x + bw, y + 44), radius=6,
                            fill=th.accent if i < score else th.rule)
    y += 108

    y = block(d, text, vf, PAD, y, TEXT_W, th.ink, 1.48)

    if voice:
        y += 30
        d.line((PAD, y, PAD + 40, y), fill=th.accent, width=3)
        block(d, voice, font(REG, 30), PAD + 56, y - 18, TEXT_W - 56,
              th.ink_faint, 1.3)

    top_line = cta.get("card_top", "다음엔 뭐가 궁금하세요?")
    bot_line = cta.get("card_bottom", "댓글로 신청받습니다")
    cy = BOT_SAFE - 150
    d.text((PAD, cy), top_line, font=font(MED, 32), fill=th.ink_soft)
    bf = fit(d, bot_line, BLACK, TEXT_W, 70, 56, 34, 1.1)
    tw = d.textlength(bot_line, font=bf)
    T.marker(d, PAD - 8, cy + 50 + int(bf.size * 0.16), int(tw) + 22,
             int(bf.size * 1.02), th, slant=3)
    d.text((PAD, cy + 50), bot_line, font=bf, fill=th.marker_on)
    return img


# ---------------------------------------------------------------- 진입점
def render_item(item: dict, outdir: Path, brand: str = "돈값하나?",
                handle: str = "@dongabhana",
                cta: dict | None = None) -> list[Path]:
    """한 편(item)을 카드 PNG 리스트로 렌더링한다. 총 장수 = 1 + len(cards) + 1"""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    total = len(item["cards"]) + 2
    root = str(Path(__file__).resolve().parent.parent)

    imgs = [cover(item, brand, handle, total, root)]
    for i, c in enumerate(item["cards"], start=2):
        imgs.append(body(c, brand, handle, i, total, item))
    imgs.append(verdict(item, brand, handle, total, cta))

    paths: list[Path] = []
    for i, im in enumerate(imgs, start=1):
        p = outdir / f"{item['id']}_{i:02d}.png"
        im.save(p, "PNG", optimize=True)
        paths.append(p)
    return paths


if __name__ == "__main__":
    import sys, yaml
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src import hooks

    q = hooks.attach(yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")))
    out = Path(sys.argv[2] if len(sys.argv) > 2 else ".preview")
    want = sys.argv[3] if len(sys.argv) > 3 else None
    for it in q["items"]:
        if want and it["id"] != want:
            continue
        ps = render_item(it, out / it["id"], it.get("brand") or q["brand"],
                         q["handle"], q.get("cta"))
        print(it["id"], "→", len(ps), "장")
