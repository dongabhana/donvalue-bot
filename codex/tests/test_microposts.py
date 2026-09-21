"""쓰레드 단문 트랙 회귀 테스트.

지키려는 것
  1. 풀이 깨진 채로 통과하지 않는다 (id 중복·빈 값·길이 초과·잘못된 주제 태그).
  2. enabled 가 참이 아니면 어떤 경로로도 올리지 않는다.
  3. 이미 올린 글을 다시 올리지 않는다.
  4. 원장이 깨졌을 때 '이력 없음'으로 넘어가지 않는다 — 그러면 전부 재발행된다.
"""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from src import microposts

ROOT = Path(__file__).resolve().parents[2]


def pool(posts, enabled=True):
    return {"enabled": enabled, "posts": posts}


OK = [{"id": "mp001-a", "text": "한 줄", "topic_tag": "비교분석"},
      {"id": "mp002-b", "text": "두 줄", "topic_tag": "절약"}]


class PoolValidationTests(unittest.TestCase):
    def _load(self, data):
        with patch.object(microposts, "POOL") as p:
            p.exists.return_value = True
            p.read_text.return_value = yaml.safe_dump(data, allow_unicode=True)
            return microposts.load_pool()

    def test_valid_pool_loads(self):
        self.assertEqual(len(self._load(pool(OK))["posts"]), 2)

    def test_duplicate_id_is_rejected(self):
        dup = OK + [{"id": "mp001-a", "text": "또", "topic_tag": "절약"}]
        with self.assertRaises(RuntimeError):
            self._load(pool(dup))

    def test_empty_text_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self._load(pool([{"id": "mp001-a", "text": "   "}]))

    def test_text_over_threads_limit_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self._load(pool([{"id": "mp001-a", "text": "가" * (microposts.MAX_LEN + 1)}]))

    def test_topic_tag_with_forbidden_char_is_rejected(self):
        # 마침표·앰퍼샌드가 들어가면 Threads API 가 거절한다. 발행 전에 잡는다.
        for bad in ("가전.", "가전&생활"):
            with self.assertRaises(RuntimeError):
                self._load(pool([{"id": "mp001-a", "text": "x", "topic_tag": bad}]))

    def test_no_topic_tag_is_allowed(self):
        self._load(pool([{"id": "mp001-a", "text": "x"}]))


class RenderTests(unittest.TestCase):
    def test_tag_is_appended_to_the_body(self):
        self.assertEqual(microposts.render({"text": "본문", "topic_tag": "절약"}),
                         "본문\n\n#절약")

    def test_no_tag_leaves_text_alone(self):
        self.assertEqual(microposts.render({"text": "본문"}), "본문")

    def test_trailing_blank_lines_do_not_stack(self):
        self.assertEqual(microposts.render({"text": "본문\n\n", "topic_tag": "절약"}),
                         "본문\n\n#절약")


class PickTests(unittest.TestCase):
    def test_already_posted_is_skipped(self):
        got = microposts.pick(pool(OK), {"mp001-a"}, 5)
        self.assertEqual([p["id"] for p in got], ["mp002-b"])

    def test_count_limits_the_batch(self):
        self.assertEqual(len(microposts.pick(pool(OK), set(), 1)), 1)

    def test_empty_when_everything_posted(self):
        self.assertEqual(microposts.pick(pool(OK), {"mp001-a", "mp002-b"}, 3), [])


class RunGuardTests(unittest.TestCase):
    def test_disabled_pool_never_publishes(self):
        with patch.object(microposts, "load_pool", return_value=pool(OK, enabled=False)), \
             patch("src.publish.publish_threads") as pub:
            self.assertEqual(microposts.run(3, dry_run=False), 0)
        pub.assert_not_called()

    def test_dry_run_never_publishes(self):
        with patch.object(microposts, "load_pool", return_value=pool(OK)), \
             patch.object(microposts, "load_ledger", return_value=[]), \
             patch("src.publish.publish_threads") as pub:
            self.assertEqual(microposts.run(2, dry_run=True), 0)
        pub.assert_not_called()

    def test_broken_ledger_raises_instead_of_reposting(self):
        with patch.object(microposts, "LEDGER") as led:
            led.exists.return_value = True
            led.read_text.return_value = "{ not json"
            with self.assertRaises(RuntimeError):
                microposts.load_ledger()


class ShippedPoolTests(unittest.TestCase):
    """저장소에 실제로 들어 있는 풀도 같은 규칙을 지켜야 한다."""

    def test_repo_pool_is_valid(self):
        data = microposts.load_pool()
        self.assertGreaterEqual(len(data["posts"]), 10)

    def test_source_text_has_no_hashtag(self):
        # 태그는 render() 가 붙인다. 원문에도 쓰면 한 글에 태그가 둘이 된다.
        for p in microposts.load_pool()["posts"]:
            self.assertNotIn("#", p["text"], f"{p['id']} 원문에 해시태그가 있습니다")

    def test_every_post_renders_exactly_one_hashtag(self):
        # 쓰레드는 글당 태그 하나만 유효하다. 두 개 이상이면 뒤엣것은 글자로만 남는다.
        for p in microposts.load_pool()["posts"]:
            out = microposts.render(p)
            self.assertEqual(out.count("#"), 1, f"{p['id']} 의 태그 수가 1개가 아닙니다")
            self.assertTrue(out.rstrip().endswith("#" + p["topic_tag"]),
                            f"{p['id']} 의 태그가 본문 끝에 붙지 않았습니다")

    def test_repo_pool_ids_match_ledger_shape(self):
        rows = microposts.load_ledger()
        self.assertIsInstance(rows, list)
        for r in rows:
            self.assertIn("id", r)


if __name__ == "__main__":
    unittest.main()
