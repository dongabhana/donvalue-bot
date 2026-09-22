"""매일 밤 점검표가 유튜브까지 보는지 확인하는 회귀 테스트.

왜 이 테스트가 있나
  점검표(tools/pipeline_status.daily_summary)는 인스타·쓰레드만 보고 있었다.
  유튜브는 content/delivery.json 한 곳에만 기록되는데 그 파일을 읽지 않아서,
  인스타에는 나갔지만 유튜브에만 빠진 날을 '이상 없음'으로 넘겼다.
  2026-09-22 에 같은 날 세 곳에 올리도록 바꾼 뒤로는, 점검표가 유튜브를 못 보면
  '빠짐없이 올라간다'를 확인할 길이 없다.

지키려는 것
  · 오늘 유튜브에 올라간 편을 점검표에 적는다 (어제 올린 편은 오늘이 아니다)
  · 오늘 인스타에 나갔는데 유튜브 기록이 없으면 ⚠ 로 경고한다
  · in_flight 로 멈춘 업로드를 ⚠ 로 경고한다
    (따라올리기가 건너뛰므로 사람이 안 보면 영영 안 올라간다)
  · 지난 기록(youtube_superseded)만 있는 편은 '올라간 것'으로 치지 않는다
  · 다른 플랫폼 기록은 유튜브 칸에 섞이지 않는다
"""
import unittest

from tools.pipeline_status import youtube_section

TODAY = '2026-09-22'


class YoutubeSectionTests(unittest.TestCase):
    def test_lists_today_uploads(self):
        lines, warn = youtube_section(
            {'a': {'youtube': {'status': 'done', 'at': '2026-09-22T14:30:18+09:00'}}},
            TODAY, {'a'})
        self.assertEqual(lines, ['[유튜브]', '14:30 a ✅'])
        self.assertEqual(warn, [])

    def test_yesterday_upload_is_not_today(self):
        lines, _ = youtube_section(
            {'a': {'youtube': {'status': 'done', 'at': '2026-09-21T14:30:18+09:00'}}},
            TODAY, set())
        self.assertEqual(lines, ['[유튜브]', '오늘 올라간 편 없음'])

    def test_posted_today_without_youtube_warns(self):
        _, warn = youtube_section(
            {'a': {'instagram': {'status': 'done', 'at': '2026-09-22T14:30:09+09:00'}}},
            TODAY, {'a'})
        self.assertEqual(warn, ['유튜브 미게시: a'])

    def test_in_flight_warns(self):
        _, warn = youtube_section({'a': {'youtube': {'status': 'in_flight'}}}, TODAY, set())
        self.assertEqual(warn, ['유튜브 업로드 중단됨: a'])

    def test_superseded_only_is_not_done(self):
        lines, warn = youtube_section(
            {'a': {'youtube_superseded': [{'status': 'done', 'id': 'OLD',
                                           'at': '2026-09-22T11:00:00+09:00'}]}},
            TODAY, {'a'})
        self.assertEqual(lines, ['[유튜브]', '오늘 올라간 편 없음'])
        self.assertEqual(warn, ['유튜브 미게시: a'])

    def test_other_platforms_do_not_leak_in(self):
        lines, warn = youtube_section(
            {'a': {'instagram_reel': {'status': 'done', 'at': '2026-09-22T14:30:09+09:00'},
                   'threads': {'status': 'in_flight'},
                   'youtube': {'status': 'done', 'at': '2026-09-22T14:30:18+09:00'}}},
            TODAY, {'a'})
        self.assertEqual(lines, ['[유튜브]', '14:30 a ✅'])
        self.assertEqual(warn, [])

    def test_empty_ledger(self):
        lines, warn = youtube_section({}, TODAY, set())
        self.assertEqual(lines, ['[유튜브]', '오늘 올라간 편 없음'])
        self.assertEqual(warn, [])


class DailySummaryWiringTests(unittest.TestCase):
    """daily_summary 가 그 칸을 실제로 붙여 쓰는지 (붙이지 않으면 경고가 사라진다)."""

    def test_daily_summary_calls_section(self):
        from pathlib import Path
        from tools import pipeline_status
        src = Path(pipeline_status.__file__).read_text(encoding='utf-8')
        self.assertIn('yt_lines, yt_warn = youtube_section(', src)
        self.assertIn('lines += yt_lines', src)
        self.assertIn('warn += yt_warn', src)


if __name__ == '__main__':
    unittest.main()
