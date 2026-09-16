"""
유튜브 리프레시 토큰 발급기 — 내 PC 에서 딱 한 번만 돌리면 된다.

쓰는 법
  1) Google Cloud 콘솔에서 OAuth 클라이언트를 '데스크톱 앱'으로 만든다
  2) 아래처럼 실행 (client_secret 은 콘솔에서 복사)
       python tools/get_yt_token.py --id <클라이언트ID> --secret <클라이언트보안비밀>
  3) 브라우저가 열리면 쇼츠를 올릴 유튜브 채널 계정으로 로그인·허용
  4) 화면에 찍히는 refresh_token 을 GitHub Secrets 의 YT_REFRESH_TOKEN 에 넣는다

왜 이렇게 하나
  구글이 옛날 방식(코드 복붙, OOB)을 막아서, 지금은 내 PC 에 잠깐 서버를
  띄워 인증 결과를 받는 '루프백' 방식만 된다. 이 스크립트가 그 서버다.
  포트는 비어 있는 걸 알아서 잡는다.

⚠ 토큰이 7일 만에 죽는다면
  Google Cloud 콘솔 → 'OAuth 동의 화면' 이 **테스트** 상태다.
  '앱 게시'(프로덕션)로 바꾸고 이 스크립트를 다시 돌려라.
  게시 상태에서는 리프레시 토큰이 만료되지 않는다(사용자가 취소하기 전까지).
"""
from __future__ import annotations

import argparse
import http.server
import json
import socket
import threading
from pathlib import Path
import urllib.parse
import webbrowser

import requests

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/youtube.upload"

_code: str | None = None


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):                                              # noqa: N802
        global _code
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _code = (q.get("code") or [None])[0]
        err = (q.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = "인증이 끝났습니다. 이 창을 닫고 터미널로 돌아가세요." if _code \
            else f"실패: {err}"
        self.wfile.write(f"<html><body style='font:16px sans-serif;padding:40px'>"
                         f"{msg}</body></html>".encode())

    def log_message(self, *a):                                     # 조용히
        pass


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def find_client_json() -> Path | None:
    """구글 콘솔에서 받은 client_secret_*.json 을 알아서 찾는다.

    명령줄에 ID·시크릿을 직접 타이핑하게 하면 따옴표·꺾쇠 때문에 꼭 한 번은
    틀린다. 파일만 받아두면 되게 만드는 쪽이 훨씬 덜 틀린다.
    """
    seen: list[Path] = []
    for folder in (Path.home() / "Downloads", Path.home() / "다운로드",
                   Path.cwd(), Path(__file__).resolve().parent.parent):
        try:
            seen += sorted(folder.glob("client_secret*.json"),
                           key=lambda f: f.stat().st_mtime, reverse=True)
        except OSError:
            pass
    return seen[0] if seen else None


def read_client_json(path: Path) -> tuple[str, str]:
    """데스크톱 앱 클라이언트 JSON 에서 (id, secret) 을 꺼낸다."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    block = data.get("installed") or data.get("web") or data
    cid = str(block.get("client_id", "")).strip()
    sec = str(block.get("client_secret", "")).strip()
    if not cid or not sec:
        raise SystemExit(f"[stop] {path} 에서 client_id/client_secret 을 찾지 못했습니다.")
    if "web" in data and "installed" not in data:
        print("[warn] 이 클라이언트는 '웹 애플리케이션' 유형입니다. "
              "루프백 방식이 막힐 수 있어요. '데스크톱 앱'으로 새로 만드는 걸 권합니다.\n")
    return cid, sec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="구글 콘솔에서 받은 client_secret_*.json 경로 "
                                   "(비우면 다운로드 폴더에서 자동으로 찾습니다)")
    ap.add_argument("--id", help="OAuth 클라이언트 ID (--file 을 쓰면 불필요)")
    ap.add_argument("--secret", help="OAuth 클라이언트 보안 비밀 (--file 을 쓰면 불필요)")
    args = ap.parse_args()

    if not (args.id and args.secret):
        path = Path(args.file) if args.file else find_client_json()
        if not path or not path.is_file():
            print("[stop] 클라이언트 JSON 을 찾지 못했습니다.\n")
            print("  1) console.cloud.google.com/auth/clients 에서")
            print("     donvalue-uploader 오른쪽 ⬇ (JSON 다운로드) 를 누르세요.")
            print("  2) 받은 파일을 다운로드 폴더에 두고 이 명령을 다시 실행하세요:")
            print("       python tools\\get_yt_token.py")
            return 1
        args.id, args.secret = read_client_json(path)
        print(f"[client] {path.name} 에서 클라이언트 정보를 읽었습니다.")
        print(f"[client] id = {args.id[:18]}…{args.id[-24:]}\n")

    port = free_port()
    redirect = f"http://127.0.0.1:{port}"
    url = AUTH + "?" + urllib.parse.urlencode({
        "client_id": args.id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",       # 리프레시 토큰을 받으려면 필수
        "prompt": "consent",            # 이미 동의했어도 다시 발급받게 강제
    })

    srv = http.server.HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.handle_request, daemon=True).start()

    print("브라우저에서 아래 주소를 열고 허용하세요:\n")
    print(url + "\n")
    try:
        webbrowser.open(url)
    except Exception:                                              # noqa: BLE001
        pass

    print("인증 대기 중…")
    for _ in range(600):
        if _code:
            break
        threading.Event().wait(0.5)
    if not _code:
        print("[stop] 인증 코드를 받지 못했습니다.")
        return 1

    r = requests.post(TOKEN, data={
        "code": _code,
        "client_id": args.id,
        "client_secret": args.secret,
        "redirect_uri": redirect,
        "grant_type": "authorization_code",
    }, timeout=30)
    if r.status_code != 200:
        print(f"[stop] 토큰 교환 실패 {r.status_code}: {r.text[:400]}")
        return 1

    data = r.json()
    rt = data.get("refresh_token")
    if not rt:
        print("[stop] refresh_token 이 안 왔습니다. 계정 권한 페이지에서 이 앱의 "
              "액세스를 삭제한 뒤 다시 실행하세요.")
        return 1

    print("\n" + "=" * 64)
    print("방법 A — 시크릿 3개로 넣기 (권장)")
    print("=" * 64)
    print(f"YT_CLIENT_ID     = {args.id}")
    print(f"YT_CLIENT_SECRET = {args.secret}")
    print(f"YT_REFRESH_TOKEN = {rt}")

    blob = json.dumps({
        "client_id": args.id,
        "client_secret": args.secret,
        "refresh_token": rt,
        "token_uri": TOKEN,
        "scopes": [SCOPE],
        "type": "authorized_user",
    }, ensure_ascii=False)
    print("\n" + "=" * 64)
    print("방법 B — 시크릿 1개(YOUTUBE_TOKEN_JSON)로 넣기")
    print("=" * 64)
    print(blob)
    print("=" * 64)
    print("\n둘 중 하나만 등록하면 됩니다. 이미 B 로 등록해뒀다면 그대로 두세요.")
    print("\n등록하는 곳:")
    print("  https://github.com/dongabhana/donvalue-bot/settings/secrets/actions")
    print("  → New repository secret 으로 위 이름·값을 그대로 넣으세요.")
    print("⚠ OAuth 동의 화면이 '테스트' 상태면 이 토큰은 7일 뒤 죽습니다. "
          "'앱 게시'로 바꿔두세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
