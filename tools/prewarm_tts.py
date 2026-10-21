"""다음에 나갈 편들의 나레이션 음성을 미리 만들어 assets/tts-cache 에 저장한다.

2026-10-21: 10/20 정기 발행이 마이크로소프트 TTS 429(요청 과다)로 실패했다. 발행 몇 시간 전에
미리 음성을 만들어 저장소에 넣어 두면, 발행 순간 TTS 서버가 막혀도 저장된 음성으로 나간다.
발행 시계(publish_clock.py)가 슬롯 전에 tts-prewarm.yml 로 돌린다. 이미 캐시에 있으면 TTS 를 부르지 않는다.

  python tools/prewarm_tts.py            # 다음 2편
  python tools/prewarm_tts.py --count 3
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import campaign  # noqa: E402


def upcoming(count: int) -> list[dict]:
    posted = {p['id'] for p in json.loads((ROOT / 'content/posted.json').read_text(encoding='utf-8'))}
    out = []
    seen = set(posted)
    for _ in range(count):
        item, _ = campaign.next_ready(seen)
        if not item:
            break
        out.append(item)
        seen.add(item['id'])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--count', type=int, default=2)
    a = ap.parse_args()
    b = campaign.builder()
    before = {p.name for p in b.TTS_CACHE.glob('*.mp3')} if b.TTS_CACHE.exists() else set()
    bad = 0
    for item in upcoming(a.count):
        try:
            with tempfile.TemporaryDirectory() as tmp:
                b.build(tmp, only=[item['id']], audio=True, video=False,
                        campaign=item.get('campaign', 'campaign27'))
            print(f"[prewarm] {item['id']} 음성 준비됨", flush=True)
        except Exception as e:                       # noqa: BLE001
            bad += 1
            print(f"[prewarm] {item['id']} 실패: {str(e)[:300]}", flush=True)
    after = {p.name for p in b.TTS_CACHE.glob('*.mp3')} if b.TTS_CACHE.exists() else set()
    print(f"[prewarm] 새 음성 {len(after - before)}개 · 캐시 {len(after)}개", flush=True)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
