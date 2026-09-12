"""
Instagram / Threads 캐러셀 발행 모듈.

두 플랫폼 모두 동일한 2단계(컨테이너 생성 → 발행) 구조를 쓴다.
이미지는 반드시 '공개 URL' 이어야 하므로, 이 프로젝트는 GitHub raw URL 을 쓴다.
"""
from __future__ import annotations

import os
import time

import requests

IG_BASE = os.getenv("IG_API_BASE", "https://graph.instagram.com")
TH_BASE = os.getenv("TH_API_BASE", "https://graph.threads.net/v1.0")
TIMEOUT = 60


class PublishError(RuntimeError):
    pass


def _post(url: str, params: dict) -> dict:
    for attempt in range(3):
        r = requests.post(url, data=params, timeout=TIMEOUT)
        if r.status_code < 300:
            return r.json()
        # 429/5xx 는 재시도할 가치가 있음
        if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
            time.sleep(15 * (attempt + 1))
            continue
        raise PublishError(f"POST {url} → {r.status_code} {r.text[:400]}")
    raise PublishError(f"POST {url} 재시도 실패")


def _get(url: str, params: dict) -> dict:
    r = requests.get(url, params=params, timeout=TIMEOUT)
    if r.status_code >= 300:
        raise PublishError(f"GET {url} → {r.status_code} {r.text[:400]}")
    return r.json()


# ------------------------------------------------------------------ 토큰 갱신
def refresh_instagram_token(token: str) -> str | None:
    """장기 토큰(60일)을 60일 더 연장. 발급 후 24시간이 지나야 동작한다."""
    try:
        j = _get(f"{IG_BASE}/refresh_access_token",
                 {"grant_type": "ig_refresh_token", "access_token": token})
        return j.get("access_token")
    except PublishError as e:
        print(f"[warn] 인스타 토큰 갱신 실패(무시하고 진행): {e}")
        return None


def refresh_threads_token(token: str) -> str | None:
    try:
        j = _get("https://graph.threads.net/refresh_access_token",
                 {"grant_type": "th_refresh_token", "access_token": token})
        return j.get("access_token")
    except PublishError as e:
        print(f"[warn] 쓰레드 토큰 갱신 실패(무시하고 진행): {e}")
        return None


# ------------------------------------------------------------------ 인스타그램
def _ig_wait_ready(container_id: str, token: str, tries: int = 20) -> None:
    """컨테이너가 FINISHED 될 때까지 대기. ERROR 면 즉시 실패."""
    for _ in range(tries):
        j = _get(f"{IG_BASE}/{container_id}",
                 {"fields": "status_code,status", "access_token": token})
        code = j.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise PublishError(f"IG 컨테이너 {container_id} 상태 {code}: {j.get('status')}")
        time.sleep(6)
    raise PublishError(f"IG 컨테이너 {container_id} 준비 시간 초과")


def publish_instagram(user_id: str, token: str, image_urls: list[str], caption: str) -> str:
    if not 2 <= len(image_urls) <= 10:
        raise PublishError(f"인스타 캐러셀은 2~10장이어야 합니다 (현재 {len(image_urls)}장)")

    children = []
    for url in image_urls:
        j = _post(f"{IG_BASE}/{user_id}/media",
                  {"image_url": url, "is_carousel_item": "true", "access_token": token})
        children.append(j["id"])
        print(f"  · IG child {j['id']} ← {url.rsplit('/', 1)[-1]}")

    for cid in children:
        _ig_wait_ready(cid, token)

    j = _post(f"{IG_BASE}/{user_id}/media",
              {"media_type": "CAROUSEL", "children": ",".join(children),
               "caption": caption, "access_token": token})
    carousel_id = j["id"]
    _ig_wait_ready(carousel_id, token)

    j = _post(f"{IG_BASE}/{user_id}/media_publish",
              {"creation_id": carousel_id, "access_token": token})
    return j["id"]


def publish_instagram_reel(user_id: str, token: str, video_url: str,
                           caption: str, cover_url: str | None = None) -> str:
    """릴스 발행. 캐러셀과 달리 팔로워가 없어도 비팔로워에게 배포된다.

    영상 인코딩에 시간이 걸려서 컨테이너 준비 대기를 캐러셀보다 길게 잡는다.
    """
    params = {"media_type": "REELS", "video_url": video_url,
              "caption": caption, "access_token": token}
    if cover_url:
        params["cover_url"] = cover_url
    j = _post(f"{IG_BASE}/{user_id}/media", params)
    container = j["id"]
    print(f"  · IG reel container {container}")

    _ig_wait_ready(container, token, tries=60)   # 영상은 최대 6분 대기

    j = _post(f"{IG_BASE}/{user_id}/media_publish",
              {"creation_id": container, "access_token": token})
    return j["id"]


def publish_instagram_comment(media_id: str, token: str, message: str) -> str:
    """내 게시물에 첫 댓글을 단다.

    첫 댓글은 두 가지를 한다.
      1) 댓글창에 이미 글이 하나 있으면 다음 사람이 달기가 쉬워진다(빈칸 저항).
      2) 캡션에 넣기엔 긴 기준·출처·다음 편 요청을 여기로 뺄 수 있다.

    instagram_business_manage_comments 권한이 필요하다. 토큰에 그 권한이 없으면
    발행 자체는 이미 끝난 뒤이므로, 호출부에서 경고만 남기고 넘어간다.
    """
    j = _post(f"{IG_BASE}/{media_id}/comments",
              {"message": message, "access_token": token})
    return j["id"]


# ------------------------------------------------------------------ 쓰레드
def publish_threads(user_id: str, token: str, image_urls: list[str], text: str,
                    reply_to_id: str | None = None, wait: int = 30,
                    topic_tag: str | None = None) -> str:
    """0장이면 텍스트, 1장이면 단일 이미지, 2장 이상이면 캐러셀.

    reply_to_id 를 주면 그 글에 달리는 답글이 된다.
    """
    base = {"text": text, "access_token": token}
    if len(text) > 500:
        raise PublishError('Threads 본문은 500자 이하여야 합니다')
    if topic_tag:
        if not 1 <= len(topic_tag) <= 50 or any(c in topic_tag for c in '.&'):
            raise PublishError('Threads 주제 태그 형식이 잘못됐습니다')
        base['topic_tag'] = topic_tag
    if reply_to_id:
        base["reply_to_id"] = reply_to_id

    if not image_urls:
        j = _post(f"{TH_BASE}/{user_id}/threads", {**base, "media_type": "TEXT"})
        container = j["id"]
    elif len(image_urls) == 1:
        # 캐러셀은 최소 2장이므로 1장은 단일 IMAGE 포스트로 보낸다.
        j = _post(f"{TH_BASE}/{user_id}/threads",
                  {**base, "media_type": "IMAGE", "image_url": image_urls[0]})
        container = j["id"]
    else:
        if len(image_urls) > 20:
            image_urls = image_urls[:20]
        children = []
        for url in image_urls:
            j = _post(f"{TH_BASE}/{user_id}/threads",
                      {"media_type": "IMAGE", "image_url": url,
                       "is_carousel_item": "true", "access_token": token})
            children.append(j["id"])
            print(f"  · TH child {j['id']} ← {url.rsplit('/', 1)[-1]}")
        j = _post(f"{TH_BASE}/{user_id}/threads",
                  {**base, "media_type": "CAROUSEL", "children": ",".join(children)})
        container = j["id"]

    time.sleep(wait)  # 문서 권장 대기. 텍스트만 올릴 땐 짧게 잡아도 된다.
    try:
        j = _post(f"{TH_BASE}/{user_id}/threads_publish",
                  {"creation_id": container, "access_token": token})
    except PublishError:
        # 컨테이너가 아직 준비 안 된 경우가 있어 한 번만 더 기다렸다 시도한다
        time.sleep(20)
        j = _post(f"{TH_BASE}/{user_id}/threads_publish",
                  {"creation_id": container, "access_token": token})
    return j["id"]


def publish_threads_chain(user_id: str, token: str, parent_id: str,
                          texts: list[str]) -> list[str]:
    """본문 글에 내 답글을 줄줄이 이어 단다.

    왜 이걸 하나
      쓰레드는 답글이 달린 글을 더 밀어준다. 남이 달아주길 기다리는 것보다
      내가 먼저 이어 붙이는 쪽이 확실하고, 본문에 다 넣으면 길어서 안 읽히는
      예외·반론·출처를 여기로 뺄 수 있다.

    각 답글은 '바로 앞 글'에 달린다. 그래야 하나의 타래로 읽힌다.
    실패해도 이미 본문은 올라간 뒤이므로 호출부에서 경고만 남긴다.
    """
    ids: list[str] = []
    prev = parent_id
    for i, t in enumerate(texts, start=1):
        t = (t or "").strip()
        if not t:
            continue
        rid = publish_threads(user_id, token, [], t, reply_to_id=prev, wait=12)
        print(f"  · TH reply {i} → {rid}")
        ids.append(rid)
        prev = rid
    return ids
