# -*- coding: utf-8 -*-
"""趋势策略回测：次日开盘买入，ATR 止损 / 目标 / 跌破 10 日线 / 时间止损。"""
import numpy as np
import pandas as pd

from . import factors as F
from . import screen as S


def build_pass_mask(f, cfg):
    """把 screen 的硬条件向量化，返回 日期 x 股票 的 bool 矩阵。"""
    m = (f["above20"] & f["align"] & f["above120"]
         & (f["ret20"] >= cfg["min_ret20"])
         & (f["to_high"] <= cfg["max_to_high"])
         & (f["turnover"] >= cfg["turnover_min"]) & (f["turnover"] <= cfg["turnover_max"])
         & (f["atr_pct"] >= cfg["atr_min_pct"]) & (f["atr_pct"] <= cfg["atr_max_pct"])
         & (f["vol_surge"] >= cfg["vol_surge_min"])
         & (f["dist_ma20"] <= cfg["max_dist_ma20"])
         & (f["pct"] < cfg["max_pct_today"])
         & (f["amt20_yi"] >= cfg["amt_min_yi"]) & (f["amt20_yi"] <= cfg["amt_max_yi"]))
    return m.fillna(False)


def _trade(mats, f, code, i, stop_pct, target_pct, hold, cost_pct, ma_exit):
    o = mats["open"][code].values; h = mats["high"][code].values
    l = mats["low"][code].values; c = mats["close"][code].values
    ma10 = f["ma10"][code].values
    n = len(o)
    if i + 1 >= n:
        return None
    entry = o[i + 1]
    if not np.isfinite(entry) or entry <= 0:
        return None
    stop = entry * (1 - stop_pct / 100.0)
    target = entry * (1 + target_pct / 100.0)
    last = min(i + hold, n - 1)
    exit_px, reason, days = None, "max_hold", last - i
    for j in range(i + 1, last + 1):
        if np.isfinite(l[j]) and l[j] <= stop:
            exit_px, reason, days = min(stop, o[j]) if np.isfinite(o[j]) else stop, "stop", j - i
            break
        if np.isfinite(h[j]) and h[j] >= target:
            exit_px, reason, days = target, "target", j - i
            break
        if ma_exit and np.isfinite(ma10[j]) and np.isfinite(c[j]) and c[j] < ma10[j]:
            exit_px, reason, days = c[j], "ma10", j - i
            break
    if exit_px is None:
        exit_px = c[last] if np.isfinite(c[last]) else entry
        reason, days = "max_hold", last - i
    ret = (exit_px / entry - 1) * 100 - cost_pct
    return {"entry": entry, "exit": exit_px, "ret": ret, "days": int(days), "reason": reason}


def run(mats, f, scores, cfg, days=200, top_n=None, hold=None, use_rules=True):
    top_n = int(top_n or cfg["top_n"])
    hold = int(hold or cfg["hold_days"])
    mask = build_pass_mask(f, cfg)
    mkt = F.market_state(mats)
    ok = mkt["ok"]
    close = mats["close"]
    idx = close.index
    n = len(idx)

    picks, skipped = [], 0
    start = max(60, n - days)
    for i in range(start, n - 1):
        if cfg.get("regime_filter") and not bool(ok.iloc[i]):
            skipped += 1
            continue
        cand = mask.iloc[i]
        codes = [c for c in close.columns if bool(cand.get(c, False))]
        if not codes:
            continue
        srow = scores["score"].iloc[i]
        scored = sorted(((float(srow.get(c, np.nan)), c) for c in codes),
                        key=lambda x: -x[0])[:top_n]
        for sc, code in scored:
            stop_pct = float(np.clip(f["atr_pct"].at[idx[i], code] * cfg["atr_stop_mult"],
                                     cfg["stop_min_pct"], cfg["stop_max_pct"]))
            r = _trade(mats, f, code, i, stop_pct, cfg["target_pct"], hold,
                       cfg["bt_cost_pct"], bool(use_rules and cfg.get("ma_exit")))
            if r is None:
                continue
            r.update({"date": str(idx[i].date()), "code": code, "score": sc})
            picks.append(r)
    return {"picks": picks, "skipped_days": skipped, "days": n - start, "hold": hold, "top_n": top_n}


def baseline(mats, days=200, hold=None):
    close = mats["close"]; o = mats["open"]
    n = len(close); start = max(60, n - days)
    rets = []
    for i in range(start, n - 1):
        j = min(i + hold, n - 1)
        r = (close.iloc[j] / o.iloc[i + 1] - 1) * 100
        r = r.replace([np.inf, -np.inf], np.nan).dropna()
        rets.extend(r.tolist())
    return rets


def summarize(res, mats, hold=None):
    p = res["picks"]
    rets = np.array([x["ret"] for x in p], dtype=float)
    base = np.array(baseline(mats, days=res["days"], hold=hold or res["hold"]), dtype=float)
    def st(a):
        if not len(a):
            return {"n": 0, "avg": 0, "median": 0, "win": 0}
        return {"n": int(len(a)), "avg": float(np.mean(a)),
                "median": float(np.median(a)), "win": float((a > 0).mean() * 100)}
    reasons = {}
    for x in p:
        reasons[x["reason"]] = reasons.get(x["reason"], 0) + 1
    return {"picks": st(rets), "baseline": st(base),
            "avg_days": float(np.mean([x["days"] for x in p])) if p else 0,
            "reasons": reasons, "skipped_days": res["skipped_days"], "total_days": res["days"]}
