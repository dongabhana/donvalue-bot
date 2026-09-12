"""
텔레그램 알림 · 발행 승인.

왜 텔레그램인가
  카카오 알림톡/친구톡은 사업자 등록 + 채널 + 발신프로필 심사가 필요하고,
  '나에게 보내기' API 는 답장을 받을 수 없어 승인 용도로는 못 쓴다.
  텔레그램 봇은 무료·즉시 발급이고 버튼 응답까지 받을 수 있어 이 용도에 맞는다.

동작
  1) 발행 직전에 렌더 결과(릴스 mp4 또는 카드 2장)와 캡션 전문을 보낸다
  2) [발행] / [건너뛰기] 버튼을 붙인다
  3) 버튼(또는 'ok' / 'no' 텍스트)을 기다린다
  4) 승인 → 발행 / 반려 → 큐를 소진하지 않고 종료 / 무응답 → 종료

무응답일 때 발행하지 않는 이유
  자동 발행의 사고는 대부분 '잘못된 내용이 그대로 나가는 것'이다.
  답이 없으면 안 내보내는 쪽이 복구 비용이 훨씬 싸다.

필요 환경변수
  TELEGRAM_BOT_TOKEN   @BotFather 에서 받은 토큰
  TELEGRAM_CHAT_ID     본인 chat id — 비워두면 content/telegram_owner.enc 에서 읽는다.
                       (tools/pair_telegram.py 가 페어링할 때 봇 토큰으로 암호화해 저장해 둔 값.
                        같은 봇을 쓰는 다른 워크플로와 수신자를 하나로 유지하기 위해서다.)
  APPROVAL_REQUIRED    1 이면 승인 없이는 발행하지 않음 (기본 1, 토큰 없으면 자동 통과)
  APPROVAL_TIMEOUT_MIN 기다리는 시간(분). 기본 45
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

API = "https://api.telegram.org"
TIMEOUT = 60


ROOT = Path(__file__).resolve().parent.parent
OWNER_ENC = ROOT / "content" / "telegram_owner.enc"
_owner_cache: dict = {}


def _paired_chat(token: str) -> str:
    """페어링 때 저장해 둔 chat id 를 복호화해서 읽는다.

    키는 봇 토큰에서 유도하므로 별도 시크릿이 필요 없고,
    토큰이 바뀌면 자동으로 읽히지 않는다(= 잘못된 사람에게 안 간다).
    """
    if "v" in _owner_cache:
        return _owner_cache["v"]
    _owner_cache["v"] = ""
    try:
        import base64
        import hashlib
        from cryptography.fernet import Fernet
        key = hashlib.sha256(("donvalue-owner-v1:" + token).encode()).digest()
        raw = Fernet(base64.urlsafe_b64encode(key)).decrypt(OWNER_ENC.read_bytes())
        _owner_cache["v"] = str(json.loads(raw).get("chat_id", "") or "")
    except Exception as e:                                        # noqa: BLE001
        print(f"[telegram] 페어링 정보 읽기 실패(무시): {e}")
    return _owner_cache["v"]


def _cfg() -> tuple[str, str]:
    tok = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if tok and not chat:
        chat = _paired_chat(tok)
    return tok, chat


def enabled() -> bool:
    tok, chat = _cfg()
    return bool(tok and chat)


def _call(method: str, data: dict | None = None, files: dict | None = None) -> dict:
    tok, _ = _cfg()
    r = requests.post(f"{API}/bot{tok}/{method}", data=data, files=files,
                      timeout=TIMEOUT)
    j = r.json()
    if not j.get("ok"):
        raise RuntimeError(f"telegram {method}: {j.get('description')}")
    return j["result"]


def send_message(text: str, buttons: list[list[dict]] | None = None) -> dict:
    _, chat = _cfg()
    data = {"chat_id": chat, "text": text[:4000], "disable_web_page_preview": "true"}
    if buttons:
        data["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    return _call("sendMessage", data)


def send_photos(paths: list[Path], caption: str = "") -> dict | None:
    """2장 이상이면 앨범으로, 1장이면 단일 사진으로 보낸다."""
    _, chat = _cfg()
    paths = [p for p in paths if Path(p).exists()][:10]
    if not paths:
        return None
    if len(paths) == 1:
        with open(paths[0], "rb") as f:
            return _call("sendPhoto", {"chat_id": chat, "caption": caption[:1000]},
                         {"photo": f})
    media, files = [], {}
    for i, p in enumerate(paths):
        key = f"f{i}"
        item = {"type": "photo", "media": f"attach://{key}"}
        if i == 0 and caption:
            item["caption"] = caption[:1000]
        media.append(item)
        files[key] = open(p, "rb")
    try:
        return _call("sendMediaGroup",
                     {"chat_id": chat, "media": json.dumps(media)}, files)
    finally:
        for f in files.values():
            f.close()


def send_video(path: Path, caption: str = "") -> dict | None:
    _, chat = _cfg()
    if not Path(path).exists():
        return None
    with open(path, "rb") as f:
        return _call("sendVideo",
                     {"chat_id": chat, "caption": caption[:1000],
                      "supports_streaming": "true"}, {"video": f})


# ------------------------------------------------------------------ 승인
def _drain_offset() -> int:
    """기다리기 전에 예전 응답을 비운다. 지난번 'ok' 가 이번 발행을 통과시키면 안 된다."""
    try:
        ups = _call("getUpdates", {"timeout": 0})
    except Exception:                                             # noqa: BLE001
        return 0
    return (ups[-1]["update_id"] + 1) if ups else 0


def ask(item_id: str, title: str, body: str,
        video: Path | None = None, photos: list[Path] | None = None,
        timeout_min: int | None = None) -> bool | None:
    """발행 승인을 묻는다. True=승인 / False=반려 / None=무응답.

    반환이 True 가 아니면 호출부는 발행하지 않고 큐도 소진하지 않아야 한다.
    """
    if not enabled():
        return True                                   # 설정이 없으면 승인 단계를 건너뛴다

    # 검수는 '나갈 것 전부'를 봐야 의미가 있다.
    # 호출부가 표지·결론만 넘겨도 같은 폴더의 나머지 장을 모아 전체를 보낸다.
    if photos:
        try:
            folder = Path(photos[0]).parent
            allp = sorted(p for p in folder.glob("*.png"))
            if len(allp) > len(photos):
                photos = allp
        except Exception:                                         # noqa: BLE001
            pass

    wait = int(timeout_min if timeout_min is not None
               else os.getenv("APPROVAL_TIMEOUT_MIN", "45"))
    offset = _drain_offset()

    head = f"🗂 {title}\n<{item_id}>"
    try:
        if video:
            send_video(video, head)
        elif photos:
            send_photos(photos, head)
        else:
            send_message(head)
        send_message(body[:3500])
    except Exception as e:                                        # noqa: BLE001
        print(f"[telegram] 미리보기 전송 실패: {e}")

    ok_data, no_data = f"ok:{item_id}", f"no:{item_id}"
    send_message(
        f"이대로 발행할까요?  ({wait}분 안에 응답이 없으면 발행하지 않습니다)",
        buttons=[[{"text": "✅ 발행", "callback_data": ok_data},
                  {"text": "✋ 건너뛰기", "callback_data": no_data}]])

    deadline = time.time() + wait * 60
    while time.time() < deadline:
        try:
            ups = _call("getUpdates", {"offset": offset, "timeout": 30})
        except Exception as e:                                    # noqa: BLE001
            print(f"[telegram] 응답 확인 실패(재시도): {e}")
            time.sleep(10)
            continue
        for u in ups:
            offset = u["update_id"] + 1
            cq = u.get("callback_query")
            if cq:
                data = cq.get("data", "")
                try:
                    _call("answerCallbackQuery",
                          {"callback_query_id": cq["id"],
                           "text": "발행합니다" if data == ok_data else "건너뜁니다"})
                except Exception:                                 # noqa: BLE001
                    pass
                if data == ok_data:
                    return True
                if data == no_data:
                    return False
                continue
            text = ((u.get("message") or {}).get("text") or "").strip().lower()
            if text in ("ok", "o", "ㅇ", "발행", "승인", "/ok"):
                return True
            if text in ("no", "n", "ㄴ", "취소", "건너뛰기", "/no"):
                return False
    return None


def done(item_id: str, product: str, results: dict, errors: list[str]) -> None:
    """발행 결과 통보. 실패도 반드시 알려야 다음 회차 전에 손을 쓸 수 있다."""
    if not enabled():
        return
    lines = [f"{'✅' if results else '❌'} {product}  <{item_id}>"]
    for k, v in results.items():
        lines.append(f"· {k}: {v}")
    for e in errors:
        lines.append(f"⚠ {e}")
    if "instagram_reel" in results or "instagram" in results:
        lines.append("https://www.instagram.com/dongabhana/")
    try:
        send_message("\n".join(lines))
    except Exception as e:                                        # noqa: BLE001
        print(f"[telegram] 결과 통보 실패: {e}")


if __name__ == "__main__":
    import sys
    if not enabled():
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 설정되지 않았습니다.")
        raise SystemExit(1)
    print(send_message(sys.argv[1] if len(sys.argv) > 1 else "테스트 메시지입니다."))
