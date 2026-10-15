"""추천템 편 제품 사진을 다이소몰 공식 상품 이미지에서 받아 assets/products/ 에 둔다.

2026-10-15 소유자 결정: 직접 촬영 대신 다이소몰 상품 대표 이미지를 쓰고, 화면·캡션에
'사진 다이소몰' 출처를 적는다. 고객 리뷰 사진은 각 작성자의 것이라 쓰지 않는다(대표 이미지만).

Claude 작업 환경에서는 다이소몰 CDN 이 막혀 있어 GitHub Actions(product-photos.yml)에서 돌린다.
이미 있는 파일은 건너뛴다(--force 로 다시 받음). 발행된 편은 다시 올라가지 않으니 바꿔도 피드에 영향 없음.
"""
import io
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image                      # noqa: E402
from codex.campaign_first10 import PHOTOS  # noqa: E402

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/128.0 Safari/537.36')


def fetch(url: str, referer: str) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Referer': referer,
                                               'Accept': 'image/avif,image/webp,image/*,*/*;q=0.8'})
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status != 200:
            raise RuntimeError(f'{url}: HTTP {r.status}')
        return r.read()


def main(force: bool = False) -> int:
    bad = 0
    for key, sp in sorted(PHOTOS.items()):
        dest = ROOT / sp['file']
        if dest.is_file() and not force:
            print(f'[photo] {key} 있음 — 건너뜀 ({dest.name})')
            continue
        try:
            raw = fetch(sp['source_url'], sp['source_page'])
            im = Image.open(io.BytesIO(raw)).convert('RGB')
            if min(im.size) < 600:
                raise RuntimeError(f'사진이 너무 작음 {im.size}')
            dest.parent.mkdir(parents=True, exist_ok=True)
            im.save(dest, 'JPEG', quality=92, optimize=True)
            print(f'[photo] {key} 저장 {dest.relative_to(ROOT)} {im.size} {dest.stat().st_size // 1024}KB')
        except Exception as e:                       # noqa: BLE001
            bad += 1
            print(f'[photo] {key} 실패: {e}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main('--force' in sys.argv))
