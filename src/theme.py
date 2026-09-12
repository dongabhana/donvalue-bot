"""
디자인 시스템 — 색·질감·공통 그리기 요소.

왜 분리했나
  카드뉴스(4:5)와 릴스(9:16)가 같은 규칙을 써야 계정이 한 덩어리로 보인다.
  색만 바꿔서 전체 톤을 갈아엎을 수 있게 테마를 데이터로 뺐다.

테마 고르기
  환경변수 THEME=paper | midnight (기본 paper)
  큐의 theme: 값으로도 지정할 수 있고, 편별 theme 이 있으면 그게 이긴다.

디자인 의도
  paper    따뜻한 종이색 + 먹색 활자 + 주황 한 가지.
           돈 얘기 계정은 거의 다 '검정+금색'이라 피드에서 묻힌다.
           밝은 바탕은 그 사이에서 먼저 눈에 걸리고, 광고처럼 안 보인다.
  midnight 검정을 유지하되 형광 라임으로 포인트를 바꾸고 패널·그레인을 넣어
           평평한 느낌을 없앤 버전.

공통 장치
  · 마커 하이라이트 — 핵심 한 줄 뒤에 색을 깔아 시선을 고정시킨다
  · 하드 오프셋 패널 — 그림자를 흐리지 않고 툭 밀어 찍는다. 또렷하고 값싸 보이지 않는다
  · 그레인 — 아주 약한 노이즈. 평면 그래픽이 '인쇄물'처럼 보이게 한다
  · 왼쪽 인덱스 레일 — 상단 진행바 대신. 흔하지 않아서 계정 표식이 된다
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- 폰트
FONT_FILES = {
    "Black": "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "Bold": "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "Medium": "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc",
    "Regular": "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "Light": "/usr/share/fonts/opentype/noto/NotoSansCJK-Light.ttc",
    "DemiLight": "/usr/share/fonts/opentype/noto/NotoSansCJK-DemiLight.ttc",
}
FALLBACK = [
    "/usr/share/fonts/truetype/noto/NotoSansCJK-{w}.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "C:/Windows/Fonts/malgunbd.ttf",
]
_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
_path_cache: dict[str, tuple[str, int]] = {}


def _resolve(weight: str) -> tuple[str, int]:
    if weight in _path_cache:
        return _path_cache[weight]
    cands = [FONT_FILES.get(weight, "")] + [p.format(w=weight) for p in FALLBACK]
    for path in cands:
        if not path or not os.path.exists(path):
            continue
        if not path.endswith(".ttc"):
            _path_cache[weight] = (path, 0)
            return _path_cache[weight]
        for idx in range(10):
            try:
                name = ImageFont.truetype(path, 12, index=idx).getname()[0]
            except Exception:
                break
            if "KR" in name or "Korean" in name:
                _path_cache[weight] = (path, idx)
                return _path_cache[weight]
        _path_cache[weight] = (path, 0)
        return _path_cache[weight]
    import subprocess
    try:
        out = subprocess.check_output(["fc-match", "-f", "%{file}", ":lang=ko"],
                                      text=True).strip()
        if out:
            _path_cache[weight] = (out, 0)
            return _path_cache[weight]
    except Exception:
        pass
    raise RuntimeError("한글 폰트를 찾지 못했습니다. fonts-noto-cjk 를 설치하세요.")


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    key = (weight, int(size))
    if key not in _cache:
        path, idx = _resolve(weight)
        _cache[key] = ImageFont.truetype(path, int(size), index=idx)
    return _cache[key]


BLACK, BOLD, MED, REG, LIGHT, DEMI = \
    "Black", "Bold", "Medium", "Regular", "Light", "DemiLight"


# ---------------------------------------------------------------- 테마
@dataclass
class Theme:
    name: str
    bg: tuple                 # 바탕
    bg2: tuple                # 아주 미세한 그라데이션 끝색
    ink: str                  # 본문 글자
    ink_soft: str             # 보조 글자
    ink_faint: str            # 캡션·번호
    accent: str               # 포인트
    on_accent: str            # 포인트 위 글자
    panel: str                # 패널 바탕
    panel_edge: str           # 패널 테두리
    rule: str                 # 얇은 선
    marker: str               # 마커 하이라이트 색
    marker_on: str            # 마커 위 글자
    grain: int = 7            # 그레인 세기 (0~20)
    shadow: str = "#000000"   # 하드 오프셋 그림자
    shadow_alpha: float = 1.0


THEMES: dict[str, Theme] = {
    "paper": Theme(
        name="paper",
        bg=(244, 241, 234), bg2=(236, 232, 223),
        ink="#14140F", ink_soft="#5B564C", ink_faint="#9A9287",
        accent="#FF4A24", on_accent="#FFFFFF",
        panel="#FFFFFF", panel_edge="#14140F", rule="#D8D2C6",
        marker="#FFD84D", marker_on="#14140F",
        grain=8, shadow="#14140F",
    ),
    "midnight": Theme(
        name="midnight",
        bg=(15, 16, 20), bg2=(9, 10, 13),
        ink="#F2F3F5", ink_soft="#98A0AC", ink_faint="#5C6470",
        accent="#C8FF3D", on_accent="#11140A",
        panel="#191C22", panel_edge="#2C313A", rule="#262B33",
        marker="#C8FF3D", marker_on="#11140A",
        grain=6, shadow="#000000",
    ),
}


def get_theme(name: str | None = None) -> Theme:
    key = (name or os.getenv("THEME") or "paper").lower()
    return THEMES.get(key, THEMES["paper"])


# ---------------------------------------------------------------- 바탕
_grain_cache: dict[tuple[int, int], Image.Image] = {}


def _grain(size: tuple[int, int]) -> Image.Image:
    if size not in _grain_cache:
        import numpy as np
        rng = np.random.default_rng(7)
        n = rng.integers(0, 256, size=(size[1] // 2, size[0] // 2), dtype="uint8")
        _grain_cache[size] = Image.fromarray(n, "L").resize(size, Image.BILINEAR)
    return _grain_cache[size]


def background(w: int, h: int, th: Theme) -> Image.Image:
    """위아래로 아주 미세하게 깊어지는 바탕 + 그레인."""
    grad = Image.new("RGB", (1, h))
    px = grad.load()
    for y in range(h):
        t = y / (h - 1)
        px[0, y] = tuple(int(th.bg[i] + (th.bg2[i] - th.bg[i]) * t) for i in range(3))
    img = grad.resize((w, h))
    if th.grain:
        noise = _grain((w, h)).convert("RGB")
        img = Image.blend(img, noise, th.grain / 255 * 1.6)
    return img


# ---------------------------------------------------------------- 요소
def panel(d: ImageDraw.ImageDraw, box, th: Theme, radius: int = 0,
          offset: int = 0, fill: str | None = None, width: int = 3):
    """하드 오프셋 패널. 그림자를 흐리지 않고 툭 밀어 찍는다."""
    x0, y0, x1, y1 = box
    if offset:
        d.rounded_rectangle((x0 + offset, y0 + offset, x1 + offset, y1 + offset),
                            radius=radius, fill=th.shadow)
    d.rounded_rectangle(box, radius=radius, fill=fill or th.panel,
                        outline=th.panel_edge, width=width)


def marker(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, th: Theme,
           slant: int = 0):
    """형광펜으로 그은 듯한 하이라이트. 살짝 기울여야 손맛이 난다."""
    if slant:
        d.polygon([(x, y + slant), (x + w, y), (x + w, y + h),
                   (x, y + h + slant)], fill=th.marker)
    else:
        d.rectangle((x, y, x + w, y + h), fill=th.marker)


def tag(d: ImageDraw.ImageDraw, text: str, x: int, y: int, th: Theme,
        size: int, pad_x: int, pad_y: int, fill: str | None = None,
        color: str | None = None, radius: int | None = None) -> tuple[int, int]:
    """알약 라벨. (오른쪽 끝 x, 아래 y) 를 돌려준다."""
    f = font(BOLD, size)
    tw = d.textlength(text, font=f)
    h = size + pad_y * 2
    box = (x, y, x + tw + pad_x * 2, y + h)
    r = h // 2 if radius is None else radius
    d.rounded_rectangle(box, radius=r, fill=fill or th.accent)
    d.text((x + pad_x, y + pad_y - size * 0.06), text, font=f,
           fill=color or th.on_accent)
    return int(box[2]), int(box[3])


def rail(d: ImageDraw.ImageDraw, x: int, y0: int, y1: int, ratio: float, th: Theme,
         width: int = 4):
    """왼쪽 인덱스 레일. 상단 진행바보다 덜 흔하고 시선을 세로로 잡아준다."""
    d.rounded_rectangle((x, y0, x + width, y1), radius=width // 2, fill=th.rule)
    end = y0 + int((y1 - y0) * max(0.0, min(1.0, ratio)))
    if end > y0:
        d.rounded_rectangle((x, y0, x + width, end), radius=width // 2, fill=th.accent)


def letterspaced(d: ImageDraw.ImageDraw, text: str, x: int, y: int,
                 f: ImageFont.FreeTypeFont, fill: str, space: float = 0.0) -> int:
    """자간을 벌려 그린다. 작은 라벨은 자간을 벌려야 '라벨'로 읽힌다."""
    cx = float(x)
    for ch in text:
        d.text((cx, y), ch, font=f, fill=fill)
        cx += d.textlength(ch, font=f) + space
    return int(cx)


# ---------------------------------------------------------------- 표지 히어로
# 표지는 본문과 다른 규칙을 쓴다.
#   본문 = 읽는 화면(깔끔하게)  /  표지 = 멈추게 하는 화면(강하게)
# 스톡 사진 API 는 라이선스·키·네트워크가 전부 변수라, 기본은 '직접 만든 배경'을 쓴다.
# assets/covers/<id>.jpg|png 가 있으면 그 사진이 우선한다.
COVER_DIR = "assets/covers"

# 편 id 로 결정되는 팔레트. 같은 편은 항상 같은 색이 나온다.
HERO_PALETTES = [
    ((14, 22, 48), (37, 84, 196), (120, 72, 255)),     # 심야 블루 → 바이올렛
    ((28, 12, 34), (168, 40, 92), (255, 122, 60)),     # 자홍 → 주황
    ((6, 30, 30), (18, 122, 108), (150, 226, 128)),    # 딥 틸 → 라임
    ((30, 16, 8), (168, 88, 24), (255, 186, 66)),      # 코냑 → 앰버
    ((10, 14, 28), (42, 60, 148), (0, 196, 210)),      # 인디고 → 시안
    ((26, 8, 20), (120, 30, 110), (255, 96, 140)),     # 플럼 → 핑크
]


def hero_background(w: int, h: int, seed: str, motif: str = "") -> Image.Image:
    """표지 배경 — 사진 대신 '거대한 숫자'를 주인공으로 쓴다.

    스톡 사진은 라이선스·검색·톤이 전부 변수인데, 이 계정의 주인공은 어차피 숫자다.
    그래서 편의 핵심 숫자를 화면 밖으로 흘러넘칠 만큼 키워 배경으로 깐다.
    흐린 그라데이션만 깔면 '뿌연 이미지'가 되지만, 거대한 활자가 하나 있으면
    구도가 생기고 편마다 화면이 완전히 달라 보인다.
    """
    import hashlib
    import numpy as np
    from PIL import ImageFilter

    seed_int = int(hashlib.sha1(seed.encode()).hexdigest()[:10], 16)
    rng = np.random.default_rng(seed_int)
    base, mid, hot = HERO_PALETTES[seed_int % len(HERO_PALETTES)]

    # --- 바탕: 어두운 베이스 + 빛 웅덩이 두 개 (과하게 겹치지 않게 약하게)
    sw = 200
    sh = int(sw * h / w)
    yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
    canvas = np.zeros((sh, sw, 3), dtype=np.float32)
    canvas[:, :] = np.array(base, dtype=np.float32) * 1.15
    for fx, fy, fr, color, gain in [(0.24, 0.18, 0.38, hot, 0.80),
                                    (0.84, 0.58, 0.46, mid, 0.62)]:
        cx = (fx + rng.uniform(-0.05, 0.05)) * sw
        cy = (fy + rng.uniform(-0.04, 0.04)) * sh
        r = fr * sw
        fall = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * r * r)))
        canvas = canvas + (np.array(color, dtype=np.float32) - canvas) * \
            (fall[..., None] * gain)
    img = Image.fromarray(np.clip(canvas, 0, 255).astype("uint8"), "RGB")
    img = img.resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(w * 0.004))

    # --- 거대한 숫자. 화면 밖으로 잘려나가야 '배경'으로 읽힌다
    if motif:
        layer = Image.new("L", (w, h), 0)
        ld = ImageDraw.Draw(layer)
        size = int(h * 0.62)
        while size > 40:
            f = font(BLACK, size)
            if ld.textlength(motif, font=f) <= w * 1.55:
                break
            size -= 12
        f = font(BLACK, size)
        tw = ld.textlength(motif, font=f)
        ld.text((w * 0.52 - tw / 2, h * 0.30), motif, font=f, fill=255)
        tint = Image.new("RGB", (w, h), tuple(min(255, int(c * 1.5) + 40) for c in hot))
        img = Image.composite(Image.blend(img, tint, 0.30), img,
                              layer.point(lambda v: int(v * 0.55)))
        # 같은 글자를 한 번 더, 아주 얇은 외곽선으로 → 판화 같은 층이 생긴다
        edge = layer.filter(ImageFilter.FIND_EDGES).point(lambda v: int(v * 0.5))
        img = Image.composite(Image.new("RGB", (w, h), (255, 255, 255)), img, edge)

    # --- 얇은 괘선 구조
    grid = Image.new("RGB", (w, h), (0, 0, 0))
    gd = ImageDraw.Draw(grid)
    step = int(h * 0.032)
    for i in range(h // step + 1):
        gd.line((0, i * step, w, i * step), fill=(255, 255, 255), width=max(1, w // 1000))
    img = Image.blend(img, Image.blend(img, grid, 1.0), 0.045)

    # --- 비네팅 + 그레인
    vy, vx = np.mgrid[0:h, 0:w].astype(np.float32)
    dd = np.sqrt(((vx - w / 2) / (w / 2)) ** 2 + ((vy - h / 2) / (h / 2)) ** 2)
    vig = np.clip(1.0 - 0.55 * np.clip(dd - 0.30, 0, None) ** 1.5, 0.28, 1.0)
    arr = np.asarray(img).astype(np.float32) * vig[..., None]
    img = Image.fromarray(np.clip(arr, 0, 255).astype("uint8"), "RGB")
    return Image.blend(img, _grain((w, h)).convert("RGB"), 0.06)


def motif_from(item: dict, h: dict | None = None) -> str:
    """표지 배경에 깔 '거대한 숫자'를 고른다. 숫자가 없으면 짧은 단어로 대체."""
    import re
    pool = [(h or {}).get("badge", ""), item.get("price", "")] + \
           [ln for ln in ((h or {}).get("big") or [])]
    for src in pool:
        m = re.search(r"[0-9][0-9,\.]*\s*(원|%|배|분|km|kWh|개월|시간|장|회|년)?", str(src))
        if m and m.group(0).strip():
            return m.group(0).strip()
    return (item.get("price") or "")[:6]


def load_cover(root, item_id: str, w: int, h: int, seed: str,
               motif: str = "") -> Image.Image:
    """assets/covers 에 사진이 있으면 그걸 꽉 채워 쓰고, 없으면 생성 배경을 쓴다."""
    from pathlib import Path
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        p = Path(root) / COVER_DIR / f"{item_id}{ext}"
        if p.exists():
            src = Image.open(p).convert("RGB")
            scale = max(w / src.width, h / src.height)
            src = src.resize((int(src.width * scale) + 1, int(src.height * scale) + 1),
                             Image.LANCZOS)
            left, top = (src.width - w) // 2, (src.height - h) // 2
            return src.crop((left, top, left + w, top + h))
    return hero_background(w, h, seed, motif)


def scrim(img: Image.Image, start: float = 0.30, strength: float = 0.92,
          color=(0, 0, 0)) -> Image.Image:
    """아래쪽으로 갈수록 어두워지는 막. 사진 위 글자가 읽히게 하는 장치."""
    import numpy as np
    w, h = img.size
    t = np.clip((np.arange(h, dtype=np.float32) / h - start) / (1 - start), 0, 1) ** 1.35
    a = (t * strength)[:, None, None]
    arr = np.asarray(img).astype(np.float32)
    out = arr * (1 - a) + np.array(color, dtype=np.float32) * a
    return Image.fromarray(np.clip(out, 0, 255).astype("uint8"), "RGB")
