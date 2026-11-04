# -*- coding: utf-8 -*-
"""触发「每日选股」工作流并盯到结束，打印每一步的状态与失败日志。

    set GH_TOKEN=...
    python tools/gh_run.py                 # 触发一次（默认不强制重跑）
    python tools/gh_run.py --force         # 强制重跑
    python tools/gh_run.py --wait 900      # 最多等 900 秒
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
OWNER = "ybl120579"
REPO = "stock-screener"
WF = "daily.yml"


def call(method, path, token, body=None, raw=False):
    req = urllib.request.Request(API + path, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "screener-run")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data, timeout=40) as r:
            content = r.read()
            return r.status, (content if raw else json.loads(content or b"{}"))
    except urllib.error.HTTPError as e:
        return e.code, (e.read().decode()[:300] if not raw else b"")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--wait", type=int, default=900, help="最长等待秒数")
    ap.add_argument("--trigger", action="store_true", default=True)
    args = ap.parse_args()
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("缺少 GH_TOKEN")

    st, _ = call("POST", f"/repos/{OWNER}/{REPO}/actions/workflows/{WF}/dispatches", token,
                 {"ref": "main", "inputs": {"force": "true" if args.force else "false"}})
    print("触发工作流:", st, flush=True)
    if st not in (204, 200):
        raise SystemExit("触发失败，检查 token 的 workflow 权限")

    run_id = None
    t0 = time.time()
    while time.time() - t0 < args.wait:
        time.sleep(8)
        st, runs = call("GET", f"/repos/{OWNER}/{REPO}/actions/runs?per_page=3", token)
        if st != 200:
            print("查询失败", st, runs)
            continue
        for r in runs.get("workflow_runs", []):
            if r["name"] == "每日选股" and r["created_at"] >= time.strftime(
                    "%Y-%m-%dT%H:%M:%S", time.gmtime(t0 - 90)):
                run_id = r["id"]
                print(f"run {run_id} status={r['status']} conclusion={r['conclusion']}", flush=True)
                break
        if run_id and r["status"] == "completed":
            conclusion = r["conclusion"]
            print("结论:", conclusion, flush=True)
            st, jobs = call("GET", f"/repos/{OWNER}/{REPO}/actions/runs/{run_id}/jobs", token)
            for j in jobs.get("jobs", []):
                print(f"job {j['name']}: {j['status']}/{j['conclusion']}")
                for s in j.get("steps", []):
                    print(f"   - {s['name']}: {s['status']}/{s['conclusion']}")
                if conclusion != "success":
                    st, logs = call("GET", f"/repos/{OWNER}/{REPO}/actions/jobs/{j['id']}/logs",
                                    token, raw=True)
                    if isinstance(logs, bytes):
                        text = logs.decode("utf-8", "replace")
                        keep = [ln for ln in text.splitlines()
                                if any(k in ln for k in ("Error", "error", "Traceback", "失败",
                                                         "timeout", "Timeout", "HTTP", "Exception"))]
                        print("---- 关键日志 ----")
                        print("\n".join(keep[-40:]) or text[-2000:])
            return 0 if conclusion == "success" else 1
    print("等待超时，请到 Actions 页面看结果")
    return 2


if __name__ == "__main__":
    sys.exit(main())
