"""
전날 승인 원장.

왜 원장이 필요한가
  승인을 물어보는 실행(발행 전날 20:00)과 실제로 발행하는 실행(당일 20:00)이
  서로 다른 GitHub Actions 런이다. 런끼리는 메모리를 공유하지 않으므로
  "어제 승인받았다"는 사실을 저장소에 남겨야 다음 날 실행이 읽을 수 있다.

왜 지문(fingerprint)까지 저장하는가
  승인한 것과 다른 것이 나가면 승인의 의미가 없다. 캡션·쓰레드 본문·실제
  렌더 파일(png, mp4)의 해시를 묶어 지문을 만들고, 발행 직전에 다시 계산해
  일치할 때만 전날 승인을 인정한다. 한 글자라도 바뀌면 그 자리에서 다시 묻는다.

원장 형식 (content/approval.json)
  {
    "003-gym-annual": {
      "decision": "approved" | "revise" | "pending",
      "ig_format": "reel",
      "publish_date": "2026-09-16",     # 이 승인이 유효한 발행일 (KST)
      "fingerprint": "3f2a...",
      "asked_at": "2026-09-15T20:00:11+09:00",
      "decided_at": "2026-09-15T20:04:02+09:00",
      "note": "썸네일 금액 키워줘"       # '수정' 을 눌렀을 때 이어서 보낸 메시지
    }
  }
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "content" / "approval.json"
KST = timezone(timedelta(hours=9))

APPROVED = "approved"
REVISE = "revise"
PENDING = "pending"


def load() -> dict:
    if not LEDGER.exists():
        return {}
    try:
        data = json.loads(LEDGER.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        # 원장이 깨졌는데 빈 dict 로 넘어가면 '승인 없음'이 되어 조용히 발행이 멈춘다.
        # 조용한 실패보다 시끄러운 실패가 낫다.
        raise RuntimeError(f"content/approval.json 을 읽을 수 없습니다: {e}") from e
    return data if isinstance(data, dict) else {}


def save(ledger: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")


def _file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(item_id: str, ig_format: str, caption: str, threads_text: str,
                files) -> str:
    """승인 대상 전체를 한 값으로 묶는다.

    파일은 이름순으로 정렬해 넣는다. 렌더 순서가 바뀌어도 내용이 같으면
    같은 지문이 나와야 하기 때문이다.
    """
    h = hashlib.sha256()
    h.update(("id:" + item_id).encode("utf-8"))
    h.update(("\nformat:" + (ig_format or "")).encode("utf-8"))
    h.update(("\ncaption:" + (caption or "")).encode("utf-8"))
    h.update(("\nthreads:" + (threads_text or "")).encode("utf-8"))
    for p in sorted((Path(f) for f in files if f), key=lambda p: p.name):
        if not p.exists():
            continue
        h.update(("\nfile:" + p.name + ":" + _file_digest(p)).encode("utf-8"))
    return h.hexdigest()


def publish_date_for(asked_at: datetime | None = None) -> str:
    """'전날 물어본다'는 규칙에 따라, 지금 묻는 건에 대응하는 발행일(내일)."""
    now = asked_at or datetime.now(KST)
    return (now.date() + timedelta(days=1)).isoformat()


def record(item_id: str, decision: str, ig_format: str, digest: str,
           publish_date: str, note: str = "") -> dict:
    ledger = load()
    entry = ledger.get(item_id, {})
    now = datetime.now(KST).isoformat(timespec="seconds")
    entry.update({
        "decision": decision,
        "ig_format": ig_format,
        "publish_date": publish_date,
        "fingerprint": digest,
        "asked_at": entry.get("asked_at") or now,
    })
    if decision != PENDING:
        entry["decided_at"] = now
    if note:
        entry["note"] = note
    ledger[item_id] = entry
    save(ledger)
    return entry


def lookup(item_id: str, today: str | None = None) -> dict | None:
    """오늘 발행분으로 유효한 원장 항목. 날짜가 다르면 없는 것으로 본다.

    날짜를 보는 이유: 지난주에 승인해 둔 항목이 이번 주 발행을 그냥 통과시키면
    안 된다. 승인은 '바로 다음 발행일 1회'에만 쓰인다.
    """
    today = today or datetime.now(KST).date().isoformat()
    entry = load().get(item_id)
    if not entry:
        return None
    if entry.get("publish_date") != today:
        return None
    return entry


def consume(item_id: str) -> None:
    """발행에 쓴 승인은 원장에서 지운다. 같은 승인이 두 번 통하면 중복 발행이 된다."""
    ledger = load()
    if ledger.pop(item_id, None) is not None:
        save(ledger)
