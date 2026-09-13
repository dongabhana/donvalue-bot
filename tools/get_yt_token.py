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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="OAuth 클라이언트 ID")
    ap.add_argument("--secret", required=True, help="OAuth 클라이언트 보안 비밀")
    args = ap.parse_args()

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
    print("⚠ OAuth 동의 화면이 '테스트' 상태면 이 토큰은 7일 뒤 죽습니다. "
          "'앱 게시'로 바꿔두세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
