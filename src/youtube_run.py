"""다음 검수 완료 콘텐츠를 음성 쇼츠로 만들어 승인 후 유튜브에 올린다."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import yaml

from src import hooks, notify, voice, youtube
from src.render import render_item
from src.reel import build_reel_for
from src.run import DELIVERY, IMAGES, KST, QUEUE, deliver_once


def already_uploaded(item_id: str) -> bool:
    if not DELIVERY.exists():
        return False
    ledger = json.loads(DELIVERY.read_text(encoding="utf-8"))
    return ledger.get(item_id, {}).get("youtube_short", {}).get("status") == "done"


def choose(queue: dict, item_id: str | None) -> dict | None:
    for item in queue["items"]:
        if item_id and item["id"] != item_id:
            continue
        if item.get("verified") and not already_uploaded(item["id"]):
            return item
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    queue = hooks.attach(yaml.safe_load(QUEUE.read_text(encoding="utf-8")))
    item = choose(queue, args.id)
    if not item:
        print("[stop] 유튜브에 올릴 검수 완료 콘텐츠가 없습니다")
        return 0

    brand = item.get("brand") or queue.get("brand", "돈값하나?")
    handle = queue.get("handle", "@dongabhana")
    outdir = IMAGES / item["id"]
    paths = render_item(item, outdir, brand, handle, queue.get("cta") or {})
    silent = outdir / f"{item['id']}-bgm.mp4"
    speech = outdir / f"{item['id']}-voice.mp3"
    final = outdir / f"{item['id']}-short.mp4"
    build_reel_for(item, paths, silent, brand, handle)
    _, script = voice.synthesize(item, speech)
    voice.mix_into_video(silent, speech, final)
    title, description = youtube.metadata(item)
    print(f"[shorts] {title} · {final.stat().st_size / 1024 / 1024:.2f}MB")
    print(f"[voice] {script}")

    if args.dry_run:
        if notify.enabled():
            notify.send_video(final, f"[쇼츠 검토용] {title}")
        return 0

    if notify.enabled() and os.getenv("APPROVAL_REQUIRED", "1") == "1":
        answer = notify.ask(item["id"], f"유튜브 쇼츠 · {title}", description, video=final)
        if answer is not True:
            print("[stop] 승인되지 않아 업로드하지 않습니다")
            return 0

    video_id = deliver_once(item["id"], "youtube_short", lambda: youtube.upload_short(
        final, title, description))
    notify.done(item["id"], title, {"youtube_short": video_id}, [])
    print(f"[youtube] https://youtu.be/{video_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
