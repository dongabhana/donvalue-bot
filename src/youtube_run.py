"""
이미 인스타에 나간 편을 유튜브 쇼츠로 '따라 올리는' 백필 도구.

왜 따로 있나
  평소 발행(src/run.py)은 릴스를 만든 그 자리에서 같은 mp4 를 쇼츠로도 올린다.
  플랫폼별 성장 비교가 목적이라 **같은 편이 같은 날 양쪽에 올라가야** 한다.

  그런데 유튜브를 나중에 붙였으니, 이미 인스타에만 나간 편들이 남는다.
  채널에 영상이 하나도 없으면 들어온 사람이 그냥 나간다. 그 구멍을 메우는 게
  이 스크립트다. 한 번 쓰고 끝나는 게 아니라, 카드뉴스로만 나간 편(=릴스 없음)을
  나중에 영상으로 만들어 올릴 때도 쓴다.

무엇을 고르나
  content/posted.json 에 있고(=인스타에 이미 나갔고)
  content/delivery.json 에 youtube 기록이 없는 편을 오래된 순으로.
  발행 원장 키는 run.py 와 같은 'youtube' 라서 같은 편을 두 번 올리지 않는다.

  python -m src.youtube_run --dry-run          # 영상만 만들어 텔레그램으로 확인
  python -m src.youtube_run --count 3          # 3편 백필
  python -m src.youtube_run --id 004-ott-stack # 특정 편
  python -m src.youtube_run --auto --count 3   # 정기 따라올리기(보류 스위치 + 하루 상한 적용)

하루 상한 (2026-09-22 추가)
  정기 실행(--auto)은 20분 간격으로 하루 종일 돈다. 밀린 편이 많을 때 매 실행마다
  3편씩 올라가면 유튜브 일일 할당량을 오전에 다 태우고 그날 남은 업로드가 전부
  실패한다. 그래서 --auto 는 오늘 올린 편 수를 delivery.json 에서 세어
  YT_DAILY_MAX(기본 3)편까지만 올린다. 손으로 돌리는 백필에는 적용하지 않는다.

승인 (2026-09-20 변경)
  유튜브에 올리는 편은 **이미 전날 승인을 거쳐 인스타에 나간 편**뿐이다.
  그래서 여기서 텔레그램 승인을 다시 묻지 않는다. (예전 notify.ask 호출은
  09-19 승인 통합 이후 approval_context 없이는 예외가 나서 업로드가 전부 막혔다.)
  대신 목소리 없는 영상은 올리지 않고, 올린 뒤 실제 공개상태를 다시 조회한다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from itertools import zip_longest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import codex_bridge, hooks, notify, youtube      # noqa: E402
from src.reel import build_reel_for                       # noqa: E402
from src.render import render_item                        # noqa: E402
from src.run import (DELIVERY, KST, POSTED, PREVIEW, QUEUE,  # noqa: E402
                     ROOT, build_caption, deliver_once)

GAP_MIN = int(os.getenv("YT_BACKFILL_GAP_MIN", "5"))
# 정기 따라올리기(--auto)가 하루에 올릴 수 있는 최대 편수. 유튜브 일일 할당량
# (기본 10,000 units / 업로드 1건 1,600 units)을 넘지 않게 여유를 둔 값.
DAILY_MAX = int(os.getenv("YT_DAILY_MAX", "3"))


def uploaded_ids() -> set[str]:
    if not DELIVERY.exists():
        return set()
    ledger = json.loads(DELIVERY.read_text(encoding="utf-8"))
    return {k for k, ops in ledger.items()
            if ops.get("youtube", {}).get("status") in ("done", "in_flight")}


def uploaded_today() -> tuple[int, list[str]]:
    """오늘(KST) API 로 유튜브에 올린 편 수와 그 id 들.

    왜 필요한가 —
      따라올리기를 하루 종일 20분 간격으로 돌린다(인스타·쓰레드에 나간 편을
      같은 날 유튜브에도 올리려는 것). 밀린 편이 많으면 매 실행마다 3편씩
      계속 올라가, 유튜브 일일 할당량(videos.insert 1건 1,600 units,
      프로젝트 기본 10,000/일 = 하루 6편 남짓)을 그날 오전에 다 태운다.
      할당량을 넘기면 그날 남은 업로드가 전부 실패하므로, '하루 몇 편'을
      크론이 아니라 코드에서 막는다.

      손으로 올린 편(source: manual-upload)은 API 할당량과 무관하므로 세지 않는다.
    """
    if not DELIVERY.exists():
        return 0, []
    today = datetime.now(KST).strftime("%Y-%m-%d")
    ids: list[str] = []
    for key, ops in json.loads(DELIVERY.read_text(encoding="utf-8")).items():
        y = ops.get("youtube") or {}
        if y.get("source") == "manual-upload":
            continue
        if y.get("status") == "in_flight":
            # 올리다 끊긴 편. 할당량은 이미 썼을 수 있으니 오늘 몫으로 센다.
            # 조용히 넘기지 않고 이름을 찍어 둔다(계속 남아 있으면 상한을 깎는다).
            print(f"[cap] ⚠ {key} 가 in_flight 로 남아 있습니다 — 오늘 몫 1편으로 셉니다")
            ids.append(key)
            continue
        if str(y.get("at", ""))[:10] == today:
            ids.append(key)
    return len(ids), ids


def posted_ids() -> list[str]:
    """인스타에 나간 순서대로. 같은 편이 여러 번 있으면 첫 기록만."""
    if not POSTED.exists():
        return []
    seen, out = set(), []
    for p in json.loads(POSTED.read_text(encoding="utf-8")):
        if p["id"] not in seen:
            seen.add(p["id"])
            out.append(p["id"])
    return out


def candidates(queue: dict, source: str = "all", strict: bool = False) -> list[dict]:
    """유튜브에 올릴 수 있는 편들을 '인스타에 나간 순서'로.

    콘텐츠가 두 군데(queue.yaml, codex/content.json)라 둘 다 훑는다.
    한쪽만 보면 GPT 트랙 편들이 통째로 빠져 채널에 구멍이 생긴다.

    strict=True(실제 업로드)면 GPT 트랙은 **실제 게시 기록**으로만 고른다.
    기록을 못 읽으면 GPT 편은 올리지 않는다 — 예정 시각이 지났다고
    나간 걸로 치면, 누락된 편(승인 안 된 편)이 유튜브에만 올라갈 수 있다.
    """
    done = uploaded_ids()
    q_rows: list[dict] = []
    c_rows: list[dict] = []

    if source in ("all", "queue"):
        by_id = {i["id"]: i for i in queue["items"]}
        for pid in posted_ids():
            if pid in by_id and pid not in done:
                q_rows.append(by_id[pid])

    if source in ("all", "codex"):
        records = codex_bridge.published_records()
        if strict and records is None:
            print("[codex] 게시 기록을 읽을 수 없어 GPT 트랙 편은 이번에 올리지 않습니다")
        else:
            for it in codex_bridge.load_items(only_published=True, records=records):
                if it["id"] not in done:
                    c_rows.append(it)

    # 두 트랙을 번갈아 낸다. 한쪽을 다 소진하고 넘어가면, 3편만 뽑을 때
    # 한쪽 트랙만 나와서 '다른 쪽은 왜 빠졌냐'는 오해가 생긴다.
    out: list[dict] = []
    for a, b in zip_longest(q_rows, c_rows):
        if a is not None:
            out.append(a)
        if b is not None:
            out.append(b)
    return out


def pick(queue: dict, want: str = "", count: int = 1,
         source: str = "all", strict: bool = False) -> list[dict]:
    if want:
        pool = {i["id"]: i for i in queue["items"]}
        pool.update({i["id"]: i for i in codex_bridge.load_items(only_published=False)})
        if want not in pool:
            print(f"[stop] '{want}' 를 두 콘텐츠 목록 어디서도 찾을 수 없습니다")
            return []
        if strict:
            # 실제로 올릴 때는 인스타에 나간(=승인된) 편만. 아직 안 나간 편을
            # --id 로 찍어 올리면 승인 없이 유튜브에만 먼저 나간다.
            published = {i["id"] for i in candidates(queue, source, strict=True)}
            if want in uploaded_ids():
                print(f"[stop] {want} 는 이미 유튜브 기록이 있습니다(중복 업로드 방지)")
                return []
            if want not in published:
                print(f"[stop] {want} 는 아직 인스타 게시 기록이 없어 올리지 않습니다")
                return []
        return [pool[want]]
    return candidates(queue, source, strict=strict)[:count]


# 윈도우에서 파일명에 못 쓰는 문자. 유튜브 제목엔 써도 되지만 파일명에선 빼야 한다.
_BAD_FILENAME = str.maketrans({c: " " for c in '\\/:*?"<>|\n\r\t'})


def filename_title(title: str) -> str:
    """유튜브 업로드 화면이 파일명을 제목 기본값으로 채운다는 점을 이용한다.

    파일명을 'NN_편id' 로 두면 업로드 후 26개 영상의 제목을 하나씩 지우고
    다시 타이핑해야 한다. 파일명을 제목 그대로 두면 그 단계가 통째로 사라진다.
    앞의 두 자리 번호는 업로드 순서를 유지하려고 남긴다(정렬용).
    """
    clean = " ".join(title.translate(_BAD_FILENAME).split())
    return clean[:90].rstrip(" .")          # 유튜브 제목 100자, 여유 두고 자른다


def save_bundle(item: dict, mp4: Path, title: str, desc: str) -> Path:
    """영상 + 제목 + 설명을 날짜 폴더 한 곳에 모은다.

    심사 통과 전까지는 이 폴더가 사실상의 '발행 대기함'이다.
        out/2026-09-14/
          01 쿠팡 와우 월 7890원, 본전 뽑는 사람 적다.mp4   ← 파일명 = 제목
          01 쿠팡 와우 월 7890원, 본전 뽑는 사람 적다.txt   ← 설명(그대로 붙여넣기)
          _업로드안내.txt                                  ← 전체 목록 한 장
    영상 여러 개를 한 번에 끌어다 놓으면 제목은 이미 채워져 있고,
    설명만 편당 한 번 붙여넣으면 된다.
    """
    day = datetime.now(KST).strftime("%Y-%m-%d")
    folder = ROOT / "out" / day
    folder.mkdir(parents=True, exist_ok=True)
    seq = len([p for p in folder.glob("*.mp4")]) + 1
    stem = f"{seq:02d} {filename_title(title)}"

    target = folder / f"{stem}.mp4"
    target.write_bytes(mp4.read_bytes())
    (folder / f"{stem}.txt").write_text(desc + "\n", encoding="utf-8")

    guide = folder / "_업로드안내.txt"
    if not guide.exists():
        guide.write_text(
            "유튜브 스튜디오 → 만들기 → 동영상 업로드\n"
            "mp4 를 한 번에 여러 개 끌어다 놓으면 제목은 파일명으로 자동으로 채워진다.\n"
            "편당 할 일은 설명 붙여넣기 하나뿐이다. 아래는 편별 설명 전문.\n"
            "공개 범위는 심사 통과 전까지 '비공개' 로 두지 말고 직접 올린 것이므로\n"
            "바로 공개해도 된다(API 로 올린 영상만 잠긴다).\n"
            + "=" * 60 + "\n", encoding="utf-8")
    with guide.open("a", encoding="utf-8") as fh:
        fh.write(f"\n[{seq:02d}] {title}\n{'-' * 60}\n{desc}\n")
    return target


def upload_one(item: dict, queue: dict, dry_run: bool) -> bool:
    brand = item.get("brand") or queue.get("brand", "돈값하나?")
    handle = queue.get("handle", "@dongabhana")
    cta = queue.get("cta") or {}
    h = hooks.resolve(item)

    outdir = PREVIEW / item["id"]
    paths = render_item(item, outdir, brand, handle, cta)
    mp4 = outdir / f"{item['id']}.mp4"
    _, note = build_reel_for(item, paths, mp4, brand, handle)

    title = youtube.build_title(item, h)
    # codex 편은 캡션에 해시태그까지 이미 들어 있다. build_caption 을 태우면
    # 꼬리말과 태그가 두 번 붙는다.
    caption = (item["caption"] if item.get("track") == "codex"
               else build_caption(item, cta))
    desc = youtube.build_description(item, caption, handle)
    size = mp4.stat().st_size / 1024 / 1024
    print(f"[shorts] {item['id']} · {note} ({size:.2f}MB)")
    print(f"[title ] {title}")

    if dry_run:
        # 손으로 올릴 거면 영상만 받아선 부족하다. 제목·설명을 매번 다시
        # 짜맞추는 게 진짜 귀찮은 일이라, 한 폴더에 같이 떨어뜨린다.
        bundle = save_bundle(item, mp4, title, desc)
        print(f"[bundle] {bundle}")
        if "목소리 없음" in note:
            print("[stop] ⚠ 나레이션이 들어가지 않았습니다. 위 [tts] 줄을 확인하세요.")
        if notify.enabled():
            try:
                warn = "  ⚠ 목소리 없음" if "목소리 없음" in note else ""
                notify.send_video(mp4, f"🔴 쇼츠 검토용 · {title}{warn}")
            except Exception as e:                                # noqa: BLE001
                print(f"[telegram] 전송 실패: {e}")
        return True

    # 나레이션 합성이 실패하면 음원만 깔린 영상이 조용히 나간다. 올리지 않는다.
    if "목소리 없음" in note:
        _tell(f"⚠ 유튜브 업로드 중단 · {title}\n나레이션이 비어 있어 올리지 않았어요. 로그의 [tts] 줄을 확인해주세요.")
        print("[stop] 나레이션 없음 → 올리지 않습니다")
        return False

    privacy = youtube.resolve_privacy()
    vid = deliver_once(item["id"], "youtube", lambda: youtube.upload_short(
        mp4, title, desc, youtube.build_tags(item)))
    url = youtube.watch_url(vid)
    print(f"[youtube] {url} (요청한 공개상태 {privacy})")

    # 업로드 응답만 믿지 않는다. 채널에서 다시 읽어 실제 공개상태를 본다.
    try:
        status = youtube.video_status(vid)
    except Exception as e:                                        # noqa: BLE001
        _tell(f"⚠ 유튜브 업로드 후 확인 실패 · {title}\n{url}\n{e}")
        print(f"[verify] 상태 조회 실패: {e}")
        return False
    actual = status.get("privacyStatus")
    print(f"[verify] 실제 공개상태={actual} 업로드상태={status.get('uploadStatus')}")
    if actual != privacy:
        # 공개로 올렸는데 비공개로 잠겼다 = 심사 미통과. 더 올리면 잠긴 영상만 쌓인다.
        _tell(f"⚠ 유튜브 공개상태 불일치 · {title}\n요청 {privacy} → 실제 {actual}\n{url}\n"
              "추가 업로드를 멈췄어요. 심사 상태를 확인해주세요.")
        return False
    _tell(f"🔴 유튜브 게시 완료 ({actual}) · {title}\n{url}")
    return True


def _tell(text: str) -> None:
    if not notify.enabled():
        return
    try:
        notify.send_message(text)
    except Exception as e:                                        # noqa: BLE001
        print(f"[telegram] 전송 실패: {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default="", help="특정 편만")
    ap.add_argument("--count", type=int, default=1, help="몇 편 백필할지")
    ap.add_argument("--source", default="all", choices=["all", "queue", "codex"],
                    help="어느 콘텐츠 목록에서 고를지 (기본 all)")
    ap.add_argument("--list", action="store_true",
                    help="올릴 수 있는 편 목록만 보여주고 끝낸다")
    ap.add_argument("--dry-run", action="store_true",
                    help="올리지 않고 영상만 만들어 텔레그램으로 확인")
    ap.add_argument("--auto", action="store_true",
                    help="정기 따라올리기 — content/youtube_hold.json 보류 중이면 아무것도 안 함")
    args = ap.parse_args()

    if args.auto and not args.dry_run:
        reason = youtube.hold_reason()
        if reason:
            print(f"[stop] 유튜브 보류 중 — {reason}")
            return 0
        # 하루 상한. 20분 간격으로 하루 종일 도는 정기 실행에만 적용한다.
        # 손으로 돌리는 백필(--id / --count)은 사람이 일부러 누른 것이므로 막지 않는다.
        used, used_ids = uploaded_today()
        room = max(0, DAILY_MAX - used)
        if room <= 0:
            print(f"[stop] 오늘 이미 {used}편 올렸습니다 (하루 상한 {DAILY_MAX}편) "
                  f"— {', '.join(used_ids)}. 남은 편은 내일 이어서 올립니다")
            return 0
        if args.count > room:
            print(f"[cap] 이번 실행 {args.count}편 → {room}편으로 줄입니다 "
                  f"(오늘 {used}편 올림 / 상한 {DAILY_MAX}편)")
            args.count = room

    queue = hooks.attach(yaml.safe_load(QUEUE.read_text(encoding="utf-8")))

    if args.list:
        rows = candidates(queue, args.source)
        done = uploaded_ids()
        print(f"이미 유튜브에 올림: {len(done)}편")
        print(f"올릴 수 있는 편: {len(rows)}편\n")
        for n, it in enumerate(rows, 1):
            src = "codex" if it.get("track") == "codex" else "queue"
            print(f"  {n:2}. [{src:5}] {it['id']:24} {it.get('product', '')}")
        return 0

    if not args.dry_run and not youtube.configured():
        print("[stop] 유튜브 인증정보가 없습니다 (YT_* 또는 YOUTUBE_TOKEN_JSON)")
        return 0

    items = pick(queue, args.id, max(1, args.count), args.source,
                 strict=not args.dry_run)
    if not items:
        print("[stop] 유튜브에 올릴 편이 없습니다 (이미 다 올렸거나 발행 이력이 없음)")
        return 0

    print(f"[backfill] {len(items)}편: {', '.join(i['id'] for i in items)}")
    for n, item in enumerate(items):
        if n and not args.dry_run:
            print(f"[backfill] {GAP_MIN}분 대기")
            time.sleep(GAP_MIN * 60)
        if not upload_one(item, queue, args.dry_run):
            # 실패를 '성공(초록불)'으로 숨기지 않는다. Actions 에 빨간불로 남긴다.
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
