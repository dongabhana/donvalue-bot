"""발행 시계 — GitHub 예약 실행(schedule) 없이 매일 슬롯에 post.yml 을 돌린다.

왜 필요한가 (2026-10-15)
  10/11부터 이 저장소의 schedule 실행이 하루 62회 → 5회로 줄고, 몇 시간씩 밀리거나 빠졌다.
  10/13·10/14 정기 발행이 연속으로 시작조차 안 됐다. GitHub 문서도 schedule 은 부하가 높으면
  '지연되거나 떨어질 수 있다'고 적는다. 반면 workflow_dispatch 는 GITHUB_TOKEN 으로 보내도
  '항상 실행이 만들어진다'(문서 명시). 그래서 시계를 dispatch 로만 굴린다.

동작
  publish-clock.yml 한 실행이 최대 BUDGET_MIN 동안 깨어 있으면서
    · 슬롯이 되면(또는 슬롯 뒤 CATCHUP_MIN 안에 아직 안 나갔으면) post.yml 을 dispatch 하고
    · 남은 시간이 부족하면 자기 자신(publish-clock.yml)을 dispatch 해서 바통을 넘긴다.
  하루 24시간을 4~5번의 릴레이로 잇는다. 공개 저장소라 러너 시간은 무료다.

중복·안전
  · 이미 오늘 게시 기록(posted.json)이 있으면 dispatch 하지 않는다.
  · post.yml 이 대기/실행 중이면 끝날 때까지 기다린다(두 번 쏘지 않음).
  · 한 슬롯에 dispatch 는 한 번. post.yml 자체도 '오늘은 이미 한 편' 검사가 있다.
  · 체인이 끊기면 publish-clock-watchdog.yml(예약)이나 사람이 다시 켠다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
# src/run.py 의 SLOTS 와 같아야 한다(테스트가 검사).
SLOTS = {0: (21, 20), 1: (21, 20), 2: (21, 20), 3: (21, 20),
         4: (15, 30), 5: (15, 30), 6: (15, 30)}
# 2026-10-15: 쓰레드 스하리 글(threads-micro.yml, 매일 21:40)도 같은 예약 누락을 겪어서 시계가 함께 챙긴다.
SOFT_SLOTS = {d: (21, 40) for d in range(7)}
CATCHUP_MIN = 180          # 슬롯 뒤 이 시간 안에 안 나갔으면 따라잡는다
BUDGET_MIN = 320           # 한 실행이 깨어 있는 최대 시간(잡 제한 360분 안쪽)
POLL_MIN = 5               # post.yml 이 돌고 있을 때 다시 볼 간격
# 2026-10-21: 10/20 발행이 TTS 429 로 실패했는데 같은 실행은 다시 쏘지 않아 그날을 놓쳤다.
# 실패하면 RETRY_MIN 뒤 다시 쏜다(한 슬롯 최대 MAX_TRIES 번). 이미 나간 플랫폼은 발행 원장
# (delivery.json)이 건너뛰고, 반쯤 나간 건 post.yml 이 멈추므로 다시 쏴도 중복 게시는 없다.
RETRY_MIN = 40
MAX_TRIES = 3
# 슬롯 몇 분 전에 다음 편 나레이션을 미리 만든다(tts-prewarm.yml). 이미 만들어져 있으면 금방 끝난다.
PREWARM_BEFORE_MIN = (180, 90, 40)
PREWARM_WINDOW_MIN = 20
REPO = os.getenv("GITHUB_REPOSITORY", "dongabhana/donvalue-bot")


def slot_for(day: datetime, slots: dict = SLOTS) -> datetime:
    h, m = slots[day.weekday()]
    return day.replace(hour=h, minute=m, second=0, microsecond=0)


def decide(now: datetime, posted_today: bool, post_running: bool, fired_slot: str | None,
           slots: dict = SLOTS, fired_at: datetime | None = None, tries: int = 0):
    """(행동, 대기 초). 행동: 'post' | 'wait' | 'sleep_until_slot'.

    fired_slot: 이번 실행이 이미 dispatch 한 슬롯(ISO). fired_at: 마지막으로 쏜 시각, tries: 쏜 횟수.
    같은 슬롯은 RETRY_MIN 이 지나야 다시 쏘고, MAX_TRIES 번까지만 쏜다.
    """
    slot = slot_for(now, slots)
    in_window = slot <= now < slot + timedelta(minutes=CATCHUP_MIN)
    if in_window and not posted_today:
        if post_running:
            return "wait", POLL_MIN * 60
        if fired_slot == slot.isoformat():
            if tries >= MAX_TRIES or fired_at is None or now - fired_at < timedelta(minutes=RETRY_MIN):
                if tries >= MAX_TRIES:
                    target = slot_for(now + timedelta(days=1), slots)
                    return "sleep_until_slot", max(1, int((target - now).total_seconds()))
                return "wait", POLL_MIN * 60
        return "post", 0
    target = slot if now < slot else slot_for(now + timedelta(days=1), slots)
    return "sleep_until_slot", max(1, int((target - now).total_seconds()))


def prewarm_due(now: datetime, posted_today: bool, done: set, slots: dict = SLOTS) -> list[str]:
    """지금 쏴야 할 나레이션 미리 만들기 키 목록(슬롯 ISO|분). 오늘 이미 나갔으면 없음."""
    if posted_today:
        return []
    slot = slot_for(now, slots)
    due = []
    for before in PREWARM_BEFORE_MIN:
        start = slot - timedelta(minutes=before)
        key = f"{slot.isoformat()}|{before}"
        if start <= now < start + timedelta(minutes=PREWARM_WINDOW_MIN) and key not in done:
            due.append(key)
    return due


# (이름, 워크플로, 슬롯, 게시 원장) — 원장에 오늘 KST 날짜 posted_at 이 있으면 '오늘 나감'
JOBS = (
    ("본편", "post.yml", SLOTS, "content/posted.json"),
    ("스하리", "threads-micro.yml", SOFT_SLOTS, "content/microposts_posted.json"),
)


def sh(*args: str) -> str:
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"{' '.join(args[:3])} 실패: {r.stderr.strip()[:400]}")
    return r.stdout


def posted_today(now: datetime, ledger: str = "content/posted.json") -> bool:
    sh("git", "fetch", "-q", "origin", "main")
    rows = json.loads(sh("git", "show", f"origin/main:{ledger}"))
    today = now.date().isoformat()
    return any(str(r.get("posted_at", "")).startswith(today) for r in rows)


def post_running(workflow: str = "post.yml") -> bool:
    out = sh("gh", "run", "list", "-R", REPO, "--workflow", workflow, "-L", "5",
             "--json", "status", "--jq", "[.[]|select(.status!=\"completed\")]|length")
    return int(out.strip() or 0) > 0


def dispatch(workflow: str) -> None:
    sh("gh", "workflow", "run", workflow, "-R", REPO, "--ref", "main")
    print(f"[clock] dispatch {workflow} @ {datetime.now(KST):%m/%d %H:%M:%S}", flush=True)


def main() -> int:
    start = time.monotonic()
    deadline = start + BUDGET_MIN * 60
    fired: dict[str, tuple[str, datetime, int]] = {}
    prewarmed: set[str] = set()
    while True:
        now = datetime.now(KST)
        waits = []
        for name, wf, slots, ledger in JOBS:
            done_today = posted_today(now, ledger)
            slot_iso, at, tries = fired.get(wf, (None, None, 0))
            act, wait = decide(now, done_today, post_running(wf), slot_iso, slots, at, tries)
            print(f"[clock] {now:%m/%d %H:%M} {name} → {act} ({wait // 60}분)", flush=True)
            if act == "post":
                cur = slot_for(now, slots).isoformat()
                n = tries + 1 if slot_iso == cur else 1
                if n > 1:
                    print(f"[clock] {name} 앞 실행이 게시 기록을 못 남김 → {n}번째 시도", flush=True)
                dispatch(wf)
                fired[wf] = (cur, now, n)
                wait = 90                  # 새 실행이 목록에 잡힐 시간
            if wf == "post.yml":
                for key in prewarm_due(now, done_today, prewarmed, slots):
                    try:
                        dispatch("tts-prewarm.yml")
                    except Exception as e:              # noqa: BLE001 — 미리 만들기는 실패해도 발행은 계속
                        print(f"[clock] 나레이션 미리 만들기 dispatch 실패: {e}", flush=True)
                    prewarmed.add(key)
                # 다음 미리 만들기 시각까지만 잔다
                slot = slot_for(now, slots)
                for before in PREWARM_BEFORE_MIN:
                    t = slot - timedelta(minutes=before)
                    if t > now:
                        wait = min(wait, max(60, int((t - now).total_seconds())))
            waits.append(wait)
        wait = min(waits)
        left = deadline - time.monotonic()
        if wait >= left:
            time.sleep(max(0, left))
            dispatch("publish-clock.yml")   # 바통 넘김
            return 0
        time.sleep(wait)


if __name__ == "__main__":
    sys.exit(main())
