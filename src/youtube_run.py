"""
이미 인스타에 나간 편을 유튜브 쇼츠로 '따라 올리는' 백필 도구.

왜 따로 있나
  평소 발행(src/run.py)은 릴스를 만든 그 자리에서 같은 mp4 를 쇼츠로도 올린다.
  플랫폼별 성장 비교가 목적이라 **같은 편이 같은 날 양쪽에 올라가야** 한다.

  그런데 유튜브를 나중에 붙였으니, 이미 인스타에만 나간 편들이 남는다.
  채널에 영상이 하나도 없으면 들어온 사람이 그냥 나간다. 그 구멍을 메우는 게
  이 스크립트다. 한 번 쓰고 끝나는 게 아니라, 카드뉴스로만 나간 편(=릴스 없음)을
  나중에 영상으로 만들어 올릴 때도 쓴다.

무엇을 고르나
  content/posted.json 에 있고(=인스타에 이미 나갔고)
  content/delivery.json 에 youtube 기록이 없는 편을 오래된 순으로.
  발행 원장 키는 run.py 와 같은 'youtube' 라서 같은 편을 두 번 올리지 않는다.

  python -m src.youtube_run --dry-run          # 영상만 만들어 텔레그램으로 확인
  python -m src.youtube_run --count 3          # 3편 백필
  python -m src.youtube_run --id 004-ott-stack # 특정 편
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import codex_bridge, hooks, notify, youtube      # noqa: E402
from src.reel import build_reel_for                       # noqa: E402
from src.render import render_item                        # noqa: E402
from src.run import (DELIVERY, POSTED, PREVIEW, QUEUE,     # noqa: E402
                     build_caption, deliver_once)

GAP_MIN = int(os.getenv("YT_BACKFILL_GAP_MIN", "5"))


def uploaded_ids() -> set[str]:
    if not DELIVERY.exists():
        return set()
    ledger = json.loads(DELIVERY.read_text(encoding="utf-8"))
    return {k for k, ops in ledger.items()
            if ops.get("youtube", {}).get("status") in ("done", "in_flight")}


def posted_ids() -> list[str]:
    """인스타에 나간 순서대로. 같은 편이 여러 번 있으면 첫 기록만."""
    if not POSTED.exists():
        return []
    seen, out = set(), []
    for p in json.loads(POSTED.read_text(encoding="utf-8")):
        if p["id"] not in seen:
            seen.add(p["id"])
            out.append(p["id"])
    return out


def candidates(queue: dict, source: str = "all") -> list[dict]:
    """유튜브에 올릴 수 있는 편들을 '인스타에 나간 순서'로.

    콘텐츠가 두 군데(queue.yaml, codex/content.json)라 둘 다 훑는다.
    한쪽만 보면 GPT 트랙 편들이 통째로 빠져 채널에 구멍이 생긴다.
    """
    done = uploaded_ids()
    out: list[dict] = []

    if source in ("all", "queue"):
        by_id = {i["id"]: i for i in queue["items"]}
        for pid in posted_ids():
            if pid in by_id and pid not in done:
                out.append(by_id[pid])

    if source in ("all", "codex"):
        for it in codex_bridge.load_items(only_published=True):
            if it["id"] not in done:
                out.append(it)

    return out


def pick(queue: dict, want: str = "", count: int = 1,
         source: str = "all") -> list[dict]:
    if want:
        pool = {i["id"]: i for i in queue["items"]}
        pool.update({i["id"]: i for i in codex_bridge.load_items(only_published=False)})
        if want not in pool:
            print(f"[stop] '{want}' 를 두 콘텐츠 목록 어디서도 찾을 수 없습니다")
            return []
        return [pool[want]]
    return candidates(queue, source)[:count]


def upload_one(item: dict, queue: dict, dry_run: bool) -> bool:
    brand = item.get("brand") or queue.get("brand", "돈값하나?")
    handle = queue.get("handle", "@dongabhana")
    cta = queue.get("cta") or {}
    h = hooks.resolve(item)

    outdir = PREVIEW / item["id"]
    paths = render_item(item, outdir, brand, handle, cta)
    mp4 = outdir / f"{item['id']}.mp4"
    _, note = build_reel_for(item, paths, mp4, brand, handle)

    title = youtube.build_title(item, h)
    # codex 편은 캡션에 해시태그까지 이미 들어 있다. build_caption 을 태우면
    # 꼬리말과 태그가 두 번 붙는다.
    caption = (item["caption"] if item.get("source") == "codex"
               else build_caption(item, cta))
    desc = youtube.build_description(item, caption, handle)
    size = mp4.stat().st_size / 1024 / 1024
    print(f"[shorts] {item['id']} · {note} ({size:.2f}MB)")
    print(f"[title ] {title}")

    if dry_run:
        if notify.enabled():
            try:
                notify.send_video(mp4, f"🔴 쇼츠 검토용 · {title}")
            except Exception as e:                                # noqa: BLE001
                print(f"[telegram] 전송 실패: {e}")
        return True

    if notify.enabled() and os.getenv("APPROVAL_REQUIRED", "1") == "1":
        answer = notify.ask(item["id"], f"유튜브 쇼츠 · {title}", desc, video=mp4)
        if answer is not True:
            print("[stop] " + ("반려됨" if answer is False else "승인 응답 없음")
                  + " → 올리지 않습니다")
            return False

    vid = deliver_once(item["id"], "youtube", lambda: youtube.upload_short(
        mp4, title, desc, youtube.build_tags(item)))
    privacy = youtube.resolve_privacy()
    print(f"[youtube] {youtube.watch_url(vid)} (공개상태 {privacy})")
    if privacy != "public":
        print("[youtube] ※ 심사 통과 전이라 비공개입니다. 통과 후 공개로 바꾸세요.")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default="", help="특정 편만")
    ap.add_argument("--count", type=int, default=1, help="몇 편 백필할지")
    ap.add_argument("--source", default="all", choices=["all", "queue", "codex"],
                    help="어느 콘텐츠 목록에서 고를지 (기본 all)")
    ap.add_argument("--list", action="store_true",
                    help="올릴 수 있는 편 목록만 보여주고 끝낸다")
    ap.add_argument("--dry-run", action="store_true",
                    help="올리지 않고 영상만 만들어 텔레그램으로 확인")
    args = ap.parse_args()

    queue = hooks.attach(yaml.safe_load(QUEUE.read_text(encoding="utf-8")))

    if args.list:
        rows = candidates(queue, args.source)
        done = uploaded_ids()
        print(f"이미 유튜브에 올림: {len(done)}편")
        print(f"올릴 수 있는 편: {len(rows)}편\n")
        for n, it in enumerate(rows, 1):
            src = "codex" if it.get("source") == "codex" else "queue"
            print(f"  {n:2}. [{src:5}] {it['id']:24} {it.get('product', '')}")
        return 0

    if not args.dry_run and not youtube.configured():
        print("[stop] 유튜브 인증정보가 없습니다 (YT_* 또는 YOUTUBE_TOKEN_JSON)")
        return 0

    items = pick(queue, args.id, max(1, args.count), args.source)
    if not items:
        print("[stop] 유튜브에 올릴 편이 없습니다 (이미 다 올렸거나 발행 이력이 없음)")
        return 0

    print(f"[backfill] {len(items)}편: {', '.join(i['id'] for i in items)}")
    for n, item in enumerate(items):
        if n and not args.dry_run:
            print(f"[backfill] {GAP_MIN}분 대기")
            time.sleep(GAP_MIN * 60)
        if not upload_one(item, queue, args.dry_run):
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
