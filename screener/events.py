# -*- coding: utf-8 -*-
"""事件风险：解禁、股东减持。

形态再好，一纸减持公告/大额解禁就能把它砸下来。这里只做最粗的两件事：
  · 未来 N 个交易日内有解禁 → 剔除（默认 5 天）
  · 最近 N 天内有股东减持公告 → 扣分或剔除（默认只扣分）

数据来自 akshare（新浪解禁队列 / 东财高管与股东增减持），全部带缓存；
拿不到数据时不影响主流程，只在 aux_missing 里记一笔。
"""

import datetime as _dt

import pandas as pd

from . import datasource as ds


def _to_date(x):
    s = str(x or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return _dt.datetime.strptime(s[:19] if " " in s else s, fmt).date()
        except ValueError:
            continue
    return None


def fetch_release_queue(code):
    """单只股票的解禁批次（新浪）。返回 DataFrame 或空表。"""
    import contextlib
    import io as _io

    import akshare as ak
    try:
        with contextlib.redirect_stderr(_io.StringIO()):
            df = ak.stock_restricted_release_queue_sina(symbol=str(code))
        return df if df is not None else pd.DataFrame()
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def release_soon(codes, today, horizon_days=5, refresh=False, log=print):
    """{code: 最近的解禁日(YYYY-MM-DD)} —— 只保留 today 之后 horizon_days 个自然日内到期的。"""
    out = {}
    if not codes:
        return out
    t0 = _to_date(today)
    if t0 is None:
        return out
    limit = t0 + _dt.timedelta(days=horizon_days + max(0, horizon_days // 5 * 2))
    for code in codes:
        df = ds.cached("aux", f"rel_{code}", lambda c=code: fetch_release_queue(c), refresh)
        if df is None or getattr(df, "empty", True):
            continue
        for _, r in df.iterrows():
            d = _to_date(r.get("解禁日期"))
            if d and t0 <= d <= limit:
                out[code] = d.isoformat()
                break
    return out


def fetch_reduce_all():
    """全市场股东增减持（东财，一份 10 多万行的表）。"""
    import contextlib
    import io as _io

    import akshare as ak
    with contextlib.redirect_stderr(_io.StringIO()):
        df = ak.stock_ggcg_em(symbol="全部")
    if df is None or df.empty:
        return pd.DataFrame()
    # 只留减持
    col = next((c for c in df.columns if "增减" in c and "变动信息" in c), None)
    if col is not None:
        df = df[df[col].astype(str).str.contains("减")]
    dcol = next((c for c in df.columns if c == "公告日"), None) or         next((c for c in df.columns if "公告" in c), None)
    if dcol is not None:
        df = df.assign(_d=df[dcol].map(_to_date))
    return df


def reduce_recent(codes, today, days=30, refresh=False):
    """{code: 最近 N 天减持公告条数}。"""
    out = {}
    df = ds.cached("aux", f"ggcg_{today}", fetch_reduce_all, refresh)
    if df is None or getattr(df, "empty", True):
        return out
    t0 = _to_date(today)
    if t0 is None:
        return out
    ccol = "代码" if "代码" in df.columns else df.columns[0]
    sub = df[df[ccol].astype(str).isin({str(c).zfill(6) for c in codes})]
    for code, grp in sub.groupby(ccol):
        if "_d" in grp.columns:
            days_hit = {d for d in grp["_d"] if d and 0 <= (t0 - d).days <= days}
            n = len(days_hit)
        else:
            n = 0
        n = min(n, 3)
        if n:
            out[str(code).zfill(6)] = n
    return out
