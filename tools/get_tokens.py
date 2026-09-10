"""
최초 1회용 토큰 발급 헬퍼 (로컬 실행).

  python tools/get_tokens.py instagram
  python tools/get_tokens.py threads

Meta 앱 대시보드에서 토큰을 바로 생성할 수 있으면 그 방법이 더 빠릅니다.
이 스크립트는 대시보드 버튼이 없거나 실패할 때 쓰는 수동 OAuth 경로입니다.

주의: 아래 엔드포인트는 Meta 공식 문서 기준입니다. Meta 가 경로를 바꾸면
스크립트가 출력하는 URL 을 문서와 대조해서 수정하세요.
  인스타: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login
  쓰레드: https://developers.facebook.com/docs/threads/get-started
"""
from __future__ import annotations

import sys
import urllib.parse

import requests

CONF = {
    "instagram": {
        "authorize": "https://www.instagram.com/oauth/authorize",
        "token": "https://api.instagram.com/oauth/access_token",
        "exchange": "https://graph.instagram.com/access_token",
        "exchange_grant": "ig_exchange_token",
        "scope": "instagram_business_basic,instagram_business_content_publish",
        "secrets": ("IG_USER_ID", "IG_ACCESS_TOKEN"),
    },
    "threads": {
        "authorize": "https://threads.net/oauth/authorize",
        "token": "https://graph.threads.net/oauth/access_token",
        "exchange": "https://graph.threads.net/access_token",
        "exchange_grant": "th_exchange_token",
        "scope": "threads_basic,threads_content_publish",
        "secrets": ("TH_USER_ID", "TH_ACCESS_TOKEN"),
    },
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in CONF:
        print("사용법: python tools/get_tokens.py [instagram|threads]")
        return 1
    c = CONF[sys.argv[1]]

    app_id = input("앱 ID (Instagram App ID / Threads App ID): ").strip()
    app_secret = input("앱 시크릿: ").strip()
    redirect = input("리디렉션 URI (앱에 등록한 것과 정확히 동일): ").strip()

    q = urllib.parse.urlencode({
        "client_id": app_id, "redirect_uri": redirect,
        "scope": c["scope"], "response_type": "code",
    })
    print("\n[1] 아래 주소를 브라우저에서 열고 권한을 허용하세요:\n")
    print(f"{c['authorize']}?{q}\n")
    print("[2] 리디렉션된 주소창의 ?code= 뒤 값을 복사하세요. 끝의 '#_' 는 빼고 붙여넣으세요.\n")
    code = input("code: ").strip().removesuffix("#_")

    r = requests.post(c["token"], data={
        "client_id": app_id, "client_secret": app_secret,
        "grant_type": "authorization_code", "redirect_uri": redirect, "code": code,
    }, timeout=60)
    r.raise_for_status()
    short = r.json()
    print("\n단기 토큰 발급 완료:", {k: v for k, v in short.items() if k != "access_token"})

    r = requests.get(c["exchange"], params={
        "grant_type": c["exchange_grant"], "client_secret": app_secret,
        "access_token": short["access_token"],
    }, timeout=60)
    r.raise_for_status()
    long_tok = r.json()

    id_key, tok_key = c["secrets"]
    user_id = short.get("user_id") or short.get("data", [{}])[0].get("user_id")
    print("\n================ GitHub Secrets 에 등록할 값 ================")
    print(f"{id_key}      = {user_id}")
    print(f"{tok_key} = {long_tok['access_token']}")
    print(f"(유효기간 약 {int(long_tok.get('expires_in', 0)) // 86400}일 — 워크플로우가 자동 연장합니다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
