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
    canvas = Image.new('RGB', (1080, 1920), '#101820')
    canvas.paste(card, (0, 160))
    d = ImageDraw.Draw(canvas)
    d.text((64, 1590), '어떤 조건에서 선택이 달라질까?',
           font=T.font(T.BOLD, 36), fill='white')
    d.text((64, 1655), '계산과 조건은 다음 화면에서 확인해요',
           font=T.font(T.REG, 28), fill='#C3CED8')
    return canvas
