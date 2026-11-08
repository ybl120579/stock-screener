# -*- coding: utf-8 -*-
"""
数据源层：行情、K线、涨停池、股东户数、人气榜、龙虎榜、资金流。
东方财富公开接口 + akshare 兜底，本地缓存避免重复请求。
"""
import contextlib
import io
import math
import os
import pickle
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

_FLOAT_SHARES = {}          # code -> 流通股数（股），K 线兜底时用来换算换手率
_KL_FAIL = {"n": 0, "dead": False}
_KL_LOCK = threading.Lock()

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
SPOT_HOSTS = ["push2.eastmoney.com", "1.push2.eastmoney.com",
              "7.push2.eastmoney.com", "33.push2.eastmoney.com",
              "82.push2.eastmoney.com", "push2delay.eastmoney.com"]
LOW_CONCURRENCY = os.environ.get("SCREENER_LOW_CONCURRENCY") == "1"

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

# ---------------------------------------------------------------- 限速与熔断
# 东财对同一 IP 有突发限流：短时间内几十个请求就会返回 rc=102（data:null）或 502，
# 而且要等几十秒才恢复。这里做两件事：
#   1. 全局匀速：每两次请求之间至少隔 MIN_INTERVAL 秒（云端更慢）；
#   2. 熔断：一旦看到 rc=102/502，全局暂停 COOLDOWN 秒，所有线程一起等，避免越撞越狠。
_PACE_LOCK = threading.Lock()
_LAST_REQ = [0.0]
_BLOCK_UNTIL = [0.0]
_TRIPS = [0]
MAX_TRIPS = 8          # 一轮里被限流这么多次就放弃，别把 CI 的时间预算耗光
# 云端默认 0.25 秒（保守）；可用 SCREENER_MIN_INTERVAL 覆盖（趋势系统要抓 3000+ 只，
# 0.25 秒一次会跑到 20 分钟以上，所以要能调快）
try:
    MIN_INTERVAL = float(os.environ.get("SCREENER_MIN_INTERVAL") or (0.25 if LOW_CONCURRENCY else 0.06))
except ValueError:
    MIN_INTERVAL = 0.25 if LOW_CONCURRENCY else 0.06
COOLDOWN = 20.0


def _pace():
    with _PACE_LOCK:
        now = time.time()
        wait = _LAST_REQ[0] + MIN_INTERVAL - now
        if wait > 0:
            time.sleep(wait)
        _LAST_REQ[0] = time.time()


def _wait_unblock():
    while True:
        delay = _BLOCK_UNTIL[0] - time.time()
        if delay <= 0:
            return
        time.sleep(min(delay, 5.0))


def _trip(reason):
    _TRIPS[0] += 1
    _BLOCK_UNTIL[0] = max(_BLOCK_UNTIL[0], time.time() + COOLDOWN)
    return RuntimeError(f"数据源限流：{reason}")


def reset_throttle():
    """每轮筛选开始前调用，重新给一次机会。"""
    _TRIPS[0] = 0
    _BLOCK_UNTIL[0] = 0.0


def _get_json(url, timeout=25, retries=3):
    last = None
    for i in range(retries):
        if _TRIPS[0] >= MAX_TRIPS:
            raise RuntimeError("数据源持续限流，本轮放弃")
        _wait_unblock()
        _pace()
        try:
            r = _session().get(url, timeout=timeout)
            if r.status_code >= 500:
                last = _trip(f"HTTP {r.status_code}")
                time.sleep(2.0 * (i + 1))
                continue
            r.raise_for_status()
            js = r.json()
            if isinstance(js, dict) and js.get("rc") == 102:
                last = _trip("rc=102")
                time.sleep(2.0 * (i + 1))
                continue
            return js
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
    """单只股票日K（前复权）。东财被限流时自动切腾讯/新浪。"""
    got = None
    if not _KL_FAIL["dead"]:
        got = _fetch_klines_any(secid(code), lmt, fqt)
        if not got:
            with _KL_LOCK:
                _KL_FAIL["n"] += 1
                if _KL_FAIL["n"] >= 2 and not _KL_FAIL["dead"]:
                    _KL_FAIL["dead"] = True
                    print("[warn] 东财 K 线连续失败，本次运行改用腾讯/新浪 K 线",
                          file=sys.stderr, flush=True)
        else:
            with _KL_LOCK:
                _KL_FAIL["n"] = 0
    if not got:
        return fetch_kline_alt(code, lmt)
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
    """取第 pn 页快照。

    东财对同一 IP 有短时限流（返回 rc=102 / data:null，或 502），因此：
    镜像域名轮换 + 每个域名两次退避重试；连续 3 个域名都失败就快速放弃，
    交给上层的“整轮重试”处理，避免在限流窗口里干耗时间。
    """
    qs = ("/api/qt/clist/get"
          f"?pn={pn}&pz=100&po=1&np=1&fltt=2&invt=2&fid=f12"
          f"&fs=m:0+t:6,m:0+t:80,m:1:t:2,m:1+t:23&fields={_SPOT_FIELDS}")
    last = None
    failed_hosts = 0
    for host in SPOT_HOSTS:
        url = f"https://{host}{qs}"
        host_ok = False
        for attempt in range(2):
            try:
                js = _get_json(url, retries=1)
                data = js.get("data") or {}
                if data.get("diff") is not None:
                    return data
                last = f"rc={js.get('rc')} data 为空"
            except Exception as e:  # noqa: BLE001
                last = e
            time.sleep(1.5 + 2.5 * attempt)
        failed_hosts += 1
        if failed_hosts >= 3:
            break
    raise RuntimeError(f"快照第 {pn} 页取不到（{last}）")

def fetch_spot_em():
    """东财全 A 股快照（不含北交所）。"""
    first = _spot_page(1)
    total = int(first.get("total") or 0)
    rows = list(first.get("diff") or [])
    pages = list(range(2, total // 100 + 3))
    if pages:
        with ThreadPoolExecutor(max_workers=(3 if LOW_CONCURRENCY else 6)) as ex:
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
    _fill_float_shares(df)
    df.attrs["source"] = "东财"
    return df


def _fill_float_shares(df):
    """用 流通市值 / 现价 估算流通股数，供 K 线兜底算换手率。"""
    try:
        for code, r in df.iterrows():
            f, p = r.get("float_mcap"), r.get("price")
            if f and p and f > 0 and p > 0:
                _FLOAT_SHARES[code] = f / p
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------ 新浪快照兜底

SINA_SPOT_URL = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                 "Market_Center.getHQNodeData?page={page}&num=100&sort=symbol"
                 "&asc=1&node=hs_a&symbol=&_s_r_a=page")
SINA_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Referer": "https://finance.sina.com.cn/"}


def _sina_spot_page(page: int):
    r = requests.get(SINA_SPOT_URL.format(page=page), headers=SINA_HEADERS, timeout=20)
    r.raise_for_status()
    js = r.json()
    return js if isinstance(js, list) else []


def _num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def fetch_spot_sina(log=print):
    """
    新浪行情兜底：字段名与东财快照对齐。
    缺失项（量比/60日涨幅/主力净流入）留 NaN —— 基本面与技术指标都从 K 线重算，
    行业由涨停池 hybk 回填，因此不影响筛选与评分。
    """
    rows = []
    lock = threading.Lock()

    def _one(page):
        for attempt in range(3):
            try:
                return _sina_spot_page(page)
            except Exception:
                time.sleep(0.8 * (attempt + 1))
        return []

    pages = list(range(1, 72))
    if LOW_CONCURRENCY:
        for pg in pages:
            got = _one(pg)
            if not got:
                break
            rows.extend(got)
            time.sleep(0.12)
    else:
        with ThreadPoolExecutor(max_workers=6) as ex:
            for got in ex.map(_one, pages):
                if not got:
                    continue
                with lock:
                    rows.extend(got)

    seen, out = set(), []
    for r in rows:
        code = str(r.get("code") or "")
        if not code or code in seen:
            continue
        seen.add(code)
        vol = _num(r.get("volume"))
        out.append({
            "code": code, "name": r.get("name"),
            "price": _num(r.get("trade")), "pct": _num(r.get("changepercent")),
            "volume": vol / 100.0 if math.isfinite(vol) else float("nan"),  # 股→手
            "amount": _num(r.get("amount")),
            "turnover": _num(r.get("turnoverratio")), "pe": _num(r.get("per")),
            "volume_ratio": float("nan"),
            "high": _num(r.get("high")), "low": _num(r.get("low")),
            "open": _num(r.get("open")), "preclose": _num(r.get("settlement")),
            "total_mcap": _num(r.get("mktcap")) * 1e4,
            "float_mcap": _num(r.get("nmc")) * 1e4,
            "gain60": float("nan"), "gain_ytd": float("nan"),
            "list_date": "", "industry": "",
            "main_net": float("nan"), "main_net_pct": float("nan"),
        })
    if not out:
        raise RuntimeError("新浪快照也拿不到数据")
    log(f"[源] 新浪快照 {len(out)} 只")
    df = pd.DataFrame(out).set_index("code")
    _fill_float_shares(df)
    df.attrs["source"] = "新浪"
    return df


_SPOT_DEAD = {"until": 0.0}


def fetch_spot():
    """全 A 股快照：优先东财，被限流时自动切新浪源。

    东财失败后 10 分钟内直接走新浪，避免每次调用都干等东财超时
    （限流窗口通常持续数十分钟，反复试探只会延长封禁）。
    """
    if time.time() < _SPOT_DEAD["until"]:
        return fetch_spot_sina()
    try:
        return fetch_spot_em()
    except Exception as e:
        _SPOT_DEAD["until"] = time.time() + 600
        print(f"[warn] 东财快照不可用（{str(e)[:80]}），切换新浪源"
              f"（10 分钟内不再试探东财）", file=sys.stderr, flush=True)
        return fetch_spot_sina()


# ------------------------------------------------------------------ 涨停池

_POOL_FIELDS = None

POOL_DIR = os.path.join(BASE_DIR, "docs", "data", "pool")


def fetch_zt_pool_cached_file(date_str: str):
    """仓库里留存的涨停池快照（docs/data/pool/DATE.json），作为离线兜底。"""
    fp = os.path.join(POOL_DIR, f"{date_str}.json")
    if not os.path.exists(fp):
        return None
    try:
        import json
        with io.open(fp, encoding="utf-8") as f:
            js = json.load(f)
        return js.get("pool") or None
    except Exception:  # noqa: BLE001
        return None


def fetch_zt_pool_fallback(spot):
    """东财涨停池不可用时，用行情快照反推当日涨停（仅收盘封板）。

    lbc 无法得知，一律记 1；多连板会在后面的“首板前 30 日无涨停”检查里被筛掉，
    所以不会把二连板当成首板。
    """
    out = []
    for code, r in spot.iterrows():
        try:
            pct = float(r.get("pct"))
            price = float(r.get("price"))
            high = float(r.get("high"))
            close = float(r.get("price"))
        except (TypeError, ValueError):
            continue
        if not (pct >= 9.7 and close > 0 and high > 0 and close >= high * 0.999):
            continue
        out.append({
            "code": code, "name": r.get("name"), "price": price, "pct": pct,
            "lbc": 1, "first_time": 0, "last_time": 0, "zbc": 0,
            "amount": float(r.get("amount") or 0),
            "float_mcap": float(r.get("float_mcap") or 0),
            "total_mcap": float(r.get("total_mcap") or 0),
            "turnover": float(r.get("turnover") or 0),
            "seal_fund": 0.0, "industry": "", "stat": {},
        })
    for x in out:
        if x["float_mcap"] and x["price"]:
            _FLOAT_SHARES.setdefault(x["code"], x["float_mcap"] / x["price"])
    return out


def save_pool_snapshot(date_str: str, pool):
    """把当日涨停池落盘到 docs/data/pool，随仓库积累历史。"""
    try:
        import json
        os.makedirs(POOL_DIR, exist_ok=True)
        fp = os.path.join(POOL_DIR, f"{date_str}.json")
        tmp = fp + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as f:
            json.dump({"date": date_str, "count": len(pool), "pool": pool},
                      f, ensure_ascii=False)
        os.replace(tmp, fp)
    except Exception:  # noqa: BLE001
        pass


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
    for x in out:
        if x.get("float_mcap") and x.get("price"):
            _FLOAT_SHARES.setdefault(x["code"], x["float_mcap"] / x["price"])
    if out:
        save_pool_snapshot(date_str, out)
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

# ------------------------------------------------------------------ 腾讯/新浪 K 线兜底

_TENCENT_KL_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,{lmt},qfq"
_SINA_KL_URL = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                "CN_MarketData.getKLineData?symbol={sym}&scale=240&ma=no&datalen={lmt}")
_ALT_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _sym(code: str) -> str:
    return ("sh" if code[0] == "6" else "sz") + code


def _klines_tencent(code: str, lmt: int):
    """腾讯前复权日 K：[[date, open, close, high, low, volume(手)], ...]"""
    url = _TENCENT_KL_URL.format(sym=_sym(code), lmt=int(lmt) + 8)
    r = requests.get(url, headers={**_ALT_HEADERS, "Referer": "https://gu.qq.com/"}, timeout=15)
    r.raise_for_status()
    js = r.json()
    d = (js.get("data") or {}).get(_sym(code)) or {}
    rows = d.get("qfqday") or d.get("day") or []
    out = []
    for x in rows:
        out.append([x[0], x[1], x[2], x[3], x[4], x[5]])
    return out


def _klines_sina(code: str, lmt: int):
    """新浪日 K（不复权）：volume 为股，换算成手。"""
    url = _SINA_KL_URL.format(sym=_sym(code), lmt=int(lmt) + 8)
    r = requests.get(url, headers={**_ALT_HEADERS, "Referer": "https://finance.sina.com.cn/"},
                     timeout=15)
    r.raise_for_status()
    arr = r.json() or []
    out = []
    for x in arr:
        out.append([x["day"], x["open"], x["close"], x["high"], x["low"],
                    float(x["volume"]) / 100.0])
    return out


def fetch_kline_alt(code: str, lmt: int = 160):
    """东财之外的日 K 兜底（腾讯 → 新浪）。

    换手率用流通股数换算（来自快照），成交额用 量×收盘 近似；
    其余列（振幅/涨跌幅/涨跌额）照常重算，接口形状与东财一致。
    """
    rows = None
    for fn in (_klines_tencent, _klines_sina):
        for attempt in range(2):
            try:
                rows = fn(code, lmt)
            except Exception:  # noqa: BLE001
                rows = None
            if rows:
                break
            time.sleep(0.5)
        if rows:
            break
    if not rows:
        return None

    shares = _FLOAT_SHARES.get(code)
    c_all = [float(x[2]) for x in rows]
    out = []
    for i, x in enumerate(rows):
        d, o, c = x[0], float(x[1]), float(x[2])
        h, lo, v = float(x[3]), float(x[4]), float(x[5])   # v: 手
        prev = c_all[i - 1] if i > 0 else None
        amt = v * 100.0 * c
        pct = (c / prev - 1.0) * 100.0 if prev else float("nan")
        chg = c - prev if prev else float("nan")
        amp = (h - lo) / prev * 100.0 if prev else float("nan")
        to = (v * 100.0 / shares * 100.0) if shares else float("nan")
        out.append([d, o, c, h, lo, v, amt, amp, pct, chg, to])

    df = pd.DataFrame(out, columns=_KL_COLS).tail(int(lmt)).reset_index(drop=True)
    df["name"] = ""
    return df


def get_klines(codes, trade_date: str, lmt: int = 160, refresh: bool = False, workers: int = None):
    """批量获取（带缓存）日K，返回 {code: DataFrame}。"""
    if workers is None:
        workers = 4 if LOW_CONCURRENCY else 8
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
            if LOW_CONCURRENCY:
                time.sleep(0.12)   # 云机房 IP 下给东财留点余量，避免触发限流
            return c, fetch_kline(c, lmt)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for c, df in ex.map(_one, todo):
                store[c] = df
        tmp = p + ".tmp"
        with open(tmp, "wb") as f:
            pickle.dump(store, f, protocol=4)
        os.replace(tmp, p)
    return store
