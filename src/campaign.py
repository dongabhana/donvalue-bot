"""27편 캠페인(원고 codex/campaign27.py) 발행.

2026-09-29 소유자 결정: 27편 제작본을 오늘부터 순서대로 낸다. 이 모듈은 src/run.py 가
슬롯마다 먼저 부른다. 낼 편이 없으면(전부 발행됐거나 표지 대기) None 을 돌려주고,
run.py 는 기존 큐(content/queue.yaml)로 넘어간다.

한 편이 나가는 순서
  1. 발행 가능 판정 — 발행 기록(posted.json)에 없고, 표지가 준비된 편(codex/campaign27.py
     의 cover_status). 표지 재제작 대상 12편은 assets/covers/<id>.editorial-v3.jpg 새 파일이
     들어와야 풀린다. 원고 JSON 을 다시 만들지 않아도 파일만 넣으면 다음 슬롯부터 대상이 된다.
  2. 렌더 — tools/build_campaign27.py 로 매번 새로 만든다(편 폴더를 비우고 시작 → 예전
     음성·영상 캐시가 섞이지 않는다). 영상 길이·무음 여부를 검사한 뒤에만 다음으로 간다.
  3. 인스타 릴스(표지 이미지를 cover_url 로) → 유튜브 쇼츠(+표지 썸네일 시도) → 쓰레드(표지+결론).
     각 발행은 run.deliver_once 로 원장(content/delivery.json)에 먼저 적고 나간다(중복 방지).
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT / ".preview" / "campaign-build"
# 공개 URL 이 필요한 파일만 images/<id>/ 로 옮겨 커밋한다(유튜브 영상은 로컬에서 바로 올린다).
PUBLIC_FILES = ("instagram.mp4", "cover.jpg", "01-cover.png", "06-conclusion.png", "verify.json")


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def builder():
    return _module("build_campaign27", ROOT / "tools" / "build_campaign27.py")


def load() -> list[dict]:
    """원고는 codex/campaign27.py 하나가 원본이다(JSON 사본을 따로 두지 않는다 → 어긋날 일이 없다)."""
    import copy
    from codex import campaign27 as C
    return copy.deepcopy(C.package()["items"])


def cover_ok(item: dict) -> tuple[bool, str]:
    """표지 판정은 JSON 에 박힌 값이 아니라 지금 파일 상태로 한다."""
    from codex import campaign27 as C
    probe = dict(item)
    own = ROOT / f"assets/covers/{item['id']}.editorial-v3.jpg"
    if own.is_file():
        probe["cover_file"] = str(own.relative_to(ROOT))
    return C.cover_status(probe)


def ids() -> set[str]:
    return {e["id"] for e in load()}


def next_ready(posted_ids: set[str]) -> tuple[dict | None, list[str]]:
    """(낼 편, 표지 때문에 건너뛴 편 목록)."""
    waiting: list[str] = []
    for item in sorted(load(), key=lambda e: e["order"]):
        if item["id"] in posted_ids:
            continue
        ok, why = cover_ok(item)
        if not ok:
            waiting.append(item["id"])
            continue
        return item, waiting
    return None, waiting


def render(item: dict) -> Path:
    """편 하나를 새로 렌더하고 결과 폴더를 돌려준다(검증 실패 시 예외)."""
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    b = builder()
    b.build(BUILD_DIR, only=[item["id"]], video=True)
    folder = BUILD_DIR / item["id"]
    report = json.loads((folder / "verify.json").read_text(encoding="utf-8"))
    for p in ("instagram", "youtube"):
        r = report[p]
        if r["duration"] < 15 or r["mean_volume_db"] < -40:
            raise RuntimeError(f"{item['id']} {p}.mp4 검증 실패: {r}")
        print(f"[campaign] {p}.mp4 {r['duration']}s · 평균 음량 {r['mean_volume_db']}dB "
              f"· 장면 {len(r['scenes'])}개 · {r['bytes'] / 1024 / 1024:.2f}MB")
    narr = json.loads((folder / "scenes.json").read_text(encoding="utf-8"))
    print(f"[reel] {item['id']} 나레이션 {len(narr)}컷 합성 (플랫폼별 영상 7컷: 표지·본문4·결론·마지막 장)")
    return folder


def _read(folder: Path, name: str) -> str:
    return (folder / name).read_text(encoding="utf-8").strip()


def publish(item: dict, ctx: dict, dry_run: bool = False) -> int:
    """ctx: run.py 의 sh, push, deliver_once, POSTED, IMAGES, PREVIEW, notify, youtube, publish."""
    sh, push, deliver_once = ctx["sh"], ctx["push"], ctx["deliver_once"]
    notify, youtube, pub = ctx["notify"], ctx["youtube"], ctx["publish"]
    print(f"[campaign] {item['order']:02d}편 {item['id']} · {item['product']}")
    folder = render(item)
    caption = _read(folder, "instagram-caption.txt")
    title = item["yt_title"] + " #Shorts"
    desc = _read(folder, "youtube-description.txt")
    threads_text = _read(folder, "threads.txt")

    outdir = (ctx["PREVIEW"] if dry_run else ctx["IMAGES"]) / item["id"]
    if outdir.exists():
        shutil.rmtree(outdir)            # 예전 렌더 결과를 남기지 않는다
    outdir.mkdir(parents=True)
    for name in PUBLIC_FILES:
        shutil.copy2(folder / name, outdir / name)
    yt_mp4 = folder / "youtube.mp4"

    if dry_run:
        for name in ("youtube.mp4", "06-conclusion.png"):
            shutil.copy2(folder / name, outdir / name)
        print(f"[dry-run] 결과: {outdir}")
        print("--- 인스타 캡션 ---\n" + caption)
        print("--- 유튜브 제목 ---\n" + title)
        print("--- 유튜브 설명 ---\n" + desc)
        print("--- 쓰레드 본문 ---\n" + threads_text)
        if notify.enabled():
            try:
                notify.send_video(outdir / "instagram.mp4", f"🗂 [검토용 · 발행 안 함] {item['product']} <{item['id']}>")
                notify.send_message("[검토용 · 발행 안 함]\n\n" + caption)
            except Exception as e:                                # noqa: BLE001
                print(f"[telegram] 전송 실패: {e}")
        return 0

    if os.getenv("APPROVAL_REQUIRED", "1") == "1" and notify.enabled():
        answer = notify.ask(item["id"], f"{item['product']} (reel)",
                            "--- 인스타 캡션 ---\n" + caption + "\n\n--- 쓰레드 ---\n" + threads_text,
                            video=outdir / "instagram.mp4",
                            photos=[outdir / "01-cover.png", outdir / "06-conclusion.png"])
        if answer is not True:
            print("[stop] 승인되지 않아 발행하지 않습니다(다음 슬롯에 다시 묻습니다).")
            return 0

    repo = os.environ["GITHUB_REPOSITORY"]
    sh("git", "add", str(outdir))
    if sh("git", "status", "--porcelain", str(outdir)):
        sh("git", "-c", "user.name=donvalue-bot", "-c", "user.email=bot@users.noreply.github.com",
           "commit", "-m", f"images: {item['id']} (campaign27)")
        push()
    sha = sh("git", "rev-parse", "HEAD")
    base = f"https://raw.githubusercontent.com/{repo}/{sha}/images/{item['id']}"
    results: dict[str, str] = {}
    errors: list[str] = []

    ig_id, ig_tok = os.getenv("IG_USER_ID"), os.getenv("IG_ACCESS_TOKEN")
    if ig_id and ig_tok:
        try:
            results["instagram_reel"] = deliver_once(item["id"], "instagram_reel", lambda: pub.publish_instagram_reel(
                ig_id, ig_tok, f"{base}/instagram.mp4", caption, f"{base}/cover.jpg"))
            print(f"[reel] 발행 완료 media_id={results['instagram_reel']}")
        except Exception as e:                                    # noqa: BLE001
            errors.append(f"instagram_reel: {e}")
            print(f"[reel] 실패: {e}")
    else:
        print("[instagram] 토큰 없음 → 건너뜀")

    hold = youtube.hold_reason()
    if youtube.configured() and not hold:
        try:
            vid = deliver_once(item["id"], "youtube", lambda: youtube.upload_short(
                yt_mp4, title, desc, item.get("youtube_tags") or []))
            results["youtube"] = vid
            print(f"[youtube] 발행 완료 {youtube.watch_url(vid)}")
            # 표지를 썸네일로. 쇼츠 맞춤 썸네일은 채널 자격에 따라 거절될 수 있어 실패해도 발행은 유지한다.
            try:
                youtube.set_thumbnail(vid, outdir / "cover.jpg")
                print("[youtube] 표지 썸네일 적용 요청 완료")
            except Exception as e:                                # noqa: BLE001
                errors.append(f"youtube_thumbnail: {e}")
                print(f"[youtube] 썸네일 적용 실패(영상은 정상): {e}")
            try:
                status = youtube.video_status(vid)
                want = youtube.resolve_privacy()
                print(f"[verify] 실제 공개상태={status.get('privacyStatus')} (요청 {want})")
                if status.get("privacyStatus") != want:
                    errors.append(f"youtube_privacy: 요청 {want} → 실제 {status.get('privacyStatus')}")
            except Exception as e:                                # noqa: BLE001
                errors.append(f"youtube_verify: {e}")
        except Exception as e:                                    # noqa: BLE001
            errors.append(f"youtube: {e}")
            print(f"[youtube] 실패: {e}")
    elif youtube.configured():
        print(f"[youtube] 보류 중 — {hold}")
    else:
        print("[youtube] 토큰 없음 → 건너뜀")

    th_id, th_tok = os.getenv("TH_USER_ID"), os.getenv("TH_ACCESS_TOKEN")
    if os.getenv("SKIP_THREADS", "").lower() in ("1", "true", "yes"):
        th_id = th_tok = None
    if th_id and th_tok:
        stagger = int(os.getenv("STAGGER_MIN", "10"))
        if stagger > 0 and results:
            print(f"[stagger] 쓰레드 발행까지 {stagger}분 대기")
            time.sleep(stagger * 60)
        try:
            results["threads"] = deliver_once(item["id"], "threads", lambda: pub.publish_threads(
                th_id, th_tok, [f"{base}/01-cover.png", f"{base}/06-conclusion.png"], threads_text,
                topic_tag=item.get("threads_tag")))
            print(f"[threads] 발행 완료 post_id={results['threads']}")
        except Exception as e:                                    # noqa: BLE001
            errors.append(f"threads: {e}")
            print(f"[threads] 실패: {e}")
    else:
        print("[threads] 토큰 없음/건너뜀")

    if not results:
        print("[stop] 어느 플랫폼에도 발행하지 못했습니다. 기록하지 않고 종료합니다.")
        return 1
    posted = json.loads(ctx["POSTED"].read_text(encoding="utf-8")) if ctx["POSTED"].exists() else []
    posted.append({"id": item["id"], "product": item["product"], "campaign": "campaign27",
                   "posted_at": datetime.now(ctx["KST"]).isoformat(timespec="seconds"),
                   "results": results, "errors": errors})
    ctx["POSTED"].write_text(json.dumps(posted, ensure_ascii=False, indent=2), encoding="utf-8")
    notify.done(item["id"], item["product"], results, errors)
    sh("git", "add", str(ctx["POSTED"]))
    sh("git", "-c", "user.name=donvalue-bot", "-c", "user.email=bot@users.noreply.github.com",
       "commit", "-m", f"posted: {item['id']}")
    push()
    return 0
