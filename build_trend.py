# -*- coding: utf-8 -*-
"""把「强趋势」这套东西接进 stock-screener 的每日流水线。

- 数据层复用 `trend/data.py`（其内部再复用 `screener/datasource.py` 的三级兜底）；
- 独立生成的页面放在 `docs/trend/`，和主页 `docs/index.html`（首板冷度）互不干扰；
- 两个页面顶部各有两个胶囊互相跳转。
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from trend import config as C  # noqa: E402
from trend import data as D  # noqa: E402
from trend import factors as F  # noqa: E402
from trend import screen as S  # noqa: E402
from trend.screen import bad_name, is_main_board  # noqa: E402

BJ = timezone(timedelta(hours=8))


def ensure_universe(log=print, lmt=300, force=False):
    """有缓存就直接用；缓存过旧或缺失就重新抓一遍。"""
    path = D.UNIVERSE
    if not force and os.path.exists(path):
        try:
            store = D.load_universe(path)
            codes, dates, mats = D.to_matrices(store)
            last = str(mats["close"].index[-1].date())
            days = D.trade_days(lmt=10)
            want = days[-1] if days else last
            if len(codes) > 500 and last >= want:
                log(f"[trend] 用本地 K 线缓存：{len(codes)} 只 · 截至 {last}")
                return store, codes, dates, mats
            log(f"[trend] 缓存停在 {last}（最新交易日 {want}），重新抓")
        except Exception as e:  # noqa: BLE001
            log(f"[trend] 缓存读取失败（{e}），重新抓")

    spot = pd.DataFrame()
    try:
        spot = D.load_spot(log=log, refresh=True)
    except Exception as e:  # noqa: BLE001
        log(f"[trend] 快照取不到：{e}")

    codes = []
    if len(spot):
        for r in spot.itertuples(index=False):
            code = str(getattr(r, "code", ""))
            name = str(getattr(r, "name", ""))
            if is_main_board(code) and not bad_name(name):
                codes.append(code)
    if not codes:
        raise RuntimeError("拿不到主板股票清单（快照为空），无法抓 K 线")

    days = D.trade_days(lmt=10)
    asof = days[-1] if days else None
    log(f"[trend] 抓 {len(codes)} 只主板日 K（lmt={lmt}）…")
    t0 = time.time()
    store = D.ds.get_klines(codes, asof, lmt=lmt)
    store = {k: v for k, v in store.items() if v is not None and len(v)}
    log(f"[trend] K 线就绪 {len(store)}/{len(codes)}，{round(time.time() - t0)}s")
    if len(store) < 500:
        raise RuntimeError(f"K 线只拿到 {len(store)} 只，疑似限流，保留上一次结果")

    codes, dates, mats = D.to_matrices(store)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        import pickle

        with open(path, "wb") as fh:
            pickle.dump(store, fh)
        log(f"[trend] 已写缓存 {path}")
    except Exception as e:  # noqa: BLE001
        log(f"[trend] 缓存写入失败：{e}")
    return store, codes, dates, mats


PILLS = """<nav class="pills">
      <a class="pill" href="../">首板冷度</a>
      <a class="pill on" href="./">强趋势</a>
    </nav>"""

CSS = """
*{box-sizing:border-box}
html,body{margin:0;background:#0a0d12;color:#e8edf5;
  font:15px/1.5 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  -webkit-text-size-adjust:100%}
body{padding:0 0 env(safe-area-inset-bottom)}
.wrap{max-width:520px;margin:0 auto;padding:0 12px}
header{padding:14px 12px 10px;display:flex;align-items:center;gap:10px}
.logo{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,#7c5cff,#3fa9ff);
  display:grid;place-items:center;font-weight:700;font-size:16px;color:#fff;flex:0 0 auto}
.tt{font-size:17px;font-weight:700;letter-spacing:.3px}
.sub{font-size:11.5px;color:#8b98ab;margin-top:1px}
.pills{display:flex;gap:8px;padding:2px 12px 10px}
.pill{flex:1;text-align:center;padding:9px 0;border-radius:11px;font-size:13.5px;font-weight:600;
  color:#9aa8bd;background:#131822;border:1px solid #1e2532;text-decoration:none}
.pill.on{color:#fff;background:linear-gradient(135deg,rgba(124,92,255,.30),rgba(63,169,255,.22));
  border-color:rgba(124,92,255,.55)}
.kpi{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:2px 0 10px}
.kpi div{background:#10151e;border:1px solid #1b2230;border-radius:12px;padding:9px 6px;text-align:center}
.kpi b{display:block;font-size:16px}
.kpi span{font-size:10.5px;color:#8b98ab}
.regime{border-radius:12px;padding:11px 12px;font-size:12.5px;line-height:1.6;margin-bottom:10px;
  border:1px solid #1e2532;background:#10151e}
.regime.bad{border-color:rgba(255,90,95,.45);background:rgba(255,90,95,.09)}
.regime.ok{border-color:rgba(43,212,143,.4);background:rgba(43,212,143,.08)}
.regime b{font-size:14px}
.regime.bad b{color:#ff5a5f}.regime.ok b{color:#2bd48f}
.card{background:#10151e;border:1px solid #1b2230;border-radius:14px;padding:12px;margin-bottom:10px}
.crow{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.rk{color:#5d6b82;font-size:12px;width:14px}
.nm{font-size:16.5px;font-weight:700}
.cd{font-size:12px;color:#7d8ba0}
.sc{margin-left:auto;font-size:19px;font-weight:700;color:#8ea2ff}
.tag{font-size:10.5px;padding:2px 7px;border-radius:7px;background:rgba(43,212,143,.13);color:#2bd48f}
.px{display:flex;gap:12px;align-items:baseline;margin:6px 0 8px}
.px b{font-size:20px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:7px 8px;font-size:12px}
.grid div span{display:block;color:#7d8ba0;font-size:10.5px}
.grid div b{font-weight:600}
.up{color:#ff5a5f}.dn{color:#2bd48f}
.plan{display:grid;grid-template-columns:repeat(2,1fr);gap:7px;margin-top:9px;
  border-top:1px dashed #1e2530;padding-top:9px;font-size:12.5px}
.plan span{color:#7d8ba0;font-size:10.5px;display:block}
.plan b{font-size:14px}
.foot{color:#6d7a8d;font-size:11px;line-height:1.6;padding:6px 2px 22px}
table{width:100%;border-collapse:collapse;font-size:11.5px;margin-top:6px}
th,td{padding:4px 3px;text-align:right;border-bottom:1px solid #161d29}
th:first-child,td:first-child{text-align:left}
th{color:#7d8ba0;font-weight:500;font-size:10.5px}
h3{font-size:13px;color:#9aa8bd;margin:14px 0 6px;font-weight:600}
"""


def _cls(v):
    try:
        if v is None or v != v:
            return ""
        return "up" if v > 0 else ("dn" if v < 0 else "")
    except Exception:  # noqa: BLE001
        return ""


def _n(v, nd=1, suffix=""):
    try:
        if v is None or v != v:
            return "—"
        return f"{v:.{nd}f}{suffix}"
    except Exception:  # noqa: BLE001
        return "—"


def page_html(res, meta, hist):
    rows = res["rows"]
    mkt_bad = not res.get("mkt_ok", True)
    regime_cls = "bad" if mkt_bad else "ok"
    regime_txt = (
        f'<b>{"空仓区 · 建议观望" if mkt_bad else "可参与"}</b>'
        f'　大盘 20 日 {_n(res.get("mom20"), 1, "%")}<br>'
        + (
            "等权指数在 20 日线下方，趋势策略在这种环境最容易连续吃面。名单仅作观察。"
            if mkt_bad
            else "等权指数站在 20 日线上方，趋势顺势可做。"
        )
    )
    cards = []
    for k, r in enumerate(rows, 1):
        cards.append(
            f"""<div class="card">
      <div class="crow"><span class="rk">{k}</span><span class="nm">{r['name']}</span>
        <span class="cd">{r['code']}</span>
        <span class="sc">{_n(r['score'], 1)}</span></div>
      <div class="px"><b>{_n(r['price'], 2)}</b>
        <span class="cd">20 日均额 {_n(r.get('amt20_yi'), 2, ' 亿')}</span></div>
      <div class="grid">
        <div><span>20 日涨幅</span><b class="{_cls(r.get('ret20'))}">{_n(r.get('ret20'), 1, '%')}</b></div>
        <div><span>相对强度</span><b>{_n((r.get('rs20') or 0) * 100, 0, '%')}</b></div>
        <div><span>距 20 日新高</span><b>{_n(r.get('to_high'), 1, '%')}</b></div>
        <div><span>离 MA20</span><b class="{_cls(r.get('dist_ma20'))}">{_n(r.get('dist_ma20'), 1, '%')}</b></div>
        <div><span>日均振幅</span><b>{_n(r.get('atr_pct'), 1, '%')}</b></div>
        <div><span>换手 / 量能</span><b>{_n(r.get('turnover'), 1, '%')} / {_n(r.get('vol_surge'), 2)}</b></div>
      </div>
      <div class="plan">
        <div><span>止损（ATR 自适应）</span><b class="dn">{_n(r.get('stop'), 2)}</b></div>
        <div><span>目标</span><b class="up">{_n(r.get('target'), 2)}</b></div>
      </div>
    </div>"""
        )
    if not cards:
        cards.append('<div class="card">今天没有符合条件的票。</div>')

    def _fval(x):
        return x["value"] if isinstance(x, dict) else x

    funnel_rows = "".join(
        f"<tr><td>{(x['name'] if isinstance(x, dict) else x)}</td><td>{_fval(x)}</td></tr>"
        for x in res["funnel"]
    )
    hist_chips = "".join(
        f'<a class="pill" style="flex:0 0 auto;padding:6px 10px" href="history/{d}.json">{d[5:]}·{n}只</a>'
        for d, n in hist[-6:][::-1]
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0a0d12">
<title>强趋势 · 高弹性选股</title>
<style>{CSS}</style>
</head><body>
<header><div class="logo">趋</div>
  <div><div class="tt">强趋势 · 高弹性</div>
  <div class="sub">数据日期 {res['asof']} · {meta['generated_at']} 生成 · {meta['elapsed_sec']}s</div></div>
</header>
{PILLS}
<div class="wrap">
  <div class="kpi">
    <div><b>{len(rows)}</b><span>入选</span></div>
    <div><b>{_fval(res['funnel'][0]) if res['funnel'] else 0}</b><span>候选池</span></div>
    <div><b>{'空仓区' if mkt_bad else '可做'}</b><span>市况</span></div>
    <div><b>{_n(res.get('mom20'), 1, '%')}</b><span>大盘 20 日</span></div>
  </div>
  <div class="regime {regime_cls}">{regime_txt}</div>
  <div class="foot" style="padding:0 2px 10px">
    每个交易日 <b>11:00</b> 自动更新（盘中快照，当日数据为当时价格）。
  </div>
  {''.join(cards)}
  <h3>筛选漏斗</h3>
  <table><thead><tr><th>阶段</th><th>剩余</th></tr></thead><tbody>{funnel_rows}</tbody></table>
  <h3>历史</h3>
  <div class="pills" style="padding:0;flex-wrap:wrap">{hist_chips or '<span class="foot">暂无</span>'}</div>
  <div class="foot">
    规则：主板（不含 ST / 科创 / 创业 / 北交所 / N·C 新股）→ 均线多头排列且站上 120 日线 →
    离 20 日新高 ≤6% → 换手 3–25%、日均振幅 2.2–9% → 量能 ≥1.0 → 离 MA20 ≤16%、当日涨幅 &lt;9%。<br>
    出场：次日开盘买；止损按 ATR 自适应（4–9%）；目标 +40%；收盘跌破 10 日线走；最长 15 个交易日。<br>
    回测（200 天，含市况开关）：464 笔、均值 +1.22%、中位 −3.85%、胜率 29.7%，基准 −0.91%。
    胜率不高，靠少数大赢家；200 天单一环境，不构成投资建议。
  </div>
</div>
</body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--top", type=int, default=None)
    ap.add_argument("--out", default=os.path.join(HERE, "docs"))
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument("--if-missing", action="store_true",
                    help="今天已经生成过就跳过（定时任务的重试时段用）")
    args = ap.parse_args()

    t0 = time.time()
    log = print
    cfg = C.load()

    if args.if_missing:
        try:
            with open(os.path.join(args.out, "trend", "data.json"), encoding="utf-8") as fh:
                done = json.load(fh).get("asof")
            days = D.trade_days(lmt=10)
            if days and done == days[-1]:
                log(f"[trend] 今天的名单已存在（{done}），跳过")
                return
        except Exception:  # noqa: BLE001
            pass
    if args.top:
        cfg["top_n"] = args.top

    store, codes, dates, mats = ensure_universe(log=log, force=not args.skip_fetch)
    f = F.compute(mats)
    scores = S.score_frames(f, mats)
    spot = D.load_spot(log=log)

    asof = args.date or D.last_trade_date(mats)
    res = S.run(mats, f, scores, spot, asof, cfg)
    if not res["rows"]:
        raise RuntimeError(f"{asof} 一只都没选出来，保留上一次结果")
    elapsed = round(time.time() - t0, 1)
    meta = {"generated_at": datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_sec": elapsed}

    out = os.path.join(args.out, "trend")
    os.makedirs(os.path.join(out, "history"), exist_ok=True)

    payload = {
        "asof": res["asof"],
        "generated_at": meta["generated_at"],
        "elapsed_sec": elapsed,
        "market": {"ok": bool(res.get("mkt_ok")), "mom20": res.get("mom20")},
        "funnel": res["funnel"],
        "stages": S.FUNNEL,
        "rows": res["rows"],
        "rejects": len(res.get("rejects") or []),
        "schedule": "11:00",
    }
    with open(os.path.join(out, "data.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False,
                  default=lambda o: o.item() if hasattr(o, "item") else str(o),
                  indent=1)
    with open(os.path.join(out, "history", f"{res['asof']}.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False,
                  default=lambda o: o.item() if hasattr(o, "item") else str(o))

    hist = []
    hdir = os.path.join(out, "history")
    for name in sorted(os.listdir(hdir)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(hdir, name), encoding="utf-8") as fh:
                d = json.load(fh)
            hist.append((d["asof"], len(d.get("rows") or [])))
        except Exception:  # noqa: BLE001
            continue
    # 只保留最近 120 天的历史，避免仓库越来越大
    keep = {d for d, _ in hist[-120:]}
    for name in os.listdir(hdir):
        if name.endswith(".json") and name[:-5] not in keep:
            try:
                os.remove(os.path.join(hdir, name))
            except Exception:  # noqa: BLE001
                pass

    with open(os.path.join(out, "history.json"), "w", encoding="utf-8") as fh:
        json.dump([{"date": d, "count": n} for d, n in hist], fh, ensure_ascii=False)

    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(page_html(res, meta, hist))

    log(f"[trend] {res['asof']} 入选 {len(rows := res['rows'])} 只 · {elapsed}s → {out}")
    for k, r in enumerate(rows, 1):
        log(f"  {k}. {r['name']} {r['code']}  {r['price']:.2f}  分{r['score']:.1f}  "
            f"止损{r['stop']:.2f} 目标{r['target']:.2f}")


if __name__ == "__main__":
    main()
