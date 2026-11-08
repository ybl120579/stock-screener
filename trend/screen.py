# -*- coding: utf-8 -*-
"""强趋势 · 高弹性选股：多头排列 + 贴近新高 + 活跃放量。"""
import numpy as np
import pandas as pd

from . import factors as F

MAIN_PREFIX = ("600", "601", "603", "605", "000", "001", "002", "003")

FUNNEL = [
    ("主板股票池", "全市场主板（不含 ST / 科创 / 创业 / 北交所 / N·C 新股）"),
    ("数据充足", "至少 150 根日 K"),
    ("价格·流动性", "股价 ≥ 3 元，20 日均成交额 0.5–20 亿"),
    ("市值 30–2000 亿", "太小容易被操纵，太大拉不动"),
    ("站上 20 日线", "收盘价在 MA20 之上"),
    ("多头排列", "MA5 > MA10 > MA20 > MA60"),
    ("仍在 120 日线上方", "长期趋势没有走坏"),
    ("中期仍在涨", "20 日涨幅 ≥ 2%"),
    ("贴近 20 日新高", "离 20 日最高价不超过 6%"),
    ("活跃且有弹性", "换手 3–25%，20 日平均振幅 2.2–9%"),
    ("没追太高", "离 MA20 不超过 16%，当日涨幅 < 9%"),
    ("最终入选", "按综合分排序取前 N"),
]


def is_main_board(code):
    return str(code)[:3] in MAIN_PREFIX


def bad_name(name):
    n = (name or "").replace(" ", "").upper()
    if any(k in n for k in ("ST", "退", "PT")):
        return True
    return n.startswith("N") or n.startswith("C")


def _num(x):
    try:
        v = float(x)
        return v if np.isfinite(v) else np.nan
    except Exception:
        return np.nan





def score_frames(f, mats):
    return F.score_frames(f, mats)


def run(mats, factors, scores, spot, asof, cfg):
    close = mats["close"]
    idx = close.index
    if asof is None:
        asof = str(idx[-1].date())
    i = idx.get_indexer([pd.Timestamp(asof)])[0]
    if i < 0:
        raise ValueError(f"{asof} 不是交易日")

    mkt = F.market_state(mats)
    mkt_ok = bool(mkt["ok"].iloc[i])
    mom20 = _num(mkt["mom20"].iloc[i])

    codes = list(close.columns)
    spot_map = {}
    if spot is not None and len(spot):
        for row in spot.itertuples(index=False):
            spot_map[str(getattr(row, "code", ""))] = row

    def _at(key, code):
        try:
            return _num(factors[key].at[idx[i], code])
        except Exception:
            return np.nan

    reached = [0] * len(FUNNEL)
    rejects = []
    rows = []

    for code in codes:
        _rec = spot_map.get(code)
        name = str(getattr(_rec, "name", "") or "") if _rec is not None else ""
        px = _num(close.at[idx[i], code])
        if not is_main_board(code) or bad_name(name) or not np.isfinite(px):
            continue
        reached[0] += 1

        bars = int(mats["close"][code].notna().sum())
        if bars < cfg["min_bars"]:
            rejects.append((code, name, f"历史只有 {bars} 根 K 线"))
            continue
        reached[1] += 1

        amt20 = _at("amt20_yi", code)
        if not (np.isfinite(amt20) and cfg["amt_min_yi"] <= amt20 <= cfg["amt_max_yi"]):
            rejects.append((code, name, f"20 日均成交 {amt20:.2f} 亿，不在区间"))
            continue
        reached[2] += 1

        rec = spot_map.get(code)
        mcap = _num(getattr(rec, "float_mcap_yi", np.nan)) if rec is not None else np.nan
        if np.isfinite(mcap) and not (cfg["mcap_min_yi"] <= mcap <= cfg["mcap_max_yi"]):
            rejects.append((code, name, f"流通市值 {mcap:.0f} 亿不在区间"))
            continue
        reached[3] += 1

        above20 = bool(factors["above20"].at[idx[i], code])
        if not above20:
            rejects.append((code, name, "收盘在 20 日线下方"))
            continue
        reached[4] += 1

        align = bool(factors["align"].at[idx[i], code])
        if not align:
            rejects.append((code, name, "均线不是多头排列"))
            continue
        reached[5] += 1

        if not bool(factors["above120"].at[idx[i], code]):
            rejects.append((code, name, "跌破 120 日线"))
            continue
        reached[6] += 1

        ret20 = _at("ret20", code)
        if not (np.isfinite(ret20) and ret20 >= cfg["min_ret20"]):
            rejects.append((code, name, f"20 日涨幅 {ret20:+.1f}% 不够"))
            continue
        reached[7] += 1

        to_high = _at("to_high", code)
        if not (np.isfinite(to_high) and to_high <= cfg["max_to_high"]):
            rejects.append((code, name, f"离 20 日新高还有 {to_high:.1f}%"))
            continue
        reached[8] += 1

        turn = _at("turnover", code)
        atr = _at("atr_pct", code)
        surge = _at("vol_surge", code)
        if not (np.isfinite(turn) and cfg["turnover_min"] <= turn <= cfg["turnover_max"]):
            rejects.append((code, name, f"换手 {turn:.1f}% 不在 3–25%"))
            continue
        if not (np.isfinite(atr) and cfg["atr_min_pct"] <= atr <= cfg["atr_max_pct"]):
            rejects.append((code, name, f"平均振幅 {atr:.1f}% 不在 2.2–9%"))
            continue
        if not (np.isfinite(surge) and surge >= cfg["vol_surge_min"]):
            rejects.append((code, name, f"成交额只有 20 日均量的 {surge:.2f} 倍"))
            continue
        reached[9] += 1

        dist = _at("dist_ma20", code)
        pct = _at("pct", code)
        if not (np.isfinite(dist) and dist <= cfg["max_dist_ma20"]):
            rejects.append((code, name, f"离 20 日线已 {dist:+.0f}%，追高风险大"))
            continue
        if np.isfinite(pct) and pct >= cfg["max_pct_today"]:
            rejects.append((code, name, f"当日已涨 {pct:.1f}%，明天买入成本太高"))
            continue
        reached[10] += 1

        sc = {k: _num(v.at[idx[i], code]) for k, v in scores.items()}
        tp = F.trade_params(px, atr, cfg)
        rows.append({
            "code": code, "name": name,
            "price": round(px, 2), "score": round(sc["score"], 1),
            "ret20": round(ret20, 1),
            "ret60": round(_at("ret60", code), 1),
            "rs20": round(_at("rs20", code), 3),
            "dist_ma20": round(dist, 1),
            "to_high": round(to_high, 1),
            "atr_pct": round(atr, 2),
            "turnover": round(turn, 2),
            "vol_surge": round(surge, 2),
            "amt20_yi": round(amt20, 2),
            "float_mcap_yi": round(mcap, 1) if np.isfinite(mcap) else None,
            "stop": round(tp["stop"], 2), "stop_pct": tp["stop_pct"],
            "target": round(tp["target"], 2), "target_pct": tp["target_pct"],
            "s_parts": {k: round(v, 1) for k, v in sc.items() if k.startswith("s_")},
        })

    rows.sort(key=lambda r: -(r["score"] or 0))
    picks = rows[: int(cfg["top_n"])]
    reached[11] = len(picks)

    if not mkt_ok:
        advice = (f"大盘（等权指数）在 20 日线下方，20 日涨幅 {mom20:+.1f}% —— "
                  f"趋势策略在这种环境里最容易连续吃面，建议空仓等指数站回 20 日线。")
    elif mom20 > 8:
        advice = f"大盘 20 日已涨 {mom20:+.1f}%，趋势很顺，但也别追太高，分笔进。"
    else:
        advice = f"大盘在 20 日线上方（20 日 {mom20:+.1f}%），趋势环境尚可，按计划执行。"

    funnel = [{"name": n, "hint": h, "value": v} for (n, h), v in zip(FUNNEL, reached)]
    return {"rows": picks, "rejects": rejects, "funnel": funnel, "asof": asof,
            "advice": advice, "mkt_ok": mkt_ok, "mom20": round(mom20, 2) if np.isfinite(mom20) else None}
