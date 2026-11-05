# -*- coding: utf-8 -*-
"""修一个会在半夜炸的坑：00:00 之后「今天」已经是新交易日，但还没有行情。

现象：2026-11-06 00:07 跑 build_static.py，get_trade_days 返回的最后一个交易日
就是 11-06（周五），于是 as_of 选成 11-06 —— 但 11-06 还没开盘、涨停池是空的，
结果筛出 0 只，把 11-05 的 12 只名单覆盖掉了。

修法：收盘数据没出来之前（默认 <15:05），"今天"不算可用，退回上一个交易日；
另外再加一道「0 只不进板」的保护，避免任何情况下用空名单覆盖。
"""
import io

# ---------------- 1. build_static.py ----------------
p = "build_static.py"
s = io.open(p, encoding="utf-8").read()

old = '''def next_trade_day(after, days):'''
new = '''def pick_as_of(days, now=None, close_hour=15, close_minute=5):
    """选出“数据可用”的最近交易日。

    交易日历里最后一个日期通常就是今天；但如果现在还没收盘（数据没出），
    就要退回上一个交易日，否则会拿一个空涨停池去算，把名单算成 0 只。
    """
    if not days:
        return None
    now = now or datetime.now(BJ)
    today = now.strftime("%Y-%m-%d")
    if days[-1] == today and (now.hour, now.minute) < (close_hour, close_minute):
        return days[-2] if len(days) >= 2 else None
    return days[-1]


def next_trade_day(after, days):'''
assert old in s
s = s.replace(old, new, 1)

old2 = '''    as_of = args.date or days[-1]'''
new2 = '''    as_of = args.date or pick_as_of(days)'''
assert old2 in s
s = s.replace(old2, new2, 1)

# 0 只保护：正常情况不该一只都选不出来，多半是数据没就绪
old3 = '''    rows = []
    for r in res["rows"]:'''
new3 = '''    if not res["rows"]:
        kt = (res.get("meta") or {}).get("kline_total") or 0
        raise RuntimeError(f"{as_of} 一只都没筛出来（K线 {kt} 只），疑似数据未就绪，保留上一次名单")

    rows = []
    for r in res["rows"]:'''
assert old3 in s
s = s.replace(old3, new3, 1)

if "from datetime import" in s and "datetime" not in s.split("\n")[0]:
    pass
io.open(p, "w", encoding="utf-8").write(s)
print("build_static ok")

# ---------------- 2. mobile/app.py 也用同一个口径 ----------------
p = "mobile/app.py"
s = io.open(p, encoding="utf-8").read()
old4 = '''                if due and not have and not running and is_trade_day(today):'''
assert old4 in s
print("app.py 有调度分支（稍后单独处理）")
