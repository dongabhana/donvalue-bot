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
    """main(): 슬롯에 post.yml 을 한 번 쏘고, 시간이 다 되면 자기 자신을 넘긴다."""

    def run_loop(self, start, posted_after_dispatch=True):
        clock = {"t": 0.0}
        now = {"dt": start}
        state = {"posted": False}
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
            if wf == "post.yml" and posted_after_dispatch:
                state["posted"] = True

        with mock.patch.object(C.time, "monotonic", lambda: clock["t"]), \
             mock.patch.object(C.time, "sleep", sleep), \
             mock.patch.object(C, "datetime", FakeDT), \
             mock.patch.object(C, "posted_today", lambda n: state["posted"]), \
             mock.patch.object(C, "post_running", lambda: False), \
             mock.patch.object(C, "dispatch", dispatch):
            self.assertEqual(C.main(), 0)
        return fired

    def test_relay_hands_off_when_slot_far(self):
        fired = self.run_loop(at(2026, 10, 15, 9, 0))
        self.assertEqual([w for w, _ in fired], ["publish-clock.yml"])
        self.assertEqual(fired[0][1], at(2026, 10, 15, 9, 0) + timedelta(minutes=C.BUDGET_MIN))

    def test_fires_post_at_slot_then_hands_off(self):
        fired = self.run_loop(at(2026, 10, 15, 19, 0))
        self.assertEqual([w for w, _ in fired], ["post.yml", "publish-clock.yml"])
        self.assertEqual(fired[0][1], at(2026, 10, 15, 21, 20))

    def test_failed_post_is_not_refired_by_same_run(self):
        fired = self.run_loop(at(2026, 10, 15, 21, 0), posted_after_dispatch=False)
        self.assertEqual([w for w, _ in fired].count("post.yml"), 1)


class WorkflowFileTests(unittest.TestCase):
    def test_clock_has_no_schedule_and_can_dispatch(self):
        import yaml
        wf = yaml.safe_load((ROOT / ".github/workflows/publish-clock.yml").read_text(encoding="utf-8"))
        on = wf.get("on", wf.get(True))
        self.assertNotIn("schedule", on)
        self.assertEqual(wf["permissions"]["actions"], "write")
        self.assertFalse(wf["concurrency"]["cancel-in-progress"])
        self.assertGreater(wf["jobs"]["clock"]["timeout-minutes"], C.BUDGET_MIN + 10)

    def test_watchdog_avoids_top_of_hour(self):
        import yaml
        wf = yaml.safe_load((ROOT / ".github/workflows/publish-clock-watchdog.yml").read_text(encoding="utf-8"))
        on = wf.get("on", wf.get(True))
        for c in on["schedule"]:
            self.assertNotEqual(c["cron"].split()[0], "0")


if __name__ == "__main__":
    unittest.main()
