# -*- coding: utf-8 -*-
"""不联网的回归测试：CI 关键逻辑（假空保护、交易日历顺延、失败原因提取）。"""
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

import build_static as bs          # noqa: E402
import record_error as re_        # noqa: E402


class TestKlineGuard(unittest.TestCase):
    """假空结果保护：K 线大面积失败时绝不能覆盖当天的正确快照。"""

    def test_ok_when_all_fetched(self):
        self.assertTrue(bs.kline_guard({"kline_total": 400, "kline_ok": 400}))

    def test_ok_when_ratio_exactly_half(self):
        self.assertTrue(bs.kline_guard({"kline_total": 400, "kline_ok": 200}))

    def test_raises_when_mostly_failed(self):
        with self.assertRaises(RuntimeError) as cm:
            bs.kline_guard({"kline_total": 400, "kline_ok": 100})
        self.assertIn("疑似限流", str(cm.exception))
        self.assertIn("100/400", str(cm.exception))

    def test_small_universe_not_guarded(self):
        # 样本太小（<50）时不触发，避免误杀
        self.assertTrue(bs.kline_guard({"kline_total": 10, "kline_ok": 1}))

    def test_missing_meta_is_tolerated(self):
        self.assertTrue(bs.kline_guard(None))
        self.assertTrue(bs.kline_guard({}))


class TestNextTradeDay(unittest.TestCase):
    def test_uses_future_day_from_calendar(self):
        days = ["2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
        self.assertEqual(bs.next_trade_day("2026-11-05", days), "2026-11-06")

    def test_falls_back_to_next_weekday(self):
        # 交易日历只到当天时，往后的周五 → 下周一（跳过周末）
        days = ["2026-11-04", "2026-11-05"]
        self.assertEqual(bs.next_trade_day("2026-11-05", days), "2026-11-06")
        self.assertEqual(bs.next_trade_day("2026-11-06", days), "2026-11-09")

    def test_weekday_skip_sunday(self):
        self.assertEqual(bs.next_trade_day("2026-11-07", []), "2026-11-09")


class TestFailureReason(unittest.TestCase):
    """手机端红点显示的原因，来自这里。"""

    def _write(self, text):
        fd, path = tempfile.mkstemp(suffix=".log", text=True)
        with io.open(fd, "w", encoding="utf-8") as f:
            f.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_picks_error_line(self):
        p = self._write("\n".join([
            "[15:40:01] 拉取行情",
            "Traceback (most recent call last):",
            '  File "build_static.py", line 133',
            "RuntimeError: K线抓取大面积失败（12/428），疑似限流",
            "[15:40:02] 结束",
        ]))
        lines = re_.tail_lines(p)
        self.assertIn("RuntimeError", re_.guess_reason(lines))
        self.assertIn("疑似限流", re_.guess_reason(lines))

    def test_falls_back_to_last_line(self):
        p = self._write("a\nb\n最后一行没有关键词\n")
        self.assertEqual(re_.guess_reason(re_.tail_lines(p)), "最后一行没有关键词")

    def test_empty_log(self):
        self.assertEqual(re_.guess_reason([]), "未知原因")


if __name__ == "__main__":
    unittest.main()


class TestPickAsOf(unittest.TestCase):
    """半夜跑不能把“今天”当成已经收盘的交易日。"""

    def test_before_close_falls_back_to_previous_day(self):
        days = ["2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
        now = bs.datetime(2026, 11, 6, 0, 7)
        self.assertEqual(bs.pick_as_of(days, now), "2026-11-05")

    def test_after_close_uses_today(self):
        days = ["2026-11-04", "2026-11-05"]
        now = bs.datetime(2026, 11, 5, 15, 40)
        self.assertEqual(bs.pick_as_of(days, now), "2026-11-05")

    def test_last_day_not_today_uses_it(self):
        # 周六跑：日历最后一天是周五，直接用周五
        days = ["2026-11-05", "2026-11-06"]
        now = bs.datetime(2026, 11, 7, 10, 0)
        self.assertEqual(bs.pick_as_of(days, now), "2026-11-06")

    def test_single_day_before_close_returns_none(self):
        self.assertIsNone(bs.pick_as_of(["2026-11-06"], bs.datetime(2026, 11, 6, 9, 0)))

    def test_empty_calendar(self):
        self.assertIsNone(bs.pick_as_of([], bs.datetime(2026, 11, 6, 16, 0)))
