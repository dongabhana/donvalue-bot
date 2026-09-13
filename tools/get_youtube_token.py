"""YouTube 업로드용 OAuth 토큰을 한 번 발급한다."""
from __future__ import annotations

import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPE = ["https://www.googleapis.com/auth/youtube.upload"]


def main() -> int:
    source = Path(sys.argv[1] if len(sys.argv) > 1 else "client_secret.json")
    if not source.exists():
        print(f"파일을 찾을 수 없습니다: {source}")
        return 1
    flow = InstalledAppFlow.from_client_secrets_file(str(source), SCOPE)
    credentials = flow.run_local_server(
        port=0, open_browser=True,
        success_message="돈값하나 쇼츠 연결 완료. 이 창을 닫아도 됩니다.",
    )
    target = Path("youtube_token.json")
    target.write_text(credentials.to_json(), encoding="utf-8")
    print(f"완료: {target.resolve()}")
    print("이 파일 전체를 GitHub Secret 'YOUTUBE_TOKEN_JSON' 값으로 등록하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
