# -*- coding: utf-8 -*-
"""
选股 App 后端（手机端）
=====================

一个不依赖任何 Web 框架的小服务：

  * 静态页面     /                -> ui/index.html（手机端单页应用）
  * 今日名单     /api/list        -> 最新交易日的筛选结果（含 20 日走势火花线）
  * 个股详情     /api/stock/CODE  -> 该股完整指标 + 60 根 K 线
  * 历史名单     /api/history     -> 已生成过的交易日快照
  * 运行状态     /api/status      -> 定时任务、最近一次运行、下次运行时间
  * 立即刷新     POST /api/refresh-> 后台重跑一次筛选（单飞，不会并发）

每日自动更新：进程内有一个后台线程，交易日 11:00（可配）之后自动重跑筛选并落盘快照，
所以只要你把服务挂着（开机自启，见 README），手机每天早上打开就是当天的新名单。

用法：
  python mobile/app.py                # 默认 0.0.0.0:8765，自动发现局域网地址
  python mobile/app.py --port 9000
  python mobile/app.py --run-now      # 启动后立刻跑一次再开服务
  python mobile/app.py --schedule 11:00
"""

import argparse
import json
import os
import socket
import sys
import threading
import time
import traceback
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)

from screener import screen                     # noqa: E402
from screener import datasource as ds           # noqa: E402
from screener.config import load_config         # noqa: E402

UI_DIR = os.path.join(HERE, "ui")
DATA_DIR = os.path.join(HERE, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ----------------------------------------------------------------------------
# 运行时状态
# ----------------------------------------------------------------------------
STATE = {
    "running": False,
    "job_started": None,
    "last_run": None,       # 最近一次筛选完成时间
    "last_error": None,
    "last_stage": "",       # 目前跑到哪一步（给前端显示）
    "next_run": None,       # 下次定时触发时间
    # 自动更新失败后的退避重试（避免被限流时每 30 秒打一次）
    "attempts": {},         # {"2026-11-05": 2}
    "last_attempt": None,   # datetime
}

RETRY_WAITS_MIN = (10, 20, 40, 60)   # 第 n 次失败后，等这么多分钟再试
MAX_ATTEMPTS_PER_DAY = 5
STATE_LOCK = threading.Lock()
RUN_LOCK = threading.Lock()

SCHEDULE_TIME = "11:00"     # 交易日收盘后自动跑（和云端 Actions 的 cron 对齐）
CONFIG_PATH = os.path.join(PROJ, "config.json")

try:  # Windows 控制台默认 GBK，中文会炸，统一切到 UTF-8
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ----------------------------------------------------------------------------
# 快照：跑一次筛选，把结果压成手机端需要的最小结构落盘
# ----------------------------------------------------------------------------
def snapshot_path(day):
    return os.path.join(DATA_DIR, f"snapshot_{day}.json")


def _slim(r):
    """列表页需要的字段（去掉 chart，换成 20 日走势火花线）。"""
    chart = r.get("chart") or {}
    bars = chart.get("bars") or []
    spark = [round(float(b[2]), 3) for b in bars[-20:]]   # b = [date, o, c, lo, hi, vol]
    keys = [
        "code", "name", "industry", "board_date", "days_since", "window",
        "board_pct", "board_turnover", "board_amount_yi", "seal_ratio_pct",
        "board_first_time", "pre_close", "board_close", "board_open",
        "today_close", "today_pct", "retrace_pct", "left_dev_pct", "hit_type",
        "today_turnover", "turnover5", "amount_yi", "vol_ratio_board",
        "float_mcap_yi", "gain60_pct", "price", "holder_avg_wan",
        "holder_chg_pct", "holder_stat_date", "retail_pct", "hot_rank",
        "lhb_on_board", "lhb_after_cnt", "score", "score_parts", "decay_penalty",
        "board_quality", "quality_parts", "ind_zt", "ind_rank",
        "board_zbc", "release_date", "reduce_cnt",
    ]
    out = {k: r.get(k) for k in keys}
    out["spark"] = spark
    return out


def build_snapshot(as_of=None, refresh=False):
    """跑一次筛选并写入 data/snapshot_YYYY-MM-DD.json，返回快照 dict。"""
    with STATE_LOCK:
        if STATE["running"]:
            raise RuntimeError("已有任务在跑")
        STATE["running"] = True
        STATE["job_started"] = datetime.now().isoformat(timespec="seconds")
        STATE["last_error"] = None
        STATE["last_stage"] = "拉取行情与涨停池"

    t0 = time.time()
    try:
        cfg = load_config(CONFIG_PATH)
        with RUN_LOCK:
            res = screen.run_screen(cfg, as_of=as_of, refresh=refresh, log=log)
        rows = res["rows"]
        meta = res["meta"]
        day = meta["trade_date"]
        snap = {
            "trade_date": day,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_sec": meta.get("elapsed_sec"),
            "count": len(rows),
            "funnel": meta.get("funnel"),
            "pool_counts": meta.get("pool_counts"),
            "kline_ok": meta.get("kline_ok"),
            "kline_total": meta.get("kline_total"),
            "universe_main_count": meta.get("universe_main_count"),
        "aux_missing": meta.get("aux_missing") or [],
        "regime": meta.get("regime"),
        "plan": meta.get("plan"),
        "spot_source": meta.get("spot_source"),
            "params": meta.get("params"),
            "weights": meta.get("weights"),
            "rejects": meta.get("rejects") or [],
            "rows": [_slim(r) for r in rows],
        }
        tmp = snapshot_path(day) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False)
        os.replace(tmp, snapshot_path(day))
        with STATE_LOCK:
            STATE["last_run"] = snap["generated_at"]
            STATE["last_stage"] = f"完成 · {len(rows)} 只"
        log(f"筛选完成 {day}：{len(rows)} 只，用时 {time.time() - t0:.1f}s")
        return snap
    except Exception as e:  # noqa: BLE001
        with STATE_LOCK:
            STATE["last_error"] = f"{type(e).__name__}: {e}"
            STATE["last_stage"] = "失败"
        log("筛选失败：" + traceback.format_exc())
        raise
    finally:
        with STATE_LOCK:
            STATE["running"] = False


def load_snapshot(day=None):
    """读落盘快照；day 为空时取最新一个。"""
    if day:
        p = snapshot_path(day)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        return None
    files = sorted((f for f in os.listdir(DATA_DIR) if f.startswith("snapshot_")),
                   reverse=True)
    for f in files:
        with open(os.path.join(DATA_DIR, f), encoding="utf-8") as fh:
            return json.load(fh)
    return None


def history_list():
    out = []
    for f in sorted(os.listdir(DATA_DIR), reverse=True):
        if not (f.startswith("snapshot_") and f.endswith(".json")):
            continue
        day = f[len("snapshot_"):-len(".json")]
        try:
            with open(os.path.join(DATA_DIR, f), encoding="utf-8") as fh:
                d = json.load(fh)
            out.append({"date": day, "count": d.get("count", 0),
                        "generated_at": d.get("generated_at")})
        except Exception:
            continue
    return out


# ----------------------------------------------------------------------------
# 定时任务
# ----------------------------------------------------------------------------
def _parse_hhmm(s):
    h, m = s.split(":")
    return int(h), int(m)


def _next_run_dt(now):
    h, m = _parse_hhmm(SCHEDULE_TIME)
    cand = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if cand <= now:
        cand = cand + timedelta(days=1)
    return cand


_TRADE_DAY_CACHE = {}


def is_trade_day(day):
    """用上证指数日线判断是否交易日（不用联网猜节假日）。结果按天缓存，避免反复请求。"""
    if day in _TRADE_DAY_CACHE:
        return _TRADE_DAY_CACHE[day]
    try:
        ok = day in ds.get_trade_days(lmt=5)
    except Exception:
        ok = datetime.strptime(day, "%Y-%m-%d").weekday() < 5
    if len(_TRADE_DAY_CACHE) > 30:
        _TRADE_DAY_CACHE.clear()
    _TRADE_DAY_CACHE[day] = ok
    return ok


def retry_delay_min(n):
    """第 n 次失败之后，要等多少分钟才允许再试。"""
    if n <= 0:
        return 0
    return RETRY_WAITS_MIN[min(n - 1, len(RETRY_WAITS_MIN) - 1)]


def retry_ready(n, last, now):
    """已经失败 n 次、上次尝试时间是 last，现在 now，是否该再试一次。"""
    if n >= MAX_ATTEMPTS_PER_DAY:
        return False
    if last is None:
        return True
    return (now - last).total_seconds() >= retry_delay_min(n) * 60


def scheduler_loop():
    log(f"定时任务已启动：交易日 {SCHEDULE_TIME} 自动更新")
    while True:
        try:
            now = datetime.now()
            h, m = _parse_hhmm(SCHEDULE_TIME)
            due = now.hour > h or (now.hour == h and now.minute >= m)
            today = now.date().isoformat()
            have = os.path.exists(snapshot_path(today))
            with STATE_LOCK:
                running = STATE["running"]
            if due and not have and not running and is_trade_day(today):
                with STATE_LOCK:
                    n = STATE["attempts"].get(today, 0)
                    last = STATE["last_attempt"]
                ready = retry_ready(n, last, now)
                if n >= MAX_ATTEMPTS_PER_DAY:
                    if n == MAX_ATTEMPTS_PER_DAY:
                        log(f"{today} 今天已经试了 {n} 次都没成功，不再自动重试")
                        with STATE_LOCK:
                            STATE["attempts"][today] = n + 1
                elif ready:
                    log(f"到达 {SCHEDULE_TIME}，开始更新 {today} 的名单"
                        + (f"（第 {n + 1} 次尝试）" if n else ""))
                    with STATE_LOCK:
                        STATE["last_attempt"] = now
                        STATE["attempts"][today] = n + 1
                    threading.Thread(target=_safe_build, kwargs={"as_of": today},
                                     daemon=True).start()
            with STATE_LOCK:
                STATE["next_run"] = _next_run_dt(now).strftime("%Y-%m-%d %H:%M")
            # 已经跑过今天的，就等到明天
            time.sleep(30)
        except Exception:
            log("调度线程异常：" + traceback.format_exc())
            time.sleep(60)


def _safe_build(**kw):
    try:
        build_snapshot(**kw)
    except Exception as e:  # noqa: BLE001
        log(f"[warn] 自动更新失败：{type(e).__name__}: {e}")
        with STATE_LOCK:
            STATE["last_error"] = f"{type(e).__name__}: {e}"
            STATE["last_stage"] = "失败"


# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------
MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def _json_bytes(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "StockScreenerApp/1.0"

    def log_message(self, fmt, *args):  # 静音默认日志，只留 5xx
        pass

    # ---------------- 基础响应 ----------------
    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if ctype.startswith("application/json") else "max-age=60")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, _json_bytes(obj))

    def _err(self, code, msg):
        self._json({"ok": False, "error": msg}, code)

    # ---------------- 静态文件 ----------------
    def _static(self, rel):
        rel = rel.lstrip("/") or "index.html"
        safe = os.path.normpath(rel).replace("\\", "/")
        if safe.startswith("..") or safe.startswith("/"):
            return self._err(403, "forbidden")
        path = os.path.join(UI_DIR, safe)
        if os.path.isdir(path):
            path = os.path.join(path, "index.html")
        if not os.path.exists(path):
            return self._err(404, "not found")
        ext = os.path.splitext(path)[1].lower()
        with open(path, "rb") as f:
            body = f.read()
        extra = {}
        if ext in (".html", ".js", ".css", ".webmanifest"):
            extra["Service-Worker-Allowed"] = "/"
        self._send(200, body, MIME.get(ext, "application/octet-stream"), extra)

    # ---------------- 路由 ----------------
    def do_GET(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        try:
            if p.startswith("/api/"):
                return self._api_get(p, q)
            if p == "/health":
                return self._json({"ok": True})
            return self._static(p)
        except Exception:
            log(traceback.format_exc())
            return self._err(500, "server error")

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/api/refresh":
            with STATE_LOCK:
                running = STATE["running"]
            if running:
                return self._json({"ok": True, "started": False, "running": True})
            threading.Thread(target=_safe_build, kwargs={"refresh": True},
                             daemon=True).start()
            time.sleep(0.05)
            return self._json({"ok": True, "started": True})
        return self._err(404, "not found")

    # ---------------- API ----------------
    def _api_get(self, p, q):
        if p == "/api/list":
            day = (q.get("date") or [None])[0]
            snap = load_snapshot(day)
            if not snap:
                return self._json({"ok": True, "empty": True,
                                   "message": "还没有生成名单，点右上角刷新试试",
                                   "status": self._status()})
            return self._json({"ok": True, **snap})

        if p.startswith("/api/stock/"):
            code = unquote(p.rsplit("/", 1)[-1])
            snap = load_snapshot((q.get("date") or [None])[0])
            if not snap:
                return self._err(404, "no snapshot")
            row = next((r for r in snap["rows"] if r["code"] == code), None)
            if not row:
                return self._err(404, "not found")
            # 详情要多带 K 线：从报告 json 里取（reports 目录按日期存的完整结果）
            detail = dict(row)
            detail["chart"] = _chart_for(snap["trade_date"], code)
            return self._json({"ok": True, "trade_date": snap["trade_date"], "stock": detail})

        if p == "/api/history":
            return self._json({"ok": True, "items": history_list()})

        if p == "/api/status":
            return self._json({"ok": True, **self._status()})

        return self._err(404, "not found")

    def _status(self):
        now = datetime.now()
        with STATE_LOCK:
            st = dict(STATE)
        st["now"] = now.strftime("%Y-%m-%d %H:%M:%S")
        st["schedule"] = SCHEDULE_TIME
        st["next_run"] = _next_run_dt(now).strftime("%Y-%m-%d %H:%M")
        if not st.get("next_run"):
            st["next_run"] = ""
        snap = load_snapshot()
        st["trade_date"] = snap["trade_date"] if snap else None
        st["generated_at"] = snap["generated_at"] if snap else None
        return st


# 详情用 K 线：优先读 reports/ 下完整 json（含 chart），没有再实时拉
_CHART_CACHE = {}


def _chart_for(trade_date, code):
    key = (trade_date, code)
    if key in _CHART_CACHE:
        return _CHART_CACHE[key]
    rp = os.path.join(PROJ, "reports", f"选股结果_{trade_date}.json")
    if os.path.exists(rp):
        try:
            with open(rp, encoding="utf-8") as f:
                d = json.load(f)
            for r in d.get("rows", []):
                if r.get("code") == code and r.get("chart"):
                    _CHART_CACHE[key] = r["chart"]
                    return r["chart"]
        except Exception:
            pass
    try:
        kl = ds.get_klines([code], trade_date)
        k = kl.get(code)
        if k is not None:
            bars = [[str(d)[:10], round(float(o), 2), round(float(c), 2),
                     round(float(l), 2), round(float(h), 2),
                     round(float(v) / 1e4, 1)]
                    for d, o, c, h, l, v in zip(k["date"], k["open"], k["close"],
                                                k["high"], k["low"], k["volume"])]
            bars = bars[-60:]
            payload = {"bars": bars, "board_idx": -1, "left_ref": None}
            _CHART_CACHE[key] = payload
            return payload
    except Exception:
        log("K线兜底失败 " + traceback.format_exc())
    return {"bars": [], "board_idx": -1, "left_ref": None}


# ----------------------------------------------------------------------------
# 局域网地址
# ----------------------------------------------------------------------------
def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def main():
    global SCHEDULE_TIME
    ap = argparse.ArgumentParser(description="选股 App 后端（手机端）")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--schedule", default=SCHEDULE_TIME, help="每日自动更新时间 HH:MM")
    ap.add_argument("--run-now", action="store_true", help="启动时立刻跑一次")
    ap.add_argument("--no-scheduler", action="store_true", help="关闭定时任务")
    a = ap.parse_args()
    SCHEDULE_TIME = a.schedule

    # 用最新的一份快照回填状态，避免界面显示“从未更新”
    try:
        files = sorted(f for f in os.listdir(DATA_DIR)
                       if f.startswith("snapshot_") and f.endswith(".json"))
        if files:
            with open(os.path.join(DATA_DIR, files[-1]), encoding="utf-8") as f:
                snap = json.load(f)
            with STATE_LOCK:
                STATE["last_run"] = snap.get("generated_at")
                STATE["last_stage"] = f"完成 · {snap.get('count', 0)} 只"
    except Exception:
        pass

    if a.run_now:
        threading.Thread(target=_safe_build, kwargs={"refresh": True}, daemon=True).start()
    if not a.no_scheduler:
        threading.Thread(target=scheduler_loop, daemon=True).start()

    ip = lan_ip()
    log("=" * 62)
    log("选股 App 已启动")
    log(f"  电脑上打开     http://127.0.0.1:{a.port}")
    log(f"  手机上打开     http://{ip}:{a.port}   （同一 WiFi）")
    log(f"  每日自动更新   交易日 {SCHEDULE_TIME}（服务需保持运行）")
    log("=" * 62)

    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.daemon_threads = True
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("已停止")


if __name__ == "__main__":
    main()
