# -*- coding: utf-8 -*-
"""给名单补上「当天涨跌幅」和「次日涨跌幅」。

- 当天涨跌幅：名单生成当天收盘的涨跌幅，screen 阶段已经算好放在 rows[i]["today_pct"]。
- 次日涨跌幅：下一个交易日的收盘价 / 名单当天收盘价 - 1；顺带算开盘、最高、最低。

历史名单（docs/data/archive/DATE.json）会就地补上这些字段，并回写：
- 每只股票：next_date / next_open_pct / next_close_pct / next_high_pct / next_low_pct
- 每份名单：day_summary / next_summary（平均涨跌、上涨家数、胜率）
- 当天名单（docs/data/list.json）、历史索引（docs/data/history.json）同步更新

用法：
    python returns.py                # 补 docs/
    python returns.py --out docs --days 30
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from screener import datasource as ds  # noqa: E402


def _read(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _write(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    os.replace(tmp, p)


def _to_bars(df):
    """把 K 线 DataFrame 变成 {date: (open, close, high, low)}，保持时间顺序。"""
    bars = {}
    for row in df.itertuples(index=False):
        bars[str(getattr(row, "date"))] = (
            float(getattr(row, "open")), float(getattr(row, "close")),
            float(getattr(row, "high")), float(getattr(row, "low")),
        )
    return bars


def _pct(a, b):
    if a is None or b in (None, 0):
        return None
    return round((a / b - 1) * 100, 2)


def _summ(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    if not vals:
        return None
    up = sum(1 for v in vals if v > 0)
    dn = sum(1 for v in vals if v < 0)
    return {
        "n": len(vals),
        "avg_pct": round(sum(vals) / len(vals), 2),
        "median_pct": round(sorted(vals)[len(vals) // 2], 2),
        "win_rate": round(up / len(vals) * 100, 1),
        "up": up,
        "down": dn,
        "flat": len(vals) - up - dn,
        "best": round(max(vals), 2),
        "worst": round(min(vals), 2),
    }


def attach(out_dir="docs", days=120, log=print, lmt=140):
    """就地补写历史名单的次日表现。返回 {date: next_summary}。"""
    arch_dir = os.path.join(out_dir, "data", "archive")
    files = sorted(glob.glob(os.path.join(arch_dir, "*.json")))[-days:]
    if not files:
        log("[returns] 没有历史名单，跳过")
        return {}

    snaps = [(os.path.basename(f)[:-5], _read(f)) for f in files]
    codes = sorted({r["code"] for _, s in snaps for r in s.get("rows", [])})
    as_of = snaps[-1][0]
    log(f"[returns] 补 {len(snaps)} 份名单 / {len(codes)} 只股票的次日表现（基准日 {as_of}）")

    kmap = ds.get_klines(codes, as_of, lmt=lmt)
    by_code = {}
    for code, df in kmap.items():
        if df is None or len(df) == 0:
            continue
        by_code[code] = (_to_bars(df), sorted(str(d) for d in df["date"]))

    result = {}
    for date, snap in snaps:
        rows = snap.get("rows", [])
        for r in rows:
            bars, dates = by_code.get(r["code"], ({}, []))
            base = r.get("today_close") or (bars.get(date, (None, None))[1])
            if date not in dates:
                r.update(next_date=None, next_open_pct=None, next_close_pct=None,
                         next_high_pct=None, next_low_pct=None)
                continue
            i = dates.index(date)
            if i + 1 >= len(dates):
                r.update(next_date=None, next_open_pct=None, next_close_pct=None,
                         next_high_pct=None, next_low_pct=None)
                continue
            nxt = dates[i + 1]
            o, c, h, lo = bars[nxt]
            r.update(
                next_date=nxt,
                next_open_pct=_pct(o, base),
                next_close_pct=_pct(c, base),
                next_high_pct=_pct(h, base),
                next_low_pct=_pct(lo, base),
            )

        snap["day_summary"] = _summ(rows, "today_pct")
        snap["next_summary"] = _summ(rows, "next_close_pct")
        _write(os.path.join(arch_dir, f"{date}.json"), snap)
        result[date] = snap["next_summary"]

        n = snap["next_summary"]
        if n:
            log(f"[returns] {date} 选出 {len(rows)} 只 → 次日平均 {n['avg_pct']:+.2f}%"
                f"（涨 {n['up']} 跌 {n['down']}，胜率 {n['win_rate']}%）")
        else:
            log(f"[returns] {date} 选出 {len(rows)} 只 → 次日数据还没出来")

    # 最新名单（list.json）与它对应的 archive 保持一致
    p_list = os.path.join(out_dir, "data", "list.json")
    if os.path.exists(p_list):
        lst = _read(p_list)
        src = dict(snaps).get(lst.get("trade_date"))
        if src:
            for key in ("rows", "day_summary", "next_summary"):
                lst[key] = src.get(key)
            _write(p_list, lst)

    # 历史索引加一列，方便列表上直接显示
    p_hist = os.path.join(out_dir, "data", "history.json")
    if os.path.exists(p_hist):
        hist = _read(p_hist)
        for it in hist.get("items", []):
            src = dict(snaps).get(it["date"])
            if not src:
                continue
            d, n = src.get("day_summary"), src.get("next_summary")
            it["day_avg_pct"] = d["avg_pct"] if d else None
            it["next_avg_pct"] = n["avg_pct"] if n else None
            it["next_win_rate"] = n["win_rate"] if n else None
            it["next_n"] = n["n"] if n else 0
        _write(p_hist, hist)

    return result


def main():
    ap = argparse.ArgumentParser(description="补写次日涨跌幅")
    ap.add_argument("--out", default="docs", help="静态站点目录（默认 docs）")
    ap.add_argument("--days", type=int, default=120, help="最多处理多少份名单")
    args = ap.parse_args()
    attach(args.out, days=args.days)


if __name__ == "__main__":
    main()
