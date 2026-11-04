# -*- coding: utf-8 -*-
"""独立复核：不复用 screen 的判定逻辑，直接从原始接口重算几只票的关键事实。"""
import sys

sys.path.insert(0, ".")
import numpy as np  # noqa: E402

from screener import datasource as ds  # noqa: E402

CASES = {
    "603303": "2026-10-28",
    "603219": "2026-10-28",
    "000608": "2026-11-03",
    "605169": "2026-10-30",
    "002284": "2026-10-27",
    "000788": "2026-10-21",
    "000411": "2026-10-26",
}

for code, bd in CASES.items():
    kl = ds.fetch_kline(code, lmt=120)
    dates = kl["date"].tolist()
    pct = kl["pct"].to_numpy(float)
    close = kl["close"].to_numpy(float)
    turn = kl["turnover"].to_numpy(float)
    j = dates.index(bd)
    pre = close[j - 1]
    print(f"\n=== {code} 首板日 {bd} (第{j}根/共{len(dates)}根) ===")
    print(f"  首板日涨幅 {pct[j]:.2f}%  收盘 {close[j]:.2f}  前收 {pre:.2f}  换手 {turn[j]:.2f}%")
    prior = pct[j - 30:j]
    print(f"  首板前30日最高涨幅 {prior.max():.2f}%  涨停日数 {(prior >= 9.7).sum()}")
    after = pct[j + 1:]
    print(f"  首板后最高涨幅 {after.max():.2f}%  涨停日数 {(after >= 9.7).sum()}")
    print(f"  今日收盘 {close[-1]:.2f}  较首板收盘 {close[-1]/close[j]-1:+.2%}  "
          f"较首板前收盘 {close[-1]/pre-1:+.2%}  今日换手 {turn[-1]:.2f}%")
    print("  最近8日: " + " | ".join(
        f"{d[5:]} {c:.2f} {p:+.1f}%" for d, c, p in
        zip(dates[-8:], close[-8:], pct[-8:])))
    # 首板当日之后是否还有涨停
    assert (after < 9.7).all(), "首板后仍有涨停！"

print("\n--- 涨停池交叉验证（akshare 独立路径） ---")
import akshare as ak
import contextlib
import io
for d, codes in [("20261028", ["603303", "603219"]), ("20261103", ["000608"]),
                 ("20261030", ["605169"]), ("20261027", ["002284"])]:
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        df = ak.stock_zt_pool_em(date=d)
    sub = df[df["代码"].isin(codes)]
    print(f"{d}: 池子 {len(df)} 条; 目标股:")
    print(sub[["代码", "名称", "涨跌幅", "连板数", "换手率", "封板资金"]].to_string(index=False))
