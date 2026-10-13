"""edge-tts 합성 주소 교체 (2026-10 마이크로소프트 서버 변경 대응).

2026-10-12 부터 예전 합성 주소(speech.platform.bing.com)가 전 세계에서 403 을 돌려준다.
edge-tts 최신판(7.2.8)도 그 주소를 쓰고 있어 나레이션 합성이 전부 실패했고,
렌더가 멈춰 10/12 정기 발행 3회가 연속 실패했다.

Edge 155 는 api.msedgeservices.com 으로 합성하며, 이 주소는 기존 토큰을
Ocp-Apim-Subscription-Key 로 받아 준다(edge-tts 이슈 #490, 수정 PR #491 — 아직 미배포).
목소리 목록은 예전 주소가 그대로 응답하므로 바꾸지 않는다.

edge-tts 가 수정판을 내면 이 모듈은 아무것도 하지 않는다(이미 새 주소면 그대로 둔다).
급할 때는 환경변수 EDGE_TTS_WSS_URL 로 주소를 직접 덮어쓸 수 있다.
"""
from __future__ import annotations

import os

NEW_HOST = "api.msedgeservices.com"
LEGACY_HOST = "speech.platform.bing.com"


def target_url(token: str) -> str:
    override = os.environ.get("EDGE_TTS_WSS_URL", "").strip()
    if override:
        return override
    return (
        f"wss://{NEW_HOST}/tts/cognitiveservices/websocket/v1"
        f"?Ocp-Apim-Subscription-Key={token}"
    )


def apply() -> str:
    """edge_tts 가 쓰는 합성 주소를 새 주소로 바꾸고, 적용된 주소를 돌려준다."""
    import edge_tts.communicate as communicate
    import edge_tts.constants as constants

    current = getattr(communicate, "WSS_URL", "") or getattr(constants, "WSS_URL", "")
    if NEW_HOST in current and not os.environ.get("EDGE_TTS_WSS_URL"):
        return current  # 라이브러리가 이미 고쳐진 판이면 손대지 않는다
    url = target_url(constants.TRUSTED_CLIENT_TOKEN)
    constants.WSS_URL = url
    communicate.WSS_URL = url  # communicate 는 import 시점에 값을 복사해 두므로 둘 다 바꾼다
    return url
