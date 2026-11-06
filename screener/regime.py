# -*- coding: utf-8 -*-
"""市场环境（情绪周期）：判断"今天这个首板行情该不该做"。

三个数决定一切：
  · 涨停家数  —— 有多少资金在做涨停
  · 炸板率    —— 封板资金够不够硬（曾涨停但没封住的占比）
  · 昨日涨停溢价 —— 昨天打板的人今天赚钱没有（最直接的赚钱效应）

结论只分三档：good / mid / bad。bad 的日子建议空仓，mid 半仓。
"""

import numpy as np

LIM = 9.7


def _pct_change(high, close, pre_close, lim=LIM):
    """曾涨停 / 封住 的布尔数组。"""
    touched = (high / pre_close - 1.0) * 100.0 >= lim
    sealed = ((close / pre_close - 1.0) * 100.0 >= lim) & (close >= high * 0.999)
    return touched, sealed


def breadth_from_spot(spot):
    """全市场情绪（当日）：从行情快照算，含创业板/科创板/北交所，反映整体热度。"""
    if spot is None or spot.empty:
        return None
    c = spot["price"].to_numpy(float)
    h = spot["high"].to_numpy(float)
    pc = "pre_close" if "pre_close" in spot.columns else (
        "preclose" if "preclose" in spot.columns else "昨收")
    p = spot[pc].to_numpy(float)
    pct = spot["pct"].to_numpy(float)
    ok = np.isfinite(c) & np.isfinite(h) & np.isfinite(p) & (p > 0)
    if not ok.any():
        return None
    touched, sealed = _pct_change(h[ok], c[ok], p[ok])
    n_touch = int(touched.sum())
    n_seal = int(sealed.sum())
    zhaban = n_touch - n_seal
    return {
        "zt": n_seal,
        "zhaban": zhaban,
        "zhaban_pct": round(100.0 * zhaban / n_touch, 1) if n_touch else None,
        "up": int((pct[ok] > 0).sum()),
        "down": int((pct[ok] < 0).sum()),
        "median_pct": round(float(np.nanmedian(pct[ok])), 2),
    }


def breadth_from_klines(klines, date, lim=LIM):
    """全市场情绪（某历史日）：从所有股票 K 线里数。"""
    zt = zhaban = up = down = 0
    pcts = []
    for df in klines.values():
        dates = df["date"].tolist()
        try:
            i = dates.index(date)
        except ValueError:
            continue
        if i == 0:
            continue
        c = float(df["close"].iloc[i])
        h = float(df["high"].iloc[i])
        p = float(df["close"].iloc[i - 1])
        if p <= 0:
            continue
        pct = (c / p - 1.0) * 100.0
        pcts.append(pct)
        touched = (h / p - 1.0) * 100.0 >= lim
        sealed = pct >= lim and c >= h * 0.999
        if sealed:
            zt += 1
        elif touched:
            zhaban += 1
        if pct > 0:
            up += 1
        elif pct < 0:
            down += 1
    n_touch = zt + zhaban
    return {
        "zt": zt,
        "zhaban": zhaban,
        "zhaban_pct": round(100.0 * zhaban / n_touch, 1) if n_touch else None,
        "up": up,
        "down": down,
        "median_pct": round(float(np.median(pcts)), 2) if pcts else None,
    }


def premium_from_klines(klines, codes, prev_date, date, lim=LIM):
    """昨日涨停股今日的平均涨跌幅（%），衡量赚钱效应。"""
    vals = []
    for code in codes:
        df = klines.get(code)
        if df is None:
            continue
        dates = df["date"].tolist()
        try:
            i = dates.index(date)
        except ValueError:
            continue
        if i == 0 or dates[i - 1] != prev_date:
            continue
        c = float(df["close"].iloc[i])
        p = float(df["close"].iloc[i - 1])
        if p > 0:
            vals.append((c / p - 1.0) * 100.0)
    if not vals:
        return None
    return {"n": len(vals), "avg_pct": round(float(np.mean(vals)), 2),
            "win_rate": round(100.0 * sum(1 for v in vals if v > 0) / len(vals), 1)}


def premium_from_pool(klines, pool_prev, date):
    """昨日涨停的股票（用昨日涨停池名单）今天平均涨跌幅。"""
    codes = [r["code"] for r in (pool_prev or [])]
    prev = None
    for r in (pool_prev or []):
        prev = r.get("date") or prev
    if not codes:
        return None
    vals = []
    for code in codes:
        df = klines.get(code)
        if df is None:
            continue
        dates = df["date"].tolist()
        if date not in dates:
            continue
        i = dates.index(date)
        if i == 0:
            continue
        c = float(df["close"].iloc[i])
        p = float(df["close"].iloc[i - 1])
        if p > 0:
            vals.append((c / p - 1.0) * 100.0)
    if not vals:
        return None
    return {"n": len(vals), "avg_pct": round(float(np.mean(vals)), 2),
            "win_rate": round(100.0 * sum(1 for v in vals if v > 0) / len(vals), 1)}


def judge(breadth, premium, cfg):
    """把三个数翻译成 good / mid / bad + 一句话结论。"""
    if not breadth:
        return {"level": "unknown", "ok": True, "note": "市场情绪数据缺失，按中性处理"}
    zt = breadth["zt"]
    zb = breadth["zhaban_pct"]
    prem = (premium or {}).get("avg_pct")
    min_zt = cfg.get("regime_min_zt", 30)
    max_zb = cfg.get("regime_max_zhaban_pct", 45)
    min_prem = cfg.get("regime_min_premium_pct", -1.5)

    bad = []
    if zt < min_zt:
        bad.append(f"涨停只有 {zt} 家（<{min_zt}）")
    if zb is not None and zb > max_zb:
        bad.append(f"炸板率 {zb:.0f}%（>{max_zb:.0f}%）")
    if prem is not None and prem < min_prem:
        bad.append(f"昨日涨停今日平均 {prem:+.1f}%（<{min_prem:.1f}%）")

    good = (zt >= min_zt * 2 and (zb is None or zb <= 30)
            and (prem is None or prem >= 0))
    if bad:
        level, note = "bad", "退潮期：%s —— 今天建议空仓，等情绪修复" % "，".join(bad)
    elif good:
        level, note = "good", f"情绪偏暖：涨停 {zt} 家、炸板率 {zb if zb is not None else '-'}%"
    else:
        level = "mid"
        bits = [f"涨停 {zt} 家"]
        if zb is not None:
            bits.append(f"炸板率 {zb:.0f}%")
        if prem is not None:
            bits.append(f"昨日溢价 {prem:+.1f}%")
        note = "情绪中性：" + "，".join(bits) + " —— 可以做，但轻仓"
    return {"level": level, "ok": level != "bad", "note": note,
            "thresholds": {"min_zt": min_zt, "max_zhaban_pct": max_zb,
                           "min_premium_pct": min_prem}}
