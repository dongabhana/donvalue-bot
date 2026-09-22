"""정기 따라올리기 하루 상한 회귀 테스트.

왜 이 테스트가 있나
  2026-09-22 부터 '유튜브 쇼츠 백필' 워크플로가 **하루 종일 20분 간격**으로 돈다.
  발행 시각이 두 트랙·요일별로 달라져(21:20 / 15:30), 예전처럼 밤에만 돌면
  낮에 나간 편이 유튜브에 몇 시간씩 늦게 올라갔기 때문이다.

  그런데 매 실행이 --count 3 이라, 밀린 편이 많으면 하루에 수십 편이 올라간다.
  유튜브 일일 할당량은 videos.insert 1건에 1,600 units, 프로젝트 기본 10,000/일
  = 하루 6편 남짓. 넘기는 순간 그날 남은 업로드가 전부 실패한다.
  그래서 상한을 크론이 아니라 코드(YT_DAILY_MAX)에서 막는다.

지키려는 것
  · 오늘 올린 편 수를 content/delivery.json 의 at 날짜로 센다
  · 손으로 올린 편(source: manual-upload)은 API 할당량과 무관하므로 세지 않는다
  · 어제 올린 편은 오늘 몫에 들어가지 않는다
  · in_flight 로 남은 편은 오늘 몫으로 센다 (할당량을 이미 썼을 수 있다)
  · 상한에 닿으면 정기 실행은 아무것도 올리지 않고 조용히 끝난다
  · 남은 몫보다 --count 가 크면 남은 몫만큼으로 줄인다
  · 손으로 돌리는 백필(--auto 없음)에는 상한을 적용하지 않는다
"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from src import youtube_run
from src.run import KST


def _ledger(tmp: Path, data: dict) -> Path:
    path = tmp / "delivery.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


class UploadedTodayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.today = datetime.now(KST)
        self.yesterday = self.today - timedelta(days=1)

    def _count(self, data):
        with patch.object(youtube_run, "DELIVERY", _ledger(self.tmp, data)):
            return youtube_run.uploaded_today()

    def test_counts_only_today(self):
        n, ids = self._count({
            "a": {"youtube": {"status": "done",
                              "at": self.today.isoformat(timespec="seconds")}},
            "b": {"youtube": {"status": "done",
                              "at": self.yesterday.isoformat(timespec="seconds")}},
        })
        self.assertEqual((n, ids), (1, ["a"]))

    def test_manual_uploads_do_not_count(self):
        # 손으로 올린 편은 API 할당량을 쓰지 않는다. 세면 상한이 헛되이 깎인다.
        n, _ = self._count({
            "a": {"youtube": {"status": "done", "source": "manual-upload",
                              "at": self.today.isoformat(timespec="seconds")}},
        })
        self.assertEqual(n, 0)

    def test_in_flight_counts(self):
        n, ids = self._count({"a": {"youtube": {"status": "in_flight"}}})
        self.assertEqual((n, ids), (1, ["a"]))

    def test_other_platforms_ignored(self):
        n, _ = self._count({
            "a": {"instagram": {"status": "done",
                                "at": self.today.isoformat(timespec="seconds")}},
        })
        self.assertEqual(n, 0)

    def test_missing_ledger(self):
        with patch.object(youtube_run, "DELIVERY", self.tmp / "nope.json"):
            self.assertEqual(youtube_run.uploaded_today(), (0, []))


class AutoCapTests(unittest.TestCase):
    """--auto 실행이 상한을 실제로 적용하는지."""

    def _run(self, argv, used, daily_max=3):
        calls = {}

        def fake_pick(queue, want, count, source, strict=False):
            calls["count"] = count
            return []                       # 뽑히는 편이 없으면 바로 끝난다

        with patch.object(youtube_run.youtube, "hold_reason", return_value=""), \
             patch.object(youtube_run.youtube, "configured", return_value=True), \
             patch.object(youtube_run, "uploaded_today",
                          return_value=(used, [f"x{i}" for i in range(used)])), \
             patch.object(youtube_run, "DAILY_MAX", daily_max), \
             patch.object(youtube_run, "pick", side_effect=fake_pick), \
             patch.object(youtube_run.hooks, "attach", return_value={"items": []}), \
             patch.object(youtube_run.yaml, "safe_load", return_value={"items": []}), \
             patch.object(Path, "read_text", return_value="items: []"), \
             patch("sys.argv", ["youtube_run"] + argv):
            code = youtube_run.main()
        return code, calls

    def test_stops_at_cap(self):
        code, calls = self._run(["--auto", "--count", "3"], used=3)
        self.assertEqual(code, 0)
        self.assertNotIn("count", calls)     # pick 까지 가지 않는다

    def test_trims_to_remaining_room(self):
        code, calls = self._run(["--auto", "--count", "3"], used=2)
        self.assertEqual(code, 0)
        self.assertEqual(calls.get("count"), 1)

    def test_full_room_untouched(self):
        _, calls = self._run(["--auto", "--count", "3"], used=0)
        self.assertEqual(calls.get("count"), 3)

    def test_manual_run_is_not_capped(self):
        # 사람이 일부러 누른 백필은 막지 않는다 (밀린 편 몰아 올리기 경로).
        _, calls = self._run(["--count", "3"], used=3)
        self.assertEqual(calls.get("count"), 3)


if __name__ == "__main__":
    unittest.main()
