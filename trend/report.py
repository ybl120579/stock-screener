# -*- coding: utf-8 -*-
"""自包含 HTML 报告。"""
import html
import io
import json

CSS = """
*{box-sizing:border-box}body{margin:0;background:#f5f6f8;color:#1b2130;
font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:26px 20px 60px}
h1{font-size:26px;margin:0 0 4px}
.sub{color:#69707d;font-size:12.5px;margin-bottom:18px}
.kpis{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px}
.kpi{background:#fff;border:1px solid #e6e9ef;border-radius:10px;padding:12px 16px;min-width:150px}
.kpi i{display:block;font-style:normal;color:#7b8494;font-size:12px;margin-bottom:4px}
.kpi b{font-size:20px}
.card{background:#fff;border:1px solid #e6e9ef;border-radius:12px;padding:16px 18px;margin-bottom:16px}
.card h2{font-size:15px;margin:0 0 12px;padding-left:9px;border-left:3px solid #3b62f6}
.regime{border-radius:10px;padding:10px 12px;margin-bottom:10px;font-size:13px}
.regime b{margin-right:10px}.regime span{color:#7b8494;font-size:12px}
.regime p{margin:4px 0 0;color:#5b6472}
.regime.ok{background:#eef7f1;border:1px solid #cfe7d8}.regime.ok b{color:#1a7f4b}
.regime.bad{background:#fdeeee;border:1px solid #f2cccc}.regime.bad b{color:#c02a2a}
.note{background:#fdf8ea;border:1px solid #f0e2b8;border-radius:8px;padding:10px 12px;font-size:12.5px;color:#6b5a20}
.frow{display:flex;align-items:center;gap:10px;margin:7px 0}
.fname{width:132px;color:#3b4354;font-size:12.5px}
.fbar{flex:1;height:9px;background:#eef0f4;border-radius:5px;overflow:hidden}
.fbar>i{display:block;height:100%;background:linear-gradient(90deg,#4f7cff,#7d5cff)}
.fval{width:62px;text-align:right;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{padding:7px 8px;border-bottom:1px solid #eef0f4;text-align:right;white-space:nowrap}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}
th{color:#7b8494;font-weight:500;background:#fafbfc}
.up{color:#d0342c;font-weight:600}.dn{color:#0f8f4e;font-weight:600}
.stock{border-top:1px solid #eef0f4;padding:14px 0}
.stock:first-of-type{border-top:0}
.shead{display:flex;align-items:baseline;gap:10px;margin-bottom:8px}
.shead b{font-size:15px}.shead code{color:#7b8494;font-size:12px}
.shead .sc{margin-left:auto;font-weight:700;color:#3b62f6}
.sbody{display:grid;grid-template-columns:380px 1fr;gap:18px}
.bars{margin-top:6px}
.bar{display:flex;align-items:center;gap:8px;font-size:11.5px;color:#6b7280;margin:3px 0}
.bar span{width:56px}.bar .bul{flex:1;height:6px;background:#eef0f4;border-radius:3px}
.bar .bul>i{display:block;height:100%;background:#7d5cff;border-radius:3px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px 14px;font-size:12px}
.grid i{color:#8b93a2;font-style:normal;display:block;font-size:11px}
.grid b{font-size:13px}
.legend{color:#8b93a2;font-size:11.5px;margin-top:6px}
"""


def _fmt(v, nd=2, suffix=""):
    if v is None:
        return "—"
    try:
        return "%.*f%s" % (nd, float(v), suffix)
    except Exception:
        return str(v)


def spark(closes, high=None, w=360, h=110, pad=8):
    if not closes or len(closes) < 2:
        return ""
    lo, hi = min(closes), max(closes)
    rng = (hi - lo) or 1
    pts = []
    for k, v in enumerate(closes):
        x = pad + k * (w - 2 * pad) / (len(closes) - 1)
        y = h - pad - (v - lo) / rng * (h - 2 * pad)
        pts.append("%.1f,%.1f" % (x, y))
    line = " ".join(pts)
    area = "%d,%d " % (pad, h - pad) + line + " %d,%d" % (w - pad, h - pad)
    extra = ""
    if high is not None and lo <= high <= hi:
        y = h - pad - (high - lo) / rng * (h - 2 * pad)
        extra = ('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#f0a020" '
                 'stroke-width="1" stroke-dasharray="4 3"/>' % (pad, y, w - pad, y))
    return ('<svg viewBox="0 0 %d %d" width="100%%" height="%d" preserveAspectRatio="none">'
            '<polygon points="%s" fill="#3b62f6" opacity=".07"/>%s'
            '<polyline points="%s" fill="none" stroke="#3b62f6" stroke-width="1.5"/></svg>'
            % (w, h, h, area, extra, line))


def render(res, hist, meta, out_path):
    rows = res["rows"]
    cfg = meta.get("cfg", {})
    mom20 = res.get("mom20")
    kpi = [("入选股票", "%d 只" % len(rows)),
           ("候选池", "%d 只" % res["funnel"][0]["value"]),
           ("市场状态", "强势" if res.get("mkt_ok") else "空仓区"),
           ("大盘 20 日", ("%+.1f%%" % mom20) if mom20 is not None else "—"),
           ("计算耗时", "%s 秒" % meta.get("elapsed_sec", 0))]
    kpi_html = "".join('<div class="kpi"><i>%s</i><b>%s</b></div>' % (k, v) for k, v in kpi)

    ok = bool(res.get("mkt_ok"))
    regime = ""
    if mom20 is not None:
        lbl = "趋势环境合格 · 可执行" if ok else "指数在 20 日线下方 · 建议空仓"
        regime = ('<div class="regime %s"><b>%s</b><span>大盘 20 日 %+.1f%%</span>'
                  '<p>%s</p></div>' % ("ok" if ok else "bad", lbl, mom20,
                                       html.escape(res.get("advice") or "")))

    fun = res["funnel"]
    top = fun[0]["value"] or 1
    frows = "".join(
        '<div class="frow"><div class="fname">%s</div>'
        '<div class="fbar"><i style="width:%.1f%%"></i></div>'
        '<div class="fval">%d</div></div>'
        '<div style="color:#9aa3b2;font-size:11.5px;margin:-3px 0 8px 142px">%s</div>'
        % (html.escape(f["name"]), f["value"] / top * 100, f["value"], html.escape(f["hint"]))
        for f in fun)

    trs = []
    for k, r in enumerate(rows, 1):
        trs.append(
            '<tr><td>%d</td><td>%s</td><td>%s</td><td>%s</td><td class="up">%s</td>'
            '<td class="up">%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
            '<td>%s</td><td>%s</td><td>%s</td><td class="dn">%s</td><td class="up">%s</td></tr>'
            % (k, html.escape(r["name"]), r["code"], _fmt(r["price"]), _fmt(r["score"], 1),
               _fmt(r["ret20"], 1, "%"), _fmt(r["rs20"] * 100, 0, "%"),
               _fmt(r["dist_ma20"], 1, "%"), _fmt(r["to_high"], 1, "%"),
               _fmt(r["atr_pct"], 1, "%"), _fmt(r["turnover"], 1, "%"),
               _fmt(r["vol_surge"], 2), _fmt(r["amt20_yi"], 2),
               _fmt(r["stop"]), _fmt(r["target"])))

    stocks = []
    for k, r in enumerate(rows, 1):
        cl = hist.get(r["code"], [])
        parts = r.get("s_parts") or {}
        bars = "".join(
            '<div class="bar"><span>%s</span><div class="bul"><i style="width:%.0f%%"></i></div></div>'
            % (n, max(0.0, min(100.0, float(v or 0))))
            for n, v in (("动量", parts.get("s_mom")), ("相对强度", parts.get("s_rs")),
                         ("量能", parts.get("s_vol")), ("弹性", parts.get("s_atr")),
                         ("贴近新高", parts.get("s_high"))))
        grid = [
            ("现价", _fmt(r["price"]), ""), ("20 日涨幅", _fmt(r["ret20"], 1, "%"), "up"),
            ("60 日涨幅", _fmt(r["ret60"], 1, "%"), ""), ("离 20 日线", _fmt(r["dist_ma20"], 1, "%"), ""),
            ("距 20 日新高", _fmt(r["to_high"], 1, "%"), ""), ("平均振幅", _fmt(r["atr_pct"], 1, "%"), ""),
            ("换手", _fmt(r["turnover"], 1, "%"), ""), ("量能倍数", _fmt(r["vol_surge"], 2), ""),
            ("20 日均额", _fmt(r["amt20_yi"], 2, " 亿"), ""),
            ("止损", "%s (−%s%%)" % (_fmt(r["stop"]), _fmt(r["stop_pct"], 1)), "dn"),
            ("目标", "%s (+%s%%)" % (_fmt(r["target"]), _fmt(r["target_pct"], 0)), "up"),
            ("流通市值", _fmt(r["float_mcap_yi"], 0, "亿"), ""),
        ]
        g = "".join('<div><i>%s</i><b class="%s">%s</b></div>' % (a, c, b) for a, b, c in grid)
        stocks.append(
            '<div class="stock"><div class="shead"><b>%d. %s</b><code>%s</code>'
            '<span class="sc">综合分 %s</span></div>'
            '<div class="sbody"><div>%s<div class="legend">近 120 日收盘（虚线=20 日最高价）</div></div>'
            '<div><div class="grid">%s</div><div class="bars">%s</div></div></div></div>'
            % (k, html.escape(r["name"]), r["code"], _fmt(r["score"], 1),
               spark(cl, r.get("hi20")), g, bars))

    rej = {}
    for _c, _n, why in res["rejects"]:
        key = why.split(" ")[0][:12]
        rej[key] = rej.get(key, 0) + 1
    mx = max(rej.values()) if rej else 1
    rrows = "".join(
        '<div class="frow"><div class="fname">%s</div>'
        '<div class="fbar"><i style="width:%.1f%%"></i></div><div class="fval">%d</div></div>'
        % (html.escape(k), v / mx * 100, v)
        for k, v in sorted(rej.items(), key=lambda x: -x[1])[:12])

    doc = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>强趋势选股 · %(asof)s</title><style>%(css)s</style></head><body><div class="wrap">
<h1>强趋势 · 高弹性选股 <span style="font-size:14px;color:#7b8494;font-weight:400">多头排列 · 贴近新高 · 放量活跃</span></h1>
<div class="sub">数据日期 %(asof)s · 生成于 %(gen)s · 数据源：东方财富 / 新浪 / 腾讯（公开行情接口）</div>
<div class="kpis">%(kpi)s</div>
<div class="card"><h2>策略逻辑</h2>
<div style="font-size:13px;line-height:1.9;color:#3b4354">
① <b>均线多头排列</b>：MA5 &gt; MA10 &gt; MA20 &gt; MA60，且站上 120 日线 —— 趋势明确向上。<br>
② <b>贴着 20 日新高</b>：离 20 日最高价 ≤ %(tohigh).0f%%，只做强中强。<br>
③ <b>要有弹性</b>：20 日平均振幅 %(atrmin)s–%(atrmax)s%%，换手 %(tmin)s–%(tmax)s%%，不温不火的不做。<br>
④ <b>量能配合</b>：成交额 ≥ 20 日均量 %(vmin)s 倍。<br>
⑤ <b>不追太高</b>：离 MA20 ≤ %(dist).0f%%，当日涨幅 &lt; %(pctmax).0f%%。
</div>
%(regime)s
<div class="note" style="margin-top:10px">出场：次日开盘买入；止损按 ATR 自适应（%(smin)s–%(smax)s%%）；目标 +%(tgt).0f%%；<b>收盘跌破 10 日线立即走</b>；最长持有 %(hold)d 个交易日。</div>
</div>
<div class="card"><h2>筛选漏斗</h2>%(frows)s</div>
<div class="card"><h2>入选结果（按综合分排序）</h2>
<table><tr><th>#</th><th>名称</th><th>代码</th><th>现价</th><th>综合分</th><th>20日涨</th><th>RS20</th>
<th>离20线</th><th>距新高</th><th>振幅</th><th>换手</th><th>量能</th><th>均额亿</th><th>止损</th><th>目标</th></tr>
%(trs)s</table></div>
<div class="card"><h2>逐只详情</h2>%(stocks)s</div>
<div class="card"><h2>被剔除的常见原因</h2>%(rrows)s</div>
</div></body></html>""" % {
        "asof": res["asof"], "css": CSS, "gen": meta.get("generated_at", ""),
        "kpi": kpi_html, "regime": regime, "frows": frows, "trs": "".join(trs),
        "stocks": "".join(stocks), "rrows": rrows,
        "tohigh": cfg.get("max_to_high", 6), "atrmin": cfg.get("atr_min_pct", 2.2),
        "atrmax": cfg.get("atr_max_pct", 9), "tmin": cfg.get("turnover_min", 3),
        "tmax": cfg.get("turnover_max", 25), "vmin": cfg.get("vol_surge_min", 1),
        "dist": cfg.get("max_dist_ma20", 16), "pctmax": cfg.get("max_pct_today", 9),
        "smin": cfg.get("stop_min_pct", 4), "smax": cfg.get("stop_max_pct", 9),
        "tgt": cfg.get("target_pct", 25), "hold": cfg.get("hold_days", 10),
    }
    with io.open(out_path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return out_path


def write_json(res, meta, out_path):
    payload = {"asof": res["asof"], "meta": meta, "funnel": res["funnel"],
               "advice": res.get("advice"), "mkt_ok": res.get("mkt_ok"),
               "mom20": res.get("mom20"), "rows": res["rows"],
               "rejects": [{"code": c, "name": n, "reason": w} for c, n, w in res["rejects"]]}
    with io.open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1, default=float)
    return out_path
