# -*- coding: utf-8 -*-
"""
命令行入口：选股 → 生成 HTML 报告 + CSV/Excel。

用法示例：
  python run.py                             # 用最新交易日、默认参数
  python run.py --date 2026-11-04 --refresh # 指定日期并强制刷新数据
  python run.py --top 20 --min-score 40     # 只看前 20 只、冷度分 ≥40
  python run.py --set turnover_today_max=8 --set amount_today_max_yi=12
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:  # Windows 控制台中文输出
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from screener.config import load_config  # noqa: E402
from screener.report import build_report  # noqa: E402
from screener.screen import run_screen  # noqa: E402


def _parse_set(items):
    out = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit(f"--set 需要 key=value 形式：{it}")
        k, v = it.split("=", 1)
        k = k.strip()
        v = v.strip()
        try:
            if v.lower() in ("true", "false"):
                v = v.lower() == "true"
            elif "." in v or "e" in v.lower():
                v = float(v)
            else:
                v = int(v)
        except ValueError:
            pass
        out[k] = v
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="首板回踩左侧 + 低热度 A 股选股系统")
    ap.add_argument("--date", help="交易日 YYYY-MM-DD，默认最新交易日")
    ap.add_argument("--config", help="配置文件路径，默认 ./config.json")
    ap.add_argument("--refresh", action="store_true", help="强制刷新行情/涨停池/辅助数据")
    ap.add_argument("--top", type=int, help="报告展示数量")
    ap.add_argument("--min-score", type=float, dest="score_min", help="最低冷度分")
    ap.add_argument("--out", default=None, help="报告输出目录")
    ap.add_argument("--quiet", action="store_true", help="不打印过程日志")
    ap.add_argument("--set", dest="overrides", action="append",
                    help="临时覆盖任意参数，如 --set left_tolerance_pct=4")
    args = ap.parse_args(argv)

    over = _parse_set(args.overrides)
    if args.top is not None:
        over["top_n"] = args.top
    if args.score_min is not None:
        over["score_min"] = args.score_min

    cfg = load_config(args.config, over)
    log = (lambda *a, **k: None) if args.quiet else (lambda s="": print(s, file=sys.stderr))

    res = run_screen(cfg, as_of=args.date, refresh=args.refresh, log=log)
    out_dir = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       cfg["output_dir"])
    paths = build_report(res, out_dir)

    meta = res["meta"]
    print(f"\n交易日 {meta['trade_date']}｜漏斗：")
    for k, v in meta["funnel"].items():
        print(f"  {k:>16s} {v:>6d}")
    print(f"\n入选 {len(res['all_rows'])} 只：")
    for i, r in enumerate(res["all_rows"], 1):
        print(f"  {i:>2d}. {r['code']} {r['name']:<6s} {r['window']} 首板{r['board_date']}"
              f" 距今{r['days_since']}日 回踩{r['retrace_pct']:+.1f}% "
              f"左侧偏离{r['left_dev_pct']:+.1f}% 换手{r['today_turnover']:.1f}% "
              f"冷度分{r['score']:.1f}")
    print("\n报告：")
    for k, p in paths.items():
        if p:
            print(f"  {k:<5s} {p}")
    return paths


if __name__ == "__main__":
    main()
