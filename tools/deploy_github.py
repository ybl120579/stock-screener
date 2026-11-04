# -*- coding: utf-8 -*-
"""
一键把这个项目发布到 GitHub（建仓库 → 推代码 → 开 Pages）
=========================================================

    set GH_TOKEN=ghp_xxx
    python tools/deploy_github.py --repo stock-screener

做的事：
  1. 用 token 查出用户名
  2. 仓库不存在就创建（public）
  3. 推代码到 main 分支（token 只用于这一次推送，不会留在 .git/config）
  4. 打开 GitHub Pages（source = main / docs）
  5. 打印站点地址

幂等：重跑不会报错，已存在的仓库继续推、Pages 已开就跳过。
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"


def call(method, path, token, body=None, ok=(200, 201, 204)):
    req = urllib.request.Request(API + path, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "stock-screener-deploy")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data, timeout=30) as r:
            raw = r.read().decode() or "{}"
            return r.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode() or "{}"
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"message": raw[:200]}
        if e.code in ok:
            return e.code, parsed
        raise SystemExit(f"GitHub API {method} {path} → {e.code}: {parsed.get('message')}")


def git(*args, **kw):
    print("  $ git", " ".join(a if "token" not in a else "<hidden>" for a in args), flush=True)
    subprocess.run(["git"] + list(args), check=True, cwd=kw.get("cwd"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="stock-screener")
    ap.add_argument("--private", action="store_true", help="建成私有仓库（注意：私有仓库的 Pages 需要 Pro 账号）")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--dir", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    args = ap.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("缺少 GH_TOKEN 环境变量")

    status, me = call("GET", "/user", token)
    login = me["login"]
    print(f"账号：{login}")

    status, repo = call("GET", f"/repos/{login}/{args.repo}", token, ok=(200, 404))
    if status == 404:
        print(f"创建仓库 {login}/{args.repo} …")
        call("POST", "/user/repos", token, {
            "name": args.repo,
            "description": "首板回踩·低冷度选股：每日自动更新的 A 股筛选名单（手机 PWA）",
            "private": bool(args.private),
            "has_issues": False, "has_wiki": False, "auto_init": False,
        })
    else:
        print(f"仓库已存在：{repo['html_url']}")

    print("推送代码 …")
    git("branch", "-M", args.branch, cwd=args.dir)
    clean = f"https://github.com/{login}/{args.repo}.git"
    subprocess.run(["git", "remote", "remove", "origin"], cwd=args.dir,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    git("remote", "add", "origin", clean, cwd=args.dir)
    # 临时带上 token 推送（用 -c 传 header，不写进 config）
    subprocess.run(
        ["git", "-c", f"http.extraheader=Authorization: Basic {_basic(login, token)}",
         "push", "-u", "origin", args.branch, "--force"],
        cwd=args.dir, check=True)
    print("已推送")

    print("开启 Pages（main / docs）…")
    call("POST", f"/repos/{login}/{args.repo}/pages", token,
         {"source": {"branch": args.branch, "path": "/docs"}}, ok=(201, 204, 409, 422))
    for _ in range(20):
        st, info = call("GET", f"/repos/{login}/{args.repo}/pages", token, ok=(200, 404))
        if st == 200 and info.get("status") in ("built", "building"):
            url = info.get("html_url")
            print("\n站点地址：", url)
            break
        time.sleep(6)
    else:
        print(f"\nPages 已配置，地址稍后可用：https://{login}.github.io/{args.repo}/")

    print(f"仓库：https://github.com/{login}/{args.repo}")
    if args.private:
        print("提醒：私有仓库的 Pages 需要 GitHub Pro；如未生效请改成 public。")


def _basic(user, token):
    import base64
    return base64.b64encode(f"{user}:{token}".encode()).decode()


if __name__ == "__main__":
    sys.exit(main())
