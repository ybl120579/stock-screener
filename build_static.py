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
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


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


def run_once(cfg, as_of):
    return screen.run_screen(cfg, as_of, refresh=True, log=log)


def main():
    ap = argparse.ArgumentParser(description="生成静态站点到 docs/")
    ap.add_argument("--date", help="指定交易日（默认最近交易日）")
    ap.add_argument("--out", default=os.path.join(HERE, "docs"), help="输出目录")
    ap.add_argument("--schedule", default="15:35", help="展示用的自动更新时间")
    ap.add_argument("--skip-ui", action="store_true", help="只更新数据，不复制前端文件")
    ap.add_argument("--if-missing", action="store_true",
                    help="该交易日已有快照就跳过（定时任务用，避免节假日重复跑）")
    args = ap.parse_args()

    cfg = cfgmod.load_config(os.path.join(HERE, "config.json")) if os.path.exists(
        os.path.join(HERE, "config.json")) else cfgmod.load_config()
    days = ds.get_trade_days(lmt=60)
    as_of = args.date or days[-1]
    if as_of > days[-1]:
        raise SystemExit(f"还没有 {as_of} 的数据（最近交易日 {days[-1]}）")

    have = os.path.join(args.out, "data", "archive", f"{as_of}.json")
    if args.if_missing and os.path.exists(have):
        log(f"{as_of} 已有快照，跳过（要重跑请去掉 --if-missing）")
        return 0

    t0 = time.time()
    res = None
    for attempt in (1, 2):
        try:
            res = run_once(cfg, as_of)
            break
        except Exception as e:  # 网络抖动重试一次
            log(f"第 {attempt} 次运行失败：{e}")
            traceback.print_exc()
            if attempt == 2:
                raise SystemExit("筛选失败，保留上一次的数据不做覆盖")
            time.sleep(20)

    rows = []
    for r in res["rows"]:
        s = mobile_app._slim(r)
        s["chart"] = r.get("chart") or {"bars": [], "board_idx": -1, "left_ref": None}
        rows.append(s)

    meta = res["meta"]
    now = time.strftime("%Y-%m-%d %H:%M:%S")
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
        "params": meta.get("params"),
        "weights": meta.get("weights"),
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
