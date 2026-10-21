"""2026-10-15 발행 시계(tools/publish_clock.py) 회귀 테스트.

10/13·10/14 정기 발행이 GitHub 예약 실행 누락으로 시작조차 안 됐다. 시계는 schedule 없이
dispatch 릴레이로 슬롯을 지킨다. 여기서는 '언제 무엇을 하는가'만 검사한다(외부 호출 없음).
"""
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tools import publish_clock as C

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[2]


def at(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=KST)


class DecideTests(unittest.TestCase):
    def test_slots_match_publisher(self):
        from src import run
        self.assertEqual(C.SLOTS, run.SLOTS)
        # 스하리 21:40 은 threads-micro.yml 첫 예약(12:40 UTC)과 같아야 한다
        wf = (ROOT / ".github/workflows/threads-micro.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "40 12 * * *"', wf)
        self.assertEqual(set(C.SOFT_SLOTS.values()), {(21, 40)})

    def test_sleeps_until_today_slot(self):
        act, wait = C.decide(at(2026, 10, 15, 9, 0), False, False, None)      # 목 21:20
        self.assertEqual(act, "sleep_until_slot")
        self.assertEqual(wait, (12 * 60 + 20) * 60)

    def test_posts_at_slot_once(self):
        now = at(2026, 10, 15, 21, 20)
        self.assertEqual(C.decide(now, False, False, None)[0], "post")
        fired = C.slot_for(now).isoformat()
        self.assertEqual(C.decide(now + timedelta(minutes=3), False, False, fired)[0], "wait")

    def test_waits_while_post_running(self):
        self.assertEqual(C.decide(at(2026, 10, 15, 21, 30), False, True, None)[0], "wait")

    def test_catches_up_within_window_only(self):
        self.assertEqual(C.decide(at(2026, 10, 15, 23, 10), False, False, None)[0], "post")
        # 슬롯 뒤 3시간이 지나면(=자정 넘김 포함) 따라잡지 않고 다음 슬롯을 기다린다
        act, _ = C.decide(at(2026, 10, 16, 0, 30), False, False, None)
        self.assertEqual(act, "sleep_until_slot")

    def test_done_today_sleeps_to_tomorrow(self):
        act, wait = C.decide(at(2026, 10, 15, 21, 40), True, False, None)
        self.assertEqual(act, "sleep_until_slot")
        # 목 21:40 → 금 15:30
        self.assertEqual(wait, int((at(2026, 10, 16, 15, 30) - at(2026, 10, 15, 21, 40)).total_seconds()))

    def test_weekend_slot(self):
        self.assertEqual(C.decide(at(2026, 10, 17, 15, 30), False, False, None)[0], "post")
        self.assertEqual(C.decide(at(2026, 10, 17, 15, 0), False, False, None)[0], "sleep_until_slot")


class LoopTests(unittest.TestCase):
    """main(): 슬롯마다 본편(post.yml)·스하리(threads-micro.yml)를 한 번씩 쏘고, 시간이 다 되면 넘긴다."""

    def run_loop(self, start, posted_after_dispatch=True):
        clock = {"t": 0.0}
        now = {"dt": start}
        posted = {"content/posted.json": False, "content/microposts_posted.json": False}
        ledger_of = {wf: led for _, wf, _, led in C.JOBS}
        fired = []

        def sleep(s):
            clock["t"] += s
            now["dt"] = now["dt"] + timedelta(seconds=s)

        class FakeDT:
            @staticmethod
            def now(tz=None):
                return now["dt"]

        def dispatch(wf):
            fired.append((wf, now["dt"]))
            if wf in ledger_of and posted_after_dispatch:
                posted[ledger_of[wf]] = True

        with mock.patch.object(C.time, "monotonic", lambda: clock["t"]), \
             mock.patch.object(C.time, "sleep", sleep), \
             mock.patch.object(C, "datetime", FakeDT), \
             mock.patch.object(C, "posted_today", lambda n, led="content/posted.json": posted[led]), \
             mock.patch.object(C, "post_running", lambda wf="post.yml": False), \
             mock.patch.object(C, "dispatch", dispatch):
            self.assertEqual(C.main(), 0)
        return fired

    def test_relay_hands_off_when_slot_far(self):
        fired = self.run_loop(at(2026, 10, 15, 9, 0))
        self.assertEqual([w for w, _ in fired], ["publish-clock.yml"])
        self.assertEqual(fired[0][1], at(2026, 10, 15, 9, 0) + timedelta(minutes=C.BUDGET_MIN))

    def test_prewarm_before_slot(self):
        """2026-10-21: 슬롯 3시간·1시간 반·40분 전에 나레이션을 미리 만든다(TTS 429 대비)."""
        fired = self.run_loop(at(2026, 10, 15, 17, 0))           # 목 21:20 슬롯
        pre = [t for w, t in fired if w == "tts-prewarm.yml"]
        self.assertEqual(pre, [at(2026, 10, 15, 18, 20), at(2026, 10, 15, 19, 50), at(2026, 10, 15, 20, 40)])
        post = [t for w, t in fired if w == "post.yml"]
        self.assertEqual(post, [at(2026, 10, 15, 21, 20)])

    def test_fires_post_and_soft_at_their_slots_then_hands_off(self):
        fired = [f for f in self.run_loop(at(2026, 10, 15, 19, 0)) if f[0] != "tts-prewarm.yml"]
        self.assertEqual([w for w, _ in fired], ["post.yml", "threads-micro.yml", "publish-clock.yml"])
        self.assertEqual(fired[0][1], at(2026, 10, 15, 21, 20))
        self.assertEqual(fired[1][1], at(2026, 10, 15, 21, 40))

    def test_weekend_soft_still_at_night(self):
        fired = [f for f in self.run_loop(at(2026, 10, 17, 14, 0)) if f[0] != "tts-prewarm.yml"]
        names = [w for w, _ in fired]
        self.assertEqual(names[0], "post.yml")
        self.assertEqual(fired[0][1], at(2026, 10, 17, 15, 30))
        self.assertNotIn("threads-micro.yml", names)          # 21:40 은 이 실행 예산 밖 → 다음 시계가 맡음

    def test_failed_post_is_retried_then_gives_up(self):
        """2026-10-21: 실패하면 RETRY_MIN 뒤 다시 쏘되 한 슬롯 MAX_TRIES 번까지(텔레그램 실패 알림 폭주 방지)."""
        fired = self.run_loop(at(2026, 10, 15, 21, 0), posted_after_dispatch=False)
        posts = [t for w, t in fired if w == "post.yml"]
        self.assertEqual(len(posts), C.MAX_TRIES)
        self.assertEqual(posts[0], at(2026, 10, 15, 21, 20))
        for a, b in zip(posts, posts[1:]):
            self.assertGreaterEqual(b - a, timedelta(minutes=C.RETRY_MIN))
        self.assertTrue(all(t < at(2026, 10, 15, 21, 20) + timedelta(minutes=C.CATCHUP_MIN) for t in posts))
        names = [w for w, _ in fired]
        self.assertEqual(names.count("threads-micro.yml"), C.MAX_TRIES)

    def test_no_prewarm_when_already_posted(self):
        self.assertEqual(C.prewarm_due(at(2026, 10, 15, 18, 25), True, set()), [])
        self.assertEqual(len(C.prewarm_due(at(2026, 10, 15, 18, 25), False, set())), 1)


class WorkflowFileTests(unittest.TestCase):
    def test_clock_has_no_schedule_and_can_dispatch(self):
        import yaml
        wf = yaml.safe_load((ROOT / ".github/workflows/publish-clock.yml").read_text(encoding="utf-8"))
        on = wf.get("on", wf.get(True))
        self.assertNotIn("schedule", on)
        self.assertEqual(wf["permissions"]["actions"], "write")
        self.assertFalse(wf["concurrency"]["cancel-in-progress"])
        self.assertGreater(wf["jobs"]["clock"]["timeout-minutes"], C.BUDGET_MIN + 10)

    def test_prewarm_workflow_commits_cache(self):
        import yaml
        wf = yaml.safe_load((ROOT / ".github/workflows/tts-prewarm.yml").read_text(encoding="utf-8"))
        on = wf.get("on", wf.get(True))
        self.assertIn("workflow_dispatch", on)
        self.assertEqual(wf["permissions"]["contents"], "write")
        steps = " ".join(str(x.get("run", "")) for x in wf["jobs"]["prewarm"]["steps"])
        self.assertIn("tools/prewarm_tts.py", steps)
        self.assertIn("assets/tts-cache", steps)
        self.assertIn("ffmpeg", steps)

    def test_watchdog_avoids_top_of_hour(self):
        import yaml
        wf = yaml.safe_load((ROOT / ".github/workflows/publish-clock-watchdog.yml").read_text(encoding="utf-8"))
        on = wf.get("on", wf.get(True))
        for c in on["schedule"]:
            self.assertNotEqual(c["cron"].split()[0], "0")


if __name__ == "__main__":
    unittest.main()
