# -*- coding: utf-8 -*-
"""交易系统化改造的单元测试：环境判定、首板质量、事件过滤、规则出场。"""
import os
import sys
import unittest
from unittest import mock

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from screener import events as ev          # noqa: E402
from screener import quality as qual       # noqa: E402
from screener import regime as reg         # noqa: E402
import backtest as bt                      # noqa: E402


CFG = {"regime_min_zt": 30, "regime_max_zhaban_pct": 45.0,
       "regime_min_premium_pct": -1.5}


class TestRegime(unittest.TestCase):
    def test_good_when_breadth_healthy(self):
        b = {"zt": 60, "zhaban_pct": 20.0, "up": 3000, "down": 1500, "median_pct": 0.8}
        r = reg.judge(b, {"avg_pct": 2.0, "win_rate": 60}, CFG)
        self.assertEqual(r["level"], "good")
        self.assertTrue(r["ok"])

    def test_bad_when_too_few_limit_ups(self):
        b = {"zt": 10, "zhaban_pct": 20.0, "up": 1000, "down": 4000, "median_pct": -2.0}
        r = reg.judge(b, {"avg_pct": 1.0}, CFG)
        self.assertEqual(r["level"], "bad")
        self.assertFalse(r["ok"])
        self.assertIn("涨停", r["note"])

    def test_bad_when_zhaban_rate_high(self):
        b = {"zt": 50, "zhaban_pct": 62.0, "up": 500, "down": 4500, "median_pct": -1.9}
        r = reg.judge(b, None, CFG)
        self.assertEqual(r["level"], "bad")
        self.assertIn("炸板", r["note"])

    def test_premium_missing_is_neutral(self):
        b = {"zt": 50, "zhaban_pct": 30.0, "up": 2000, "down": 2000, "median_pct": 0.0}
        r = reg.judge(b, None, CFG)
        self.assertNotEqual(r["level"], "bad")

    def test_breadth_from_spot_counts(self):
        # 3 只：一个封死涨停、一个炸板、一个平盘
        df = pd.DataFrame({
            "price": [11.0, 10.5, 10.0],
            "high": [11.0, 11.0, 10.1],
            "preclose": [10.0, 10.0, 10.0],
            "pct": [10.0, 5.0, 0.0],
        }, index=["600000", "600001", "600002"])
        b = reg.breadth_from_spot(df)
        self.assertEqual(b["zt"], 1)          # 只有第一只收盘=最高且涨停
        self.assertEqual(b["zhaban"], 1)      # 第二只摸过涨停但收在别处
        self.assertEqual(b["up"], 2)      # +10% 与 +5%
        self.assertEqual(b["down"], 0)


class TestQuality(unittest.TestCase):
    def test_early_seal_beats_late_seal(self):
        early, _ = qual.quality(first_time=93000, zbc=0, seal_ratio_pct=0.2,
                                board_open=10, board_close=11, board_high=11,
                                board_low=10.9, board_turnover=5)
        late, _ = qual.quality(first_time=145500, zbc=0, seal_ratio_pct=0.2,
                               board_open=10, board_close=11, board_high=11,
                               board_low=10, board_turnover=5)
        self.assertGreater(early, late)

    def test_zbc_lowers_score(self):
        a, _ = qual.quality(first_time=93000, zbc=0, seal_ratio_pct=0.5,
                            board_open=10, board_close=11, board_high=11,
                            board_low=10.5, board_turnover=6)
        b, _ = qual.quality(first_time=93000, zbc=3, seal_ratio_pct=0.5,
                            board_open=10, board_close=11, board_high=11,
                            board_low=10.5, board_turnover=6)
        self.assertGreater(a, b)

    def test_repeated_breaks_score_zero(self):
        _, parts = qual.quality(first_time=93000, zbc=5, seal_ratio_pct=1.0,
                                board_open=10, board_close=11, board_high=11,
                                board_low=10, board_turnover=6)
        self.assertEqual(parts["zbc"], 0)

    def test_is_yizi(self):
        self.assertTrue(qual.is_yizi(11, 11, 11, 11))
        self.assertFalse(qual.is_yizi(10, 11, 11, 10))

    def test_industry_context_and_rank(self):
        pool = [
            {"industry": "银行", "first_time": 93000},
            {"industry": "银行", "first_time": 101500},
            {"industry": "券商", "first_time": 94000},
        ]
        ctx = qual.industry_context(pool)
        self.assertEqual(ctx["银行"]["zt"], 2)
        rank, n = qual.industry_rank("银行", 101500, ctx)
        self.assertEqual((rank, n), (2, 2))
        rank1, _ = qual.industry_rank("券商", 94000, ctx)
        self.assertEqual(rank1, 1)


class TestEvents(unittest.TestCase):
    def test_to_date_formats(self):
        self.assertEqual(str(ev._to_date("2026-11-06")), "2026-11-06")
        self.assertEqual(str(ev._to_date("2026/11/06")), "2026-11-06")
        self.assertIsNone(ev._to_date("—"))

    def test_reduce_recent_filters_by_date_and_code(self):
        df = pd.DataFrame({
            "代码": ["600000", "600000", "600001"],
            "公告日": ["2026-11-01", "2026-06-01", "2026-10-30"],
            "_d": [ev._to_date("2026-11-01"), ev._to_date("2026-06-01"),
                   ev._to_date("2026-10-30")],
        })
        with mock.patch.object(ev.ds, "cached", return_value=df):
            out = ev.reduce_recent(["600000", "600001"], "2026-11-06", days=30)
        self.assertEqual(out.get("600000"), 1)   # 只算 30 天内的那条
        self.assertEqual(out.get("600001"), 1)

    def test_reduce_recent_empty(self):
        with mock.patch.object(ev.ds, "cached", return_value=pd.DataFrame()):
            self.assertEqual(ev.reduce_recent(["600000"], "2026-11-06"), {})


class TestTradeRule(unittest.TestCase):
    def _df(self, rows):
        return pd.DataFrame(rows, columns=["date", "open", "close", "high", "low", "pct"])

    def test_stop_hit(self):
        # 入选日收 10，次日开盘 10，第三天跌破止损 9.5
        df = self._df([["d0", 9.8, 10.0, 10.0, 9.7, 10.0],
                       ["d1", 10.0, 10.1, 10.2, 9.9, 1.0],
                       ["d2", 10.0, 9.2, 10.0, 9.1, -8.0],
                       ["d3", 9.2, 9.2, 9.3, 9.1, 0.0]])
        tr = bt.trade_rule(df, 0, stop_px=9.5, target_px=12.0, cost_pct=0.2)
        self.assertEqual(tr["exit_reason"], "stop")
        self.assertAlmostEqual(tr["entry_px"], 10.0)
        self.assertAlmostEqual(tr["ret_net"], round(-5.0 - 0.4, 2))

    def test_target_hit(self):
        df = self._df([["d0", 9.8, 10.0, 10.0, 9.7, 10.0],
                       ["d1", 10.0, 10.5, 12.5, 10.0, 5.0],
                       ["d2", 12.0, 12.0, 12.2, 11.8, 0.0]])
        tr = bt.trade_rule(df, 0, stop_px=9.0, target_px=12.0, cost_pct=0.2)
        self.assertEqual(tr["exit_reason"], "target")
        self.assertAlmostEqual(tr["ret_gross"], 20.0)

    def test_no_next_bar_returns_none(self):
        df = self._df([["d0", 9.8, 10.0, 10.0, 9.7, 10.0]])
        self.assertIsNone(bt.trade_rule(df, 0, 9.0, 12.0))


if __name__ == "__main__":
    unittest.main()
