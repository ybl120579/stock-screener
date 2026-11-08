# -*- coding: utf-8 -*-
"""数据层：把「一只一只的日 K 表」整理成「日期 × 股票」的矩阵，方便向量化算因子。

数据来自 `stock-screener/` 里那套已经磨过的取数逻辑（东财 → 腾讯/新浪自动回退），
这里只做两件事：
1. 把数据对齐成矩阵（缺失值用 NaN，滚动计算自然跳过）；
2. 附上榜快照（流通市值、行业）与交易日历。
"""
import io
import os
import pickle
import sys

import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "stock-screener")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from screener import datasource as ds  # noqa: E402

UNIVERSE = os.path.join(HERE, "cache", "universe.pkl")
FIELDS = ("open", "close", "high", "low", "volume", "amount", "turnover")


def load_universe(path=UNIVERSE):
    """{code: DataFrame} → 原始字典。"""
    with open(path, "rb") as f:
        return pickle.load(f)


def to_matrices(store):
    """把 {code: df} 折成 (codes, dates, {field: DataFrame})。"""
    frames = {}
    for field in FIELDS:
        cols = {}
        for code, df in store.items():
            if df is None or df.empty or field not in df.columns:
                continue
            s = pd.Series(df[field].to_numpy(), index=pd.to_datetime(df["date"]))
            cols[code] = s[~s.index.duplicated(keep="last")]
        frames[field] = pd.DataFrame(cols).sort_index()
    dates = frames["close"].index
    codes = list(frames["close"].columns)
    for field in FIELDS:
        frames[field] = frames[field].reindex(index=dates, columns=codes)
    return codes, dates, frames


def load_spot(log=print, refresh=False):
    """行情快照（代码/名称/流通市值/行业），失败返回空表而不是崩。

    结果按日期缓存到 cache/spot_YYYY-MM-DD.pkl —— 名称和流通市值一天内不变，
    没必要每次跑都重新抓 56 页。
    """
    import pickle
    from datetime import date
    day = date.today().isoformat()
    cache = os.path.join(HERE, "cache", f"spot_{day}.pkl")
    if not refresh and os.path.exists(cache):
        try:
            with open(cache, "rb") as fh:
                spot = pickle.load(fh)
            if len(spot):
                return spot
        except Exception:  # noqa: BLE001
            pass
    try:
        spot = ds.fetch_spot()
    except Exception as e:  # noqa: BLE001
        log(f"[warn] 快照取不到：{e}")
        return pd.DataFrame(columns=["code", "name", "float_mcap", "industry"])
    spot = spot.copy()
    if "float_mcap" in spot.columns:
        spot["float_mcap_yi"] = pd.to_numeric(spot["float_mcap"], errors="coerce") / 1e8
    else:
        spot["float_mcap_yi"] = float("nan")
    if "code" not in spot.columns:
        spot = spot.reset_index()
        spot.columns = [str(c).lower() for c in spot.columns]
    keep = [c for c in ("code", "name", "industry", "float_mcap_yi", "price",
                        "pct", "turnover", "amount") if c in spot.columns]
    out = spot[keep].reset_index(drop=True)
    out["code"] = out["code"].astype(str)
    try:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "wb") as fh:
            pickle.dump(out, fh)
    except Exception:  # noqa: BLE001
        pass
    return out


def trade_days(lmt=400):
    return ds.get_trade_days(lmt=lmt)


def last_trade_date(frames):
    """数据里最后一个有效交易日（而不是日历上的今天）。"""
    close = frames["close"]
    valid = close.notna().sum(axis=1)
    return str(close.index[valid > len(close.columns) * 0.3][-1].date())
