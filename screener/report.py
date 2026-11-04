# -*- coding: utf-8 -*-
"""报告生成：自包含 HTML（含漏斗、可排序表格、逐股 SVG K 线、评分构成）+ CSV/Excel。"""
import csv
import html
import json
import os

CSS = r"""
:root{
  --bg:#f5f6f8; --card:#ffffff; --line:#e7e9ee; --ink:#1b1f26; --muted:#6b7280;
  --red:#e0453c; --green:#12a06a; --blue:#2f6fed; --amber:#d98700; --purple:#7a5af8;
  --shadow:0 1px 2px rgba(16,24,40,.05),0 8px 24px rgba(16,24,40,.06);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
  font-size:14px;line-height:1.6;-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:28px 22px 64px}
header.top{display:flex;justify-content:space-between;align-items:flex-end;gap:18px;flex-wrap:wrap;margin-bottom:20px}
h1{font-size:25px;margin:0 0 4px;letter-spacing:.2px}
h1 small{font-size:13px;font-weight:500;color:var(--muted);margin-left:8px}
.sub{color:var(--muted);font-size:13px}
.stamp{text-align:right;font-size:12px;color:var(--muted)}
.stamp b{color:var(--ink);font-size:15px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow)}
.card+.card{margin-top:16px}
.card h2{font-size:15px;margin:0;padding:16px 20px;border-bottom:1px solid var(--line);display:flex;
  align-items:center;gap:8px}
.card h2 .tagline{font-weight:400;font-size:12px;color:var(--muted)}
.card .body{padding:16px 20px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;box-shadow:var(--shadow)}
.kpi .k{font-size:12px;color:var(--muted)}
.kpi .v{font-size:22px;font-weight:700;margin-top:2px;font-variant-numeric:tabular-nums}
.kpi .v small{font-size:12px;font-weight:500;color:var(--muted);margin-left:3px}
.cond{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.cond .c{border:1px solid var(--line);border-radius:10px;padding:12px 14px;background:linear-gradient(180deg,#fff,#fbfcfe)}
.cond .c b{display:block;font-size:13px;margin-bottom:4px}
.cond .c span{font-size:12px;color:var(--muted);line-height:1.55}
.cond .c i{display:inline-block;width:18px;height:18px;border-radius:6px;color:#fff;font-style:normal;
  font-size:11px;text-align:center;line-height:18px;margin-right:6px;font-weight:700}
.funnel{display:flex;flex-direction:column;gap:6px}
.fr{display:grid;grid-template-columns:180px 1fr 64px;align-items:center;gap:10px;font-size:12.5px}
.fr .lab{color:var(--muted);text-align:right}
.fr .bar{height:20px;border-radius:4px;background:linear-gradient(90deg,#2f6fed,#6aa2ff);
  min-width:2px;transition:width .3s}
.fr:last-child .bar{background:linear-gradient(90deg,#e0453c,#ff7f75)}
.fr .num{font-variant-numeric:tabular-nums;font-weight:600}
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.toolbar input{flex:1;min-width:180px;padding:8px 12px;border:1px solid var(--line);border-radius:8px;
  font-size:13px;outline:none;background:#fff}
.toolbar input:focus{border-color:var(--blue);box-shadow:0 0 0 3px rgba(47,111,237,.12)}
.toolbar .hint{font-size:12px;color:var(--muted)}
.btn{display:inline-block;padding:8px 14px;border-radius:8px;border:1px solid var(--line);background:#fff;
  color:var(--ink);font-size:13px;text-decoration:none}
.btn:hover{border-color:#c9ced8}
.btn.primary{background:var(--blue);border-color:var(--blue);color:#fff}
.tblwrap{overflow:auto;border:1px solid var(--line);border-radius:10px;max-height:none}
table{border-collapse:separate;border-spacing:0;width:100%;font-size:12px;white-space:nowrap}
th,td{padding:6px 7px;text-align:right;border-bottom:1px solid var(--line)}
th{position:sticky;top:0;background:#f0f2f6;font-weight:600;color:#414856;cursor:pointer;user-select:none;z-index:2}
th:hover{background:#e8ebf1}
th .ar{opacity:.35;font-size:10px;margin-left:2px}
th.asc .ar,th.desc .ar{opacity:1;color:var(--blue)}
td.l,th.l{text-align:left}
tr:hover td{background:#fafbfe}
tr.low td{color:#98a1ae}
.code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:#414856}
.nm{font-weight:600}
.ind{font-size:10.5px;color:#98a1ae;font-weight:400;line-height:1.35}
.red{color:var(--red)} .green{color:var(--green)} .blue{color:var(--blue)} .muted{color:var(--muted)}
.pill{display:inline-block;padding:1px 7px;border-radius:20px;font-size:11px;border:1px solid transparent;line-height:18px}
.pill.w5{background:#eaf1ff;color:#2f6fed;border-color:#cfdfff}
.pill.w10{background:#f1ecff;color:#6b46e5;border-color:#e0d6ff}
.pill.pf{background:#e9f7f1;color:#0f8a5c;border-color:#c9ecdd}
.pill.op{background:#fff4e2;color:#b06c00;border-color:#ffe2b3}
.score{font-weight:700;font-variant-numeric:tabular-nums}
.dgrid{display:grid;grid-template-columns:1.15fr .85fr;gap:18px}
@media(max-width:900px){.dgrid{grid-template-columns:1fr}}
.detail{border-top:1px solid var(--line);padding:18px 20px}
.detail:first-of-type{border-top:none}
.dhead{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:10px}
.dhead .nm{font-size:17px}
.dhead .rank{background:#eef2fb;color:var(--blue);border-radius:6px;padding:1px 8px;font-size:12px;font-weight:700}
.dhead .meta{font-size:12px;color:var(--muted)}
.metrics{display:grid;grid-template-columns:repeat(2,1fr);gap:6px 16px;font-size:12.5px}
.metrics .m{display:flex;justify-content:space-between;gap:8px;border-bottom:1px dashed #eef0f4;padding:3px 0}
.metrics .m .k{color:var(--muted)}
.metrics .m .v{font-variant-numeric:tabular-nums;font-weight:600}
.spark{font-size:12px;color:var(--muted);margin-top:6px}
.sbars{display:flex;flex-direction:column;gap:4px;margin-top:4px}
.sb{display:grid;grid-template-columns:112px 1fr 104px;gap:8px;align-items:center;font-size:11.5px}
.sb .k{color:var(--muted);text-align:right}
.sb .k em{font-style:normal;color:#b6bcc6;font-size:10px;margin-left:3px}
.sb .t{height:12px;background:#eef0f4;border-radius:3px;overflow:hidden}
.sb .t i{display:block;height:100%;background:linear-gradient(90deg,#7a5af8,#a78bfa)}
.sb .v{font-variant-numeric:tabular-nums;font-weight:600;text-align:right}
.sb .v u{text-decoration:none;color:var(--blue);font-size:11px;margin-left:5px}
.sb.total{border-top:1px solid var(--line);padding-top:5px;margin-top:2px}
.sb.total .k{color:#414856;font-weight:600;text-align:right}
.sb.total .v{color:var(--blue);font-size:13px}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11.5px;color:var(--muted);margin-top:6px}
.legend i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:4px;vertical-align:-1px}
details{border:1px solid var(--line);border-radius:10px;padding:10px 14px;background:#fbfcfe}
details summary{cursor:pointer;font-size:13px;font-weight:600}
details .body{padding-top:10px}
.small{font-size:12px;color:var(--muted)}
.warn{background:#fff8ec;border:1px solid #ffe6bd;color:#8a5a00;border-radius:10px;padding:10px 14px;font-size:12.5px}
ul.brief{margin:0;padding:13px 18px 13px 34px;background:linear-gradient(180deg,#f7f9ff,#ffffff);
  border:1px solid #e3e9f7;border-radius:10px;font-size:13px;line-height:1.85}
ul.brief li{margin:2px 0}
ul.brief li::marker{color:var(--blue)}
footer{margin-top:22px;color:#98a1ae;font-size:12px;text-align:center;line-height:1.8}
"""

JS = r"""
(function(){
  var tbl=document.getElementById('result');
  if(tbl){
    tbl.querySelectorAll('th').forEach(function(th,i){
      th.addEventListener('click',function(){
        var tbody=tbl.tBodies[0], rows=Array.prototype.slice.call(tbody.rows);
        var cur=th.getAttribute('data-dir')==='asc'?'desc':'asc';
        tbl.querySelectorAll('th').forEach(function(x){x.removeAttribute('data-dir');x.classList.remove('asc','desc')});
        th.setAttribute('data-dir',cur); th.classList.add(cur);
        rows.sort(function(a,b){
          var va=a.cells[i].getAttribute('data-v'), vb=b.cells[i].getAttribute('data-v');
          if(va===null||va==='') va=a.cells[i].textContent.trim();
          if(vb===null||vb==='') vb=b.cells[i].textContent.trim();
          var na=parseFloat(va), nb=parseFloat(vb);
          var r=(!isNaN(na)&&!isNaN(nb))?na-nb:String(va).localeCompare(String(vb),'zh');
          return cur==='asc'?r:-r;
        });
        rows.forEach(function(r){tbody.appendChild(r)});
      });
    });
  }
  var box=document.getElementById('q');
  if(box){
    box.addEventListener('input',function(){
      var v=box.value.trim().toLowerCase();
      document.querySelectorAll('#result tbody tr').forEach(function(tr){
        tr.style.display=(!v||tr.textContent.toLowerCase().indexOf(v)>=0)?'':'none';
      });
    });
  }
})();
"""

WEIGHTS_LABEL = {
    "turnover_today": "今日换手率(低)",
    "turnover_5d": "5日均换手(低)",
    "amount_today": "成交额(低)",
    "vol_vs_board": "较首板缩量",
    "avg_holding_value": "户均持股市值(高)",
    "holder_change": "股东户数(降)",
    "gain60": "60日涨幅(低)",
    "retail_flow": "小单净流入(低)",
}


def esc(s):
    return html.escape(str(s if s is not None else "-"))


def _f(v, nd=2, dash="-"):
    if v is None or v == "":
        return dash
    if isinstance(v, float):
        return f"{v:,.{nd}f}"
    return str(v)


def _signed(v, nd=1, suffix=""):
    if v is None:
        return "-"
    cls = "red" if v > 0 else ("green" if v < 0 else "muted")
    return f'<span class="{cls}">{v:+.{nd}f}{suffix}</span>'


def _hm(t):
    t = str(t).zfill(6)
    return f"{t[0:2]}:{t[2:4]}"


# ------------------------------------------------------------------ SVG K线

def svg_chart(chart, w=620, h=250):
    bars = chart["bars"]
    n = len(bars)
    high = max(b[4] for b in bars)
    low = min(b[3] for b in bars)
    pad_l, pad_r, pad_t = 46, 10, 12
    vol_h = 46
    price_h = h - pad_t - vol_h - 26
    rng = max(high - low, 0.01)

    def y(p):
        return pad_t + (high - p) / rng * price_h

    plot_w = w - pad_l - pad_r
    bw = plot_w / n
    max_vol = max(b[5] for b in bars) or 1
    vol_top = pad_t + price_h + 12
    left_ref = chart["left_ref"]
    bidx = chart["board_idx"]

    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" xmlns="http://www.w3.org/2000/svg" '
           f'font-family="-apple-system,Segoe UI,Microsoft YaHei,sans-serif">']
    # 网格
    for i in range(4):
        p = low + rng * i / 3
        yy = y(p)
        out.append(f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{w-pad_r}" y2="{yy:.1f}" stroke="#eceef2"/>')
        out.append(f'<text x="{pad_l-6}" y="{yy+3.5:.1f}" font-size="10" fill="#98a1ae" '
                   f'text-anchor="end">{p:.2f}</text>')
    # 首板日背景高亮（画在蜡烛之下）
    if 0 <= bidx < n:
        bx = pad_l + bidx * bw
        out.append(f'<rect x="{bx:.1f}" y="{pad_t}" width="{bw:.1f}" height="{price_h+12+vol_h:.1f}" '
                   f'fill="#e0453c" opacity="0.08"/>')
    # 左侧锚点线
    if low <= left_ref <= high:
        yy = y(left_ref)
        out.append(f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{w-pad_r}" y2="{yy:.1f}" stroke="#2f6fed" '
                   f'stroke-dasharray="4 3" stroke-width="1"/>')
    # 蜡烛
    for i, b in enumerate(bars):
        _, o, c, lo, hi, v = b
        x = pad_l + i * bw + bw * 0.18
        cw = max(bw * 0.64, 1.0)
        up = c >= o
        col = "#e0453c" if up else "#12a06a"
        out.append(f'<line x1="{x+cw/2:.1f}" y1="{y(hi):.1f}" x2="{x+cw/2:.1f}" y2="{y(lo):.1f}" '
                   f'stroke="{col}" stroke-width="1"/>')
        yo, yc = y(o), y(c)
        top = min(yo, yc)
        bh = max(abs(yc - yo), 1.0)
        out.append(f'<rect x="{x:.1f}" y="{top:.1f}" width="{cw:.1f}" height="{bh:.1f}" fill="{col}"/>')
        vh = v / max_vol * (vol_h - 4)
        out.append(f'<rect x="{x:.1f}" y="{vol_top+vol_h-vh:.1f}" width="{cw:.1f}" height="{max(vh,0.6):.1f}" '
                   f'fill="{col}" opacity="0.45"/>')
    # 首板标签（置顶，避免被蜡烛遮挡）
    if 0 <= bidx < n:
        bx = pad_l + bidx * bw
        out.append(f'<rect x="{bx+bw/2-15:.1f}" y="{pad_t+1:.1f}" width="30" height="13" rx="3" '
                   f'fill="#ffffff" opacity="0.92"/>')
        out.append(f'<text x="{bx+bw/2:.1f}" y="{pad_t+10.5:.1f}" font-size="9.5" fill="#e0453c" '
                   f'font-weight="600" text-anchor="middle">首板</text>')
    # 锚点标签（置顶 + 白底）
    if low <= left_ref <= high:
        yy = y(left_ref)
        txt = f"首板前收盘 {left_ref:.2f}"
        tw = 9.2 * len(txt) * 0.62 + 3
        out.append(f'<rect x="{w-pad_r-tw-4:.1f}" y="{yy-13:.1f}" width="{tw+4:.1f}" height="12.5" rx="2" '
                   f'fill="#ffffff" opacity="0.92"/>')
        out.append(f'<text x="{w-pad_r-2:.1f}" y="{yy-3.6:.1f}" font-size="9.5" fill="#2f6fed" '
                   f'text-anchor="end">{txt}</text>')
    # X 轴日期
    for i in (0, n // 2, n - 1):
        x = pad_l + i * bw + bw / 2
        anchor = "start" if i == 0 else ("end" if i == n - 1 else "middle")
        out.append(f'<text x="{x:.1f}" y="{h-4}" font-size="9.5" fill="#98a1ae" '
                   f'text-anchor="{anchor}">{bars[i][0][5:]}</text>')
    out.append(f'<text x="{pad_l-6}" y="{vol_top+10}" font-size="9.5" fill="#98a1ae" text-anchor="end">量</text>')
    out.append("</svg>")
    return "".join(out)


# ------------------------------------------------------------------ 片段

def brief_html(rows, meta):
    """顶部速览：市场背景 + 收敛结论 + 结构 + 榜首。"""
    pc = meta["pool_counts"]
    hot_days = sorted(pc.items(), key=lambda kv: -kv[1])[:2]
    hot_txt = "、".join(f"{d[5:]}（{v} 条）" for d, v in hot_days)
    n5 = sum(1 for r in rows if r["days_since"] <= 5)
    npf = sum(1 for r in rows if r["hit_type"] == "平台")
    f = meta["funnel"]
    top = rows[0] if rows else None
    top_txt = ""
    if top:
        top_txt = (f"<b>{esc(top['name'])}</b>（{top['code']}，冷度分 {top['score']:.1f}）"
                   f"换手 {top['today_turnover']:.2f}%、户均持股市值 {_f(top['holder_avg_wan'],1)} 万、"
                   f"股东户数 {_f(top['holder_chg_pct'],1)}%")
    items = [
        f"<b>市场背景</b>：近 {len(pc)} 个交易日涨停池共 {sum(pc.values())} 条，"
        f"最集中的两天是 {esc(hot_txt)}，属于涨停潮环境，首板供给充足。",
        f"<b>收敛路径</b>：{f['首板(1连板)']} 条首板 → {f['已回落到首板左侧']} 条回踩到首板左侧 → "
        f"<b>{len(rows)}</b> 只通过热度硬过滤。",
        f"<b>结构</b>：平台命中 {npf} 只、开盘价命中 {len(rows)-npf} 只；"
        f"5 日内首板 {n5} 只、10 日内首板 {len(rows)-n5} 只。"
        + (f"<br><b>冷度榜首</b>：{top_txt}。" if top else ""),
    ]
    lis = "".join(f"<li>{x}</li>" for x in items)
    return f'<ul class="brief">{lis}</ul>'


def conditions_html(meta):
    p = meta["params"]
    items = [
        ("1", "#2f6fed", "条件一 · 5/10 日内首板",
         f"在首板距今 1–{p['board_window_days']} 个交易日的涨停池中，取连板数=1 且首板前 "
         f"{p['first_board_lookback_days']} 个交易日内无涨停的记录（真首板），且首板之后不得再有涨停；"
         f"首板距今 ≤{p['short_window_days']} 天归入「5日内」，其余归入「10日内」。"),
        ("2", "#7a5af8", "条件二 · 回踩到首板左侧",
         f"今日收盘较首板收盘回落 ≥ {p['pullback_min_pct']}%，且距「首板前一日收盘价」"
         f"±{p['left_tolerance_pct']}% 以内（平台命中）；若首板日高开 >2%，"
         f"回踩到首板开盘价 ±1.5% 亦算命中（开盘价命中）。"),
        ("3", "#12a06a", "条件三 · 主板非 ST",
         "仅保留 600/601/603/605/000/001/002/003 开头；剔除全部 ST/*ST/退市整理、"
         "上市不久的 N/C 次新股，以及股价 < 2 元的仙股。"),
        ("4", "#d98700", "条件四 · 低热度 · 散户少",
         f"今日换手 ≤{p['turnover_today_max']}%、5 日均换手 ≤{p['turnover_5d_max']}%、"
         f"成交额 ≤{p['amount_today_max_yi']} 亿、60 日涨幅 ≤{p['gain60_max_pct']}%、"
         f"流通市值 {p['float_mcap_min_yi']:.0f}–{p['float_mcap_max_yi']:.0f} 亿；"
         f"剔除东财人气榜前 {p['exclude_hot_rank_top']}；再按户均持股市值、股东户数变化、"
         "缩量程度、小单净流入打「冷度分」排序。"),
    ]
    out = ['<div class="cond">']
    for no, color, title, desc in items:
        out.append(f'<div class="c"><b><i style="background:{color}">{no}</i>{esc(title)}</b>'
                   f'<span>{esc(desc)}</span></div>')
    out.append("</div>")
    return "".join(out)


def funnel_html(meta):
    f = meta["funnel"]
    mx = max(f.values()) or 1
    rows = []
    for k, v in f.items():
        rows.append(f'<div class="fr"><div class="lab">{esc(k)}</div>'
                    f'<div class="bar" style="width:{max(v/mx*100,0.6):.2f}%"></div>'
                    f'<div class="num">{v}</div></div>')
    return '<div class="funnel">' + "".join(rows) + "</div>"


def table_html(rows):
    heads = [
        ("排名", "l", None), ("代码", "l", None), ("名称 / 行业", "l", None),
        ("首板日", "l", None), ("窗口", "", None),
        ("现价 / 首板收盘", "", None), ("回踩%", "", None), ("左偏%", "", None),
        ("命中", "", None),
        ("换手%", "", None), ("成交亿", "", None),
        ("流通亿", "", None), ("60日涨%", "", None),
        ("户均万", "", None), ("户变%", "", None),
        ("冷度分", "", None),
    ]
    h = ['<div class="tblwrap"><table id="result"><thead><tr>']
    for i, (label, cls, _) in enumerate(heads):
        h.append(f'<th class="{cls}" data-dir="">{esc(label)}<span class="ar">↕</span></th>')
    h.append("</tr></thead><tbody>")

    def td(v, cls="", data=None, raw=None):
        dv = "" if data is None else f' data-v="{data}"'
        return f'<td class="{cls}"{dv}>{raw if raw is not None else esc(v)}</td>'

    for i, r in enumerate(rows, 1):
        wcls = "w5" if r["days_since"] <= 5 else "w10"
        httag = "pf" if r["hit_type"] == "平台" else "op"
        h.append("<tr>")
        h.append(td(i, "l", i))
        h.append(f'<td class="l code">{r["code"]}</td>')
        h.append(f'<td class="l"><span class="nm">{esc(r["name"])}</span>'
                 f'<div class="ind">{esc(r["industry"])}</div></td>')
        h.append(f'<td class="l" data-v="{r["board_date"]}">'
                 f'{r["board_date"][5:]}<div class="ind">距今 {r["days_since"]} 日</div></td>')
        h.append(f'<td><span class="pill {wcls}">{r["window"]}</span></td>')
        h.append(td(f'{r["today_close"]:.2f} / {r["board_close"]:.2f}', "", r["today_close"]))
        h.append(td(r["retrace_pct"], "red", r["retrace_pct"], _signed(r["retrace_pct"])))
        h.append(td(r["left_dev_pct"], "", r["left_dev_pct"], _signed(r["left_dev_pct"])))
        h.append(f'<td><span class="pill {httag}">{r["hit_type"]}</span></td>')
        h.append(td(_f(r["today_turnover"], 2), "", r["today_turnover"]))
        h.append(td(_f(r["amount_yi"], 2), "", r["amount_yi"]))
        h.append(td(_f(r["float_mcap_yi"], 1), "", r["float_mcap_yi"]))
        h.append(td(r["gain60_pct"], "", r["gain60_pct"], _signed(r["gain60_pct"])))
        h.append(td(_f(r["holder_avg_wan"], 1), "", r["holder_avg_wan"]))
        h.append(td(r["holder_chg_pct"], "", r["holder_chg_pct"], _signed(r["holder_chg_pct"])))
        h.append(f'<td class="score blue" data-v="{r["score"]}">{r["score"]:.1f}</td>')
        h.append("</tr>")
    h.append("</tbody></table></div>")
    return "".join(h)


def detail_html(rows, meta):
    w = meta["weights"]
    out = []
    for i, r in enumerate(rows, 1):
        metrics = [
            ("首板日 / 距今", f'{r["board_date"]} · {r["days_since"]} 日'),
            ("首板涨幅 / 封板时间", f'{r["board_pct"]:+.2f}% · {_hm(r["board_first_time"])}'),
            ("首板日换手 / 成交额", f'{r["board_turnover"]:.2f}% · {r["board_amount_yi"]:.2f} 亿'),
            ("封板资金 / 占流通", f'{r["board_seal_yi"]:.2f} 亿 · {_f(r["seal_ratio_pct"],2)}%'),
            ("首板前收盘（左侧）", f'{r["pre_close"]:.2f}'),
            ("首板收盘 / 开盘", f'{r["board_close"]:.2f} / {r["board_open"]:.2f}'),
            ("今收盘 / 今涨幅", f'{r["today_close"]:.2f} / {r["today_pct"]:+.2f}%'),
            ("回踩幅度", f'{r["retrace_pct"]:+.2f}%'),
            ("左侧偏离", f'{r["left_dev_pct"]:+.2f}%'),
            ("今日换手 / 5日均", f'{r["today_turnover"]:.2f}% / {r["turnover5"]:.2f}%'),
            ("成交额 / 较首板量比", f'{r["amount_yi"]:.2f} 亿 / {_f(r["vol_ratio_board"],2)}'),
            ("流通市值 / 股价", f'{r["float_mcap_yi"]:.1f} 亿 / {r["price"]:.2f} 元'),
            ("60日涨幅", f'{_f(r["gain60_pct"],1)}%'),
            ("户均持股市值", f'{_f(r["holder_avg_wan"],1)} 万（{r["holder_stat_date"] or "-"}）'),
            ("股东户数变化", f'{_f(r["holder_chg_pct"],1)}%'),
            ("今日小单净占比", f'{_f(r["retail_pct"],1)}%'),
            ("东财人气排名", r["hot_rank"] if r["hot_rank"] is not None else "未上榜"),
            ("龙虎榜（首板后）",
             f'{"有 " + str(r["lhb_after_cnt"]) + " 次" if r["lhb_after_cnt"] else "无"}'),
        ]
        m = "".join(f'<div class="m"><span class="k">{esc(k)}</span><span class="v">{esc(v)}</span></div>'
                    for k, v in metrics)
        pts = r["score_parts"]
        sb = []
        for key, label in WEIGHTS_LABEL.items():
            if key not in pts:
                continue
            val = pts[key]
            ww = w.get(key, 0) * 100
            sb.append(f'<div class="sb"><span class="k">{esc(label)}<em>{ww:.0f}%</em></span>'
                      f'<span class="t"><i style="width:{val:.1f}%"></i></span>'
                      f'<span class="v">{val:.0f}<u>+{val*ww/100:.1f}</u></span></div>')
        penalty = 20 * min(r.get("lhb_after_cnt", 0), 2)
        total_note = f"冷度分 {r['score']:.1f}" + (f"（龙虎榜 -{penalty}）" if penalty else "")
        sb.append(f'<div class="sb total"><span class="k">加权合计</span>'
                  f'<span class="t" style="visibility:hidden"></span>'
                  f'<span class="v">{total_note}</span></div>')
        out.append(f"""
<div class="detail">
  <div class="dhead">
    <span class="rank">#{i}</span>
    <span class="nm">{esc(r['name'])}</span>
    <span class="code muted">{r['code']}</span>
    <span class="meta">{esc(r['industry'])}</span>
    <span class="pill {'w5' if r['days_since'] <= 5 else 'w10'}">{r['window']}首板</span>
    <span class="pill {'pf' if r['hit_type'] == '平台' else 'op'}">{r['hit_type']}命中</span>
    <span class="score blue" style="margin-left:auto">冷度分 {r['score']:.1f}</span>
  </div>
  <div class="dgrid">
    <div>{svg_chart(r['chart'])}
      <div class="legend"><span><i style="background:#e0453c"></i>阳线</span>
      <span><i style="background:#12a06a"></i>阴线</span>
      <span><i style="background:#2f6fed"></i>首板前收盘（左侧锚点）</span>
      <span><i style="background:#e0453c;opacity:.25"></i>首板日</span></div>
    </div>
    <div>
      <div class="metrics">{m}</div>
      <div class="spark">评分构成（单项 0–100 分，加权后求和，满分 100）</div>
      <div class="sbars">{''.join(sb)}</div>
    </div>
  </div>
</div>""")
    return "".join(out)


def rejects_html(meta):
    rows = meta.get("rejects") or []
    from collections import Counter
    cnt = Counter(r["reason"] for r in rows)
    summary = " · ".join(f"{k} {v}" for k, v in cnt.most_common(12))
    body = "".join(
        f'<tr><td class="l">{esc(r["board_date"])}</td><td class="l code">{r["code"]}</td>'
        f'<td class="l">{esc(r["name"])}</td><td class="l muted">{esc(r["stage"])}</td>'
        f'<td class="l muted">{esc(r["reason"])}</td></tr>'
        for r in rows)
    return f"""
<details>
  <summary>被剔除记录（{len(rows)} 条）— {esc(summary)}</summary>
  <div class="body small" style="margin-bottom:8px">
    说明：同一股票可能有多条涨停记录（不同首板日），逐条记录淘汰原因，便于核对。
  </div>
  <div class="tblwrap" style="max-height:360px;overflow:auto">
    <table><thead><tr><th class="l">首板日</th><th class="l">代码</th><th class="l">名称</th>
    <th class="l">通过到</th><th class="l">剔除/停止原因</th></tr></thead>
    <tbody>{body}</tbody></table>
  </div>
</details>"""


def params_html(meta):
    p = meta["params"]
    w = meta["weights"]
    labels = {
        "board_window_days": "首板回溯交易日数",
        "short_window_days": "「5日内」阈值（天）",
        "first_board_lookback_days": "首板前无涨停回溯（天）",
        "pullback_min_pct": "最小回踩幅度（%）",
        "left_tolerance_pct": "左侧锚点容差（%）",
        "price_min": "最低股价（元）",
        "float_mcap_min_yi": "流通市值下限（亿）",
        "float_mcap_max_yi": "流通市值上限（亿）",
        "turnover_today_max": "今日换手上限（%）",
        "turnover_5d_max": "5日均换手上限（%）",
        "amount_today_max_yi": "今日成交额上限（亿）",
        "gain60_max_pct": "60日涨幅上限（%）",
        "exclude_hot_rank_top": "剔除人气榜前 N",
        "lhb_after_penalty": "首板后龙虎榜每次扣分",
        "min_bars": "最少K线数量",
    }
    prow = "".join(f'<div class="m"><span class="k">{esc(labels.get(k,k))}</span>'
                   f'<span class="v">{esc(v)}</span></div>' for k, v in p.items())
    wrow = "".join(f'<div class="m"><span class="k">{esc(WEIGHTS_LABEL.get(k,k))}</span>'
                   f'<span class="v">{v*100:.0f}%</span></div>' for k, v in w.items())
    return f"""
<div class="dgrid">
  <div><div class="spark">硬条件参数（可在 config.json 中修改）</div>
    <div class="metrics">{prow}</div></div>
  <div><div class="spark">冷度评分权重</div>
    <div class="metrics">{wrow}</div></div>
</div>"""


# ------------------------------------------------------------------ 导出

def _export_csv(path, rows):
    cols = [("code", "代码"), ("name", "名称"), ("industry", "行业"), ("board_date", "首板日"),
            ("days_since", "距今交易日"), ("window", "窗口"), ("today_close", "现价"),
            ("board_close", "首板收盘"), ("retrace_pct", "回踩幅度%"),
            ("left_dev_pct", "左侧偏离%"), ("hit_type", "命中类型"),
            ("today_turnover", "今日换手%"), ("turnover5", "5日均换手%"),
            ("amount_yi", "成交额亿"), ("vol_ratio_board", "较首板量比"),
            ("float_mcap_yi", "流通市值亿"), ("gain60_pct", "60日涨幅%"),
            ("holder_avg_wan", "户均持股市值万"), ("holder_chg_pct", "股东户数变化%"),
            ("retail_pct", "小单净占比%"), ("hot_rank", "人气排名"),
            ("board_pct", "首板涨幅%"), ("board_turnover", "首板日换手%"),
            ("board_first_time", "首板封板时间"), ("lhb_after_cnt", "首板后龙虎榜次数"),
            ("score", "冷度评分")]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f)
        wr.writerow([c[1] for c in cols])
        for r in rows:
            wr.writerow([r.get(k, "") for k, _ in cols])


def _export_xlsx(path, rows, meta):
    try:
        import pandas as pd
    except ImportError:
        return None
    df = pd.DataFrame(rows)
    keep = ["code", "name", "industry", "board_date", "days_since", "window", "today_close",
            "board_close", "retrace_pct", "left_dev_pct", "hit_type", "today_turnover",
            "turnover5", "amount_yi", "vol_ratio_board", "float_mcap_yi", "gain60_pct",
            "holder_avg_wan", "holder_chg_pct", "retail_pct", "hot_rank", "board_pct",
            "board_turnover", "lhb_after_cnt", "score"]
    df = df[[c for c in keep if c in df.columns]]
    df.columns = ["代码", "名称", "行业", "首板日", "距今", "窗口", "现价", "首板收盘",
                  "回踩幅度%", "左侧偏离%", "命中类型", "今日换手%", "5日均换手%", "成交额亿",
                  "较首板量比", "流通市值亿", "60日涨幅%", "户均持股市值万", "股东户数变化%",
                  "小单净占比%", "人气排名", "首板涨幅%", "首板日换手%", "首板后龙虎榜",
                  "冷度评分"][: len(df.columns)]
    funnel = pd.DataFrame({"漏斗": list(meta["funnel"].keys()),
                           "数量": list(meta["funnel"].values())})
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name="筛选结果", index=False)
        funnel.to_excel(xw, sheet_name="筛选漏斗", index=False)
        params = pd.DataFrame({"参数": list(meta["params"].keys()),
                               "取值": [str(v) for v in meta["params"].values()]})
        params.to_excel(xw, sheet_name="参数", index=False)
        pd.DataFrame({"权重项": list(meta["weights"].keys()),
                      "权重": list(meta["weights"].values())}).to_excel(
            xw, sheet_name="评分权重", index=False)
    return path


# ------------------------------------------------------------------ 主入口

def build_report(res, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    meta = res["meta"]
    rows = res["rows"]
    T = meta["trade_date"]
    base = os.path.join(out_dir, f"选股结果_{T}")
    html_path = base + ".html"
    csv_path = base + ".csv"
    xlsx_path = base + ".xlsx"
    json_path = base + ".json"

    _export_csv(csv_path, rows)
    xlsx = _export_xlsx(xlsx_path, rows, meta)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "rows": rows}, f, ensure_ascii=False, indent=1)

    n = len(rows)
    doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>首板回踩左侧 · 低热度选股 {T}</title>
<style>{CSS}</style></head><body><div class="wrap">
<header class="top">
  <div>
    <h1>首板回踩左侧 · 低热度选股<small>条件选股系统</small></h1>
    <div class="sub">首板后回踩到左侧平台 / 首板开盘价附近 · 剔除 ST / 创业板 / 科创板 · 热度与散户筹码过滤</div>
  </div>
  <div class="stamp">数据日期 <b>{T}</b><br>生成于 {meta['generated_at']}<br>
    数据源 东方财富（行情 / 涨停池 / 股东户数 / 人气榜 / 龙虎榜 / 资金流）</div>
</header>

<div class="kpis">
  <div class="kpi"><div class="k">交易日</div><div class="v">{T}</div></div>
  <div class="kpi"><div class="k">入选股票</div><div class="v">{n}<small>只</small></div></div>
  <div class="kpi"><div class="k">窗口内涨停池</div><div class="v">{sum(meta['pool_counts'].values())}<small>条</small></div></div>
  <div class="kpi"><div class="k">K线覆盖</div><div class="v">{meta['kline_ok']}<small>/{meta['kline_total']}</small></div></div>
  <div class="kpi"><div class="k">主板股票池</div><div class="v">{meta['universe_main_count']}<small>只</small></div></div>
  <div class="kpi"><div class="k">计算耗时</div><div class="v">{meta['elapsed_sec']}<small>秒</small></div></div>
</div>

<div class="card"><h2>今日速览 <span class="tagline">一眼看懂今天筛出了什么</span></h2>
  <div class="body">{brief_html(rows, meta)}</div></div>

<div class="card"><h2>四个条件如何落地 <span class="tagline">参数均可通过 config.json 调整</span></h2>
  <div class="body">{conditions_html(meta)}</div></div>

<div class="card"><h2>筛选漏斗 <span class="tagline">逐级收敛，每个阶段为「通过该阶段」的记录数</span></h2>
  <div class="body">{funnel_html(meta)}</div></div>

<div class="card"><h2>入选结果 <span class="tagline">点击表头排序 · 输入关键字过滤</span></h2>
  <div class="body">
    <div class="toolbar">
      <input id="q" placeholder="搜索代码 / 名称 / 行业">
      <a class="btn primary" href="{os.path.basename(csv_path)}" download>下载 CSV</a>
      {f'<a class="btn" href="{os.path.basename(xlsx_path)}" download>下载 Excel</a>' if xlsx else ''}
      <span class="hint">共 {n} 只 · 按冷度分降序</span>
    </div>
    {table_html(rows)}
    <div class="legend" style="margin-top:8px">
      <span><span class="pill w5">5日内</span> 首板距今 1–5 个交易日</span>
      <span><span class="pill w10">10日内</span> 距今 6–10 个交易日</span>
      <span><span class="pill pf">平台</span> 回踩到首板前一日收盘价 ±{meta['params']['left_tolerance_pct']}%</span>
      <span><span class="pill op">开盘价</span> 回踩到首板开盘价 ±1.5%</span>
      <span>回踩幅度 = 现价/首板收盘 − 1</span>
      <span>左侧偏离 = 现价/首板前收盘 − 1</span>
    </div>
  </div></div>

<div class="card"><h2>逐股详情 <span class="tagline">近 60 根日K · 左侧锚点 · 评分构成</span></h2>
  <div class="body" style="padding-bottom:0">
    <div class="warn">冷度分只衡量「热度低 / 散户少 / 缩量」的程度，不代表基本面或上涨概率。
      首板回踩属于右侧转左侧的博弈形态，若跌破首板前收盘（左侧锚点）需重新评估形态是否破坏。</div>
  </div>
  {detail_html(rows, meta)}
</div>

<div class="card"><h2>筛选日志与参数</h2>
  <div class="body">
    {rejects_html(meta)}
    <div style="height:14px"></div>
    {params_html(meta)}
  </div></div>

<footer>
  本报告由本地脚本自动生成，数据来自东方财富公开接口，仅供研究参考，不构成任何投资建议。<br>
  涨停池为收盘封板数据；K 线为前复权日线；股东户数为最近一次披露值（可能滞后）。
</footer>
</div><script>{JS}</script></body></html>"""
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(doc)
    return {"html": html_path, "csv": csv_path, "xlsx": xlsx, "json": json_path}
