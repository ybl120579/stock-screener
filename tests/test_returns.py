# -*- coding: utf-8 -*-
"""次日涨跌幅（returns.py）的单元测试：不联网，用假 K 线。"""

import json
import os
import sys
import tempfile
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import returns  # noqa: E402


def fake_kline(rows):
    """rows: [(date, open, close, high, low)] → 补齐 volume/pct，与东财列一致。"""
    out = []
    for d, o, c, h, lo in rows:
        pct = (c / o - 1) * 100 if o else None
        out.append([d, o, c, h, lo, 0, pct])
    return pd.DataFrame(out, columns=["date", "open", "close", "high", "low", "volume", "pct"])


class TestPct(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(returns._pct(110, 100), 10.0)
        self.assertEqual(returns._pct(90, 100), -10.0)

    def test_bad_input(self):
        self.assertIsNone(returns._pct(None, 100))
        self.assertIsNone(returns._pct(110, 0))
        self.assertIsNone(returns._pct(110, None))


class TestSumm(unittest.TestCase):
    def test_stats(self):
        rows = [{"x": 5.0}, {"x": -1.0}, {"x": 0.0}, {"x": 2.0}]
        s = returns._summ(rows, "x")
        self.assertEqual(s["n"], 4)
        self.assertEqual(s["avg_pct"], 1.5)
        self.assertEqual(s["up"], 2)
        self.assertEqual(s["down"], 1)
        self.assertEqual(s["flat"], 1)
        self.assertEqual(s["win_rate"], 50.0)
        self.assertEqual(s["best"], 5.0)
        self.assertEqual(s["worst"], -1.0)

    def test_empty(self):
        self.assertIsNone(returns._summ([{"x": None}], "x"))


class TestAttach(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "data", "archive"))
        # 11-03 的名单：两只票，11-04 是它的下一个交易日
        snap1 = {"trade_date": "2026-11-03", "count": 2, "rows": [
            {"code": "600000", "name": "甲", "today_close": 10.0, "today_pct": 1.0},
            {"code": "600001", "name": "乙", "today_close": 20.0, "today_pct": -2.0},
        ]}
        snap2 = {"trade_date": "2026-11-04", "count": 1, "rows": [
            {"code": "600000", "name": "甲", "today_close": 11.0, "today_pct": 10.0},
        ]}
        for d, s in (("2026-11-03", snap1), ("2026-11-04", snap2)):
            with open(os.path.join(self.tmp, "data", "archive", f"{d}.json"), "w", encoding="utf-8") as f:
                json.dump(s, f)
        with open(os.path.join(self.tmp, "data", "list.json"), "w", encoding="utf-8") as f:
            json.dump(snap2, f)
        with open(os.path.join(self.tmp, "data", "history.json"), "w", encoding="utf-8") as f:
            json.dump({"items": [{"date": "2026-11-04", "count": 1},
                                 {"date": "2026-11-03", "count": 2}]}, f)

        self.klines = {
            "600000": fake_kline([
                ("2026-11-03", 9.9, 10.0, 10.1, 9.8),
                ("2026-11-04", 10.0, 11.0, 11.2, 9.9),
            ]),
            "600001": fake_kline([
                ("2026-11-03", 20.0, 20.0, 20.3, 19.7),
                ("2026-11-04", 19.8, 19.0, 19.9, 18.8),
            ]),
        }
        self._orig = returns.ds.get_klines
        returns.ds.get_klines = lambda codes, as_of, lmt=140, **kw: {
            c: self.klines[c] for c in codes if c in self.klines}

    def tearDown(self):
        returns.ds.get_klines = self._orig

    def _load(self, name):
        with open(os.path.join(self.tmp, "data", name), encoding="utf-8") as f:
            return json.load(f)

    def test_next_day_pct(self):
        res = returns.attach(self.tmp, log=lambda *_: None)
        a = self._load("archive/2026-11-03.json")
        jia, yi = a["rows"]
        # 甲：10.0 → 11.0，开 10.0（0%），最高 11.2（+12%）
        self.assertEqual(jia["next_date"], "2026-11-04")
        self.assertEqual(jia["next_close_pct"], 10.0)
        self.assertEqual(jia["next_open_pct"], 0.0)
        self.assertEqual(jia["next_high_pct"], 12.0)
        self.assertEqual(jia["next_low_pct"], -1.0)
        # 乙：20.0 → 19.0
        self.assertEqual(yi["next_close_pct"], -5.0)
        # 汇总
        self.assertEqual(a["next_summary"]["n"], 2)
        self.assertEqual(a["next_summary"]["avg_pct"], 2.5)
        self.assertEqual(a["next_summary"]["up"], 1)
        self.assertEqual(a["next_summary"]["down"], 1)
        # 11-04 没有下一个交易日
        b = self._load("archive/2026-11-04.json")
        self.assertIsNone(b["rows"][0]["next_close_pct"])
        self.assertIsNone(b["next_summary"])
        self.assertIn("2026-11-03", res)

    def test_list_and_history_updated(self):
        returns.attach(self.tmp, log=lambda *_: None)
        lst = self._load("list.json")
        self.assertIn("next_summary", lst)
        self.assertIsNone(lst["next_summary"])
        hist = self._load("history.json")
        it = {i["date"]: i for i in hist["items"]}
        self.assertEqual(it["2026-11-03"]["next_avg_pct"], 2.5)
        self.assertEqual(it["2026-11-03"]["next_n"], 2)
        self.assertEqual(it["2026-11-03"]["day_avg_pct"], -0.5)
        self.assertEqual(it["2026-11-04"]["next_n"], 0)

    def test_missing_code_is_null(self):
        returns.ds.get_klines = lambda codes, as_of, lmt=140, **kw: {}
        returns.attach(self.tmp, log=lambda *_: None)
        a = self._load("archive/2026-11-03.json")
        self.assertIsNone(a["rows"][0]["next_close_pct"])
        self.assertIsNone(a["next_summary"])


if __name__ == "__main__":
    unittest.main()
