"""유튜브 쇼츠 썸네일을 표지(images/<id>/cover.jpg)로 맞춘다.

2026-10-05 소유자 요청: "앞으로는 무조건 썸네일 잘 잡게".
  - 그동안 thumbnails.set 이 매번 403 이었다. 원인은 채널 전화 인증이 안 된 것.
    10/5 인증을 마쳐 스튜디오에 '파일 업로드/동영상에서 선택'이 열렸다.
  - 유튜브는 맞춤 썸네일이 없으면 영상 중간·끝 장면(좋아요+구독 화면 등)을
    자동으로 고른다. 그래서 채널 목록이 제각각으로 보였다.

동작
  - 발행 직후(src/campaign.py) 한 번 걸고 결과를 원장(content/delivery.json)의
    'youtube_thumbnail' 에 남긴다.
  - 실패했거나 기록이 없는 편은 20분마다 도는 youtube-shorts.yml 이 다시 건다
    (`python -m src.thumbs`). 같은 편은 6시간에 한 번, 최대 8번까지만 시도한다
    — thumbnails.set 은 호출당 할당량 50 을 쓴다.
  - 처음 실패하면 텔레그램으로 알린다. 조용히 실패하지 않는다.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

KEY = "youtube_thumbnail"
RETRY_GAP = timedelta(hours=6)
MAX_TRIES = 8
WINDOW = timedelta(days=30)      # 이보다 오래된 편은 사람이 스튜디오에서 맞춘다


def _parse(at: str):
    try:
        return datetime.fromisoformat(at)
    except (TypeError, ValueError):
        return None


def cover_path(root: Path, item_id: str) -> Path:
    return Path(root) / "images" / item_id / "cover.jpg"


def due(item_id: str, ops: dict, root: Path, now: datetime) -> bool:
    """이 편에 썸네일을 (다시) 걸어야 하는가."""
    yt = ops.get("youtube") or {}
    if yt.get("status") != "done" or not yt.get("id"):
        return False
    if not cover_path(root, item_id).is_file():
        return False
    up = _parse(yt.get("at", ""))
    if up is None or now - up > WINDOW:
        return False
    th = ops.get(KEY) or {}
    if th.get("status") == "done":
        return False
    if int(th.get("tries", 0)) >= MAX_TRIES:
        return False
    last = _parse(th.get("at", ""))
    return last is None or now - last >= RETRY_GAP


def record(ledger: dict, item_id: str, ok: bool, error: str, now: datetime) -> dict:
    ops = ledger.setdefault(item_id, {})
    prev = ops.get(KEY) or {}
    tries = int(prev.get("tries", 0)) + 1
    row = {"status": "done" if ok else "error", "at": now.isoformat(timespec="seconds"),
           "tries": tries}
    if not ok:
        row["error"] = error[:300]
    ops[KEY] = row
    return row


def apply(item_id: str, video_id: str, cover: Path, ledger: dict, now: datetime,
          setter=None) -> dict:
    """썸네일을 걸고 원장에 결과를 적는다. 예외를 밖으로 던지지 않는다."""
    if setter is None:
        from src import youtube
        setter = youtube.set_thumbnail
    try:
        setter(video_id, cover)
        return record(ledger, item_id, True, "", now)
    except Exception as e:                                        # noqa: BLE001
        return record(ledger, item_id, False, str(e), now)


def _tell(text: str) -> None:
    from src import notify
    if not notify.enabled():
        return
    try:
        notify.send_message(text)
    except Exception as e:                                        # noqa: BLE001
        print(f"[telegram] 통보 실패: {e}")


def catch_up(limit: int = 3, setter=None) -> int:
    """기록이 없거나 실패한 편에 썸네일을 다시 건다. 건 편 수를 돌려준다."""
    from src.run import DELIVERY, KST, ROOT, push, sh
    now = datetime.now(KST)
    if not DELIVERY.exists():
        return 0
    ledger = json.loads(DELIVERY.read_text(encoding="utf-8"))
    todo = [i for i, ops in ledger.items() if isinstance(ops, dict) and due(i, ops, ROOT, now)]
    if not todo:
        print("[thumbs] 다시 걸 썸네일이 없습니다")
        return 0
    done, failed = [], []
    for item_id in todo[:limit]:
        vid = ledger[item_id]["youtube"]["id"]
        row = apply(item_id, vid, cover_path(ROOT, item_id), ledger, now, setter)
        (done if row["status"] == "done" else failed).append((item_id, row))
        print(f"[thumbs] {item_id} ({vid}) → {row['status']} {row.get('error', '')}")
    DELIVERY.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    sh("git", "add", str(DELIVERY))
    sh("git", "-c", "user.name=donvalue-bot", "-c", "user.email=bot@users.noreply.github.com",
       "commit", "-m", f"thumbs: {len(done)} done, {len(failed)} failed")
    push()
    first_fail = [f"{i}: {r.get('error', '')[:120]}" for i, r in failed if r["tries"] == 1]
    if first_fail:
        _tell("🖼 유튜브 썸네일 적용 실패 — 6시간 뒤 다시 시도합니다\n" + "\n".join(first_fail))
    return len(done)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    catch_up()
