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
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.render import render_item                      # noqa: E402
from src.reel import build_reel_for, plan_summary       # noqa: E402
from src import publish                                 # noqa: E402
from src import hooks                                   # noqa: E402
from src import notify                                  # noqa: E402
from src import youtube                                 # noqa: E402
from src import approval                                # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "content" / "queue.yaml"
POSTED = ROOT / "content" / "posted.json"
DELIVERY = ROOT / "content" / "delivery.json"
IMAGES = ROOT / "images"
# 미리보기 렌더는 저장소에 남기지 않는다(.gitignore 처리). 발행분만 images/ 에 커밋된다.
PREVIEW = ROOT / ".preview"
KST = timezone(timedelta(hours=9))


def sh(*args: str) -> str:
    return subprocess.run(args, cwd=ROOT, check=True, capture_output=True,
                          text=True).stdout.strip()


def push(tries: int = 5) -> None:
    """push 가 밀리면 rebase 후 다시 시도한다.

    같은 저장소에 다른 워크플로(예: 15분 주기 승인 봇)가 동시에 커밋하면
    push 가 non-fast-forward 로 거부된다. 승인 대기 몇 분 사이에 흔히 생긴다.
    원격 변경을 rebase 하고 재시도한다. 이미지나 발행 기록이 충돌하면
    자동 병합으로 덮어쓰지 않고 중단한다.
    """
    last = ""
    for n in range(1, tries + 1):
        try:
            sh("git", "push")
            return
        except subprocess.CalledProcessError as e:                # noqa: PERF203
            last = (e.stderr or e.stdout or "").strip()
            if n == tries:
                break
            print(f"[git] push 거부({n}/{tries}) → 원격 반영 후 재시도")
            try:
                sh("git", "-c", "user.name=donvalue-bot",
                   "-c", "user.email=bot@users.noreply.github.com",
                   "pull", "--rebase", "--autostash")
            except subprocess.CalledProcessError as pe:
                print(f"[git] rebase 실패: {(pe.stderr or '').strip()[:300]}")
                try:
                    sh("git", "rebase", "--abort")
                except subprocess.CalledProcessError:
                    pass
                raise RuntimeError("원격 변경과 충돌하여 발행을 중단했습니다. "
                                   "발행 기록을 확인한 뒤 재실행하세요.") from None
            time.sleep(3 * n)
    raise RuntimeError(f"git push 실패(재시도 {tries}회): {last[:400]}")


def load_posted() -> list[dict]:
    if POSTED.exists():
        return json.loads(POSTED.read_text(encoding="utf-8"))
    return []


def deliver_once(item_id: str, key: str, action):
    """Persist the attempt before an external write; uncertain attempts need review."""
    ledger = json.loads(DELIVERY.read_text()) if DELIVERY.exists() else {}
    operations = ledger.setdefault(item_id, {})
    old = operations.get(key)
    if old:
        if old['status'] == 'done':
            return old['id']
        raise RuntimeError(f"{item_id}/{key}: 이전 발행 결과 확인이 필요합니다")

    def save():
        DELIVERY.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding='utf-8')
        sh('git', 'add', str(DELIVERY))
        sh('git', '-c', 'user.name=donvalue-bot', '-c', 'user.email=bot@users.noreply.github.com',
           'commit', '-m', f'delivery: {item_id}/{key} {operations[key]["status"]}')
        push()

    operations[key] = {'status': 'in_flight'}
    save()
    result = action()
    operations[key] = {'status': 'done', 'id': result,
                       'at': datetime.now(KST).isoformat(timespec='seconds')}
    save()
    return result


def pick_next(queue: dict, posted_ids: set[str], only: str = "") -> dict | None:
    """다음 발행분을 고른다.

    only 를 주면 그 포맷으로 지정된 편만 고른다(예: 프로필을 채우려고
    카드뉴스만 몰아서 낼 때). 지정이 없는 편은 대상이 아니다.
    """
    skipped: list[str] = []
    for item in queue["items"]:
        if item["id"] in posted_ids:
            continue
        if only and (item.get("ig_format") or "").lower() != only:
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


def build_caption(item: dict, cta: dict | None = None) -> str:
    """인스타 캡션. 마지막에 댓글 요청 한 줄을 붙인다.

    댓글은 참여 신호이자 다음 소재의 공급원이라 두 번 남는 장사다.
    """
    cta = cta or {}
    tail = cta.get("caption_tail",
                   "다음에 계산해줬으면 하는 거 있으면 댓글로 남겨주세요. 하나씩 다 따져봅니다.")
    tags = " ".join(f"#{t}" for t in item.get("hashtags", []))
    body = item["caption"].strip()
    # 캡션은 약 125자에서 '... 더 보기'로 잘린다. 첫 줄이 사실상 두 번째 훅이다.
    head = hooks.caption_first_line(item)
    if head and not body.startswith(head[:12]):
        body = f"{head}\n\n{body}"
    if tail:
        body = f"{body}\n\n{tail}"
    return f"{body}\n\n{tags}".strip()


def build_threads_text(item: dict, cta: dict | None = None, ig_format: str = "") -> str:
    """쓰레드용 본문. 쓰레드는 게시물당 주제 태그를 1개만 인식한다.

    인스타에 릴스가 나가는 날에는 꼬리말을 바꿔 '영상 버전이 저쪽에 있다'고 알린다.
    쓰레드가 인스타보다 초반 도달이 빠르니, 교차 유입은 이 방향이 효율이 좋다.
    """
    cta = cta or {}
    body = item["threads_text"].strip()

    question = (item.get("threads_question") or "").strip()
    if question:
        body = f"{body}\n\n{question}"

    default_tail = "다음에 뭐 계산해볼까요? 궁금한 거 답글로 남겨주세요."
    if ig_format == "reel":
        tail = cta.get("threads_reel_tail") or cta.get("threads_tail", default_tail)
    else:
        tail = cta.get("threads_tail", default_tail)
    if tail:
        body = f"{body}\n\n{tail}"

    tag = item.get("threads_tag") or (item.get("hashtags") or [None])[0]
    if tag:
        body = f"{body}\n\n#{str(tag).lstrip('#')}"
    return body.strip()


def build_first_comment(item: dict, cta: dict | None = None) -> str:
    """발행 직후 내 게시물에 다는 첫 댓글.

    댓글창이 비어 있으면 아무도 첫 번째가 되고 싶어 하지 않는다.
    기준·출처처럼 캡션에 넣기엔 긴 내용도 여기로 빼면 캡션이 깔끔해진다.
    """
    return (item.get("first_comment") or (cta or {}).get("first_comment") or "").strip()


def threads_images(paths: list) -> list:
    """쓰레드에는 표지와 결론 2장만 보낸다."""
    if len(paths) <= 2:
        return list(paths)
    return [paths[0], paths[-1]]


def _commit(paths: list, message: str) -> bool:
    """대상에 바뀐 게 있을 때만 커밋·푸시한다. 반환값은 실제로 커밋했는지 여부."""
    targets = [str(p) for p in paths]
    sh("git", "add", *targets)
    if not sh("git", "status", "--porcelain", *targets):
        return False
    sh("git", "-c", "user.name=donvalue-bot",
       "-c", "user.email=bot@users.noreply.github.com",
       "commit", "-m", message)
    push()
    return True


def ask_for_tomorrow(item: dict, ig_format: str, paths: list, mp4, body: str,
                     digest: str) -> int:
    """발행 전날 20:00 — 내일 나갈 것을 통째로 보여주고 승인을 받아 둔다.

    승인 결과를 저장소(content/approval.json)에 남기는 이유는, 내일 20:00 의
    실행이 오늘 이 실행과 완전히 다른 런이라 메모리를 공유하지 않기 때문이다.
    렌더 결과물도 지금 커밋해 둔다. 내일 다시 렌더하면 승인한 것과 달라질 수 있다.
    """
    outdir = Path(paths[0]).parent
    publish_date = approval.publish_date_for()

    _commit([outdir], f"preview: {item['id']} ({publish_date} 발행 예정)")

    if not notify.enabled():
        print("[stop] 텔레그램이 설정되지 않아 전날 승인을 받을 수 없습니다.")
        return 1

    wait = int(os.getenv("EVE_APPROVAL_TIMEOUT_MIN", "180"))
    answer = notify.ask(
        item["id"], f"{item['product']} ({ig_format})", body,
        video=mp4, photos=[paths[0], paths[-1]] if not mp4 else None,
        timeout_min=wait,
        prompt=(f"{notify.LABEL} · 내일 {publish_date} 20:00 에 이대로 나갑니다.\n"
                f"[승인] 을 누르면 내일 자동으로 발행되고, "
                f"[수정] 을 누르면 발행하지 않습니다.\n"
                f"({wait}분 안에 응답이 없으면 내일 20:00 에 한 번 더 물어봅니다)"),
        approve_label="✅ 승인", reject_label="✏️ 수정", collect_note=True)

    decision = {True: approval.APPROVED,
                False: approval.REVISE}.get(answer, approval.PENDING)
    approval.record(item["id"], decision, ig_format, digest, publish_date,
                    note=notify.last_note.get(item["id"], ""))
    _commit([approval.LEDGER], f"approval: {item['id']} {decision} ({publish_date})")
    print(f"[approval] {item['id']} → {decision} (발행 예정일 {publish_date})")
    return 0


def run_once(args) -> int:
    # 직접 Namespace 를 만들어 호출하는 곳(테스트 등)이 있어 기본값을 여기서 채운다.
    ask_tomorrow = getattr(args, "ask_tomorrow", False)

    # content/hooks.yaml 을 각 항목의 reel 블록으로 합친다(릴스 훅·화자·배경음 무드).
    queue = hooks.attach(yaml.safe_load(QUEUE.read_text(encoding="utf-8")))
    posted = load_posted()
    posted_ids = {p["id"] for p in posted}

    if args.id:
        item = next((i for i in queue["items"] if i["id"] == args.id), None)
        if item is None:
            print(f"[stop] id '{args.id}' 를 큐에서 찾을 수 없습니다.")
            return 1
        if item['id'] in posted_ids:
            print(f"[stop] {item['id']}는 이미 발행됐습니다")
            return 0
        if not item.get('verified'):
            print(f"[stop] {item['id']}는 사실 검수가 필요합니다")
            return 1
    else:
        item = pick_next(queue, posted_ids, (args.pick or "").lower())
        if item is None:
            return 0

    # 편에 brand 가 있으면 그 편만 다른 시리즈 이름으로 나간다
    brand = item.get("brand") or queue.get("brand", "돈값하나?")
    handle = queue.get("handle", "@dongabhana")
    cta = queue.get("cta") or {}

    # ---------------- 오늘의 인스타 포맷
    # "reel"(기본) | "carousel" | "both"
    # 팔로워가 적을 때 비팔로워에게 닿는 건 사실상 릴스뿐이라, 초반에는 릴스 비중을 높게 간다.
    # 카드뉴스는 프로필에 들어온 사람이 볼 깊이 있는 콘텐츠 역할만 맡는다.
    # 0=월 … 6=일. 큐의 ig_format_by_weekday 로 언제든 바꿀 수 있다.
    # 쓰레드 꼬리말도 이 값을 보고 갈리므로 dry-run(전날 검토)에서도 먼저 정해둔다.
    by_weekday = queue.get("ig_format_by_weekday") or {1: "reel", 3: "carousel", 6: "reel"}
    when = datetime.now(KST) + timedelta(days=1 if (args.tomorrow or ask_tomorrow) else 0)
    wd = when.weekday()
    ig_format = ((args.pick or "").lower() or item.get("ig_format")
                 or os.getenv("IG_FORMAT")
                 or by_weekday.get(wd)
                 or queue.get("ig_format_default")
                 or "reel").lower()
    print(f"[format] {'내일' if (args.tomorrow or ask_tomorrow) else '오늘'} "
          f"{'월화수목금토일'[wd]}요일 → {ig_format}")

    for w in hooks.validate(item):
        print(f"[hook] ⚠ {item['id']}: {w}")

    outdir = (PREVIEW if args.dry_run else IMAGES) / item["id"]

    # ---------------- 전날 승인분 재사용
    # 어제 승인받은 그림·영상을 그대로 올린다. 다시 렌더하면 그레인·음원 선택·
    # 나레이션 합성처럼 매번 달라질 수 있는 요소 때문에 '승인한 것과 다른 것'이
    # 나갈 수 있다. 승인의 의미를 지키려면 결과물을 재사용해야 한다.
    prior = (None if (args.dry_run or ask_tomorrow or args.id)
             else approval.lookup(item["id"]))
    cached_mp4 = outdir / f"{item['id']}.mp4"
    reused = False
    if prior and prior.get("decision") == approval.APPROVED \
            and prior.get("ig_format") == ig_format:
        cached = sorted(outdir.glob("*.png"))
        if cached and (ig_format == "carousel" or cached_mp4.exists()):
            paths, reused = cached, True
            print(f"[approval] 전날 승인분 재사용 → {len(paths)}장"
                  + (f" + {cached_mp4.name}" if cached_mp4.exists() else ""))
    if not reused:
        paths = render_item(item, outdir, brand, handle, cta)
        print(f"[render] {item['id']} · {item['product']} → {len(paths)}장")

    results: dict[str, str] = {}
    errors: list[str] = []

    # 릴스는 발행 전에 미리 만들어 둔다. 승인 화면에 '실제로 나갈 영상'이 보여야
    # 검토가 의미가 있고, 승인 후 인코딩을 기다릴 필요도 없다.
    mp4: Path | None = None
    if ig_format in ("reel", "both") and reused and cached_mp4.exists():
        mp4 = cached_mp4
        print(f"[reel] 전날 승인분 재사용 {mp4.name} "
              f"({mp4.stat().st_size / 1024 / 1024:.2f}MB)")
    elif ig_format in ("reel", "both"):
        try:
            mp4 = outdir / f"{item['id']}.mp4"
            _, plan_note = build_reel_for(item, paths, mp4, brand, handle)
            print(f"[reel] {mp4.name} · {plan_note} "
                  f"({mp4.stat().st_size / 1024 / 1024:.2f}MB)")
        except Exception as e:                                    # noqa: BLE001
            errors.append(f"instagram_reel: {e}")
            print(f"[reel] 실패: {e}")
            mp4 = None

    if args.dry_run:
        print(f"[dry-run] 이미지: {outdir}")
        print(f"[reel-plan] {plan_summary(item, paths)}")
        if mp4:
            print(f"[dry-run] 릴스: {mp4}")
        print("--- 인스타 캡션 ---\n" + build_caption(item, cta))
        print("--- 첫 댓글 ---\n" + (build_first_comment(item, cta) or "(없음)"))
        print("--- 쓰레드 본문 ---\n" + build_threads_text(item, cta, ig_format))
        chain = [str(t).strip() for t in (item.get("threads_chain") or []) if str(t).strip()]
        for i, t in enumerate(chain, start=1):
            print(f"--- 쓰레드 답글 {i} ---\n{t}")
        if not chain:
            print("--- 쓰레드 답글 ---\n(없음)")
        if mp4:
            h_yt = hooks.resolve(item)
            print("--- 유튜브 제목 ---\n" + youtube.build_title(item, h_yt))
            print("--- 유튜브 설명 ---\n"
                  + youtube.build_description(item, build_caption(item, cta), handle))
        if notify.enabled():
            try:
                preview = (f"[검토용 · 발행 안 함]\n\n{build_caption(item, cta)}")
                if mp4:
                    notify.send_video(mp4, f"🗂 {item['product']} <{item['id']}>")
                else:
                    notify.send_photos([paths[0], paths[-1]],
                                       f"🗂 {item['product']} <{item['id']}>")
                notify.send_message(preview)
            except Exception as e:                                # noqa: BLE001
                print(f"[telegram] 전송 실패: {e}")
        return 0

    # ---------------- 발행 승인 (텔레그램)
    # 승인이 아니면 큐를 소진하지 않는다. 같은 편이 다음 회차에 다시 올라온다.
    caption_text = build_caption(item, cta)
    # threads_text 가 없는 편(인스타 전용)도 있으므로 없으면 빈 값으로 둔다.
    threads_preview = (build_threads_text(item, cta, ig_format)
                       if item.get("threads_text") else "")
    digest = approval.fingerprint(item["id"], ig_format, caption_text,
                                  threads_preview,
                                  list(paths) + ([mp4] if mp4 else []))
    body = ("--- 인스타 캡션 ---\n" + caption_text
            + "\n\n--- 쓰레드 ---\n" + threads_preview)

    if ask_tomorrow:
        return ask_for_tomorrow(item, ig_format, paths, mp4, body, digest)

    approved_earlier = False
    if prior and prior.get("decision") == approval.REVISE:
        note = prior.get("note") or "(메모 없음)"
        print(f"[stop] 전날 검토에서 '수정'을 선택한 편입니다 → 발행하지 않습니다. "
              f"메모: {note}")
        if notify.enabled():
            try:
                notify.send_message(
                    f"{notify.LABEL} · 오늘 발행을 건너뜁니다\n"
                    f"{item['product']} <{item['id']}>\n"
                    f"전날 검토에서 '수정'을 선택하셨습니다.\n메모: {note}")
            except Exception as e:                                # noqa: BLE001
                print(f"[telegram] 통보 실패: {e}")
        return 0
    if prior and prior.get("decision") == approval.APPROVED:
        if prior.get("fingerprint") == digest:
            approved_earlier = True
            print(f"[approval] 전날 승인({prior.get('decided_at', '')}) 확인 "
                  f"→ 바로 발행합니다")
        else:
            # 승인한 것과 지금 나갈 것이 다르다. 조용히 넘기면 승인이 무의미해진다.
            print("[approval] ⚠ 승인 이후 내용이 바뀌었습니다 → 지금 다시 확인합니다")

    if (not approved_earlier) and notify.enabled() \
            and os.getenv("APPROVAL_REQUIRED", "1") == "1":
        answer = notify.ask(item["id"], f"{item['product']} ({ig_format})", body,
                            video=mp4,
                            photos=[paths[0], paths[-1]] if not mp4 else None)
        if answer is not True:
            print("[stop] " + ("반려됨" if answer is False else "승인 응답 없음")
                  + " → 발행하지 않고 종료합니다(큐 유지).")
            return 0

    # ---------------- 이미지를 커밋/푸시해서 공개 URL 확보
    repo = os.environ["GITHUB_REPOSITORY"]          # owner/repo
    sh("git", "add", str(outdir))
    if sh("git", "status", "--porcelain", str(outdir)):
        sh("git", "-c", "user.name=donvalue-bot",
           "-c", "user.email=bot@users.noreply.github.com",
           "commit", "-m", f"images: {item['id']}")
        push()
    sha = sh("git", "rev-parse", "HEAD")
    base = f"https://raw.githubusercontent.com/{repo}/{sha}/images/{item['id']}"
    urls = [f"{base}/{p.name}" for p in paths]
    print(f"[urls] {urls[0]}")

    # ---------------- 인스타그램 (포맷은 위에서 이미 정해졌다)
    ig_id, ig_tok = os.getenv("IG_USER_ID"), os.getenv("IG_ACCESS_TOKEN")

    if ig_id and ig_tok:
        did_reel = False
        if mp4 is not None:
            try:
                sh("git", "add", str(mp4))
                if sh("git", "diff", "--cached", "--name-only", str(mp4)):
                    sh("git", "-c", "user.name=donvalue-bot",
                       "-c", "user.email=bot@users.noreply.github.com",
                       "commit", "-m", f"reel: {item['id']}")
                push()
                sha2 = sh("git", "rev-parse", "HEAD")
                video_url = (f"https://raw.githubusercontent.com/{repo}/{sha2}"
                             f"/images/{item['id']}/{mp4.name}")
                results["instagram_reel"] = deliver_once(item['id'], 'instagram_reel', lambda: publish.publish_instagram_reel(
                    ig_id, ig_tok, video_url, build_caption(item, cta), urls[0]))
                print(f"[reel] 발행 완료 media_id={results['instagram_reel']}")
                did_reel = True
            except Exception as e:                                # noqa: BLE001
                errors.append(f"instagram_reel: {e}")
                print(f"[reel] 실패: {e}")

        # 릴스만 하기로 했는데 실패하면 캐러셀로 폴백한다(빈손으로 끝내지 않는다).
        # 다만 이미 발행한 편을 --id 로 재실행한 경우엔 폴백하지 않는다.
        # 그 경우 폴백은 같은 내용을 두 번 올리는 중복 발행이 된다.
        already_posted = item["id"] in posted_ids
        ledger = json.loads(DELIVERY.read_text()) if DELIVERY.exists() else {}
        uncertain_reel = ledger.get(item['id'], {}).get('instagram_reel', {}).get('status') == 'in_flight'
        allow_fallback = (ig_format == "reel" and not did_reel and not already_posted and not uncertain_reel)
        if already_posted and not did_reel:
            print("[instagram] 이미 발행된 편이라 캐러셀 폴백을 건너뜁니다(중복 방지)")
        if ig_format in ("carousel", "both") or allow_fallback:
            try:
                results["instagram"] = deliver_once(item['id'], 'instagram', lambda: publish.publish_instagram(
                    ig_id, ig_tok, urls, build_caption(item, cta)))
                print(f"[instagram] 발행 완료 media_id={results['instagram']}")
            except Exception as e:                                # noqa: BLE001
                errors.append(f"instagram: {e}")
                print(f"[instagram] 실패: {e}")
        # 발행된 게시물마다 첫 댓글을 단다.
        # 권한(instagram_business_manage_comments)이 없어도 발행은 이미 끝났으니
        # 여기서 실패해도 전체를 실패로 처리하지 않는다.
        first = build_first_comment(item, cta)
        if first:
            for key in ("instagram_reel", "instagram"):
                mid = results.get(key)
                if not mid:
                    continue
                try:
                    cid = deliver_once(item['id'], key+'_comment', lambda: publish.publish_instagram_comment(mid, ig_tok, first))
                    results[f"{key}_comment"] = cid
                    print(f"[comment] {key} 첫 댓글 완료 id={cid}")
                except Exception as e:                            # noqa: BLE001
                    errors.append(f"{key}_comment: {e}")
                    print(f"[comment] {key} 첫 댓글 실패(발행은 정상): {e}")
    else:
        print("[instagram] 토큰 없음 → 건너뜀")

    # ---------------- 유튜브 쇼츠
    # 같은 mp4 를 그대로 올린다. 추가 제작비가 없고, 유튜브는 릴스와 달리
    # 반년 뒤에도 검색·추천으로 조회가 붙어 '재고'로 남는다.
    # ⚠ 구글 심사(audit) 전에는 올라간 영상이 비공개로 잠긴다 → YT_PRIVACY=private 기본
    # ⚠ 더 중요한 것: 잠긴 채로 원장에 'done' 이 박히면 심사 통과 후 몰아 올릴 때
    #    그 편을 건너뛴다. 그래서 심사 전에는 아예 올리지 않는다(youtube.hold_reason).
    yt_hold = youtube.hold_reason()
    if mp4 is not None and youtube.configured() and not yt_hold:
        try:
            h_yt = hooks.resolve(item)
            vid = deliver_once(item["id"], "youtube", lambda: youtube.publish_short(
                item, mp4, build_caption(item, cta), handle, h_yt))
            results["youtube"] = vid
            privacy = os.getenv("YT_PRIVACY", "private")
            print(f"[youtube] 발행 완료 {youtube.watch_url(vid)} (공개상태 {privacy})")
            if privacy != "public":
                print("[youtube] ※ 아직 비공개입니다. 심사 통과 후 YT_PRIVACY=public 으로 바꾸세요.")
        except Exception as e:                                    # noqa: BLE001
            errors.append(f"youtube: {e}")
            print(f"[youtube] 실패: {e}")
    elif mp4 is not None and youtube.configured():
        print(f"[youtube] 보류 중이라 올리지 않습니다 — {yt_hold}")
        print("[youtube] 심사 통과 후 '유튜브 쇼츠 백필' 워크플로로 몰아서 올립니다.")
    elif mp4 is not None:
        print("[youtube] 토큰 없음 → 건너뜀")

    # ---------------- 쓰레드
    # 같은 시각에 두 플랫폼에 같은 내용이 뜨면 서로 도달을 갉아먹는다.
    stagger = int(os.getenv("STAGGER_MIN", "10"))
    # 이미 쓰레드에 올린 편의 릴스만 추가로 낼 때 중복 발행을 막는다.
    skip_threads = os.getenv("SKIP_THREADS", "").lower() in ("1", "true", "yes")
    th_id, th_tok = os.getenv("TH_USER_ID"), os.getenv("TH_ACCESS_TOKEN")
    if skip_threads:
        th_id = th_tok = None
        print("[threads] SKIP_THREADS 설정 → 건너뜀")
    if th_id and th_tok:
        if stagger > 0 and results:
            print(f"[stagger] 쓰레드 발행까지 {stagger}분 대기")
            time.sleep(stagger * 60)
        try:
            th_names = {p.name for p in threads_images(paths)}
            th_urls = [u for u in urls if u.rsplit("/", 1)[-1] in th_names]
            print(f"[threads] 이미지 {len(th_urls)}장 (표지+결론)")
            results["threads"] = deliver_once(item['id'], 'threads', lambda: publish.publish_threads(
                th_id, th_tok, th_urls, build_threads_text(item, cta, ig_format), topic_tag=item.get('threads_tag')))
            print(f"[threads] 발행 완료 post_id={results['threads']}")

            # 내 글에 답글을 이어 단다. 쓰레드는 답글이 붙은 글을 더 밀어준다.
            chain = [t for t in (item.get("threads_chain") or []) if str(t).strip()]
            if chain:
                try:
                    ids = deliver_once(item['id'], 'threads_chain', lambda: publish.publish_threads_chain(
                        th_id, th_tok, results["threads"], chain))
                    results["threads_chain"] = ",".join(ids)
                    print(f"[threads] 답글 {len(ids)}개 완료")
                except Exception as e:                            # noqa: BLE001
                    errors.append(f"threads_chain: {e}")
                    print(f"[threads] 답글 실패(본문은 정상): {e}")
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
    notify.done(item["id"], item["product"], results, errors)
    # 다 쓴 승인은 원장에서 지운다. 남겨두면 나중에 같은 승인이 또 통과할 수 있다.
    approval.consume(item["id"])
    targets = [str(POSTED)] + ([str(approval.LEDGER)] if approval.LEDGER.exists()
                               else [])
    sh("git", "add", "-A", *targets)
    sh("git", "-c", "user.name=donvalue-bot",
       "-c", "user.email=bot@users.noreply.github.com",
       "commit", "-m", f"posted: {item['id']}")
    push()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="렌더링만 하고 종료")
    ap.add_argument("--id", help="특정 항목 강제 발행")
    ap.add_argument("--tomorrow", action="store_true",
                    help="내일 기준으로 포맷을 계산 (발행 전날 검토용)")
    ap.add_argument("--ask-tomorrow", action="store_true",
                    help="내일 나갈 편을 렌더해 텔레그램으로 승인받아 둔다 "
                         "(발행 전날 20:00). 승인은 content/approval.json 에 남는다")
    ap.add_argument("--pick", default="",
                    help="이 ig_format 으로 지정된 편만 고른다 (carousel | reel)")
    ap.add_argument("--count", type=int, default=1,
                    help="한 번에 몇 편을 낼지. 밀린 카드뉴스 소진용 (기본 1)")
    args = ap.parse_args()

    # 전날 승인 모드는 '내일 나갈 것'을 보여주는 것이므로 포맷도 내일 기준이어야 한다.
    # 그리고 하루에 한 편만 묻는다(여러 편을 한꺼번에 승인받으면 무엇을 승인했는지 흐려진다).
    if args.ask_tomorrow:
        args.tomorrow = True
        args.count = 1

    # 같은 날 여러 편을 몰아 올리면 뒤 글이 앞 글의 도달을 먹는다.
    # 그래도 프로필을 채워야 할 때가 있어 간격을 두고 순차 발행한다.
    gap = int(os.getenv("BURST_GAP_MIN", "40"))
    count = 1 if args.id else max(1, args.count)
    if count > 1:
        print(f"[burst] {count}편을 {gap}분 간격으로 발행합니다")

    rc = 0
    previous_start = None
    for n in range(count):
        if previous_start is not None and not args.dry_run:
            remaining = max(0, gap * 60 - (time.monotonic() - previous_start))
            print(f"[burst] {remaining / 60:.1f}분 후 {n + 1}번째 편 (시작 간격 {gap}분)")
            time.sleep(remaining)
        previous_start = time.monotonic()
        rc = run_once(args)
        if rc:
            break
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
