# -*- coding: utf-8 -*-
"""趋势/动量因子：全部矩阵化（日期 x 股票）。"""
import numpy as np
import pandas as pd


def _ma(df, n):
    return df.rolling(n, min_periods=max(2, n // 2)).mean()


def compute(mats):
    close = mats["close"]; high = mats["high"]; low = mats["low"]
    amt = mats["amount"]; turn = mats["turnover"]

    f = {}
    f["ma5"] = _ma(close, 5)
    f["ma10"] = _ma(close, 10)
    f["ma20"] = _ma(close, 20)
    f["ma60"] = _ma(close, 60)
    f["ma120"] = _ma(close, 120)

    f["ret5"] = (close / close.shift(5) - 1) * 100
    f["ret20"] = (close / close.shift(20) - 1) * 100
    f["ret60"] = (close / close.shift(60) - 1) * 100
    f["rs20"] = f["ret20"].rank(axis=1, pct=True)
    f["rs60"] = f["ret60"].rank(axis=1, pct=True)

    # 波动（刺激度）
    prev = close.shift(1)
    f["atr_pct"] = ((high - low) / prev).rolling(20, min_periods=10).mean() * 100
    f["vol_surge"] = amt / amt.rolling(20, min_periods=10).mean()

    f["dist_ma20"] = (close / f["ma20"] - 1) * 100
    f["dist_ma60"] = (close / f["ma60"] - 1) * 100

    hi20 = high.rolling(20, min_periods=10).max()
    f["to_high"] = (hi20 - close) / hi20 * 100          # 离 20 日新高多远（越小越强）
    f["hi20"] = hi20

    f["align"] = (f["ma5"] > f["ma10"]) & (f["ma10"] > f["ma20"]) & (f["ma20"] > f["ma60"])
    f["above20"] = close > f["ma20"]
    f["above120"] = close > f["ma120"]

    f["turnover"] = turn
    f["pct"] = (close / prev - 1) * 100
    f["amt20_yi"] = amt.rolling(20, min_periods=10).mean() / 1e8
    return f


def _rank01(df):
    return df.rank(axis=1, pct=True)


def score_frames(f, mats):
    """综合分（0-100）：越强越猛分越高。"""
    r_ret20 = _rank01(f["ret20"])
    r_ret60 = _rank01(f["ret60"])
    r_rs = f["rs20"]
    r_vol = _rank01(f["vol_surge"])
    r_atr = _rank01(f["atr_pct"])
    r_high = 1 - _rank01(f["to_high"])          # 越贴近新高越强

    score = (r_ret20 * 0.25 + r_ret60 * 0.15 + r_rs * 0.20
             + r_vol * 0.15 + r_atr * 0.10 + r_high * 0.15) * 100.0
    return {
        "score": score,
        "s_mom": r_ret20 * 100,
        "s_mid": r_ret60 * 100,
        "s_rs": r_rs * 100,
        "s_vol": r_vol * 100,
        "s_atr": r_atr * 100,
        "s_high": r_high * 100,
    }


def market_state(mats):
    """等权全市场指数：是否在 20 日线上方 + 20 日涨幅。"""
    pct = mats["close"].pct_change() * 100.0
    lvl = (1 + pct.mean(axis=1) / 100.0).cumprod()
    ma20 = lvl.rolling(20, min_periods=10).mean()
    mom20 = (lvl / lvl.shift(20) - 1.0) * 100.0
    return {"level": lvl, "ma20": ma20, "mom20": mom20, "ok": lvl > ma20}


def trade_params(px, atr_pct, cfg):
    """止损按 ATR 自适应，上限不超过 max_stop_pct。"""
    stop_pct = min(cfg["stop_max_pct"], max(cfg["stop_min_pct"], atr_pct * cfg["atr_stop_mult"]))
    return {"stop": px * (1 - stop_pct / 100.0),
            "stop_pct": round(stop_pct, 2),
            "target": px * (1 + cfg["target_pct"] / 100.0),
            "target_pct": cfg["target_pct"]}
