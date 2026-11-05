# -*- coding: utf-8 -*-
"""
条件筛选核心逻辑。

条件一：5 日 / 10 日内出现“首板”（1 连板，且此前 30 个交易日无涨停）
条件二：首板之后，今日价格回落到首板左侧（首板前一日收盘价附近）并已回落
条件三：剔除 ST、创业板、科创板、北交所、仙股、次新
条件四：热度不高、散户少（换手率、成交额、户均持股市值、股东户数变化、
        缩量程度、小单净流入、人气榜、龙虎榜）
"""
import math
import time

import numpy as np

from . import datasource as ds

MAIN_PREFIX = ("600", "601", "603", "605", "000", "001", "002", "003")

FUNNEL_STAGES = [
    "涨停池记录",
    "主板·非ST·非次新",
    "首板(1连板)",
    "K线数据充足",
    "首板前无涨停",
    "首板后无再涨停",
    "首板在时间窗口内",
    "已回落到首板左侧",
    "热度/市值硬过滤",
    "最终入选",
]


def is_main_board(code: str) -> bool:
    return code.startswith(MAIN_PREFIX)


def is_st_name(name: str) -> bool:
    n = (name or "").upper().replace(" ", "")
    return ("ST" in n) or ("退" in n)


def is_new_name(name: str) -> bool:
    return (name or "").strip().upper().startswith(("N", "C"))


def _f(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _scale(x, lo, hi, log=False):
    """映射到 0-100：x>=hi 得 100，x<=lo 得 0。"""
    if x is None:
        return 50.0
    if log:
        if x <= 0:
            return 0.0
        x, lo, hi = math.log10(x), math.log10(lo), math.log10(hi)
    if hi == lo:
        return 50.0
    t = (x - lo) / (hi - lo)
    return round(max(0.0, min(1.0, t)) * 100, 1)


def _inv(x, cold, hot, log=False):
    """反向映射：x<=cold 得 100（越冷分越高），x>=hot 得 0。"""
    return round(100 - _scale(x, cold, hot, log), 1)


def run_screen(cfg, as_of=None, refresh=False, log=print):
    t0 = time.time()
    days = ds.get_trade_days(90)
    T = as_of or days[-1]
    if T not in days:
        raise ValueError(f"{T} 不是交易日。最近交易日: {days[-5:]}")
    iT = days.index(T)

    # ---------- 行情快照 / 辅助数据（按交易日缓存） ----------
    spot = ds.cached("spot", f"spot_{T}", ds.fetch_spot, refresh)
    gdhs = ds.cached("aux", f"gdhs_{T}", ds.fetch_gdhs, refresh)
    try:
        hotrank = ds.cached("aux", f"hotrank_{T}", ds.fetch_hot_rank, refresh)
    except Exception as e:  # noqa: BLE001
        log(f"[warn] 人气榜获取失败，跳过：{e}")
        hotrank = None
    try:
        fundflow = ds.cached("aux", f"fundflow_{T}", ds.fetch_fund_flow, refresh)
    except Exception as e:  # noqa: BLE001
        log(f"[warn] 资金流获取失败，跳过：{e}")
        fundflow = None

    # ---------- 最近 N 日涨停池（含今日，共 N+1 天，覆盖“首板距今 N 天”） ----------
    n_days = cfg["board_window_days"]
    window_days = days[max(0, iT - n_days): iT + 1]
    pools = {}
    for d in window_days:
        def _fetch(d=d):
            try:
                got = ds.fetch_zt_pool(d)
                if got:
                    return got
            except Exception as e:  # noqa: BLE001
                log(f"[warn] {d} 涨停池接口失败：{str(e)[:60]}")
            snap = ds.fetch_zt_pool_cached_file(d)
            if snap:
                log(f"[warn] {d} 涨停池改用仓库快照（{len(snap)} 条）")
                return snap
            if d == T:
                log(f"[warn] {d} 涨停池按行情快照反推（仅当日，连板数按 1 记）")
                return ds.fetch_zt_pool_fallback(spot)
            log(f"[warn] {d} 涨停池缺失，跳过该日")
            return []
        pools[d] = ds.cached("pool", f"pool_{d}", _fetch, refresh and d == T)

    # ---------- 龙虎榜（覆盖整个窗口） ----------
    lhb = None
    try:
        lhb = ds.cached("aux", f"lhb_{window_days[0]}_{T}",
                        lambda: ds.fetch_lhb(window_days[0].replace("-", ""),
                                             T.replace("-", "")), refresh)
    except Exception as e:  # noqa: BLE001
        log(f"[warn] 龙虎榜获取失败，跳过：{e}")

    reached = [0] * len(FUNNEL_STAGES)
    records, rejects = [], []

    for d in window_days:
        for x in pools[d]:
            code, name = x["code"], x["name"]
            reached[0] += 1
            if not is_main_board(code):
                rejects.append((0, code, name, d, "非主板"))
                continue
            reached[1] += 1
            if cfg["exclude_st"] and is_st_name(name):
                rejects.append((1, code, name, d, "ST"))
                continue
            if is_new_name(name):
                rejects.append((1, code, name, d, "次新股"))
                continue
            if x["lbc"] != 1:
                rejects.append((1, code, name, d, f"{x['lbc']}连板"))
                continue
            reached[2] += 1
            records.append({**x, "board_date": d})

    log(f"主板首板记录 {len(records)} 条，去重股票 {len({r['code'] for r in records})} 只")
    codes = sorted({r["code"] for r in records})
    klines = ds.get_klines(codes, T, lmt=170, refresh=refresh)
    log(f"K线就绪 {sum(1 for c in codes if klines.get(c) is not None)}/{len(codes)}")

    # 龙虎榜索引
    lhb_on, lhb_after = {}, {}
    if lhb is not None and not lhb.empty:
        for code, grp in lhb.groupby("code"):
            lhb_on[code] = set(grp["date"])
            lhb_after[code] = sorted(set(grp["date"]))

    rows = []
    for rec in records:
        stage, row = _evaluate(rec, klines.get(rec["code"]), T, days, cfg,
                               spot, gdhs, hotrank, lhb_after, fundflow)
        for k in range(3, stage):
            reached[k] += 1
        if row is None:
            rejects.append((stage, rec["code"], rec["name"], rec["board_date"],
                            FUNNEL_STAGES[stage] if stage < len(FUNNEL_STAGES) else "未知"))
        else:
            rows.append(row)

    # 同一股票多条记录：保留最近一次首板
    rows.sort(key=lambda r: (r["code"], r["days_since"]))
    uniq, seen = [], set()
    for r in rows:
        if r["code"] in seen:
            continue
        seen.add(r["code"])
        uniq.append(r)

    for r in uniq:
        r["score_parts"] = _score_parts(r)
        r["score"] = _score(r, cfg)
    uniq = [r for r in uniq if r["score"] >= cfg["score_min"]]
    uniq.sort(key=lambda r: (-r["score"], r["days_since"], r["code"]))
    reached[9] = len(uniq)

    meta = {
        "trade_date": T,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 1),
        "funnel": dict(zip(FUNNEL_STAGES, reached)),
        "pool_counts": {d: len(pools[d]) for d in window_days},
        "kline_ok": sum(1 for c in codes if klines.get(c) is not None),
        "kline_total": len(codes),
        "rejects": [{"stage": FUNNEL_STAGES[s], "code": c, "name": n,
                     "board_date": d, "reason": reason}
                    for s, c, n, d, reason in rejects],
        "params": {k: cfg[k] for k in (
            "board_window_days", "short_window_days", "first_board_lookback_days",
            "pullback_min_pct", "left_tolerance_pct", "price_min",
            "float_mcap_min_yi", "float_mcap_max_yi", "turnover_today_max",
            "turnover_5d_max", "amount_today_max_yi", "gain60_max_pct",
            "exclude_hot_rank_top", "lhb_after_penalty", "min_bars")},
        "weights": dict(cfg["weights"]),
        "universe_main_count": int(sum(1 for c in spot.index if is_main_board(c))),
    }
    return {"rows": uniq[: cfg["top_n"]], "all_rows": uniq, "meta": meta}


def _evaluate(rec, kl, T, days, cfg, spot, gdhs, hotrank, lhb_after, fundflow):
    """返回 (通过阶段数, row)。阶段数：3=K线 4=首板前 5=首板后 6=窗口 7=回踩 8=热度 9=全通过"""
    code, name, d = rec["code"], rec["name"], rec["board_date"]

    if kl is None or len(kl) < cfg["min_bars"]:
        return 3, None
    dates = kl["date"].tolist()
    if dates[-1] != T or d not in dates:
        return 3, None
    j = dates.index(d)
    if j < cfg["first_board_lookback_days"]:
        return 3, None

    o = kl["open"].to_numpy(float)
    c = kl["close"].to_numpy(float)
    h = kl["high"].to_numpy(float)
    lo = kl["low"].to_numpy(float)
    v = kl["volume"].to_numpy(float)
    amt = kl["amount"].to_numpy(float)
    pct = kl["pct"].to_numpy(float)
    to = kl["turnover"].to_numpy(float)
    n = len(kl)

    lim = cfg["limit_up_pct"]
    look = cfg["first_board_lookback_days"]
    if pct[j] < lim or np.any(pct[j - look:j] >= lim):
        return 4, None
    if np.any(pct[j + 1:] >= lim):
        return 5, None

    days_since = days.index(T) - days.index(d)
    if not (1 <= days_since <= cfg["board_window_days"]):
        return 6, None

    pre_close = c[j - 1]
    board_close = c[j]
    board_open = o[j]
    close_T = c[-1]
    retrace = close_T / board_close - 1.0
    if retrace > -cfg["pullback_min_pct"] / 100.0:
        return 7, None

    left_dev = close_T / pre_close - 1.0
    tol = cfg["left_tolerance_pct"] / 100.0
    hit_platform = abs(left_dev) <= tol
    hit_open = (board_open > pre_close * 1.02) and abs(close_T / board_open - 1.0) <= 0.015
    if not (hit_platform or hit_open):
        return 7, None

    sp = spot.loc[code] if code in spot.index else None
    price = close_T
    float_mcap = _f(sp["float_mcap"]) if sp is not None else None
    if float_mcap is None:
        float_mcap = rec.get("float_mcap")
    float_mcap_yi = float_mcap / 1e8 if float_mcap else None
    if price < cfg["price_min"]:
        return 8, None
    if float_mcap_yi is None or not (cfg["float_mcap_min_yi"] <= float_mcap_yi <= cfg["float_mcap_max_yi"]):
        return 8, None

    base = c[-61] if n > 60 else c[0]
    gain60 = (close_T / base - 1.0) * 100 if base > 0 else None

    turnover_today = float(to[-1])
    turnover5 = float(np.mean(to[-5:])) if n >= 5 else turnover_today
    amount_yi = float(amt[-1]) / 1e8
    vol_ratio = float(v[-1] / v[j]) if v[j] > 0 else None

    hot_rank = None
    if hotrank is not None and code in hotrank.index:
        hot_rank = int(hotrank.loc[code, "rank"])
    if cfg["exclude_hot_rank_top"] and hot_rank is not None and hot_rank <= cfg["exclude_hot_rank_top"]:
        return 8, None
    if turnover_today > cfg["turnover_today_max"]:
        return 8, None
    if turnover5 > cfg["turnover_5d_max"]:
        return 8, None
    if amount_yi > cfg["amount_today_max_yi"]:
        return 8, None
    if gain60 is not None and gain60 > cfg["gain60_max_pct"]:
        return 8, None

    holder_avg_wan = holder_chg = holder_stat = None
    if gdhs is not None and code in gdhs.index:
        g = gdhs.loc[code]
        hv = _f(g.get("avg_hold_value"))
        holder_avg_wan = hv / 1e4 if hv else None
        holder_chg = _f(g.get("holders_chg_pct"))
        holder_stat = str(g.get("stat_date") or "")
    retail_pct = None
    if fundflow is not None and code in fundflow.index:
        retail_pct = _f(fundflow.loc[code, "retail_pct"])

    lhb_days = lhb_after.get(code, [])
    lhb_after_cnt = sum(1 for x in lhb_days if x > d)

    row = {
        "code": code, "name": name, "industry": rec.get("industry") or "",
        "board_date": d, "days_since": days_since,
        "window": "5日内" if days_since <= cfg["short_window_days"] else "10日内",
        "board_pct": round(float(rec["pct"]), 2),
        "board_turnover": round(float(to[j]), 2),
        "board_amount_yi": round(float(amt[j]) / 1e8, 2),
        "board_seal_yi": round(rec["seal_fund"] / 1e8, 2),
        "seal_ratio_pct": round(rec["seal_fund"] / rec["float_mcap"] * 100, 2) if rec.get("float_mcap") else None,
        "board_first_time": (f"{rec['first_time']:06d}" if rec.get("first_time") else ""),
        "pre_close": round(float(pre_close), 2),
        "board_close": round(float(board_close), 2),
        "board_open": round(float(board_open), 2),
        "today_close": round(float(close_T), 2),
        "today_pct": round(float(pct[-1]), 2),
        "retrace_pct": round(retrace * 100, 2),
        "left_dev_pct": round(left_dev * 100, 2),
        "hit_type": "平台" if hit_platform else "开盘价",
        "today_turnover": round(turnover_today, 2),
        "turnover5": round(turnover5, 2),
        "amount_yi": round(amount_yi, 2),
        "vol_ratio_board": round(vol_ratio, 2) if vol_ratio is not None else None,
        "float_mcap_yi": round(float(float_mcap_yi), 1),
        "gain60_pct": round(float(gain60), 1) if gain60 is not None else None,
        "price": round(float(price), 2),
        "holder_avg_wan": round(float(holder_avg_wan), 1) if holder_avg_wan else None,
        "holder_chg_pct": round(float(holder_chg), 1) if holder_chg is not None else None,
        "holder_stat_date": holder_stat,
        "retail_pct": round(float(retail_pct), 1) if retail_pct is not None else None,
        "hot_rank": hot_rank,
        "lhb_on_board": bool(d in set(lhb_days)),
        "lhb_after_cnt": int(lhb_after_cnt),
        "chart": _chart_payload(kl, j, pre_close, 60),
    }
    return 9, row


def _chart_payload(kl, j, left_ref, n_bars=60):
    c = kl["close"].to_numpy(float)
    o = kl["open"].to_numpy(float)
    h = kl["high"].to_numpy(float)
    lo = kl["low"].to_numpy(float)
    v = kl["volume"].to_numpy(float)
    dates = kl["date"].tolist()
    start = max(0, len(kl) - n_bars)
    bars = []
    for k in range(start, len(kl)):
        bars.append([dates[k], round(float(o[k]), 2), round(float(c[k]), 2),
                     round(float(lo[k]), 2), round(float(h[k]), 2),
                     round(float(v[k]) / 1e4, 1)])
    return {"bars": bars, "board_idx": j - start, "left_ref": round(float(left_ref), 2)}


# ------------------------------------------------------------------ 评分

def _score_parts(r):
    return {
        "turnover_today": _inv(r["today_turnover"], 1.0, 10.0),
        "turnover_5d": _inv(r["turnover5"], 1.5, 12.0),
        "amount_today": _inv(max(r["amount_yi"], 0.01), 0.4, 20.0, log=True),
        "vol_vs_board": _inv(r["vol_ratio_board"], 0.25, 1.0),
        "avg_holding_value": _scale(r["holder_avg_wan"], 4.0, 150.0, log=True),
        "holder_change": _inv(r["holder_chg_pct"], -20.0, 20.0),
        "gain60": _inv(r["gain60_pct"], -10.0, 60.0),
        "retail_flow": _inv(r["retail_pct"], -15.0, 15.0),
    }


def _score(r, cfg):
    w = cfg["weights"]
    parts = r["score_parts"]
    total = sum(parts[k] * w.get(k, 0.0) for k in parts)
    total -= cfg["lhb_after_penalty"] * min(r.get("lhb_after_cnt", 0), 2)
    return round(max(0.0, min(100.0, total)), 1)
