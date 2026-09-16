"""
유튜브 쇼츠 업로드 모듈.

왜 쇼츠도 내나
  같은 세로영상 하나로 인스타 릴스 + 유튜브 쇼츠 두 곳을 먹을 수 있다.
  추가 제작비는 0인데, 유튜브는 검색·추천이 오래 살아있어 반년 뒤에도
  조회가 붙는다(릴스는 사실상 며칠). 재고 콘텐츠로서 가치가 다르다.

쇼츠로 인정받는 조건 (2026 기준)
  · 세로 또는 정사각 (가로세로비 1:1 이하) → 우리는 1080x1920 이라 통과
  · 3분 이하 → 우리는 40초 안팎이라 통과
  제목에 #Shorts 를 넣지 않아도 자동 판별되지만, 초기 노출에 도움이 된다는
  관측이 많아 제목·설명에 붙인다. 확정된 사실은 아니다.

⚠ 반드시 알아야 할 제약 — '미심사 프로젝트는 비공개로 잠긴다'
  2020-07-28 이후 만든 구글 API 프로젝트로 videos.insert 를 호출하면
  올라간 영상이 **비공개(private)로 고정**된다. 풀려면 구글에
  YouTube API Services 심사(audit)를 신청해 통과해야 한다.
  그래서 기본값을 private 으로 두었다. 심사 통과 후 YT_PRIVACY=public 으로
  바꾸면 그때부터 바로 공개 발행된다.
  (출처: developers.google.com/youtube/v3/docs/videos/insert)

할당량
  videos.insert 는 '동영상 업로드' 버킷에서 1단위. 기본 한도 안에서
  주 3회 발행은 전혀 문제되지 않는다.

인증 — 두 가지 형태를 다 받는다
  (A) YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN   ← 권장
  (B) YOUTUBE_TOKEN_JSON  (authorized_user JSON 통째로)
  둘 중 아무거나 있으면 된다. tools/get_yt_token.py 가 두 형태를 다 출력한다.

  업로드는 requests 로 직접 한다(이어올리기 규약이 단순해서).
  google-api-python-client 를 안 쓰므로 CI 설치가 가볍고 빠르다.

그 밖의 환경변수
  YT_PRIVACY        private(기본) | unlisted | public
  YT_CATEGORY_ID    22(인물/블로그, 기본) | 26(노하우/스타일)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
SCOPE = "https://www.googleapis.com/auth/youtube.upload"

TITLE_MAX = 100
DESC_MAX = 4900
CHUNK = 4 * 1024 * 1024
PRIVACIES = ("private", "unlisted", "public")


class YouTubeError(RuntimeError):
    pass


# ---------------------------------------------------------------- 인증
def _creds() -> tuple[str, str, str]:
    """(client_id, client_secret, refresh_token). 두 시크릿 형태를 모두 받는다."""
    cid = os.getenv("YT_CLIENT_ID", "").strip()
    sec = os.getenv("YT_CLIENT_SECRET", "").strip()
    ref = os.getenv("YT_REFRESH_TOKEN", "").strip()
    if cid and sec and ref:
        return cid, sec, ref

    raw = os.getenv("YOUTUBE_TOKEN_JSON", "").strip()
    if raw:
        try:
            d = json.loads(raw)
        except json.JSONDecodeError as e:
            raise YouTubeError(f"YOUTUBE_TOKEN_JSON 이 올바른 JSON 이 아닙니다: {e}") from None
        cid = cid or str(d.get("client_id", "")).strip()
        sec = sec or str(d.get("client_secret", "")).strip()
        ref = ref or str(d.get("refresh_token", "")).strip()
        if cid and sec and ref:
            return cid, sec, ref

    raise YouTubeError(
        "유튜브 인증정보가 없습니다. "
        "YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN 또는 "
        "YOUTUBE_TOKEN_JSON 중 하나를 등록하세요.")


def configured() -> bool:
    try:
        _creds()
    except YouTubeError:
        return False
    return True


# ------------------------------------------------- 정기 발행에서의 보류 스위치
HOLD_FILE = Path(__file__).resolve().parent.parent / "content" / "youtube_hold.json"


def hold_reason() -> str:
    """정기 발행(post.yml)에서 유튜브 업로드를 보류할 이유. 보류가 아니면 빈 문자열.

    왜 필요한가 —
      심사(audit) 전에 videos.insert 로 올린 영상은 비공개로 잠기고, 채널 주인이
      손으로도 공개로 못 바꾼다. 그런데 올라간 순간 content/delivery.json 에
      'youtube: done' 으로 남기 때문에, 나중에 심사가 풀려 몰아 올릴 때
      그 편들을 전부 건너뛴다. 즉 '영영 공개 못 하는 편'이 조용히 쌓인다.
      그래서 심사가 풀릴 때까지 정기 발행에서는 유튜브만 건너뛴다.
      (인스타·쓰레드 발행은 이 스위치와 무관하게 그대로 나간다.)

    우선순위
      1. 환경변수 YT_AUTO 가 있으면 그게 이긴다 (1/true/yes/on 이면 올림).
      2. 없으면 content/youtube_hold.json 의 hold 값을 본다.
      3. 파일도 없거나 읽을 수 없으면 **보류**가 기본이다.
         잘못 올려서 잠기는 쪽이, 안 올려서 나중에 몰아 올리는 쪽보다
         되돌리기가 훨씬 어렵기 때문.

    주의: 이 스위치는 정기 발행(src/run.py)에만 적용된다.
    손으로 돌리는 백필(src/youtube_run.py · 유튜브 쇼츠 백필 워크플로)은
    사람이 일부러 누른 것이므로 그대로 올라간다 — 심사 통과 후 몰아 올릴 때
    쓰는 경로가 바로 그것이다.
    """
    env = os.getenv("YT_AUTO", "").strip().lower()
    if env:
        return "" if env in ("1", "true", "yes", "on") else "YT_AUTO 가 꺼져 있음"
    try:
        data = json.loads(HOLD_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "content/youtube_hold.json 이 없음 (기본값은 보류)"
    except (OSError, json.JSONDecodeError) as e:
        # 파일이 깨졌다고 조용히 올려버리면 안 된다. 보류 쪽으로 넘어간다.
        return f"content/youtube_hold.json 을 읽을 수 없음: {e}"
    if not data.get("hold", True):
        return ""
    return str(data.get("reason") or "보류 중").strip()


def auto_enabled() -> bool:
    """정기 발행에서 유튜브까지 같이 올려도 되는가."""
    return not hold_reason()


def access_token() -> str:
    """리프레시 토큰으로 1시간짜리 액세스 토큰을 받는다.

    'invalid_grant' 가 나면 십중팔구 OAuth 동의화면이 '테스트' 상태다.
    테스트 상태의 리프레시 토큰은 7일이면 죽는다. 게시(프로덕션)로 바꿔야 한다.
    """
    cid, sec, ref = _creds()
    r = requests.post(TOKEN_URL, data={
        "client_id": cid, "client_secret": sec,
        "refresh_token": ref, "grant_type": "refresh_token",
    }, timeout=30)
    if r.status_code != 200:
        hint = ""
        if "invalid_grant" in r.text:
            hint = (" — 동의화면이 '테스트' 상태면 리프레시 토큰이 7일 만에 만료됩니다. "
                    "Google Cloud 콘솔에서 '앱 게시'로 바꾸고 토큰을 다시 받으세요.")
        raise YouTubeError(f"토큰 갱신 실패 {r.status_code}: {r.text[:300]}{hint}")
    return r.json()["access_token"]


def resolve_privacy(privacy: str = "") -> str:
    """YT_PRIVACY / YOUTUBE_PRIVACY 둘 다 받는다. 기본값은 안전하게 private."""
    v = (privacy or os.getenv("YT_PRIVACY") or os.getenv("YOUTUBE_PRIVACY")
         or "private").strip().lower()
    if v not in PRIVACIES:
        raise YouTubeError(f"공개상태 값이 잘못됐습니다: {v} (가능: {', '.join(PRIVACIES)})")
    return v


# ---------------------------------------------------------------- 메타데이터
def build_title(item: dict, h: dict | None = None) -> str:
    """쇼츠 제목. 앞 40자 안에 '무엇을 얼마' 가 들어가야 클릭이 붙는다."""
    h = h or {}
    big = " ".join(h.get("big") or []).strip()
    product = str(item.get("product", "")).strip()
    hook = str(item.get("hook", "")).strip()

    head = big or (f"{product} {hook}".strip())
    # 제목 앞에 제품명이 없으면 뭘 계산한 영상인지 모른다. 다만 훅에 이미
    # 제품명 일부가 들어있으면(예: '1년권 끊고…') 겹쳐 붙지 않게 한다.
    toks = [w for w in product.split(" ") if len(w) >= 2]
    if product:
        hit = next((i for i, w in enumerate(toks) if w in head), None)
        if hit is None:                     # 제품명이 통째로 없다 → 앞에 붙인다
            head = f"{product} {head}".strip()
        elif hit > 0:                       # 뒷부분만 겹친다 → 앞 토막만 채운다
            head = f"{' '.join(toks[:hit])} {head}".strip()
    title = f"{head} #Shorts".strip()
    if len(title) > TITLE_MAX:
        title = head[:TITLE_MAX - 8].rstrip(" ,.·") + "… #Shorts"
    return title


def build_description(item: dict, caption: str = "",
                      handle: str = "@dongabhana") -> str:
    """설명란. 유튜브는 여기 텍스트로 주제를 잡으므로 캡션을 그대로 재활용한다."""
    caption = (caption or item.get("caption") or "").strip()
    tags = " ".join(f"#{str(t).lstrip('#')}" for t in (item.get("hashtags") or []))
    parts = [caption]
    # 사람에게 보여줄 근거 출처만 넣는다. 어느 트랙에서 왔는지(track)는 내부용이라
    # 설명란에 나가면 안 된다 — 예전엔 "기준·출처: codex" 가 그대로 나갔다.
    src = str(item.get("sources") or "").strip()
    if src:
        parts.append(f"기준·출처: {src}")
    parts.append(f"{handle} · 돈값하나?")
    parts.append(f"#Shorts {tags}".strip())
    return "\n\n".join(p for p in parts if p)[:DESC_MAX]


def build_tags(item: dict) -> list[str]:
    tags = [str(t).lstrip("#") for t in (item.get("hashtags") or [])]
    for extra in ("돈값하나", "생활비절약", "가성비"):
        if extra not in tags:
            tags.append(extra)
    # 유튜브 태그 총합 500자 제한
    out, total = [], 0
    for t in tags:
        if total + len(t) + 1 > 480:
            break
        out.append(t)
        total += len(t) + 1
    return out


def metadata(item: dict, h: dict | None = None) -> tuple[str, str]:
    """(제목, 설명). 예전 호출부 호환용."""
    return build_title(item, h), build_description(item)


# ---------------------------------------------------------------- 업로드
def upload_short(mp4: Path, title: str, description: str,
                 tags: list[str] | None = None,
                 privacy: str = "", category_id: str = "",
                 token: str = "") -> str:
    """세로영상 하나를 쇼츠로 올리고 video_id 를 돌려준다.

    이어올리기(resumable) 방식이라 중간에 끊겨도 같은 세션 URL 로 재개된다.
    """
    mp4 = Path(mp4)
    if not mp4.exists():
        raise YouTubeError(f"영상 파일이 없습니다: {mp4}")
    privacy = resolve_privacy(privacy)
    category_id = category_id or os.getenv("YT_CATEGORY_ID") or "22"
    token = token or access_token()
    size = mp4.stat().st_size

    meta = {
        "snippet": {
            "title": title[:TITLE_MAX],
            "description": description[:DESC_MAX],
            "tags": tags or [],
            "categoryId": str(category_id),
            "defaultLanguage": "ko",
            "defaultAudioLanguage": "ko",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "license": "youtube",
            "embeddable": True,
        },
    }

    # 1) 업로드 세션 열기
    r = requests.post(
        UPLOAD_URL,
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(size),
            "X-Upload-Content-Type": "video/mp4",
        },
        data=json.dumps(meta, ensure_ascii=False).encode("utf-8"),
        timeout=60)
    if r.status_code not in (200, 201):
        raise YouTubeError(f"업로드 세션 실패 {r.status_code}: {r.text[:400]}")
    session = r.headers.get("Location")
    if not session:
        raise YouTubeError("업로드 세션 URL(Location) 을 받지 못했습니다")

    # 2) 본문 전송 (끊기면 308 로 재개)
    sent, stalls = 0, 0
    with mp4.open("rb") as fh:
        while sent < size:
            fh.seek(sent)
            chunk = fh.read(CHUNK)
            end = sent + len(chunk) - 1
            up = requests.put(
                session, data=chunk,
                headers={"Content-Length": str(len(chunk)),
                         "Content-Range": f"bytes {sent}-{end}/{size}"},
                timeout=300)
            if up.status_code in (200, 201):
                vid = up.json().get("id")
                if not vid:
                    raise YouTubeError(f"응답에 video_id 가 없습니다: {up.text[:300]}")
                return vid
            if up.status_code == 308:
                rng = up.headers.get("Range")          # "bytes=0-1048575"
                sent = int(rng.split("-")[-1]) + 1 if rng else sent + len(chunk)
                continue
            if up.status_code in (500, 502, 503, 504):
                stalls += 1
                if stalls > 6:
                    raise YouTubeError(f"업로드 재시도 6회 초과: {up.status_code}")
                time.sleep(3 * stalls)
                continue
            raise YouTubeError(f"업로드 실패 {up.status_code}: {up.text[:400]}")

    raise YouTubeError("업로드가 끝났는데 video_id 를 못 받았습니다")


def watch_url(video_id: str) -> str:
    return f"https://youtube.com/shorts/{video_id}"


def publish_short(item: dict, mp4: Path, caption: str = "",
                  handle: str = "@dongabhana", h: dict | None = None) -> str:
    """run.py 가 부르는 진입점. 제목·설명·태그까지 만들어서 올린다."""
    return upload_short(mp4, build_title(item, h),
                        build_description(item, caption, handle),
                        build_tags(item))


if __name__ == "__main__":                     # 연결 점검
    import sys
    if not configured():
        print("[stop] 유튜브 인증정보가 없습니다 (YT_* 또는 YOUTUBE_TOKEN_JSON)")
        raise SystemExit(1)
    tok = access_token()
    print("토큰 발급 OK")
    me = requests.get("https://www.googleapis.com/youtube/v3/channels",
                      params={"part": "snippet", "mine": "true"},
                      headers={"Authorization": f"Bearer {tok}"}, timeout=30)
    print(me.status_code, me.text[:300])
    if len(sys.argv) > 1:
        vid = upload_short(Path(sys.argv[1]), "테스트 업로드 #Shorts", "연결 점검용",
                           ["테스트"])
        print("→", watch_url(vid), f"(공개상태 {resolve_privacy()})")
