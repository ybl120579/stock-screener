# -*- coding: utf-8 -*-
"""首板质量与板块地位：同样是首板，"9:31 一次封死" 和 "14:55 烂板" 不是一回事。

质量分（0–100）只看首板当天能看到的客观信息：
  · 首封时间   —— 越早越硬（30%）
  · 炸板次数   —— 一次没炸最好（30%）
  · 封单/流通  —— 封得厚不厚（20%）
  · 首板换手   —— 有换手才健康，一字板筹码没换（10%）
  · 是否一字板 —— 形态太极端不利于后续回踩（10%）

板块地位：同一天同行业有几只涨停、它是不是最早封的那只（龙头）。
"""


def _clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def _time_score(hhmmss):
    """首封时间 → 0~100。9:30 封死 100，14:55 才封 10。"""
    if not hhmmss:
        return 45.0
    s = str(hhmmss).zfill(6)
    try:
        h, m = int(s[0:2]), int(s[2:4])
    except ValueError:
        return 45.0
    mins = (h - 9) * 60 + m - 30          # 距 9:30 的分钟数
    if mins <= 5:
        return 100.0
    if mins <= 30:
        return 100.0 - (mins - 5) * 0.8   # 9:35→100, 10:00→80
    if mins <= 120:
        return 80.0 - (mins - 30) * 0.4   # 10:00→80, 11:30→44
    if mins <= 210:
        return 44.0 - (mins - 120) * 0.25  # 13:00→44
    return _clamp(20.0 - (mins - 210) * 0.2, 8.0, 20.0)


def _zbc_score(zbc):
    z = int(zbc or 0)
    return {0: 100.0, 1: 60.0, 2: 25.0}.get(z, 0.0)


def _seal_score(seal_ratio_pct):
    """封单占流通市值 %。"""
    if seal_ratio_pct is None:
        return 45.0
    r = float(seal_ratio_pct)
    if r >= 1.0:
        return 100.0
    if r >= 0.3:
        return 80.0
    if r >= 0.1:
        return 55.0
    if r > 0:
        return 30.0
    return 15.0


def _turnover_score(to_pct):
    """首板换手率：3%–20% 最健康；过低多为一字/无换手，过高说明筹码散。"""
    if to_pct is None:
        return 45.0
    t = float(to_pct)
    if t < 0.5:
        return 20.0
    if t < 3:
        return 45.0 + (t - 0.5) * 14      # 0.5→45, 3→80
    if t <= 20:
        return 80.0 + min(20.0, (t - 3) * 0.8)   # 3→80, 20→96
    if t <= 30:
        return 96.0 - (t - 20) * 2.0      # 30→76
    return _clamp(76.0 - (t - 30) * 1.2, 25.0, 76.0)


def is_yizi(board_open, board_close, board_high, board_low):
    """一字板：全天一个价（近似）。"""
    try:
        o, c, h, lo = float(board_open), float(board_close), float(board_high), float(board_low)
    except (TypeError, ValueError):
        return False
    if c <= 0:
        return False
    return (abs(o - c) / c < 0.005) and (abs(h - lo) / c < 0.005)


def quality(first_time=None, zbc=None, seal_ratio_pct=None,
            board_open=None, board_close=None, board_high=None, board_low=None,
            board_turnover=None):
    """返回 (总分, 明细 dict)。入参都是首板当天能看到的客观值。"""
    seal_ratio = seal_ratio_pct
    yizi = is_yizi(board_open, board_close, board_high, board_low)

    parts = {
        "first_time": round(_time_score(first_time), 1),
        "zbc": round(_zbc_score(zbc), 1),
        "seal": round(_seal_score(seal_ratio), 1),
        "turnover": round(_turnover_score(board_turnover), 1),
        "yizi": 0.0 if yizi else 100.0,
    }
    w = {"first_time": 0.30, "zbc": 0.30, "seal": 0.20, "turnover": 0.10, "yizi": 0.10}
    total = sum(parts[k] * w[k] for k in parts)
    parts["seal_ratio_pct"] = round(seal_ratio, 2) if seal_ratio is not None else None
    parts["yizi"] = yizi
    return round(total, 1), parts


def industry_context(pool_rows_day):
    """某一天各行业涨停数 + 行业最早封板时间（用于判断龙头）。

    返回 {industry: {"zt": n, "first_time": hhmmss}}
    """
    out = {}
    for r in pool_rows_day or []:
        ind = (r.get("industry") or "").strip() or "其他"
        st = out.setdefault(ind, {"zt": 0, "first_time": ""})
        st["zt"] += 1
        t = str(r.get("first_time") or "").zfill(6)
        if t != "000000" and (not st["first_time"] or t < st["first_time"]):
            st["first_time"] = t
    return out


def industry_rank(rec_industry, rec_first_time, ctx):
    """在行业里排第几（1 = 龙头）。返回 (rank, 同行业涨停数)。"""
    ind = (rec_industry or "").strip() or "其他"
    st = ctx.get(ind) or {"zt": 0, "first_time": ""}
    n = int(st.get("zt") or 0)
    t = str(rec_first_time or "").zfill(6)
    if n <= 0:
        return 0, n
    if not st.get("first_time") or t == "000000":
        return 2, n
    rank = 1 if t <= st["first_time"] else 2
    return rank, n
