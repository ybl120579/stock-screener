# -*- coding: utf-8 -*-
"""
数据源层：行情、K线、涨停池、股东户数、人气榜、龙虎榜、资金流。
东方财富公开接口 + akshare 兜底，本地缓存避免重复请求。
"""
import contextlib
import io
import os
import pickle
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "cache")
for _sub in ("klines", "spot", "pool", "aux", "days"):
    os.makedirs(os.path.join(CACHE_DIR, _sub), exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "*/*",
}

_thread_local = threading.local()

# 东财的行情接口有多个镜像域名，单个域名偶发返回 data:null（尤其海外/云机房 IP），
# 轮换一遍能显著提高云端的成功率。
KL_HOSTS = ["push2his.eastmoney.com", "33.push2his.eastmoney.com",
            "7.push2his.eastmoney.com", "62.push2his.eastmoney.com"]


def _session():
    s = getattr(_thread_local, "s", None)
    if s is None:
        s = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=16, pool_maxsize=16, max_retries=2)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        s.headers.update(HEADERS)
        _thread_local.s = s
    return s

def _get_json(url, timeout=25, retries=3):
    last = None
    for i in range(retries):
        try:
            r = _session().get(url, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.6 * (i + 1))
    raise RuntimeError(f"请求失败: {url[:90]} -> {last}")

def _kline_url(host, sec, lmt, fqt):
    return (f"https://{host}/api/qt/stock/kline/get?secid={sec}"
            f"&fields1=f1,f2,f3,f4,f5,f6&fields2={_KL_FIELDS}"
            f"&klt=101&fqt={fqt}&end=20500101&lmt={lmt}")


def _fetch_klines_any(sec: str, lmt: int, fqt: int = 1):
    """按镜像轮换取 K 线，返回 (name, klines) 或 None。data 为空也会换下一个域名。"""
    for host in KL_HOSTS:
        for attempt in range(2):
            try:
                js = _get_json(_kline_url(host, sec, lmt, fqt), retries=2)
            except Exception:  # noqa: BLE001
                js = None
            data = (js or {}).get("data") or {}
            klines = data.get("klines") or []
            if klines:
                return data.get("name"), klines
            time.sleep(0.8 + 1.2 * attempt)
    return None


def _cache_path(kind, key):
    return os.path.join(CACHE_DIR, kind, f"{key}.pkl")

def cached(kind, key, fetch, refresh=False):
    """按 key 读取 pickle 缓存；不存在或 refresh 时调用 fetch 并落盘。"""
    p = _cache_path(kind, key)
    if not refresh and os.path.exists(p):
        try:
            with open(p, "rb") as f:
                return pickle.load(f)
        except Exception:  # noqa: BLE001
            pass
    val = fetch()
    try:
        tmp = p + ".tmp"
        with open(tmp, "wb") as f:
            pickle.dump(val, f, protocol=4)
        os.replace(tmp, p)
    except Exception:  # noqa: BLE001
        pass
    return val

# ------------------------------------------------------------------ 基础

def secid(code: str) -> str:
    return ("1." if code[0] == "6" else "0.") + code

_KL_FIELDS = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
_KL_COLS = ["date", "open", "close", "high", "low", "volume", "amount",
            "amplitude", "pct", "change", "turnover"]

def fetch_kline(code: str, lmt: int = 160, fqt: int = 1):
    """单只股票日K（前复权），返回 DataFrame 或 None。"""
    got = _fetch_klines_any(secid(code), lmt, fqt)
    if not got:
        return None
    name, klines = got
    rows = []
    for line in klines:
        p = line.split(",")
        rows.append([p[0], float(p[1]), float(p[2]), float(p[3]), float(p[4]),
                     float(p[5]), float(p[6]), float(p[7]), float(p[8]),
                     float(p[9]), float(p[10])])
    df = pd.DataFrame(rows, columns=_KL_COLS)
    df["name"] = name
    return df

def get_trade_days(lmt: int = 60):
    """最近交易日列表（升序）。

    东财指数 K 线 → (失败则) akshare 新浪交易日历 → (再失败) 工作日近似。
    云端跑定时任务时，任何一环偶发抽风都不该让当天没有结果。
    """
    df = fetch_kline_index("000001", lmt)
    if df is not None and len(df):
        return df["date"].tolist()

    days = _trade_days_akshare(lmt)
    if days:
        return days

    print("[warn] 交易日历接口不可用，改用工作日近似", file=sys.stderr)
    from datetime import date, timedelta
    out, cur = [], date.today()
    while len(out) < lmt:
        if cur.weekday() < 5:
            out.append(cur.isoformat())
        cur -= timedelta(days=1)
    return sorted(out)


def _trade_days_akshare(lmt: int):
    try:
        import akshare as ak
        with contextlib.redirect_stderr(io.StringIO()):
            df = ak.tool_trade_date_hist_sina()
        col = "trade_date" if "trade_date" in df.columns else df.columns[0]
        vals = sorted({str(v)[:10] for v in df[col].astype(str)})
        from datetime import date
        today = date.today().isoformat()
        vals = [v for v in vals if v <= today]
        return vals[-lmt:]
    except Exception:  # noqa: BLE001
        return None

def fetch_kline_index(code: str, lmt: int = 60):
    sec = "1." + code if code.startswith("0") and code == "000001" else secid(code)
    got = _fetch_klines_any(sec, lmt, 1)
    if not got:
        return None
    kl = got[1]
    return pd.DataFrame([l.split(",")[0] for l in kl], columns=["date"])

# ------------------------------------------------------------------ 全景快照

_SPOT_FIELDS = ("f2,f3,f5,f6,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21,f22,"
                "f23,f24,f25,f26,f100,f62,f184")

def _spot_page(pn: int):
    url = ("https://push2.eastmoney.com/api/qt/clist/get"
           f"?pn={pn}&pz=100&po=1&np=1&fltt=2&invt=2&fid=f12&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
           f"&fields={_SPOT_FIELDS}")
    js = _get_json(url)
    return js.get("data") or {}

def fetch_spot():
    """全 A 股快照（不含北交所）。"""
    first = _spot_page(1)
    total = int(first.get("total") or 0)
    rows = list(first.get("diff") or [])
    pages = list(range(2, total // 100 + 3))
    if pages:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for data in ex.map(_spot_page, pages):
                rows.extend(data.get("diff") or [])
    seen, uniq = set(), []
    for r in rows:
        c = str(r.get("f12"))
        if c and c not in seen:
            seen.add(c)
            uniq.append(r)
    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return float("nan")
    out = []
    for r in uniq:
        out.append({
            "code": str(r.get("f12")), "name": r.get("f14"),
            "price": _num(r.get("f2")), "pct": _num(r.get("f3")),
            "volume": _num(r.get("f5")), "amount": _num(r.get("f6")),
            "turnover": _num(r.get("f8")), "pe": _num(r.get("f9")),
            "volume_ratio": _num(r.get("f10")),
            "high": _num(r.get("f15")), "low": _num(r.get("f16")),
            "open": _num(r.get("f17")), "preclose": _num(r.get("f18")),
            "total_mcap": _num(r.get("f20")), "float_mcap": _num(r.get("f21")),
            "gain60": _num(r.get("f24")), "gain_ytd": _num(r.get("f25")),
            "list_date": str(r.get("f26") or ""), "industry": r.get("f100"),
            "main_net": _num(r.get("f62")), "main_net_pct": _num(r.get("f184")),
        })
    df = pd.DataFrame(out).set_index("code")
    return df

# ------------------------------------------------------------------ 涨停池

_POOL_FIELDS = None

def fetch_zt_pool(date_str: str):
    """
    指定交易日的涨停股池（收盘封板）。
    date_str: 'YYYY-MM-DD'
    """
    d = date_str.replace("-", "")
    url = ("https://push2ex.eastmoney.com/getTopicZTPool"
           "?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt"
           f"&Pageindex=0&pagesize=300&sort=fbt%3Aasc&date={d}")
    js = _get_json(url)
    data = js.get("data") or {}
    out = []
    for x in data.get("pool") or []:
        try:
            out.append({
                "code": x["c"], "name": x["n"], "price": x["p"] / 1000.0,
                "pct": x["zdp"], "lbc": int(x["lbc"]),
                "first_time": int(x["fbt"]), "last_time": int(x["lbt"]),
                "zbc": int(x.get("zbc") or 0),
                "amount": float(x.get("amount") or 0),
                "float_mcap": float(x.get("ltsz") or 0),
                "total_mcap": float(x.get("tshare") or 0),
                "turnover": float(x.get("hs") or 0),
                "seal_fund": float(x.get("fund") or 0),
                "industry": x.get("hybk") or "",
                "stat": x.get("zttj") or {},
            })
        except Exception:  # noqa: BLE001
            continue
    return out

# ------------------------------------------------------------------ 辅助数据

def _ak(func, *args, **kwargs):
    import akshare as ak  # noqa: F401
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        return func(*args, **kwargs)

def fetch_gdhs():
    """最新股东户数（全市场），akshare 东方财富。"""
    import akshare as ak
    df = _ak(ak.stock_zh_a_gdhs, symbol="最新")
    df = df.rename(columns={
        "代码": "code", "名称": "name",
        "股东户数-本次": "holders", "股东户数-上次": "holders_prev",
        "股东户数-增减": "holders_chg", "股东户数-增减比例": "holders_chg_pct",
        "户均持股市值": "avg_hold_value", "户均持股数量": "avg_hold_shares",
        "股东户数统计截止日-本次": "stat_date",
        "总市值": "total_mcap", "公告日期": "ann_date",
    })
    df["code"] = df["code"].astype(str)
    return df.drop_duplicates("code").set_index("code")

def fetch_hot_rank():
    """东财人气榜（前100）。"""
    import akshare as ak
    df = _ak(ak.stock_hot_rank_em)
    df["code"] = df["代码"].astype(str).str.replace(r"^(SH|SZ|BJ)", "", regex=True)
    df["rank"] = df["当前排名"].astype(int)
    return df.set_index("code")

def fetch_lhb(start_date: str, end_date: str):
    """龙虎榜明细（含上榜日）。日期 YYYYMMDD。"""
    import akshare as ak
    df = _ak(ak.stock_lhb_detail_em, start_date=start_date, end_date=end_date)
    if df is None or df.empty:
        return pd.DataFrame(columns=["code", "date", "reason", "net_buy"])
    df = df.rename(columns={"代码": "code", "上榜日": "date", "上榜原因": "reason",
                            "龙虎榜净买额": "net_buy", "换手率": "turnover"})
    df["code"] = df["code"].astype(str)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df[["code", "date", "reason", "net_buy", "turnover"]]

def fetch_fund_flow():
    """个股资金流今日排行（主力/小单净占比）。"""
    import akshare as ak
    df = _ak(ak.stock_individual_fund_flow_rank, indicator="今日")
    df = df.rename(columns={"代码": "code", "今日小单净流入-净占比": "retail_pct",
                            "今日主力净流入-净占比": "main_pct"})
    df["code"] = df["code"].astype(str).str.zfill(6)
    return df.drop_duplicates("code").set_index("code")

# ------------------------------------------------------------------ 批量 K 线

def get_klines(codes, trade_date: str, lmt: int = 160, refresh: bool = False, workers: int = 8):
    """批量获取（带缓存）日K，返回 {code: DataFrame}。"""
    key = f"klines_{trade_date}_{lmt}"
    p = _cache_path("klines", key)
    store = {}
    if not refresh and os.path.exists(p):
        try:
            with open(p, "rb") as f:
                store = pickle.load(f)
        except Exception:  # noqa: BLE001
            store = {}
    todo = [c for c in codes if store.get(c) is None]
    if todo:
        def _one(c):
            return c, fetch_kline(c, lmt)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for c, df in ex.map(_one, todo):
                store[c] = df
        tmp = p + ".tmp"
        with open(tmp, "wb") as f:
            pickle.dump(store, f, protocol=4)
        os.replace(tmp, p)
    return store
