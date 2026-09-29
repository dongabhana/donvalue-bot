"""Per-topic photographic covers; only explicitly supplied v3 assets opt in."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from src import theme as T


def asset_path(root, item):
    return Path(root) / 'assets' / 'covers' / f"{item['id']}.editorial-v3.jpg"


def available(root, item):
    return bool(item.get('id')) and asset_path(root, item).is_file()


def _wrap(draw, text, size, width):
    result = []
    for para in str(text).splitlines():
        current = ''
        for word in para.split():
            trial = (current + ' ' + word).strip()
            if draw.textlength(trial, font=T.font(T.BOLD, size)) <= width:
                current = trial
            else:
                if current:
                    result.append(current)
                current = word
        if current:
            result.append(current)
    return result


def render(item, brand, handle, root='.', reel=False, reveal=None):
    with Image.open(asset_path(root, item)) as source:
        card = ImageOps.fit(source.convert('RGB'), (1080, 1350))
    draw = ImageDraw.Draw(card)
    accent = '#FFB54A'
    draw.text((64, 42), brand, font=T.font(T.BOLD, 30), fill=accent)
    product = str(item.get('product', '')).strip()
    size = 34
    while size > 22 and draw.textlength(product, font=T.font(T.BOLD, size)) > 950:
        size -= 2
    draw.text((64, 102), product, font=T.font(T.BOLD, size), fill='#DDE5EC')
    headline = str(item.get('hook') or product).strip()
    for size in range(92, 47, -2):
        lines = _wrap(draw, headline, size, 952)
        if len(lines) <= 3 and all(draw.textlength(line, font=T.font(T.BOLD, size)) <= 952 for line in lines):
            break
    else:
        raise ValueError(f"Cover headline exceeds safe area: {item['id']}")
    visible = lines if reveal is None else lines[:max(1, reveal)]
    for index, line in enumerate(visible):
        draw.text((64, 166 + int(index * size * 1.20)), line,
                  font=T.font(T.BOLD, size),
                  fill=accent if index == len(lines) - 1 else 'white',
                  stroke_width=2, stroke_fill='#101820')
    draw.rounded_rectangle((56, 1212, 1024, 1320), radius=18, fill='#101820')
    draw.text((76, 1230), handle, font=T.font(T.BOLD, 24), fill='white')
    draw.text((76, 1270), '내용의 상황을 표현한 AI 연출 이미지',
              font=T.font(T.REG, 23), fill='#C3CED8')
    if not reel:
        return card
    return render_reel(item, brand, handle, root, reveal)


def _hook_lines(item):
    """릴스 첫 화면 문구. 훅 시트(reel.big)가 있으면 그 줄바꿈을 그대로 쓴다."""
    big = [str(x).strip() for x in ((item.get('reel') or {}).get('big') or []) if str(x).strip()]
    return big or [str(item.get('hook') or item.get('product') or '').strip()]


def render_reel(item, brand, handle, root='.', reveal=None):
    """릴스 첫 화면 — 표지 사진을 세로 전체(1080x1920)에 깔고 훅을 크게 얹는다.

    2026-09-29 이전에는 4:5 카드를 검은 세로 화면 가운데 붙이고 아래에
    '어떤 조건에서 선택이 달라질까?' 같은 공통 문구를 넣었다. 스크롤을 멈춰야 할
    첫 1초에 화면 절반이 빈 상자라 훅이 약했다. 이제 사진이 화면을 꽉 채우고
    편마다 다른 훅 문구가 화면 중앙에 크게 뜬다.

    글자는 세로 화면 가운데(프로필 격자에서 잘리지 않는 3:4 영역) 안에 둔다.
    """
    W, H = 1080, 1920
    with Image.open(asset_path(root, item)) as source:
        img = ImageOps.fit(source.convert('RGB'), (W, H), centering=(0.5, 0.45))
    # 아래로 갈수록 어두워지는 막 — 사진은 살리고 글자는 읽히게
    shade = Image.new('L', (1, H))
    for y in range(H):
        t = max(0.0, (y / H - 0.28) / 0.72)
        shade.putpixel((0, y), int(40 + 190 * min(1.0, t) ** 1.2))
    dark = Image.new('RGB', (W, H), '#0B1117')
    img = Image.composite(dark, img, shade.resize((W, H)))
    draw = ImageDraw.Draw(img)

    accent = '#FFB54A'
    x0, text_w = 72, W - 144
    draw.text((x0, 250), brand, font=T.font(T.BOLD, 34), fill=accent,
              stroke_width=2, stroke_fill='#0B1117')

    # 무엇에 대한 얘기인지 — 제품/주제 알약
    product = str(item.get('product', '')).strip()
    lines = _hook_lines(item)
    size = 132
    while size > 64:
        f = T.font(T.BLACK, size)
        if all(draw.textlength(ln, font=f) <= text_w for ln in lines) and len(lines) * size * 1.18 <= 700:
            break
        size -= 4
    f = T.font(T.BLACK, size)
    lh = int(size * 1.18)
    block_h = lh * len(lines)
    top = 1500 - block_h                      # 아래에서 쌓아 올린다(자막·버튼 영역 위)

    if product:
        pf = T.font(T.BOLD, 44)
        pw = int(draw.textlength(product, font=pf))
        py = top - 110
        draw.rounded_rectangle((x0 - 6, py, x0 + pw + 42, py + 76), radius=38, fill=accent)
        draw.text((x0 + 18, py + 12), product, font=pf, fill='#101820')

    shown = lines if reveal is None else lines[:max(1, reveal)]
    for i, ln in enumerate(shown):
        y = top + i * lh
        last = i == len(lines) - 1
        th = T.get_theme(item.get('theme'))
        if last:
            tw = draw.textlength(ln, font=f)
            T.marker(draw, x0 - 14, y + int(size * 0.14), int(tw) + 34, int(size * 1.02),
                     th, slant=6)
        draw.text((x0, y), ln, font=f, fill=th.marker_on if last else 'white',
                  stroke_width=0 if last else 3, stroke_fill='#0B1117')

    draw.text((x0, 1560), handle, font=T.font(T.BOLD, 30), fill='#DDE5EC')
    draw.text((x0, 1606), '상황을 표현한 AI 연출 이미지', font=T.font(T.REG, 24),
              fill='#AEB9C4')
    return img
