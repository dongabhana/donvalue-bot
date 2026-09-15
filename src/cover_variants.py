from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

# 표지 사진 규칙 (2026-09-15)
#   주제와 '직접' 맞는 사진이 있을 때만 쓴다. 대충 비슷한 사진을 깔면 정수기 편에
#   세제 사진이, 헬스장 편에 등산 배낭 사진이 깔린다. 무엇에 대한 글인지 흐려진다.
#   맞는 사진이 없으면 여기서 아예 빼고, 코드가 만든 배경(팔레트 + 거대한 숫자)으로
#   가게 둔다. 사진 없는 표지가 엉뚱한 사진이 붙은 표지보다 낫다.
#   편 전용 사진은 assets/covers/<편id>.jpg 로 넣으면 이 표보다 우선한다.
#
# 가진 사진이 실제로 무엇인지 (2026-09-15 눈으로 확인):
#   appliance=에어프라이어·오븐 / bike=자전거 / cafe=테이크아웃컵 / camera=카메라
#   coupon=장바구니·영수증 / desk=책상·모니터 / food=도시락 / hobby=등산배낭·등산화
#   household=세제·수납함 / laptop=노트북 / parking=주차장의 차 / refill=청소용품
#   robot=로봇청소기 / subscription=폰·이어폰 / taxi=야간 도로의 택시 / travel=캐리어·침대
PHOTO_RECIPES = {
    "001-coupang-wow": ("coupon-photo-v1.jpg", "household-photo-v2.jpg"),
    "004-ott-stack": ("subscription-photo-v2.jpg", "camera-photo-v2.jpg"),
    "005-mvno": ("subscription-photo-v2.jpg", "laptop-photo-v1.jpg"),
    "006-car-tco": ("parking-photo-v2.jpg", "travel-photo-v2.jpg"),
    "007-dishwasher": ("appliance-photo-v2.jpg", "household-photo-v2.jpg"),
    "008-commute-vs-rent": ("travel-photo-v2.jpg", "desk-photo-v2.jpg"),
    "009-certificate": ("desk-photo-v2.jpg", "laptop-photo-v1.jpg"),
    "010-coffee": ("cafe-photo-v2.jpg", "food-photo-v2.jpg"),
    "011-ai-subscription": ("laptop-photo-v1.jpg", "camera-photo-v2.jpg"),
    "012-youtube-premium": ("camera-photo-v2.jpg", "subscription-photo-v2.jpg"),
    "013-airpods-vs-cheap": ("subscription-photo-v2.jpg", "camera-photo-v2.jpg"),
    "014-delivery-vs-pickup": ("food-photo-v2.jpg", "cafe-photo-v2.jpg"),
    "015-card-annual-fee": ("desk-photo-v2.jpg", "coupon-photo-v1.jpg"),
    "016-office-chair": ("desk-photo-v2.jpg", "household-photo-v2.jpg"),
    "017-premium-gas": ("parking-photo-v2.jpg", "taxi-photo-v1.jpg"),
    "018-mvno-vs-5g": ("subscription-photo-v2.jpg", "laptop-photo-v1.jpg"),
    "019-dryer": ("appliance-photo-v2.jpg", "food-photo-v2.jpg"),
    "020-starbucks-vs-mega": ("cafe-photo-v2.jpg", "travel-photo-v2.jpg"),
    "021-ott-bundle": ("subscription-photo-v2.jpg", "laptop-photo-v1.jpg"),
    "022-aircon-90min": ("appliance-photo-v2.jpg", "household-photo-v2.jpg"),
    "023-card-golden-ratio": ("coupon-photo-v1.jpg", "desk-photo-v2.jpg"),
    "024-choice-discount": ("subscription-photo-v2.jpg", "coupon-photo-v1.jpg"),
    "025-mileage-rider": ("parking-photo-v2.jpg", "taxi-photo-v1.jpg"),
    "026-energy-cashback": ("appliance-photo-v2.jpg", "travel-photo-v2.jpg"),
}


def _seed(item_id: str) -> int:
    return int(hashlib.sha1(item_id.encode("utf-8")).hexdigest()[:8], 16)


def _cover_crop(src: Image.Image, w: int, h: int, seed: int, variant: int) -> Image.Image:
    src = src.convert("RGB")
    zoom = 1.05 + ((seed >> (variant * 3)) & 7) * 0.018
    scale = max(w / src.width, h / src.height) * zoom
    rw, rh = int(src.width * scale) + 2, int(src.height * scale) + 2
    src = src.resize((rw, rh), Image.LANCZOS)

    spare_x, spare_y = max(0, rw - w), max(0, rh - h)
    x_bias = ((seed >> 5) & 255) / 255.0
    y_bias = ((seed >> 13) & 255) / 255.0
    # Feed (4:5) and video (9:16) deliberately use different vertical framing.
    y_bias = (0.24 + y_bias * 0.34) if h / w > 1.5 else (0.30 + y_bias * 0.38)
    left, top = int(spare_x * x_bias), int(spare_y * y_bias)
    out = src.crop((left, top, left + w, top + h))
    if ((seed >> (19 + variant)) & 1) == 1:
        out = ImageOps.mirror(out)
    return out


def _grade(img: Image.Image, seed: int) -> Image.Image:
    img = ImageEnhance.Contrast(img).enhance(1.02 + ((seed >> 2) & 7) * 0.018)
    img = ImageEnhance.Color(img).enhance(0.92 + ((seed >> 8) & 7) * 0.025)
    img = ImageEnhance.Brightness(img).enhance(0.94 + ((seed >> 14) & 7) * 0.012)
    return img


def _edge_mask(w: int, h: int, seed: int) -> Image.Image:
    edge = seed % 4
    strength = (64 + seed % 28) / 255.0
    if edge in (0, 2):
        axis = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
        t = np.clip(1.0 - axis / 0.46, 0, 1) if edge == 0 else np.clip((axis - 0.54) / 0.46, 0, 1)
        arr = np.repeat(t, w, axis=1)
    else:
        axis = np.linspace(0.0, 1.0, w, dtype=np.float32)[None, :]
        t = np.clip((axis - 0.54) / 0.46, 0, 1) if edge == 1 else np.clip(1.0 - axis / 0.46, 0, 1)
        arr = np.repeat(t, h, axis=0)
    arr = np.clip(255.0 * strength * np.power(arr, 1.7), 0, 255).astype("uint8")
    return Image.fromarray(arr, "L")


def render_variant(root: str, item_id: str, w: int, h: int) -> Image.Image | None:
    recipe = PHOTO_RECIPES.get(item_id)
    if not recipe:
        return None
    seed = _seed(item_id)
    cover_dir = Path(root) / "assets" / "covers"
    p1, p2 = cover_dir / recipe[0], cover_dir / recipe[1]
    if not p1.exists():
        return None

    with Image.open(p1) as im1:
        base = _grade(_cover_crop(im1, w, h, seed, 0), seed)
    if not p2.exists():
        return base

    with Image.open(p2) as im2:
        second = _cover_crop(im2, w, h, seed ^ 0x5A17C9E3, 1)
    second = second.filter(ImageFilter.GaussianBlur(max(2, int(w * 0.004))))
    return Image.composite(second, base, _edge_mask(w, h, seed))


def install(theme_module) -> None:
    original = theme_module.load_cover

    def load_cover(root, item_id: str, w: int, h: int, seed: str, motif: str = ""):
        custom = render_variant(root, item_id, w, h)
        if custom is not None:
            return custom
        return original(root, item_id, w, h, seed, motif)

    theme_module.load_cover = load_cover
