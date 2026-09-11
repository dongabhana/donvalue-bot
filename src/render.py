"""
'돈값하나?' 카드뉴스 렌더러 v2
1080x1350 (4:5) PNG 카드를 제목/본문 데이터로부터 자동 생성한다.

v2 변경점
  - 모든 카드 하단에 계정 핸들 고정 노출
  - 상단 진행 바(현재 몇 번째 카드인지 한눈에)
  - 배경 그라데이션 + 타이틀 뒤 소프트 글로우로 깊이감
  - 타이포 위계 강화(제목 더 크고 타이트하게, 자간/행간 조정)
  - 본문 카드에 챕터 넘버 마커
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ---------------------------------------------------------------- 폰트 해결
FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-{w}.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK{w}.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-{w}.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",  # macOS 로컬 테스트용
    "C:/Windows/Fonts/malgunbd.ttf",               # Windows 로컬 테스트용
]
_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _find_ttc(weight: str) -> tuple[str, int]:
    """Noto Sans CJK KR 페이스를 찾아 (경로, ttc index)를 돌려준다."""
    for pattern in FONT_CANDIDATES:
        path = pattern.format(w=weight)
        if not os.path.exists(path):
            continue
        if not path.endswith(".ttc"):
            return path, 0
        for idx in range(10):
            try:
                name = ImageFont.truetype(path, 12, index=idx).getname()[0]
            except Exception:
                break
            if "KR" in name or "Korean" in name:
                return path, idx
        return path, 0
    try:
        out = subprocess.check_output(
            ["fc-match", "-f", "%{file}", ":lang=ko"], text=True
        ).strip()
        if out:
            return out, 0
    except Exception:
        pass
    raise RuntimeError(
        "한글 폰트를 찾지 못했습니다. `sudo apt-get install -y fonts-noto-cjk` 를 실행하세요."
    )


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    key = (weight, size)
    if key not in _font_cache:
        path, idx = _find_ttc(weight)
        _font_cache[key] = ImageFont.truetype(path, size, index=idx)
    return _font_cache[key]


BLACK, BOLD, MED, REG = "Black", "Bold", "Medium", "Regular"

# ---------------------------------------------------------------- 테마
W, H = 1080, 1350
PAD = 96
FOOTER_Y = H - 92          # 핸들/브랜드가 놓이는 기준선
SAFE_BOTTOM = H - 150      # 본문이 침범하면 안 되는 하단 경계


@dataclass
class Theme:
    bg_top: tuple = (18, 20, 27)
    bg_bottom: tuple = (11, 12, 17)
    fg: str = "#F5F7FA"
    sub: str = "#8E97A8"
    dim: str = "#5A6272"
    accent: str = "#FFC93C"        # 시그니처 골드
    accent_soft: str = "#7A5E12"
    ink: str = "#0E1015"           # accent 위에 얹는 글자색
    card_bg: str = "#191C25"
    hair: str = "#262A36"


THEME = Theme()


# ---------------------------------------------------------------- 텍스트 유틸
def wrap(draw, text: str, fnt, max_w: int) -> list[str]:
    """한글은 어절 단위, 어절이 너무 길면 글자 단위로 줄바꿈. 명시적 개행 존중."""
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split(" "):
            trial = f"{cur} {word}".strip()
            if draw.textlength(trial, font=fnt) <= max_w:
                cur = trial
                continue
            if cur:
                lines.append(cur)
            if draw.textlength(word, font=fnt) <= max_w:
                cur = word
            else:
                cur = ""
                for ch in word:
                    if draw.textlength(cur + ch, font=fnt) <= max_w:
                        cur += ch
                    else:
                        lines.append(cur)
                        cur = ch
        lines.append(cur)
    return [ln for ln in lines if ln != ""] or [""]


def draw_block(draw, text, fnt, x, y, max_w, fill, line_gap=1.35) -> int:
    lh = int(fnt.size * line_gap)
    for line in wrap(draw, text, fnt, max_w):
        draw.text((x, y), line, font=fnt, fill=fill)
        y += lh
    return y


def block_h(draw, text, fnt, max_w, line_gap=1.35) -> int:
    return len(wrap(draw, text, fnt, max_w)) * int(fnt.size * line_gap)


def fit_font(draw, text, weight, max_w, max_h, start, min_size=40, line_gap=1.2):
    """주어진 박스에 들어갈 때까지 폰트 크기를 줄인다."""
    size = start
    while size > min_size:
        f = font(weight, size)
        if len(wrap(draw, text, f, max_w)) * int(size * line_gap) <= max_h:
            return f
        size -= 3
    return font(weight, min_size)


def rounded(draw, box, r, fill):
    draw.rounded_rectangle(box, radius=r, fill=fill)


# ---------------------------------------------------------------- 배경/공통
def _gradient_bg() -> Image.Image:
    """위에서 아래로 아주 미세하게 어두워지는 배경."""
    top, bot = THEME.bg_top, THEME.bg_bottom
    grad = Image.new("RGB", (1, H))
    px = grad.load()
    for y in range(H):
        t = y / (H - 1)
        px[0, y] = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
    return grad.resize((W, H))


def _glow(img: Image.Image, cx: int, cy: int, r: int, color=(255, 201, 60), alpha=26):
    """타이틀 뒤에 은은한 원형 글로우를 깔아 깊이감을 준다."""
    layer = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
    layer = layer.filter(ImageFilter.GaussianBlur(r * 0.75))
    return Image.blend(img, Image.blend(img, layer, 1.0), alpha / 255 * 1.6)


def _progress(d: ImageDraw.ImageDraw, idx: int, total: int):
    """상단 진행 바 — 현재 몇 번째 카드인지 한눈에."""
    if total <= 1:
        return
    y, gap = 0, 6
    seg = (W - gap * (total - 1)) / total
    for i in range(total):
        x0 = i * (seg + gap)
        d.rectangle((x0, y, x0 + seg, y + 7),
                    fill=THEME.accent if i < idx else THEME.hair)


def _footer(d: ImageDraw.ImageDraw, handle: str, page: str | None = None):
    """모든 카드 공통 하단: 브랜드 마크 · 핸들 · 페이지."""
    d.line((PAD, FOOTER_Y - 34, W - PAD, FOOTER_Y - 34), fill=THEME.hair, width=2)

    dot_r = 7
    d.ellipse((PAD, FOOTER_Y + 15, PAD + dot_r * 2, FOOTER_Y + 15 + dot_r * 2),
              fill=THEME.accent)
    d.text((PAD + dot_r * 2 + 16, FOOTER_Y), handle, font=font(BOLD, 34),
           fill=THEME.sub)

    if page:
        tw = d.textlength(page, font=font(BOLD, 34))
        d.text((W - PAD - tw, FOOTER_Y), page, font=font(BOLD, 34), fill=THEME.dim)


def _base(brand: str, idx: int, total: int, handle: str,
          glow_at: tuple[int, int] | None = None):
    img = _gradient_bg()
    if glow_at:
        img = _glow(img, glow_at[0], glow_at[1], 480)
    d = ImageDraw.Draw(img)
    _progress(d, idx, total)
    # 상단 시리즈 라벨
    d.text((PAD, 74), brand, font=font(BLACK, 34), fill=THEME.accent)
    return img, d


# ---------------------------------------------------------------- 카드 그리기
def cover(item: dict, brand: str, handle: str, total: int) -> Image.Image:
    img, d = _base(brand, 1, total, handle, glow_at=(W - 120, 300))
    maxw = W - PAD * 2
    top, bottom = 230, SAFE_BOTTOM - 260
    price = item.get("price", "")
    hook = item.get("hook", "")

    # 손가락을 멈추게 하는 건 제품명이 아니라 훅이다.
    # 훅을 주인공으로 키우고 제품명은 위쪽 라벨로 내린다.
    label = item["product"]
    label_f = font(BLACK, 44)
    hook_f = fit_font(d, hook, BLACK, maxw, 620, 118, 62, 1.16) if hook else None

    total_h = (108 if price else 0)
    total_h += block_h(d, label, label_f, maxw, 1.2) + 30
    if hook:
        total_h += block_h(d, hook, hook_f, maxw, 1.16)
    y = max(top, top + (bottom - top - total_h) // 2)

    if price:
        tw = d.textlength(price, font=font(BOLD, 38))
        rounded(d, (PAD, y, PAD + tw + 60, y + 72), 36, THEME.accent)
        d.text((PAD + 30, y + 13), price, font=font(BOLD, 38), fill=THEME.ink)
        y += 108

    y = draw_block(d, label, label_f, PAD, y, maxw, THEME.accent, 1.2) + 30
    if hook:
        draw_block(d, hook, hook_f, PAD, y, maxw, THEME.fg, 1.16)

    # 하단 시그니처
    sig_y = SAFE_BOTTOM - 236
    d.text((PAD, sig_y), "돈값하나?", font=font(BLACK, 104), fill=THEME.accent)
    d.text((PAD + 4, sig_y + 132), "5초 안에 결론부터", font=font(MED, 38), fill=THEME.sub)
    aw = d.textlength("5초 안에 결론부터", font=font(MED, 38))
    d.text((PAD + 4 + aw + 18, sig_y + 130), "→", font=font(BOLD, 40), fill=THEME.accent)

    _footer(d, handle)
    return img


def body(card: dict, brand: str, handle: str, idx: int, total: int) -> Image.Image:
    img, d = _base(brand, idx, total, handle)
    maxw = W - PAD * 2
    top, bottom = 240, SAFE_BOTTOM - 40
    note = card.get("note")

    num = f"{idx - 1:02d}"
    n_f = font(BLACK, 42)
    t_f = fit_font(d, card["title"], BLACK, maxw, 250, 88, 56, 1.18)

    figure = card.get("figure")
    fig_label = card.get("figure_label", "")
    as_of = card.get("as_of", "")

    avail = bottom - top

    def measure(body_size: int, note_size: int, fig_size: int):
        """주어진 폰트 크기 조합으로 전체 높이를 계산한다."""
        bf = font(MED, body_size)
        nf = font(REG, note_size)
        ff = font(BLACK, fig_size) if figure else None
        fl = int(ff.size * 1.42) if figure else 0
        fh = (52 + (46 if fig_label else 0) + fl + (40 if as_of else 0) + 44) if figure else 0
        nlines = wrap(d, note, nf, maxw - 76) if note else []
        h = 74 + block_h(d, card["title"], t_f, maxw, 1.18) + 46 + fh
        h += block_h(d, card["body"], bf, maxw, 1.55)
        if note:
            h += 52 + len(nlines) * int(note_size * 1.43) + 60
        return h, bf, nf, ff, fl, fh, nlines

    # 숫자 카드와 note 가 함께 오면 높이를 넘길 수 있으므로 들어갈 때까지 줄인다.
    body_size, note_size, fig_size = 50, 35, 128
    if figure:
        # 숫자는 폭도 넘치면 안 되므로 폭 기준으로 먼저 맞춘다.
        fig_size = fit_font(d, str(figure), BLACK, maxw - 80, 200, 128, 56, 1.05).size
    total_h, b_f, note_f, fig_f, fig_line, fig_h, note_lines = measure(
        body_size, note_size, fig_size)
    while total_h > avail:
        shrunk = False
        if body_size > 34:
            body_size -= 2
            shrunk = True
        if note and note_size > 28:
            note_size -= 1
            shrunk = True
        if figure and total_h > avail and fig_size > 72:
            fig_size -= 6
            shrunk = True
        if not shrunk:
            break
        total_h, b_f, note_f, fig_f, fig_line, fig_h, note_lines = measure(
            body_size, note_size, fig_size)

    y = max(top, top + (avail - total_h) // 2)

    # 챕터 넘버
    d.text((PAD, y), num, font=n_f, fill=THEME.accent)
    nw = d.textlength(num, font=n_f)
    d.line((PAD + nw + 20, y + 26, PAD + nw + 92, y + 26), fill=THEME.accent_soft, width=3)
    y += 74

    y = draw_block(d, card["title"], t_f, PAD, y, maxw, THEME.fg, 1.18) + 46

    if figure:
        box_top = y
        box_h = fig_h - 44
        rounded(d, (PAD, box_top, W - PAD, box_top + box_h), 26, THEME.card_bg)
        yy = box_top + 30
        if fig_label:
            d.text((PAD + 40, yy), fig_label, font=font(MED, 34), fill=THEME.sub)
            yy += 46
        d.text((PAD + 40, yy), str(figure), font=fig_f, fill=THEME.accent)
        yy += fig_line
        if as_of:
            d.text((PAD + 40, yy), as_of, font=font(REG, 28), fill=THEME.dim)
        y = box_top + box_h + 44

    y = draw_block(d, card["body"], b_f, PAD, y, maxw, THEME.sub, 1.55)

    if note:
        y += 52
        note_lh = int(note_f.size * 1.43)
        box_h = len(note_lines) * note_lh + 60
        rounded(d, (PAD, y, W - PAD, y + box_h), 26, THEME.card_bg)
        rounded(d, (PAD, y + 16, PAD + 6, y + box_h - 16), 3, THEME.accent)
        yy = y + 30
        for line in note_lines:
            d.text((PAD + 40, yy), line, font=note_f, fill=THEME.sub)
            yy += note_lh

    _footer(d, handle, f"{idx}/{total}")
    return img


def verdict(item: dict, brand: str, handle: str, total: int) -> Image.Image:
    img, d = _base(brand, total, total, handle, glow_at=(140, H - 560))
    maxw = W - PAD * 2
    top, bottom = 240, SAFE_BOTTOM - 200
    score = max(0, min(5, int(item.get("verdict", 3))))
    v_f = fit_font(d, item["verdict_text"], MED, maxw, 520, 52, 38, 1.5)

    total_h = 168 + 40 + 78 + 108 + block_h(d, item["verdict_text"], v_f, maxw, 1.5)
    y = max(top, top + (bottom - top - total_h) // 2)

    d.text((PAD, y), "결론", font=font(BLACK, 92), fill=THEME.fg)
    y += 168

    gw, gap = (maxw - 4 * 20) // 5, 20
    for i in range(5):
        x = PAD + i * (gw + gap)
        rounded(d, (x, y, x + gw, y + 26), 13,
                THEME.accent if i < score else THEME.hair)
    y += 78

    d.text((PAD, y), "돈값 지수", font=font(MED, 40), fill=THEME.sub)
    lw = d.textlength("돈값 지수", font=font(MED, 40))
    d.text((PAD + lw + 22, y - 12), str(score), font=font(BLACK, 62), fill=THEME.accent)
    sw = d.textlength(str(score), font=font(BLACK, 62))
    d.text((PAD + lw + 22 + sw + 8, y + 4), "/ 5", font=font(BOLD, 40), fill=THEME.dim)
    y += 104

    draw_block(d, item["verdict_text"], v_f, PAD, y, maxw, THEME.fg, 1.5)

    # 하단 CTA
    cta_y = SAFE_BOTTOM - 176
    d.text((PAD, cta_y), "이런 계산, 주 2회 올립니다", font=font(MED, 38), fill=THEME.sub)
    d.text((PAD, cta_y + 60), "저장 · 팔로우", font=font(BLACK, 62), fill=THEME.accent)

    _footer(d, handle, f"{total}/{total}")
    return img


def render_item(item: dict, outdir: Path, brand: str = "돈값하나?",
                handle: str = "@dongabhana") -> list[Path]:
    """한 편(item)을 카드 PNG 리스트로 렌더링한다. 총 장수 = 1 + len(cards) + 1"""
    outdir.mkdir(parents=True, exist_ok=True)
    total = len(item["cards"]) + 2

    imgs = [cover(item, brand, handle, total)]
    for i, c in enumerate(item["cards"], start=2):
        imgs.append(body(c, brand, handle, i, total))
    imgs.append(verdict(item, brand, handle, total))

    paths: list[Path] = []
    for i, im in enumerate(imgs, start=1):
        p = outdir / f"{item['id']}_{i:02d}.png"
        im.save(p, "PNG", optimize=True)
        paths.append(p)
    return paths


if __name__ == "__main__":
    import sys, yaml

    queue = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "out")
    brand = queue.get("brand", "돈값하나?")
    handle = queue.get("handle", "@dongabhana")
    for it in queue["items"]:
        ps = render_item(it, out / it["id"], brand, handle)
        print(it["id"], "→", len(ps), "장")
