# -*- coding: utf-8 -*-
"""
生成静态站点（给 GitHub Pages / 任意静态托管用）
================================================

跑一次筛选，把结果和前端页面一起写进 `docs/`，推上 GitHub 后由 Pages 托管，
手机上随时能打开，不需要家里的电脑开着。

    python build_static.py                 # 用最近交易日的数据
    python build_static.py --date 2026-11-04
    python build_static.py --out site      # 换输出目录

产出：
    docs/index.html / style.css / app.js / sw.js / manifest.webmanifest / icon-*.png
    docs/data/list.json            最新名单（含 K 线）
    docs/data/archive/YYYY-MM-DD.json  历史名单
    docs/data/history.json         已有快照的日期列表
    docs/data/status.json          运行状态（上次生成时间、下次更新时间）
"""

import argparse
import json
import os
import shutil
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone

BJ = timezone(timedelta(hours=8))   # 统一用北京时间（GitHub 的机器是 UTC，本地是 +08）

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "mobile"))

from screener import config as cfgmod          # noqa: E402
from screener import datasource as ds          # noqa: E402
from screener import screen                    # noqa: E402

import app as mobile_app                       # noqa: E402  (mobile/app.py，复用 _slim)

UI_FILES = ["index.html", "style.css", "app.js", "sw.js", "manifest.webmanifest",
            "icon-180.png", "icon-192.png", "icon-512.png", "icon-512-maskable.png"]


def log(msg):
    print(f"[{datetime.now(BJ):%H:%M:%S}] {msg}", flush=True)


def write_json(path, obj, indent=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":") if indent is None else None,
                  indent=indent)
    os.replace(tmp, path)


def next_trade_day(after, days):
    """交易日历只到当天，往后按工作日顺延（节假日由当天自动更新纠正）。"""
    for d in days:
        if d > after:
            return d
    from datetime import date, timedelta
    y, m, dd = (int(x) for x in after.split("-"))
    cur = date(y, m, dd)
    for _ in range(10):
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            return cur.isoformat()
    return after


def run_once(cfg, as_of, cached=False):
    return screen.run_screen(cfg, as_of, refresh=not cached, log=log)


def main():
    ap = argparse.ArgumentParser(description="生成静态站点到 docs/")
    ap.add_argument("--date", help="指定交易日（默认最近交易日）")
    ap.add_argument("--out", default=os.path.join(HERE, "docs"), help="输出目录")
    ap.add_argument("--schedule", default="15:35", help="展示用的自动更新时间")
    ap.add_argument("--skip-ui", action="store_true", help="只更新数据，不复制前端文件")
    ap.add_argument("--cached", action="store_true",
                    help="优先用本地缓存（cache/）出数据，网络不通时也能重建页面")
    ap.add_argument("--if-missing", action="store_true",
                    help="该交易日已有快照就跳过（定时任务用，避免节假日重复跑）")
    args = ap.parse_args()

    cfg = cfgmod.load_config(os.path.join(HERE, "config.json")) if os.path.exists(
        os.path.join(HERE, "config.json")) else cfgmod.load_config()
    days = None
    for attempt in (1, 2, 3):
        try:
            days = ds.get_trade_days(lmt=60)
            break
        except Exception as e:  # noqa: BLE001
            log(f"取交易日历失败（第 {attempt} 次）：{e}")
            if attempt == 3:
                raise SystemExit("交易日历不可用，保留上一次数据")
            time.sleep(15)
    as_of = args.date or days[-1]
    if as_of > days[-1]:
        raise SystemExit(f"还没有 {as_of} 的数据（最近交易日 {days[-1]}）")

    have = os.path.join(args.out, "data", "archive", f"{as_of}.json")
    if args.if_missing and os.path.exists(have):
        log(f"{as_of} 已有快照，跳过（要重跑请去掉 --if-missing）")
        return 0

    t0 = time.time()
    res = None
    # 东财会按 IP 做短时限流（几十秒到一两分钟），所以失败后等久一点再重试；
    # 连续三次仍然不行才放弃，保留上一次的数据。
    for attempt, wait in ((1, 0), (2, 30), (3, 90)):
        try:
            ds.reset_throttle()
            res = run_once(cfg, as_of, cached=args.cached)
            break
        except Exception as e:  # noqa: BLE001
            log(f"第 {attempt} 次运行失败：{e}")
            if attempt == 3:
                traceback.print_exc()
                raise SystemExit("筛选失败，保留上一次的数据不做覆盖")
            log(f"等待 {wait}s 后重试…")
            time.sleep(wait)

    # 数据源被限流时 K 线会大面积失败，筛选结果会变成空集 —— 这种“假空结果”
    # 绝不能覆盖当天已经正确的快照，宁可重试。
    meta0 = res["meta"]
    kt, ko = meta0.get("kline_total") or 0, meta0.get("kline_ok") or 0
    if kt >= 50 and ko < kt * 0.5:
        raise RuntimeError(f"K线抓取大面积失败（{ko}/{kt}），疑似限流")

    rows = []
    for r in res["rows"]:
        s = mobile_app._slim(r)
        s["chart"] = r.get("chart") or {"bars": [], "board_idx": -1, "left_ref": None}
        rows.append(s)

    meta = res["meta"]
    now = datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "trade_date": as_of,
        "generated_at": now,
        "elapsed_sec": round(time.time() - t0, 1),
        "count": len(rows),
        "funnel": meta.get("funnel"),
        "pool_counts": meta.get("pool_counts"),
        "kline_ok": meta.get("kline_ok"),
        "kline_total": meta.get("kline_total"),
        "universe_main_count": meta.get("universe_main_count"),
        "aux_missing": meta.get("aux_missing") or [],
        "spot_source": meta.get("spot_source"),
        "params": meta.get("params"),
        "weights": meta.get("weights"),
        "rejects": meta.get("rejects") or [],
        "rows": rows,
    }
    log(f"{as_of} 筛出 {len(rows)} 只，用时 {payload['elapsed_sec']}s")

    out = args.out
    data_dir = os.path.join(out, "data")
    write_json(os.path.join(data_dir, "archive", f"{as_of}.json"), payload)
    write_json(os.path.join(data_dir, "list.json"), payload)

    hist_path = os.path.join(data_dir, "history.json")
    items = []
    if os.path.exists(hist_path):
        try:
            with open(hist_path, encoding="utf-8") as f:
                items = json.load(f).get("items") or []
        except Exception:
            items = []
    items = [it for it in items if it.get("date") != as_of]
    items.append({"date": as_of, "count": len(rows),
                  "top": rows[0]["name"] if rows else None,
                  "top_score": rows[0]["score"] if rows else None})
    items.sort(key=lambda x: x["date"], reverse=True)
    write_json(hist_path, {"items": items[:120]})

    nxt = next_trade_day(as_of, days) or as_of
    write_json(os.path.join(data_dir, "status.json"), {
        "ok": True, "running": False, "mode": "static",
        "last_run": now, "last_stage": f"完成 · {len(rows)} 只", "last_error": None,
        "schedule": args.schedule, "next_run": f"{nxt} {args.schedule}",
        "trade_date": as_of, "generated_at": now,
    })

    # 涨停池快照随仓库积累，用于东财接口不可用时回溯；只保留最近 60 个交易日
    pool_dir = os.path.join(data_dir, "pool")
    try:
        names = sorted(f for f in os.listdir(pool_dir) if f.endswith(".json"))
        for old in names[:-60]:
            os.remove(os.path.join(pool_dir, old))
    except FileNotFoundError:
        pass

    if not args.skip_ui:
        ui = os.path.join(HERE, "mobile", "ui")
        for name in UI_FILES:
            src = os.path.join(ui, name)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(out, name))
        open(os.path.join(out, ".nojekyll"), "w").close()

    log(f"完成 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
