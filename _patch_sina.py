import io, re, sys

p = r'screener/datasource.py'
s = io.open(p, encoding='utf-8').read()

# 1) 把原 fetch_spot 改名为 fetch_spot_em
s = s.replace('def fetch_spot():\n    """全 A 股快照（不含北交所）。"""',
              'def fetch_spot_em():\n    """东财全 A 股快照（不含北交所）。"""', 1)

# 2) 在涨停池分节之前插入新浪兜底 + 统一入口
anchor = '# ------------------------------------------------------------------ 涨停池'
sina_code = '''# ------------------------------------------------------------------ 新浪快照兜底

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
    return pd.DataFrame(out).set_index("code")


def fetch_spot():
    """全 A 股快照：优先东财，被限流时自动切新浪。"""
    try:
        return fetch_spot_em()
    except Exception as e:
        print(f"[warn] 东财快照不可用（{str(e)[:80]}），切换新浪源", file=sys.stderr, flush=True)
        return fetch_spot_sina()


''' + anchor
s = s.replace(anchor, sina_code, 1)

io.open(p, 'w', encoding='utf-8').write(s)
print('patched', 'threading' in s.split('\n\n')[0] or 'need threading import')
