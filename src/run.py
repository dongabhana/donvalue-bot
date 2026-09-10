"""
파이프라인 엔트리포인트.

  python -m src.run --dry-run      # 다음 발행분 렌더링만 (API 호출 없음)
  python -m src.run                # 렌더 → 이미지 커밋/푸시 → IG·쓰레드 발행 → 이력 기록

필요 환경변수
  IG_USER_ID, IG_ACCESS_TOKEN      인스타그램 (Instagram Login 방식)
  TH_USER_ID, TH_ACCESS_TOKEN      쓰레드
  GITHUB_REPOSITORY                owner/repo  (GitHub Actions 가 자동 주입)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.render import render_item          # noqa: E402
from src import publish                     # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "content" / "queue.yaml"
POSTED = ROOT / "content" / "posted.json"
IMAGES = ROOT / "images"
KST = timezone(timedelta(hours=9))


def sh(*args: str) -> str:
    return subprocess.run(args, cwd=ROOT, check=True, capture_output=True,
                          text=True).stdout.strip()


def load_posted() -> list[dict]:
    if POSTED.exists():
        return json.loads(POSTED.read_text(encoding="utf-8"))
    return []


def pick_next(queue: dict, posted_ids: set[str]) -> dict | None:
    skipped: list[str] = []
    for item in queue["items"]:
        if item["id"] in posted_ids:
            continue
        if not item.get("verified"):
            skipped.append(item["id"])
            continue
        if skipped:
            print(f"[info] 미검수라 건너뜀: {', '.join(skipped)}")
        return item
    if skipped:
        print("[stop] 발행 가능한 항목이 없습니다. "
              f"아래 항목의 verify 를 확인하고 verified: true 로 바꾸세요 → {', '.join(skipped)}")
    else:
        print("[stop] 큐가 비었습니다. content/queue.yaml 에 새 항목을 추가하세요.")
    return None


def build_caption(item: dict) -> str:
    tags = " ".join(f"#{t}" for t in item.get("hashtags", []))
    return f"{item['caption'].strip()}\n\n{tags}".strip()


def build_threads_text(item: dict) -> str:
    tags = " ".join(f"#{t}" for t in item.get("hashtags", [])[:3])
    return f"{item['threads_text'].strip()}\n\n{tags}".strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="렌더링만 하고 종료")
    ap.add_argument("--id", help="특정 항목 강제 발행")
    args = ap.parse_args()

    queue = yaml.safe_load(QUEUE.read_text(encoding="utf-8"))
    posted = load_posted()
    posted_ids = {p["id"] for p in posted}

    if args.id:
        item = next((i for i in queue["items"] if i["id"] == args.id), None)
        if item is None:
            print(f"[stop] id '{args.id}' 를 큐에서 찾을 수 없습니다.")
            return 1
    else:
        item = pick_next(queue, posted_ids)
        if item is None:
            return 0

    brand = queue.get("brand", "돈값하나?")
    outdir = IMAGES / item["id"]
    paths = render_item(item, outdir, brand)
    print(f"[render] {item['id']} · {item['product']} → {len(paths)}장")

    if args.dry_run:
        print(f"[dry-run] 이미지: {outdir}")
        print("--- 인스타 캡션 ---\n" + build_caption(item))
        print("--- 쓰레드 본문 ---\n" + build_threads_text(item))
        return 0

    # ---------------- 이미지를 커밋/푸시해서 공개 URL 확보
    repo = os.environ["GITHUB_REPOSITORY"]          # owner/repo
    sh("git", "add", str(outdir))
    if sh("git", "status", "--porcelain", str(outdir)):
        sh("git", "-c", "user.name=donvalue-bot",
           "-c", "user.email=bot@users.noreply.github.com",
           "commit", "-m", f"images: {item['id']}")
        sh("git", "push")
    sha = sh("git", "rev-parse", "HEAD")
    base = f"https://raw.githubusercontent.com/{repo}/{sha}/images/{item['id']}"
    urls = [f"{base}/{p.name}" for p in paths]
    print(f"[urls] {urls[0]}")

    results: dict[str, str] = {}
    errors: list[str] = []

    # ---------------- 인스타그램
    ig_id, ig_tok = os.getenv("IG_USER_ID"), os.getenv("IG_ACCESS_TOKEN")
    if ig_id and ig_tok:
        try:
            results["instagram"] = publish.publish_instagram(
                ig_id, ig_tok, urls, build_caption(item))
            print(f"[instagram] 발행 완료 media_id={results['instagram']}")
        except Exception as e:                                    # noqa: BLE001
            errors.append(f"instagram: {e}")
            print(f"[instagram] 실패: {e}")
    else:
        print("[instagram] 토큰 없음 → 건너뜀")

    # ---------------- 쓰레드
    th_id, th_tok = os.getenv("TH_USER_ID"), os.getenv("TH_ACCESS_TOKEN")
    if th_id and th_tok:
        try:
            results["threads"] = publish.publish_threads(
                th_id, th_tok, urls, build_threads_text(item))
            print(f"[threads] 발행 완료 post_id={results['threads']}")
        except Exception as e:                                    # noqa: BLE001
            errors.append(f"threads: {e}")
            print(f"[threads] 실패: {e}")
    else:
        print("[threads] 토큰 없음 → 건너뜀")

    if not results:
        print("[stop] 어느 플랫폼에도 발행하지 못했습니다. 큐를 소진하지 않고 종료합니다.")
        return 1

    # ---------------- 이력 기록 (한 곳이라도 성공하면 소진 처리)
    posted.append({
        "id": item["id"],
        "product": item["product"],
        "posted_at": datetime.now(KST).isoformat(timespec="seconds"),
        "results": results,
        "errors": errors,
    })
    POSTED.write_text(json.dumps(posted, ensure_ascii=False, indent=2), encoding="utf-8")
    sh("git", "add", str(POSTED))
    sh("git", "-c", "user.name=donvalue-bot",
       "-c", "user.email=bot@users.noreply.github.com",
       "commit", "-m", f"posted: {item['id']}")
    sh("git", "push")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
