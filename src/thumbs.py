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
  - 2026-10-05 추가: 영상 장면이 아니라 표지 이미지를 올린다. 캠페인 이전 편은
    cover.jpg 가 없으므로 make_cover() 가 인스타 1장과 같은 표지를 만들어 쓴다.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

KEY = "youtube_thumbnail"
RETRY_GAP = timedelta(hours=6)
MAX_TRIES = 8
WINDOW = timedelta(days=45)      # 이보다 오래된 편은 다시 손대지 않는다


def _parse(at: str):
    try:
        return datetime.fromisoformat(at)
    except (TypeError, ValueError):
        return None


def cover_path(root: Path, item_id: str) -> Path:
    return Path(root) / "images" / item_id / "cover.jpg"


def _pad_vertical(img):
    """4:5 카드 표지를 쇼츠 썸네일(9:16) 캔버스 가운데에 놓는다."""
    from PIL import Image
    img = img.convert("RGB")
    if img.size[0] != 1080:
        img = img.resize((1080, round(img.size[1] * 1080 / img.size[0])))
    canvas = Image.new("RGB", (1080, 1920), "#111614")
    canvas.paste(img, (0, max(0, (1920 - img.size[1]) // 2)))
    return canvas


def make_cover(root: Path, item_id: str):
    """표지 이미지를 찾거나 만든다. 없으면 None.

    2026-10-05 소유자 지적: 영상에서 고른 장면 말고 '표지'가 썸네일이어야 한다.
    순서: ① images/<id>/cover.jpg (캠페인 편, 발행 때 만든 그대로)
          ② codex 편 — 인스타 1장과 같은 렌더러로 표지를 다시 그린다
          ③ 예전 큐 편 — 인스타에 올라간 1장(images/<id>/<id>_01.png)
    ②·③은 .preview/thumbs/<id>.jpg 로 저장해 쓴다(저장소에는 커밋하지 않음).
    """
    root = Path(root)
    own = cover_path(root, item_id)
    if own.is_file():
        return own
    out = root / ".preview" / "thumbs" / f"{item_id}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    img = None
    content = root / "codex" / "content.json"
    if content.is_file():
        data = json.loads(content.read_text(encoding="utf-8"))
        items = data.get("items", data) if isinstance(data, dict) else data
        item = next((i for i in items if i.get("id") == item_id), None)
        if item and item.get("slides"):
            from codex import media
            if item.get("cover_photo"):
                img = media.photographic_cover(item, item["slides"][0], reel=True)
            else:
                from PIL import Image
                made = media.render(item, root)
                img = _pad_vertical(Image.open(root / made["cards"][0]))
    card = root / "images" / item_id / f"{item_id}_01.png"
    if img is None and card.is_file():
        from PIL import Image
        img = _pad_vertical(Image.open(card))
    if img is None:
        return None
    img.convert("RGB").save(out, "JPEG", quality=90)
    return out


def has_cover_source(root: Path, item_id: str) -> bool:
    """표지를 만들 재료가 있는가(만들지는 않는다)."""
    root = Path(root)
    if cover_path(root, item_id).is_file() or (root / "images" / item_id / f"{item_id}_01.png").is_file():
        return True
    content = root / "codex" / "content.json"
    if not content.is_file():
        return False
    data = json.loads(content.read_text(encoding="utf-8"))
    items = data.get("items", data) if isinstance(data, dict) else data
    return any(i.get("id") == item_id and i.get("slides") for i in items)


def due(item_id: str, ops: dict, root: Path, now: datetime) -> bool:
    """이 편에 썸네일을 (다시) 걸어야 하는가."""
    yt = ops.get("youtube") or {}
    if yt.get("status") != "done" or not yt.get("id"):
        return False
    if not has_cover_source(root, item_id):
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
        try:
            cover = make_cover(ROOT, item_id)
        except Exception as e:                                    # noqa: BLE001
            cover, why = None, f"표지 만들기 실패: {e}"
        else:
            why = "표지 재료 없음"
        if cover is None:
            row = record(ledger, item_id, False, why, now)
        else:
            row = apply(item_id, vid, cover, ledger, now, setter)
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
