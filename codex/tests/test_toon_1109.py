"""2026-11-09 「0년」 컷툰 릴스 자동 게시 + 돈값하나 인스타·쓰레드 중단 회귀 테스트.

소유자 결정
  · 인스타(@dongabhana)를 「0년」 컷툰 계정으로 바꾼다. 돈값하나 본편은 유튜브에만 낸다.
  · 컷툰 한 화 = 15장. 공식 API 캐러셀은 10장까지라 릴스 영상으로 이어 붙여 올린다.
  · 월·수·금 21:20 KST. 하루 한 화.
"""
import json
import re
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import yaml
from PIL import Image

from src import toon

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[2]


def at(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=KST)


class TempToon:
    """toon/ 폴더를 임시 폴더로 바꿔 끼운다."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.patches = [mock.patch.object(toon, "TOON", base / "toon"),
                        mock.patch.object(toon, "LEDGER", base / "toon" / "posted.json"),
                        mock.patch.object(toon, "OUT", base / "out")]
        for p in self.patches:
            p.start()
        (base / "toon").mkdir()
        return base / "toon"

    def __exit__(self, *a):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()


def make_ep(root: Path, name: str, n: int, size=(1024, 1536), caption="캡션 #웹툰", timing=None):
    ep = root / name
    ep.mkdir()
    for i in range(1, n + 1):
        Image.new("RGB", size, (20 * i % 255, 80, 120)).save(ep / f"{i:02d}.png")
    if caption is not None:
        (ep / "caption.txt").write_text(caption, encoding="utf-8")
    if timing is not None:
        (ep / "timing.yaml").write_text(yaml.safe_dump(timing), encoding="utf-8")
    return ep


class FolderRules(unittest.TestCase):
    def test_next_episode_skips_posted_and_reports_missing_images(self):
        with TempToon() as root:
            make_ep(root, "ep01", 2)
            (root / "ep02").mkdir()
            ep, why = toon.next_episode([])
            self.assertEqual(ep.name, "ep01")
            ep, why = toon.next_episode([{"episode": "ep01"}])
            self.assertIsNone(ep)
            self.assertIn("ep02", why)
            self.assertIn("그림", why)

    def test_numeric_order_not_text_order(self):
        with TempToon() as root:
            ep = root / "ep01"
            ep.mkdir()
            for name in ("10.png", "2.png", "1.png"):
                Image.new("RGB", (10, 10)).save(ep / name)
            self.assertEqual([p.name for p in toon.images_of(ep)], ["1.png", "2.png", "10.png"])

    def test_unnumbered_or_duplicate_files_stop(self):
        with TempToon() as root:
            ep = root / "ep01"
            ep.mkdir()
            Image.new("RGB", (10, 10)).save(ep / "cover.png")
            with self.assertRaises(toon.ToonError):
                toon.images_of(ep)
            (ep / "cover.png").unlink()
            Image.new("RGB", (10, 10)).save(ep / "01.png")
            Image.new("RGB", (10, 10)).save(ep / "1.jpg")
            with self.assertRaises(toon.ToonError):
                toon.images_of(ep)

    def test_caption_and_timing_validation(self):
        with TempToon() as root:
            ep = make_ep(root, "ep01", 3, caption="")
            with self.assertRaises(toon.ToonError):
                toon.caption_of(ep)
            (ep / "timing.yaml").write_text("durations: [3, 3]\n", encoding="utf-8")
            with self.assertRaises(toon.ToonError):
                toon.timing_of(ep, 3)
            (ep / "timing.yaml").write_text("durations: [3, 3, 3]\nsfx: {2: [boom]}\n", encoding="utf-8")
            with self.assertRaises(toon.ToonError):
                toon.timing_of(ep, 3)
            (ep / "timing.yaml").write_text("durations: [3, 2, 4]\nsfx: {2: click}\n", encoding="utf-8")
            self.assertEqual(toon.timing_of(ep, 3), ([3.0, 2.0, 4.0], {2: ["click"]}))

    def test_episode_one_is_ready_except_images(self):
        ep = ROOT / "toon" / "ep01"
        durs, sfx = toon.timing_of(ep, 15)
        self.assertEqual(sum(durs), 48)
        self.assertEqual(sfx, {11: ["click", "click"], 13: ["shutter"]})
        cap = toon.caption_of(ep)
        self.assertIn("「0년」 1화", cap)
        self.assertNotIn("유튜브", cap)                 # 영상판은 보류(2026-11-09)
        self.assertNotIn("옆으로 넘겨", cap)            # 캐러셀이 아니라 릴스


class LaterEpisodes(unittest.TestCase):
    """2026-11-09 저녁 추가: 2·3화 캡션·장별 시간, 효과음 crack(딱)·hiss(치익)."""

    def test_episodes_two_and_three_ready_except_images(self):
        for name, total, sfx in (("ep02", 50, {10: ["crack"], 11: ["hiss", "hiss"]}),
                                 ("ep03", 53, {2: ["click", "click"], 8: ["crack"]})):
            ep = ROOT / "toon" / name
            durs, got = toon.timing_of(ep, 15)
            self.assertEqual(sum(durs), total, name)
            self.assertEqual(got, sfx, name)
            cap = toon.caption_of(ep)
            self.assertIn(f"「0년」 {int(name[2:])}화", cap)
            self.assertNotIn("유튜브", cap)

    def test_captions_use_five_researched_hashtags(self):
        """2026-11-10: 실제 게시물 수를 보고 고른 5개(인스타 한도 5개)."""
        import re as _re
        for name in ("ep01", "ep02", "ep03"):
            cap = toon.caption_of(ROOT / "toon" / name)
            self.assertEqual(_re.findall(r"#\S+", cap),
                             ["#인스타툰", "#미스터리", "#서바이벌", "#캠핑", "#부시크래프트"])
        with TempToon() as root:
            ep = make_ep(root, "ep01", 2, caption="a #1 #2 #3 #4 #5 #6")
            with self.assertRaises(toon.ToonError):
                toon.caption_of(ep)

    def test_new_sound_effects_are_audible(self):
        import numpy as np
        rng = np.random.default_rng(0)
        for kind in ("crack", "hiss"):
            self.assertIn(kind, toon.SFX_KINDS)
            self.assertGreater(float(abs(toon.SFX[kind](rng)).max()), 0.3, kind)
        mix = toon.soundtrack([2, 2], {2: ["crack", "hiss"]})
        self.assertGreater(float(abs(mix).max()), 0.3)


class Schedule(unittest.TestCase):
    def test_only_mon_wed_fri_from_schedule(self):
        self.assertEqual(toon.schedule_skip(at(2026, 11, 10, 21, 20), "schedule")[:2], "오늘")   # 화
        self.assertEqual(toon.schedule_skip(at(2026, 11, 9, 21, 25), "schedule"), "")          # 월
        self.assertIn("이릅", toon.schedule_skip(at(2026, 11, 9, 12, 0), "schedule"))
        self.assertEqual(toon.schedule_skip(at(2026, 11, 10, 9, 0), "workflow_dispatch"), "")

    def test_workflow_cron_matches_slots(self):
        wf = (ROOT / ".github/workflows/toon.yml").read_text(encoding="utf-8")
        crons = re.findall(r'cron: "([^"]+)"', wf)
        self.assertEqual(crons[0], "20 12 * * 1,3,5")           # 21:20 KST = 12:20 UTC
        self.assertEqual(set(toon.SLOTS), {0, 2, 4})
        self.assertEqual(set(toon.SLOTS.values()), {(21, 20)})

    def test_one_episode_a_day(self):
        with TempToon() as root:
            make_ep(root, "ep01", 2)
            make_ep(root, "ep02", 2)
            toon.LEDGER.write_text(json.dumps([{"episode": "ep01", "posted_at": "2026-11-09T21:22:00+09:00"}]))
            with mock.patch.object(toon, "build") as build:
                self.assertEqual(toon.run(now=at(2026, 11, 9, 22, 20)), 0)
                build.assert_not_called()


    def test_missing_images_alert_once_a_day(self):
        """그림이 없는 날: 알림은 한 번. 시계 재시도·보조 실행은 '쉼' 기록을 보고 조용히 넘어간다."""
        with TempToon() as root:
            (root / "ep01").mkdir()
            told = []
            with mock.patch("src.run.sh", return_value=""), mock.patch("src.run.push"), \
                 mock.patch.object(toon, "_tell", told.append), \
                 mock.patch.dict("os.environ", {"GITHUB_EVENT_NAME": "workflow_dispatch"}):
                now = datetime.now(KST)
                self.assertEqual(toon.run(now=now), 0)
                self.assertEqual(toon.run(now=now), 0)
            self.assertEqual(len(told), 1)
            led = json.loads(toon.LEDGER.read_text())
            self.assertEqual(len(led), 1)
            self.assertTrue(led[0]["skipped"])
            # 쉰 기록은 '올린 화'로 치지 않는다 → 그림이 들어오면 ep01 부터
            for i in (1, 2):
                Image.new("RGB", (10, 10)).save(root / "ep01" / f"{i:02d}.png")
            self.assertEqual(toon.next_episode(led)[0].name, "ep01")


class Build(unittest.TestCase):
    def test_builds_vertical_reel_with_sound(self):
        with TempToon() as root:
            ep = make_ep(root, "ep01", 3, timing={"durations": [1.5, 1, 1.5], "sfx": {2: ["shutter"]}})
            out = toon.build(ep)
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height",
                 "-show_entries", "format=duration", "-of", "json", str(out["mp4"])],
                capture_output=True, text=True, check=True)
            info = json.loads(probe.stdout)
            kinds = {s["codec_type"] for s in info["streams"]}
            self.assertEqual(kinds, {"video", "audio"})
            v = next(s for s in info["streams"] if s["codec_type"] == "video")
            self.assertEqual((v["width"], v["height"]), (1080, 1920))
            self.assertAlmostEqual(float(info["format"]["duration"]), 4.0, delta=0.25)
            with Image.open(out["cover"]) as c:
                self.assertEqual(c.size, (1080, 1920))
            self.assertEqual(out["slides"], 3)

    def test_soundtrack_is_not_silent(self):
        mix = toon.soundtrack([2, 2], {1: ["click"]})
        self.assertGreater(float(abs(mix).max()), 0.3)

    def test_wide_and_tall_images_fit_inside_frame(self):
        with tempfile.TemporaryDirectory() as d:
            for size in ((1080, 1350), (1024, 1536), (1600, 900)):
                src = Path(d) / "a.png"
                Image.new("RGB", size, (200, 0, 0)).save(src)
                with Image.open(toon.frame(src, Path(d) / "f.jpg")) as f:
                    self.assertEqual(f.size, (1080, 1920))
                    self.assertGreater(f.getpixel((540, 900))[0], 150)   # 가운데는 원본 그림


class Publish(unittest.TestCase):
    def test_posts_reel_through_delivery_ledger(self):
        with TempToon() as root:
            make_ep(root, "ep01", 2)
            calls = {}

            def deliver(item_id, key, action):
                calls["key"] = (item_id, key)
                return action()

            def reel(uid, tok, video_url, caption, cover):
                calls["reel"] = (video_url, caption, cover)
                return "MEDIA1"

            fake_out = {"mp4": root / "r.mp4", "cover": root / "c.jpg", "slides": 2, "seconds": 6.0}
            with mock.patch.object(toon, "build", return_value=fake_out), \
                 mock.patch("src.run.deliver_once", deliver), \
                 mock.patch("src.run.push"), \
                 mock.patch("src.run.sh", return_value="abc123"), \
                 mock.patch("src.publish.publish_instagram_reel", reel), \
                 mock.patch("src.notify.done"), \
                 mock.patch.dict("os.environ", {"IG_USER_ID": "u", "IG_ACCESS_TOKEN": "t",
                                                "GITHUB_REPOSITORY": "o/r", "GITHUB_EVENT_NAME": "workflow_dispatch"}):
                self.assertEqual(toon.run(now=at(2026, 11, 9, 21, 20)), 0)
            self.assertEqual(calls["key"], ("toon-ep01", "instagram_reel"))
            self.assertEqual(calls["reel"][0], "https://raw.githubusercontent.com/o/r/abc123/images/toon/ep01/reel.mp4")
            self.assertTrue(calls["reel"][2].endswith("/cover.jpg"))
            led = json.loads(toon.LEDGER.read_text())
            self.assertEqual([r["episode"] for r in led], ["ep01"])
            self.assertEqual(led[0]["media_id"], "MEDIA1")


class MoneyChannelOff(unittest.TestCase):
    """돈값하나 본편은 유튜브만. 인스타·쓰레드는 멈춘다(스위치만 끔, 코드는 보존)."""

    def test_post_workflow_skips_instagram_and_threads(self):
        wf = yaml.safe_load((ROOT / ".github/workflows/post.yml").read_text(encoding="utf-8"))
        env = next(s for s in wf["jobs"]["publish"]["steps"] if s.get("name") == "발행")["env"]
        self.assertEqual(env["SKIP_INSTAGRAM"], "1")
        self.assertEqual(env["SKIP_THREADS"], "1")
        self.assertEqual(env["YT_AUTO"], "1")              # 유튜브는 계속

    def test_skip_instagram_switch(self):
        from src import run
        with mock.patch.dict("os.environ", {"SKIP_INSTAGRAM": "1"}):
            self.assertTrue(run.skip_instagram())
        with mock.patch.dict("os.environ", {"SKIP_INSTAGRAM": ""}):
            self.assertFalse(run.skip_instagram())

    def test_threads_micro_disabled(self):
        from src import microposts
        self.assertFalse(microposts.load_pool().get("enabled"))


if __name__ == "__main__":
    unittest.main()
