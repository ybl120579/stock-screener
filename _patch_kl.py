import io

p = r'screener/datasource.py'
s = io.open(p, encoding='utf-8').read()

# 1) 全局：流通股数缓存 + 东财 K 线熔断计数
s = s.replace('''BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))''',
'''_FLOAT_SHARES = {}          # code -> 流通股数（股），K 线兜底时用来换算换手率
_KL_FAIL = {"n": 0, "dead": False}
_KL_LOCK = threading.Lock()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))''', 1)

# 2) fetch_kline 挂钩兜底
old_fk = '''def fetch_kline(code: str, lmt: int = 160, fqt: int = 1):
    """单只股票日K（前复权），返回 DataFrame 或 None。"""
    got = _fetch_klines_any(secid(code), lmt, fqt)
    if not got:
        return None
    name, klines = got'''
new_fk = '''def fetch_kline(code: str, lmt: int = 160, fqt: int = 1):
    """单只股票日K（前复权）。东财被限流时自动切腾讯/新浪。"""
    got = None
    if not _KL_FAIL["dead"]:
        got = _fetch_klines_any(secid(code), lmt, fqt)
        if not got:
            with _KL_LOCK:
                _KL_FAIL["n"] += 1
                if _KL_FAIL["n"] >= 8 and not _KL_FAIL["dead"]:
                    _KL_FAIL["dead"] = True
                    print("[warn] 东财 K 线连续失败，本次运行改用腾讯/新浪 K 线",
                          file=sys.stderr, flush=True)
        else:
            with _KL_LOCK:
                _KL_FAIL["n"] = 0
    if not got:
        return fetch_kline_alt(code, lmt)
    name, klines = got'''
assert old_fk in s
s = s.replace(old_fk, new_fk, 1)

# 3) 在 get_klines 之前插入腾讯/新浪 K 线兜底
anchor = 'def get_klines(codes, trade_date: str, lmt: int = 160, refresh: bool = False, workers: int = None):'
alt = '''# ------------------------------------------------------------------ 腾讯/新浪 K 线兜底

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


''' + anchor
assert anchor in s
s = s.replace(anchor, alt, 1)

# 4) 快照里回填流通股数
s = s.replace('''    df = pd.DataFrame(out).set_index("code")
    return df

# ------------------------------------------------------------------ 新浪快照兜底''',
'''    df = pd.DataFrame(out).set_index("code")
    _fill_float_shares(df)
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


# ------------------------------------------------------------------ 新浪快照兜底''', 1)

s = s.replace('''    log(f"[源] 新浪快照 {len(out)} 只")
    return pd.DataFrame(out).set_index("code")''',
'''    log(f"[源] 新浪快照 {len(out)} 只")
    df = pd.DataFrame(out).set_index("code")
    _fill_float_shares(df)
    return df''', 1)

# 5) 涨停池也记下流通市值 → 流通股数（无快照时也能算换手）
s = s.replace('''        except Exception:  # noqa: BLE001
            continue
    return out''','''        except Exception:  # noqa: BLE001
            continue
    for x in out:
        if x.get("float_mcap") and x.get("price"):
            _FLOAT_SHARES.setdefault(x["code"], x["float_mcap"] / x["price"])
    return out''', 1)

io.open(p, 'w', encoding='utf-8').write(s)
print("patched")
