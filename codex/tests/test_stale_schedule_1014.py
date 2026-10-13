"""2026-10-14: 밀린 예약 실행이 새벽에 게시하지 않도록.

10/13(화) 21:20 예약과 보조 실행(22:20·23:20)이 GitHub 쪽에서 몇 시간씩 밀렸다.
밀린 실행이 10/14 새벽에 돌면 새벽에 게시되고, '오늘은 이미 한 편' 검사로
10/14 21:20 정식 슬롯까지 건너뛰어진다. 예약 실행만 막고 손으로 돌린 실행은 그대로 둔다.
"""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from src import run

KST = timezone(timedelta(hours=9))


class StaleScheduleTests(unittest.TestCase):
    def test_overnight_leftover_is_skipped(self):
        for hhmm in ("00:30", "03:00", "07:10", "19:59"):
            h, m = map(int, hhmm.split(":"))
            now = datetime(2026, 10, 14, h, m, tzinfo=KST)          # 수요일, 슬롯 21:20
            with self.subTest(now=hhmm):
                self.assertTrue(run.stale_schedule(now, "schedule"))

    def test_slot_and_backup_runs_go(self):
        for hhmm in ("20:25", "21:20", "22:05", "23:20", "23:59"):
            h, m = map(int, hhmm.split(":"))
            now = datetime(2026, 10, 14, h, m, tzinfo=KST)
            with self.subTest(now=hhmm):
                self.assertEqual(run.stale_schedule(now, "schedule"), "")

    def test_weekend_slot(self):
        sat = datetime(2026, 10, 17, 10, 0, tzinfo=KST)            # 토 15:30 슬롯
        self.assertTrue(run.stale_schedule(sat, "schedule"))
        self.assertEqual(run.stale_schedule(sat.replace(hour=15, minute=40), "schedule"), "")
        self.assertEqual(run.stale_schedule(sat.replace(hour=17, minute=35), "schedule"), "")

    def test_manual_dispatch_is_never_blocked(self):
        now = datetime(2026, 10, 14, 0, 30, tzinfo=KST)
        self.assertEqual(run.stale_schedule(now, "workflow_dispatch"), "")

    def test_main_returns_without_publishing(self):
        now = datetime(2026, 10, 14, 3, 0, tzinfo=KST)
        with patch.object(run, "datetime") as dt, \
             patch.dict("os.environ", {"GITHUB_EVENT_NAME": "schedule"}), \
             patch.object(run.notify, "enabled", return_value=False), \
             patch.object(run, "run_once") as once, \
             patch("sys.argv", ["run.py"]):
            dt.now.return_value = now
            self.assertEqual(run.main(), 0)
        once.assert_not_called()


if __name__ == "__main__":
    unittest.main()
