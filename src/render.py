"""
'돈값하나?' 카드뉴스 렌더러
1080x1350 (4:5) PNG 카드를 제목/본문 데이터로부터 자동 생성한다.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

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
        for idx in range(8):
            try:
                name = ImageFont.truetype(path, 12, index=idx).getname()[0]
            except Exception:
                break
            if "KR" in name or "Korean" in name:
                return path, idx
        return path, 0
    # 최후: fc-match 로 시스템 한글 폰트 아무거나
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
PAD = 88


@dataclass
class Theme:
    bg: str = "#12141A"
    fg: str = "#FFFFFF"
    sub: str = "#9AA3B2"
    accent: str = "#FFD24A"
    accent_dark: str = "#12141A"
    card_bg: str = "#1B1E27"


THEME = Theme()


# ---------------------------------------------------------------- 텍스트 유틸
def wrap(draw, text: str, fnt, max_w: int) -> list[str]:
    """한글은 어절 단위, 어절이 너무 길면 글자 단위로 줄바꿈."""
    lines, cur = [], ""
    for word in text.split(" "):
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=fnt) <= max_w:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        if draw.textlength(word, font=fnt) <= max_w:
            cur = word
        else:  # 한 어절이 폭보다 김 → 글자 단위 분해
            cur = ""
            for ch in word:
                if draw.textlength(cur + ch, font=fnt) <= max_w:
                    cur += ch
                else:
                    lines.append(cur)
                    cur = ch
    if cur:
        lines.append(cur)
    return lines


def draw_block(draw, text, fnt, x, y, max_w, fill, line_gap=1.35) -> int:
    """줄바꿈해서 그리고 다음 y 좌표를 반환."""
    lh = int(fnt.size * line_gap)
    for line in wrap(draw, text, fnt, max_w):
        draw.text((x, y), line, font=fnt, fill=fill)
        y += lh
    return y


def block_h(draw, text, fnt, max_w, line_gap=1.35) -> int:
    """draw_block 이 차지할 높이를 미리 계산."""
    return len(wrap(draw, text, fnt, max_w)) * int(fnt.size * line_gap)


def fit_font(draw, text, weight, max_w, max_h, start, min_size=40) -> ImageFont.FreeTypeFont:
    """주어진 박스에 들어갈 때까지 폰트 크기를 줄인다."""
    size = start
    while size > min_size:
        f = font(weight, size)
        lines = wrap(draw, text, f, max_w)
        if len(lines) * int(size * 1.25) <= max_h:
            return f
        size -= 4
    return font(weight, min_size)


def rounded(draw, box, r, fill):
    draw.rounded_rectangle(box, radius=r, fill=fill)


# ---------------------------------------------------------------- 카드 그리기
def _base(brand: str, page: str | None) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), THEME.bg)
    d = ImageDraw.Draw(img)
    # 상단 시리즈 라벨
    d.text((PAD, 64), brand, font=font(BOLD, 34), fill=THEME.accent)
    if page:
        tw = d.textlength(page, font=font(BOLD, 34))
        d.text((W - PAD - tw, 64), page, font=font(BOLD, 34), fill=THEME.sub)
    return img, d


def cover(item: dict, brand: str) -> Image.Image:
    img, d = _base(brand, None)
    maxw = W - PAD * 2
    top, bottom = 200, H - 300          # 본문이 놓일 수 있는 영역
    price = item.get("price", "")
    hook = item.get("hook", "")

    title_f = fit_font(d, item["product"], BLACK, maxw, 480, 120, 64)
    hook_f = font(MED, 46)

    total = (100 if price else 0)
    total += block_h(d, item["product"], title_f, maxw, 1.18) + 34
    total += block_h(d, hook, hook_f, maxw, 1.4)
    y = max(top, top + (bottom - top - total) // 2)

    if price:
        tw = d.textlength(price, font=font(BOLD, 40))
        rounded(d, (PAD, y, PAD + tw + 56, y + 76), 38, THEME.accent)
        d.text((PAD + 28, y + 14), price, font=font(BOLD, 40), fill=THEME.accent_dark)
        y += 100

    y = draw_block(d, item["product"], title_f, PAD, y, maxw, THEME.fg, 1.18) + 34
    draw_block(d, hook, hook_f, PAD, y, maxw, THEME.sub, 1.4)

    # 하단 시그니처
    d.line((PAD, H - 262, W - PAD, H - 262), fill="#2A2E3A", width=2)
    d.text((PAD, H - 224), "돈값하나?", font=font(BLACK, 92), fill=THEME.accent)
    d.text((PAD, H - 116), "5초 안에 결론부터  →", font=font(MED, 38), fill=THEME.sub)
    return img


def body(card: dict, brand: str, page: str) -> Image.Image:
    img, d = _base(brand, page)
    maxw = W - PAD * 2
    top, bottom = 200, H - 150
    note = card.get("note")

    t_f = fit_font(d, card["title"], BLACK, maxw, 240, 84, 54)
    b_f = fit_font(d, card["body"], MED, maxw, 620, 50, 36)
    n_f = font(REG, 36)

    total = block_h(d, card["title"], t_f, maxw, 1.2) + 44
    total += block_h(d, card["body"], b_f, maxw, 1.55)
    note_lines = wrap(d, note, n_f, maxw - 60) if note else []
    if note:
        total += 48 + len(note_lines) * 50 + 56

    y = max(top, top + (bottom - top - total) // 2)

    # 제목 왼쪽 강조 바
    th = block_h(d, card["title"], t_f, maxw, 1.2)
    rounded(d, (PAD - 30, y + 12, PAD - 18, y + th - 4), 6, THEME.accent)

    y = draw_block(d, card["title"], t_f, PAD, y, maxw, THEME.accent, 1.2) + 44
    y = draw_block(d, card["body"], b_f, PAD, y, maxw, THEME.fg, 1.55)

    if note:
        y += 48
        rounded(d, (PAD, y, W - PAD, y + len(note_lines) * 50 + 56), 28, THEME.card_bg)
        yy = y + 28
        for line in note_lines:
            d.text((PAD + 30, yy), line, font=n_f, fill=THEME.sub)
            yy += 50
    return img


def verdict(item: dict, brand: str, page: str) -> Image.Image:
    img, d = _base(brand, page)
    maxw = W - PAD * 2
    top, bottom = 200, H - 260
    score = max(0, min(5, int(item.get("verdict", 3))))
    v_f = fit_font(d, item["verdict_text"], MED, maxw, 560, 52, 38)

    total = 112 + 34 + 40 + 62 + 60 + block_h(d, item["verdict_text"], v_f, maxw, 1.5)
    y = max(top, top + (bottom - top - total) // 2)

    d.text((PAD, y), "결론", font=font(BLACK, 88), fill=THEME.accent)
    y += 132

    gw, gap = (maxw - 4 * 22) // 5, 22
    for i in range(5):
        x = PAD + i * (gw + gap)
        rounded(d, (x, y, x + gw, y + 30), 15,
                THEME.accent if i < score else THEME.card_bg)
    y += 60
    d.text((PAD, y), f"돈값 지수  {score} / 5", font=font(BOLD, 54), fill=THEME.fg)
    y += 104

    draw_block(d, item["verdict_text"], v_f, PAD, y, maxw, THEME.fg, 1.5)

    d.line((PAD, H - 232, W - PAD, H - 232), fill="#2A2E3A", width=2)
    d.text((PAD, H - 194), "이런 거 계속 계산해드립니다", font=font(MED, 40), fill=THEME.sub)
    d.text((PAD, H - 130), "저장 · 팔로우", font=font(BLACK, 60), fill=THEME.accent)
    return img


def render_item(item: dict, outdir: Path, brand: str = "돈값하나?") -> list[Path]:
    """한 편(item)을 카드 PNG 리스트로 렌더링한다. 총 장수 = 1 + len(cards) + 1"""
    outdir.mkdir(parents=True, exist_ok=True)
    total = len(item["cards"]) + 2
    paths: list[Path] = []

    imgs = [cover(item, brand)]
    for i, c in enumerate(item["cards"], start=2):
        imgs.append(body(c, brand, f"{i}/{total}"))
    imgs.append(verdict(item, brand, f"{total}/{total}"))

    for i, im in enumerate(imgs, start=1):
        p = outdir / f"{item['id']}_{i:02d}.png"
        im.save(p, "PNG", optimize=True)
        paths.append(p)
    return paths


if __name__ == "__main__":
    import sys, yaml

    queue = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "out")
    for it in queue["items"]:
        ps = render_item(it, out / it["id"])
        print(it["id"], "→", len(ps), "장")
