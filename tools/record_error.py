# -*- coding: utf-8 -*-
"""把失败原因写进仓库（docs/data/last_error.json）和 Actions 摘要。

无 token 也能从公开站点读到失败原因：
https://ybl120579.github.io/stock-screener/data/last_error.json
"""
import argparse
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone

BJ = timezone(timedelta(hours=8))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "data", "last_error.json")
LOG = os.path.join(ROOT, "build.log")
TAIL = 40


def tail_lines(path, n=TAIL):
    if not os.path.exists(path):
        return []
    with io.open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    return lines[-n:]


def guess_reason(lines):
    """从日志尾部挑出最像原因的一行。"""
    keys = ("Error", "error", "失败", "不可用", "限流", "Traceback",
            "Exception", "raise", "拒绝", "timeout", "超时")
    for line in reversed(lines):
        if any(k in line for k in keys):
            return line.strip()[:400]
    return (lines[-1].strip()[:400] if lines else "未知原因")


def main():
    ap = argparse.ArgumentParser(description="记录一次失败的原因")
    ap.add_argument("--log", default=LOG, help="构建日志路径（默认 build.log）")
    ap.add_argument("--out", default=os.path.join(ROOT, "docs"),
                    help="站点输出目录（默认 docs）")
    args = ap.parse_args()
    out = os.path.join(args.out, "data", "last_error.json")

    now = datetime.now(BJ)
    lines = tail_lines(args.log)
    payload = {
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "reason": guess_reason(lines),
        "tail": lines[-12:],
        "note": "定时任务失败时写入；下次成功运行会删除该文件。",
    }
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with io.open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with io.open(summary, "a", encoding="utf-8") as f:
            f.write("### 选股任务失败\n\n```\n")
            f.write("\n".join(lines[-12:]))
            f.write("\n```\n\n原因：%s\n" % payload["reason"])
    print("已记录失败原因：", payload["reason"])


if __name__ == "__main__":
    main()
