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


# ------------------------------------------------------------------ 쓰레드
def publish_threads(user_id: str, token: str, image_urls: list[str], text: str) -> str:
    """0장이면 텍스트, 1장이면 단일 이미지, 2장 이상이면 캐러셀."""
    if not image_urls:
        j = _post(f"{TH_BASE}/{user_id}/threads",
                  {"media_type": "TEXT", "text": text, "access_token": token})
        container = j["id"]
    elif len(image_urls) == 1:
        # 캐러셀은 최소 2장이므로 1장은 단일 IMAGE 포스트로 보낸다.
        j = _post(f"{TH_BASE}/{user_id}/threads",
                  {"media_type": "IMAGE", "image_url": image_urls[0],
                   "text": text, "access_token": token})
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
                  {"media_type": "CAROUSEL", "children": ",".join(children),
                   "text": text, "access_token": token})
        container = j["id"]

    time.sleep(30)  # 문서 권장 대기
    j = _post(f"{TH_BASE}/{user_id}/threads_publish",
              {"creation_id": container, "access_token": token})
    return j["id"]
