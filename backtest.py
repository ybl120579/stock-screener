# -*- coding: utf-8 -*-
"""冷度分回测：用历史行情检验「首板回踩左侧」条件与冷度分排序是否有效。

它完全不依赖东财涨停池接口——涨停判定直接用 K 线（涨幅≥9.7% 且收盘≈最高），
因此可以在东财限流时独立跑通。

用法：
    python backtest.py --days 20                 # 回测最近 20 个交易日
    python backtest.py --days 40 --refresh       # 重建 K 线缓存
    python backtest.py --start 2026-10-01        # 指定起点

输出：reports/backtest_<天数>d.json + 控制台表格
"""
import argparse
import json
import os
import pickle
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from screener import config as cfgmod          # noqa: E402
from screener import datasource as ds          # noqa: E402
from screener import screen as sc              # noqa: E402

CACHE = os.path.join(HERE, "cache", "bt_klines.pkl")
LIM = 9.7


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _fetch_one(code, lmt):
    """抓一只 K 线：腾讯 → 新浪，失败重试一次。"""
    for _ in range(2):
        try:
            df = ds.fetch_kline_alt(code, lmt)
            if df is not None and len(df) >= 60:
                return df
        except Exception:
            pass
        time.sleep(0.2)
    return None


def load_klines(force=False, lmt=260):
    if not force and os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            data = pickle.load(f)
        log(f"K 线缓存 {len(data)} 只（{time.strftime('%m-%d %H:%M', time.localtime(os.path.getmtime(CACHE)))}）")
        return data

    spot = ds.fetch_spot()
    codes = [c for c in spot.index
             if sc.is_main_board(c)
             and not sc.is_st_name(spot.loc[c, "name"])
             and not sc.is_new_name(spot.loc[c, "name"])]
    log(f"主板股票 {len(codes)} 只，开始抓 {lmt} 根日 K …")

    # 回测是批量抓取，直接走腾讯（东财对批量请求的限流最狠，留给每日筛选用）
    ds._KL_FAIL["dead"] = True

    out, done, fail = {}, 0, 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_fetch_one, c, lmt): c for c in codes}
        for fu in as_completed(futs):
            c = futs[fu]
            done += 1
            df = fu.result()
            if df is None or len(df) < 60:
                fail += 1
            else:
                out[c] = df
            if done % 100 == 0:
                rate = done / max(1e-6, time.time() - t0)
                eta = (len(codes) - done) / max(1e-6, rate)
                log(f"  {done}/{len(codes)} 成功 {len(out)} 失败 {fail} "
                    f"{rate:.1f}/s 剩余约 {eta/60:.1f} 分钟")
            if done % 600 == 0:
                with open(CACHE, "wb") as f:
                    pickle.dump(out, f)
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "wb") as f:
        pickle.dump(out, f)
    log(f"K 线就绪 {len(out)} 只（失败 {fail}），用时 {time.time()-t0:.0f}s")
    return out


def limit_up_flags(df):
    c = df["close"].to_numpy(float)
    h = df["high"].to_numpy(float)
    pct = df["pct"].to_numpy(float)
    return (pct >= LIM) & (c >= h * 0.999)


def forward_returns(df, i, horizons=(1, 3, 5, 10)):
    """第 i 根 K 线之后 h 个交易日的收盘收益率（%）。"""
    c = df["close"].to_numpy(float)
    out = {}
    for h in horizons:
        j = i + h
        out[f"r{h}"] = round((c[j] / c[i] - 1) * 100, 2) if j < len(c) and c[i] > 0 else None
    return out


def trade_rule(df, i, stop_px, target_px, max_hold=10, time_stop=3, cost_pct=0.2):
    """次日开盘买入 → 按规则出场（先看止损、再看目标），返回明细。

    i 是入选日那根 K 线；i+1 是真正能买的那天。
    止损价 stop_px 由调用方按「左侧锚点 * (1-3%)」给出；
    目标价 target_px 用首板收盘价（回到首板高点附近就走）。
    """
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    lo = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    if i + 1 >= len(c) or o[i + 1] <= 0:
        return None
    entry = float(o[i + 1])
    exit_px, reason, hold = None, "time_stop", 0
    for k in range(1, max_hold + 1):
        j = i + k
        if j >= len(c):
            break
        hold = k
        # 先判止损：跳空低开则按开盘价成交，否则按止损价
        if lo[j] <= stop_px:
            exit_px = min(float(o[j]), float(stop_px))
            reason = "stop"
            break
        if target_px and h[j] >= target_px:
            exit_px = max(float(o[j]), float(target_px))
            reason = "target"
            break
        if k >= time_stop and c[j] < entry:
            exit_px = float(c[j])
            reason = "time_stop"
            break
    if exit_px is None:
        j = min(i + max_hold, len(c) - 1)
        exit_px, hold = float(c[j]), j - i
        reason = "max_hold"
    gross = (exit_px / entry - 1) * 100
    return {
        "entry_px": round(entry, 2),
        "exit_px": round(exit_px, 2),
        "ret_gross": round(gross, 2),
        "ret_net": round(gross - 2 * cost_pct, 2),
        "exit_reason": reason,
        "hold_days": int(hold),
    }


def build_regime_map(klines, boards, days, cfg):
    """每天的涨停家数 / 炸板率 / 昨日涨停溢价（用 K 线自己算，不依赖外部接口）。"""
    px = {}
    for code, df in klines.items():
        px[code] = (df["date"].tolist(), df["close"].to_numpy(float),
                    df["high"].to_numpy(float), df["close"].to_numpy(float),
                    df["pct"].to_numpy(float))

    out = {}
    prev = None
    for d in days:
        zt = touched = 0
        for code, (dates, c, h, cl, pct) in px.items():
            if d not in dates:
                continue
            i = dates.index(d)
            if pct[i] >= LIM:
                touched += 1
                if c[i] >= h[i] * 0.999:
                    zt += 1
        zhaban = (touched - zt) / touched * 100 if touched else 0.0
        prem = None
        if prev:
            rets = []
            for code, (dates, c, h, cl, pct) in px.items():
                if prev not in dates or d not in dates:
                    continue
                ip, id_ = dates.index(prev), dates.index(d)
                if pct[ip] >= LIM and c[ip] > 0:
                    rets.append((c[id_] / c[ip] - 1) * 100)
            if rets:
                prem = round(float(np.mean(rets)), 2)
        bad = (zt < cfg.get("regime_min_zt", 30)
               or zhaban > cfg.get("regime_max_zhaban_pct", 45)
               or (prem is not None and prem < cfg.get("regime_min_premium_pct", -1.5)))
        out[d] = {"zt": zt, "zhaban_pct": round(zhaban, 1), "premium_pct": prem,
                  "level": "bad" if bad else "good"}
        prev = d
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=20, help="回测最近多少个交易日")
    ap.add_argument("--start", help="起始日 YYYY-MM-DD（优先于 --days）")
    ap.add_argument("--refresh", action="store_true", help="重建 K 线缓存")
    ap.add_argument("--out", default=os.path.join(HERE, "reports"))
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="临时覆盖 config 里的参数，可重复，如 --set break_dip_pct=0")
    ap.add_argument("--tag", default="", help="输出文件名后缀，方便对比")
    ap.add_argument("--entry", default="open", choices=["open", "close"],
                    help="入场价：open=次日开盘（现实）/ close=当日收盘（不现实，仅对照）")
    ap.add_argument("--cost", type=float, default=0.2, help="单边交易成本 %（佣金+税+滑点）")
    ap.add_argument("--topn", type=int, default=0, help="每天只取冷度分前 N 只（0=全部）")
    ap.add_argument("--no-rule", action="store_true", help="不做规则出场，只看持有 N 日")
    ap.add_argument("--no-regime", action="store_true", help="不按市场环境过滤交易日")
    args = ap.parse_args()

    cfg = cfgmod.load_config()
    for kv in args.set:
        k, _, v = kv.partition("=")
        k = k.strip()
        if not k:
            continue
        try:
            val = json.loads(v)
        except Exception:  # noqa: BLE001
            val = v
        cfg[k] = val
        print(f"[cfg] {k} = {val!r}")
    alldays = ds.get_trade_days(lmt=400)          # 用来算“距首板几天”
    if args.start:
        days = [d for d in alldays if d >= args.start][:args.days]
    else:
        days = alldays[-args.days:]
    log(f"回测区间 {days[0]} → {days[-1]}，共 {len(days)} 个交易日")

    klines = load_klines(force=args.refresh)
    spot = ds.fetch_spot()
    names = {c: spot.loc[c, "name"] for c in spot.index if "name" in spot.columns}

    # 预先算出每只股票的全部“真首板日”（涨停且前 30 日无涨停）
    boards = {}
    for code, df in klines.items():
        lu = limit_up_flags(df)
        if not lu.any():
            continue
        dates = df["date"].tolist()
        look = cfg["first_board_lookback_days"]
        idx = np.flatnonzero(lu)
        hit = []
        for i in idx:
            if i < look:
                continue
            if lu[i - look:i].any():
                continue
            hit.append(i)
        if hit:
            boards[code] = hit

    log(f"有真首板记录的股票 {len(boards)} 只")

    regime_map = build_regime_map(klines, boards, days, cfg)
    if not args.no_regime:
        nb = sum(1 for v in regime_map.values() if v["level"] == "bad")
        log(f"市场环境：{len(days)} 天中 {nb} 天判定为退潮期")

    daily, all_picks = [], []
    for d in days:
        if not args.no_regime and regime_map.get(d, {}).get("level") == "bad":
            daily.append({"date": d, "first_boards": 0, "candidates": 0, "picks": 0,
                          "pick_codes": [], "regime": regime_map[d], "skipped": True,
                          "avg_r1_picks": None, "avg_r1_base": None, "avg_r3_picks": None,
                          "avg_r3_base": None, "avg_r5_picks": None, "avg_r5_base": None,
                          "avg_r10_picks": None, "avg_r10_base": None})
            log(f"{d} 环境退潮（涨停 {regime_map[d]['zt']} 家 / 炸板 {regime_map[d]['zhaban_pct']}% / "
                f"溢价 {regime_map[d]['premium_pct']}%）→ 空仓")
            continue
        iT = alldays.index(d)
        picks, cand = [], []
        n_board_today = 0
        for code, hit in boards.items():
            df = klines[code]
            dates = df["date"].tolist()
            if d not in dates:
                continue
            i = dates.index(d)
            for j in hit:
                if j > i:
                    break
                since = i - j
                if since == 0:
                    n_board_today += 1
                if not (1 <= since <= cfg["board_window_days"]):
                    continue
                bd = dates[j]
                sub = df.iloc[: i + 1].reset_index(drop=True)
                rec = {"code": code, "name": names.get(code, code), "board_date": bd,
                       "lbc": 1, "pct": float(df["pct"].iloc[j]), "float_mcap": None,
                       "seal_fund": None, "first_time": 0, "industry": ""}
                fr = forward_returns(df, i)
                # 基准组：窗口内的所有首板股（不加条件二/四）
                cand.append({"code": code, "name": rec["name"], **fr})
                stage, row, _why = sc._evaluate(rec, sub, d, alldays, cfg, spot,
                                                None, None, {}, None)
                if row is not None:
                    row["score_parts"] = sc._score_parts(row)
                    row["score"] = sc._score(row, cfg)
                    row.update(fr)
                    row["board_date"] = bd
                    row["eval_date"] = d
                    row["days_since"] = since
                    picks.append(row)

        # 同一只股票在窗口内可能有多条首板记录：只保留最近一次
        picks.sort(key=lambda r: (r["code"], -r["days_since"]))
        seen, uniq = set(), []
        for r in picks:
            if r["code"] in seen:
                continue
            seen.add(r["code"])
            uniq.append(r)
        picks = uniq
        picks.sort(key=lambda r: -r["score"])
        if args.topn:
            picks = picks[: args.topn]
        for k, p in enumerate(picks, 1):
            p["rank"] = k
            p["regime"] = regime_map.get(d, {}).get("level")
            df = klines[p["code"]]
            i = df["date"].tolist().index(d) if d in df["date"].tolist() else None
            if i is not None and not args.no_rule:
                stop_px = float(p["pre_close"]) * (1 - cfg.get("plan_stop_pct", 3.0) / 100.0)
                tr = trade_rule(df, i, stop_px, float(p["board_close"]),
                                max_hold=10, time_stop=int(cfg.get("plan_time_stop_days", 3)),
                                cost_pct=args.cost)
                if tr:
                    p.update(tr)
                    if args.entry == "close":
                        # 不现实的口径：当天收盘就买（用来对照）
                        p["ret_net"] = p.get("r5")
            all_picks.append(p)

        daily.append({
            "date": d,
            "first_boards": n_board_today,
            "candidates": len(cand),
            "picks": len(picks),
            "pick_codes": [p["code"] for p in picks],
            "avg_r1_picks": _mean([p["r1"] for p in picks]),
            "avg_r1_base": _mean([c["r1"] for c in cand]),
            "avg_r3_picks": _mean([p["r3"] for p in picks]),
            "avg_r3_base": _mean([c["r3"] for c in cand]),
            "avg_r5_picks": _mean([p["r5"] for p in picks]),
            "avg_r5_base": _mean([c["r5"] for c in cand]),
            "avg_r10_picks": _mean([p["r10"] for p in picks]),
            "avg_r10_base": _mean([c["r10"] for c in cand]),
            "regime": regime_map.get(d),
            "avg_rule_net": _mean([p.get("ret_net") for p in picks]),
        })
        log(f"{d} 首板 {n_board_today:3d} · 窗口候选 {len(cand):3d} → 入选 {len(picks):2d}  "
            f"r5 入选 {_fmt(daily[-1]['avg_r5_picks'])} / 全体 {_fmt(daily[-1]['avg_r5_base'])}")

    report = summarize(daily, all_picks)
    os.makedirs(args.out, exist_ok=True)
    tag = f"_{args.tag}" if getattr(args, "tag", "") else ""
    path = os.path.join(args.out, f"backtest_{len(days)}d{tag}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"daily": daily, "summary": report,
                   "picks": all_picks}, f, ensure_ascii=False, indent=1,
                  default=lambda o: o.item() if hasattr(o, "item") else str(o))

    print_report(report, daily, all_picks)
    log(f"已写入 {path}")
    return 0


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(float(np.mean(xs)), 2) if xs else None


def _median(xs):
    xs = [x for x in xs if x is not None]
    return round(float(np.median(xs)), 2) if xs else None


def _win(xs, th=0.0):
    xs = [x for x in xs if x is not None]
    return round(100.0 * sum(1 for x in xs if x > th) / len(xs), 1) if xs else None


def _fmt(x):
    return "  -  " if x is None else f"{x:+.1f}%"


def summarize(daily, picks):
    def col(key):
        return [p.get(key) for p in picks]

    out = {
        "days": len(daily),
        "total_picks": len(picks),
        "picks_per_day": round(len(picks) / max(1, len(daily)), 2),
        "bars_with_picks": sum(1 for d in daily if d["picks"] > 0),
        "fwd": {},
        "baseline_fwd": {},
        "score_quintiles": [],
    }
    for h in (1, 3, 5, 10):
        key = f"r{h}"
        out["fwd"][key] = {
            "mean": _mean(col(key)), "median": _median(col(key)),
            "win_rate": _win(col(key)), "n": sum(1 for x in col(key) if x is not None),
        }
        base = [d.get(f"avg_r{h}_base") for d in daily]
        base = [b for b in base if b is not None]
        out["baseline_fwd"][key] = {"mean_per_day": _mean(base)}

    # 按冷度分分位看 5 日收益，检验“分越高越有效”是否成立
    ranked = [p for p in picks if p.get("r5") is not None]
    ranked.sort(key=lambda r: -r["score"])
    n = len(ranked)
    if n >= 5:
        q = max(1, n // 5)
        for i in range(5):
            seg = ranked[i * q:(i + 1) * q] if i < 4 else ranked[4 * q:]
            if not seg:
                continue
            out["score_quintiles"].append({
                "group": f"Q{i+1}",
                "score_range": [round(min(p['score'] for p in seg), 1),
                                round(max(p['score'] for p in seg), 1)],
                "n": len(seg),
                "r5_mean": _mean([p["r5"] for p in seg]),
                "r1_mean": _mean([p["r1"] for p in seg]),
                "r10_mean": _mean([p["r10"] for p in seg]),
            })
    ruled = [p for p in picks if p.get("ret_net") is not None]
    if ruled:
        out["rule"] = {
            "n": len(ruled),
            "mean_net": _mean([p["ret_net"] for p in ruled]),
            "median_net": _median([p["ret_net"] for p in ruled]),
            "win_rate": _win([p["ret_net"] for p in ruled]),
            "avg_hold": round(float(np.mean([p.get("hold_days") or 0 for p in ruled])), 2),
            "reasons": {},
            "cost_pct": None,
        }
        for p in ruled:
            r = p.get("exit_reason") or "?"
            out["rule"]["reasons"][r] = out["rule"]["reasons"].get(r, 0) + 1

    by_reg = {}
    for p in picks:
        lv = p.get("regime") or "unknown"
        by_reg.setdefault(lv, []).append(p)
    out["by_regime"] = {
        lv: {"n": len(v), "rule_net": _mean([p.get("ret_net") for p in v]),
             "r5": _mean([p.get("r5") for p in v])}
        for lv, v in by_reg.items()
    }

    top = [p for p in picks if (p.get("rank") or 99) <= 5]
    out["top5"] = {"n": len(top), "rule_net": _mean([p.get("ret_net") for p in top]),
                   "r5": _mean([p.get("r5") for p in top])}
    return out


def print_report(rep, daily, picks):
    print("\n" + "=" * 62)
    print(f"回测区间：{daily[0]['date']} → {daily[-1]['date']}（{rep['days']} 个交易日）")
    print(f"入选合计 {rep['total_picks']} 次，日均 {rep['picks_per_day']} 只，"
          f"有入选的交易日 {rep['bars_with_picks']}/{rep['days']}")
    print("-" * 62)
    print(f"{'持有':<6}{'样本':>6}{'均值':>10}{'中位':>10}{'胜率':>9}")
    for h in (1, 3, 5, 10):
        s = rep["fwd"][f"r{h}"]
        print(f"T+{h:<5}{s['n']:>6}{_fmt(s['mean']):>10}{_fmt(s['median']):>10}"
              f"{(str(s['win_rate']) + '%') if s['win_rate'] is not None else '-':>9}")
    print("-" * 62)
    print("同期「所有首板股」基准（不加条件）：")
    for h in (1, 3, 5, 10):
        b = rep["baseline_fwd"][f"r{h}"]["mean_per_day"]
        print(f"  T+{h:<3} 日均等权 {_fmt(b) if b is not None else '-'}")
    if rep.get("rule"):
        r = rep["rule"]
        print("-" * 62)
        print(f"按规则交易（次日开盘买 → 止损/目标/时间止损，已扣双边成本）：")
        print(f"  样本 {r['n']}  均值 {_fmt(r['mean_net'])}  中位 {_fmt(r['median_net'])}  "
              f"胜率 {r['win_rate']}%  平均持有 {r['avg_hold']} 天")
        print(f"  出场原因：{r['reasons']}")
    if rep.get("by_regime"):
        print("-" * 62)
        print("按市场环境分组：")
        for lv, v in rep["by_regime"].items():
            print(f"  {lv:<8} n={v['n']:<4} 规则净收益 {_fmt(v['rule_net']):>8}  r5 {_fmt(v['r5']):>8}")
    if rep.get("top5"):
        t = rep["top5"]
        print(f"  仅取每天前 5 名：n={t['n']}  规则净收益 {_fmt(t['rule_net'])}  r5 {_fmt(t['r5'])}")
    if rep["score_quintiles"]:
        print("-" * 62)
        print("按冷度分分组（Q1=最高分）的 T+5 收益：")
        for g in rep["score_quintiles"]:
            print(f"  {g['group']}  分数 {g['score_range'][0]:5.1f}~{g['score_range'][1]:5.1f}"
                  f"  n={g['n']:<3}  r1 {_fmt(g['r1_mean']):>8}  r5 {_fmt(g['r5_mean']):>8}"
                  f"  r10 {_fmt(g['r10_mean']):>8}")
    print("=" * 62 + "\n")


if __name__ == "__main__":
    sys.exit(main())
