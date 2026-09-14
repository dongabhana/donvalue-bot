"""쇼츠 파이프라인 회귀 테스트.

여기서 지키려는 것은 세 가지다.
  1) 나레이션이 **화면과 어긋나지 않는다** — 장면별 오디오 길이가 영상 장면
     길이와 프레임 단위로 같아야 한다. (전체를 한 번에 읽어 붙이면 뒤로 갈수록
     목소리가 화면을 앞질러 간다. 그 사고를 막는 테스트다.)
  2) 제목·설명이 유튜브 한도를 넘지 않고, 제목만 봐도 무슨 편인지 안다.
  3) 공개상태 기본값이 private 이다 — 심사 통과 전에 실수로 public 을 쓰면
     구글이 어차피 잠그고, 우리는 잠긴 줄도 모르게 된다.
"""
import json
import subprocess
from pathlib import Path

import pytest

from src import reel, tts, youtube


ITEM = {
    "id": "test-laptop",
    "product": "노트북 총비용",
    "hook": "70만원이 90만원 되는 순간",
    "caption": "본체 가격만 보면 안 됩니다.",
    "hashtags": ["노트북", "가성비"],
    "cards": [
        {"title": "추가 비용", "body": "허브와 저장장치를 더하세요.", "figure": "20만원"},
        {"title": "3년 총액", "body": "감가까지 넣으면 차이가 더 벌어집니다."},
    ],
    "verdict_text": "본체가 아니라 사용 구성을 비교하세요",
    "reel": {
        "big": ["70만원", "노트북이", "90만원 된다"],
        "stake": "주변기기 가격을 빼먹었기 때문입니다",
        "beats": ["허브와 저장장치까지 더해야 합니다", "3년 쓰면 감가가 더 큽니다"],
    },
}


# ------------------------------------------------------------------ 메타데이터
def test_title_within_limit_and_names_the_product():
    title = youtube.build_title(ITEM, {"big": ITEM["reel"]["big"]})
    assert len(title) <= youtube.TITLE_MAX
    assert "#Shorts" in title
    assert "노트북" in title, "제목만 보고 무슨 편인지 알 수 있어야 한다"


def test_title_does_not_repeat_the_product_name():
    item = dict(ITEM, product="헬스장 1년권")
    title = youtube.build_title(item, {"big": ["1년권 끊고", "3개월 만에", "안 가는 사람"]})
    assert title.count("1년권") == 1


def test_description_and_tags():
    desc = youtube.build_description(ITEM, ITEM["caption"])
    assert len(desc) <= youtube.DESC_MAX
    assert "#Shorts" in desc
    tags = youtube.build_tags(ITEM)
    assert "노트북" in tags
    assert sum(len(t) + 1 for t in tags) <= 500


def test_privacy_defaults_to_private(monkeypatch):
    monkeypatch.delenv("YT_PRIVACY", raising=False)
    monkeypatch.delenv("YOUTUBE_PRIVACY", raising=False)
    assert youtube.resolve_privacy() == "private"


def test_privacy_rejects_garbage():
    with pytest.raises(youtube.YouTubeError):
        youtube.resolve_privacy("반공개")


def test_both_secret_shapes_are_accepted(monkeypatch):
    for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN",
              "YOUTUBE_TOKEN_JSON"):
        monkeypatch.delenv(k, raising=False)
    assert not youtube.configured()

    monkeypatch.setenv("YOUTUBE_TOKEN_JSON",
                       '{"client_id":"a","client_secret":"b","refresh_token":"c"}')
    assert youtube.configured() and youtube._creds() == ("a", "b", "c")

    monkeypatch.delenv("YOUTUBE_TOKEN_JSON")
    monkeypatch.setenv("YT_CLIENT_ID", "x")
    monkeypatch.setenv("YT_CLIENT_SECRET", "y")
    monkeypatch.setenv("YT_REFRESH_TOKEN", "z")
    assert youtube._creds() == ("x", "y", "z")


# ------------------------------------------------------------------ 나레이션
def test_speakable_reads_numbers_and_symbols_correctly():
    out = tts.speakable("멤버십 가치 = 7,890원 × 12개월 (부가세 포함)")
    assert "7890" in out, "천단위 쉼표를 빼야 '일 쉼표 영영영'으로 읽지 않는다"
    assert "곱하기" in out
    assert "부가세" not in out, "괄호 부연은 소리로 들으면 흐름만 끊는다"


def test_script_has_one_line_per_scene():
    h = _hooks()
    plan = reel.plan_scenes(ITEM)
    lines = tts.script_for(plan, ITEM, h)
    assert len(lines) == len(plan)
    # 훅 리빌 중간 컷(0.4초)에는 말을 얹지 않는다
    hook_lines = [ln for s, ln in zip(plan, lines) if s["kind"] == "hook"]
    assert sum(1 for x in hook_lines if x) == 1
    assert all(lines[i] for i, s in enumerate(plan)
               if s["kind"] in ("stake", "beat", "verdict"))


def test_scene_grows_when_narration_is_longer(tmp_path):
    plan = reel.plan_scenes(ITEM)
    lines = tts.script_for(plan, ITEM, _hooks())
    grown, voices = tts.plan_with_narration(
        plan, lines, tmp_path, synth=_fake_synth)

    for before, after, v in zip(plan, grown, voices):
        assert after["dur"] >= before["dur"], "장면이 줄어들면 읽을 시간이 사라진다"
        if v is not None:
            spoken = tts._duration(v) + tts.LEAD + tts.TAIL
            assert after["dur"] + 1e-6 >= spoken, "말이 장면 밖으로 삐져나오면 안 된다"


def test_narration_track_matches_scene_boundaries(tmp_path):
    """이 테스트가 싱크를 지킨다 — 트랙 길이 = 영상 장면 길이의 합."""
    plan = reel.plan_scenes(ITEM)
    lines = tts.script_for(plan, ITEM, _hooks())
    grown, voices = tts.plan_with_narration(
        plan, lines, tmp_path, synth=_fake_synth)
    track = tts.build_track(grown, voices, tmp_path)

    expected = sum(tts.frames(s["dur"]) / tts.FPS for s in grown)
    assert abs(tts._duration(track) - expected) < 0.05


# ------------------------------------------------------------------ 도우미
def _hooks():
    from src import hooks
    return hooks.resolve(ITEM)


def _fake_synth(text: str, out: Path, **kw) -> Path:
    """망을 타지 않는 가짜 TTS. 글자 수에 비례한 길이의 소리를 만든다."""
    secs = max(0.8, len(text) / 12.5)
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"sine=frequency=200:duration={secs:.2f}:sample_rate=44100",
         "-af", "tremolo=f=4:d=0.9,volume=0.5", "-ac", "2", str(out)],
        check=True, capture_output=True)
    return out


# ------------------------------------------------------------------ codex 다리
CODEX_ITEM = {
    "id": "cx999-demo",
    "publish_at": "2020-01-01T20:00:00+09:00",
    "verified": True,
    "topic": "무료배송을 채우는 순간 늘어난 결제액",
    "hook_candidates": ["배송비 3,000원 아끼려다 2,900원 더 썼다", "무료배송 버튼의 숨은 가격표"],
    "slides": [
        {"title": "표지\n두 줄", "body": "표지 본문"},
        {"title": "장바구니에\n27,900원", "body": "3만원부터 무료배송.", "note": "가정"},
        {"title": "2,100원만\n더 담으면", "body": "필요 없는 5,900원짜리."},
        {"title": "‘무료’ 말고\n마지막 합계", "body": "안 살 물건이면 멈추기."},
        {"title": "당신의 채움템은\n뭐예요?", "body": "잘 썼나요?"},
    ],
    "caption": "본문입니다.\n#돈값하나 #무료배송 #장바구니",
}


def test_codex_item_maps_into_the_reel_schema():
    from src import codex_bridge, hooks
    it = codex_bridge.to_queue_item(CODEX_ITEM)

    # 표지는 훅 장면이 담당한다 → 카드로 중복해 넣지 않는다
    assert len(it["cards"]) == 2
    assert "표지" not in json.dumps(it["cards"], ensure_ascii=False)
    # 제목 두 줄을 한 줄로 합쳐야 금액이 살아남는다
    assert "27,900원" in it["cards"][0]["title"]
    # 결론은 참여유도 슬라이드가 아니라 그 앞 슬라이드
    assert "마지막 합계" in it["verdict_text"]
    assert "채움템" in it["reel"]["loop"]
    # 꼬리표는 브랜드 태그가 아닌 주제어
    assert it["product"] == "무료배송"
    # 기존 파이프라인이 그대로 먹을 수 있어야 한다
    h = hooks.resolve(it)
    assert h["big"] and h["beats"]


def test_codex_only_offers_episodes_already_on_instagram():
    from src import codex_bridge
    future = dict(CODEX_ITEM, publish_at="2099-01-01T20:00:00+09:00")
    assert codex_bridge.already_on_instagram(CODEX_ITEM)
    assert not codex_bridge.already_on_instagram(future)
    assert codex_bridge.already_on_instagram(dict(future, posted_early_on="2026-09-12"))
