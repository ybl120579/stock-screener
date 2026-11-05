# -*- coding: utf-8 -*-
"""选股核心逻辑的回归测试（无需联网）。

运行： python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screener import config as cfgmod          # noqa: E402
from screener import screen as sc               # noqa: E402
from screener import datasource as ds           # noqa: E402


def make_days(n=90, start="2026-07-01"):
    return [f"2026-07-{i:02d}" if i <= 31 else f"2026-08-{i-31:02d}" for i in
            range(1, n + 1)] if False else [
        pd.Timestamp("2026-06-01") .strftime("%Y-%m-%d")]


def day_list(n, end="2026-11-05"):
    """生成 n 个连续“交易日”标签（只用于 index 对齐，测试不关心真实日历）。"""
    ts = pd.bdate_range(end=end, periods=n)
    return [t.strftime("%Y-%m-%d") for t in ts]


def make_kl(pcts, dates, turnover=2.0, amount=1.2e8, base=10.0):
    rows, close = [], base
    for dt, pc in zip(dates, pcts):
        open_ = close
        close = round(close * (1 + pc / 100.0), 2)
        high = round(max(open_, close) * 1.004, 2)
        low = round(min(open_, close) * 0.996, 2)
        rows.append({"date": dt, "open": open_, "close": close, "high": high, "low": low,
                     "volume": 100000.0, "amount": amount, "amplitude": 1.0,
                     "pct": pc, "change": 0.0, "turnover": turnover})
    return pd.DataFrame(rows)


class TestNaming(unittest.TestCase):
    def test_main_board(self):
        for c in ("600000", "601318", "603303", "605060", "000001", "001979", "002534", "003028"):
            self.assertTrue(sc.is_main_board(c), c)
        for c in ("300750", "301086", "688111", "689009", "830799", "920000", "400001"):
            self.assertFalse(sc.is_main_board(c), c)

    def test_st_and_new(self):
        for n in ("ST花王", "*ST东电", "S*ST前锋"):
            self.assertTrue(sc.is_st_name(n), n)
        self.assertFalse(sc.is_st_name("得邦照明"))
        for n in ("N中信", "C三态", "n测试"):
            self.assertTrue(sc.is_new_name(n), n)
        self.assertFalse(sc.is_new_name("富佳股份"))


class TestEvaluate(unittest.TestCase):
    """构造 K 线直接喂给 _evaluate，验证每个阶段的门槛。"""

    def setUp(self):
        self.cfg = cfgmod.load_config()
        self.days = day_list(90)
        self.T = self.days[-1]
        self.spot = pd.DataFrame([{"price": 0.0, "float_mcap": 3e9}],
                                 index=[{"code": "600001"}["code"]])

    def build(self, tail_pcts, board_pct=10.0, turnover=2.0, board_offset=None):
        """前 70 根平盘，然后按 tail_pcts 走；board_offset 指定首板位置。"""
        n = len(self.days)
        pcts = [0.0] * n
        bo = board_offset if board_offset is not None else n - len(tail_pcts) - 1
        pcts[bo] = board_pct
        for k, pc in enumerate(tail_pcts):
            pcts[bo + 1 + k] = pc
        kl = make_kl(pcts, self.days, turnover=turnover)
        rec = {"code": "600001", "name": "测试股份", "board_date": self.days[bo],
               "pct": board_pct, "lbc": 1, "first_time": 93000, "last_time": 93000,
               "zbc": 0, "amount": 1.5e8, "float_mcap": 3e9, "total_mcap": 4e9,
               "turnover": 2.0, "seal_fund": 5e7, "industry": "测试", "stat": {}}
        return rec, kl

    def run_eval(self, rec, kl):
        return sc._evaluate(rec, kl, self.T, self.days, self.cfg, self.spot,
                            None, None, {}, None)

    def test_pass_and_pullback(self):
        # 首板后一路回落到首板前收盘价附近 → 应通过到第 9 阶段
        rec, kl = self.build([-1.0] * 8 + [-0.2, -0.1])
        stage, row = self.run_eval(rec, kl)
        self.assertEqual(stage, 9, row)
        self.assertIn(row["hit_type"], ("平台", "开盘价"))

    def test_prior_limit_up_rejected(self):
        rec, kl = self.build([-1.0] * 10)
        # 在首板前 5 天人为加一个涨停 → 阶段 4
        i = self.days.index(rec["board_date"]) - 5
        kl.loc[i, "pct"] = 10.0
        stage, row = self.run_eval(rec, kl)
        self.assertEqual(stage, 4)

    def test_second_limit_up_after_board_rejected(self):
        rec, kl = self.build([-1.0] * 4 + [10.0] + [-1.0] * 4)
        stage, _ = self.run_eval(rec, kl)
        self.assertEqual(stage, 5)

    def test_no_pullback_rejected(self):
        # 首板后继续上涨，价格远离左侧 → 阶段 7
        rec, kl = self.build([6.0, 5.0, 4.0, 3.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0])
        stage, _ = self.run_eval(rec, kl)
        self.assertEqual(stage, 7)

    def test_hot_turnover_rejected(self):
        rec, kl = self.build([-1.0] * 8 + [-0.2, -0.1])
        kl["turnover"] = 15.0          # 换手率超过 10% 上限
        stage, _ = self.run_eval(rec, kl)
        self.assertEqual(stage, 8)

    def test_big_amount_rejected(self):
        rec, kl = self.build([-1.0] * 8 + [-0.2, -0.1])
        kl["amount"] = 30e8            # 成交额 30 亿 > 20 亿上限
        stage, _ = self.run_eval(rec, kl)
        self.assertEqual(stage, 8)

    def test_window_too_old_rejected(self):
        # 首板在第 -11 天 → 超出 10 日窗口（阶段 6）
        rec, kl = self.build([-1.0] * 8 + [-0.2, -0.1], board_offset=len(self.days) - 12)
        stage, _ = self.run_eval(rec, kl)
        self.assertEqual(stage, 6)   # 首板太早，超出 10 日窗口
        self.assertNotEqual(stage, 9)


class TestScore(unittest.TestCase):
    def test_cold_mapping(self):
        self.assertEqual(sc._inv(0.5, 1.0, 10.0), 100.0)
        self.assertEqual(sc._inv(12.0, 1.0, 10.0), 0.0)
        self.assertEqual(sc._inv(None, 1.0, 10.0), 50.0)
        self.assertLess(sc._inv(3.0, 1.0, 10.0), sc._inv(1.5, 1.0, 10.0))

    def test_scale_log(self):
        self.assertEqual(sc._scale(None, 1, 10), 50.0)
        self.assertEqual(sc._scale(0.3, 0.4, 20.0, log=True), 0.0)
        self.assertGreater(sc._scale(10.0, 0.4, 20.0, log=True),
                           sc._scale(1.0, 0.4, 20.0, log=True))


class TestPoolFallback(unittest.TestCase):
    def test_derive_limit_up_from_spot(self):
        spot = pd.DataFrame([
            {"name": "甲股份", "price": 11.0, "pct": 10.0, "high": 11.0,
             "amount": 2e8, "float_mcap": 2e9, "total_mcap": 3e9, "turnover": 3.0},
            {"name": "乙股份", "price": 10.2, "pct": 10.0, "high": 10.5,   # 未封住
             "amount": 2e8, "float_mcap": 2e9, "total_mcap": 3e9, "turnover": 3.0},
            {"name": "丙股份", "price": 10.1, "pct": 3.0, "high": 10.2,
             "amount": 1e8, "float_mcap": 2e9, "total_mcap": 3e9, "turnover": 1.0},
        ], index=["600001", "600002", "600003"])
        got = ds.fetch_zt_pool_fallback(spot)
        self.assertEqual([x["code"] for x in got], ["600001"])


class TestConfig(unittest.TestCase):
    def test_defaults_sane(self):
        cfg = cfgmod.load_config()
        self.assertEqual(cfg["board_window_days"], 10)
        self.assertEqual(cfg["short_window_days"], 5)
        self.assertLess(abs(sum(cfg["weights"].values()) - 1.0), 1e-9)
        self.assertLess(cfg["pullback_min_pct"], 10)
        self.assertGreater(cfg["left_tolerance_pct"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
