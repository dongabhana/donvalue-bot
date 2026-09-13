"""YouTube Data API를 이용한 쇼츠 업로드."""
from __future__ import annotations

import json
import os
from pathlib import Path


SCOPE = "https://www.googleapis.com/auth/youtube.upload"


def credentials_from_env():
    from google.oauth2.credentials import Credentials

    raw = os.getenv("YOUTUBE_TOKEN_JSON", "").strip()
    if not raw:
        raise RuntimeError("YOUTUBE_TOKEN_JSON 시크릿이 없습니다")
    return Credentials.from_authorized_user_info(json.loads(raw), [SCOPE])


def upload_short(video: Path, title: str, description: str,
                 privacy: str | None = None) -> str:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    privacy = privacy or os.getenv("YOUTUBE_PRIVACY", "unlisted")
    if privacy not in {"private", "unlisted", "public"}:
        raise RuntimeError(f"잘못된 YOUTUBE_PRIVACY 값: {privacy}")
    youtube = build("youtube", "v3", credentials=credentials_from_env(), cache_discovery=False)
    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "categoryId": "22",
                "defaultLanguage": "ko",
            },
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
        },
        media_body=MediaFileUpload(str(video), mimetype="video/mp4", resumable=True),
    )
    response = None
    while response is None:
        _, response = request.next_chunk()
    return response["id"]


def metadata(item: dict) -> tuple[str, str]:
    title = f"{item.get('product', '돈값하나')}｜{item.get('hook', '')}".strip("｜")
    tags = " ".join(f"#{str(t).lstrip('#')}" for t in item.get("hashtags", [])[:8])
    description = (f"{item.get('caption', '').strip()}\n\n"
                   f"돈값하는 소비를 숫자로 따져봅니다.\n{tags} #Shorts").strip()
    return title, description
