# -*- coding: utf-8 -*-
"""策略参数：全部可在 config.json 覆盖。"""
import copy
import io
import json
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 注意：trend 自己有一份 config.json（放在 trend/ 包里），不要和仓库根目录的
# 首板冷度 config.json 混用 —— 那样 top_n 之类会被静默覆盖。
CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULTS = {
    # ---- 域 ----
    "price_min": 3.0,
    "amt_min_yi": 0.5,          # 20 日均成交额下限（要有流动性才刺激得起来）
    "amt_max_yi": 20.0,
    "mcap_min_yi": 30.0,
    "mcap_max_yi": 2000.0,
    "min_bars": 150,
    "top_n": 5,

    # ---- 趋势 ----
    "max_dist_ma20": 16.0,      # 离 20 日线不超过 16%（别追在甘蔗梢上）
    "max_to_high": 6.0,         # 离 20 日新高不超过 6%
    "min_ret20": 2.0,           # 20 日涨幅至少 2%
    "max_pct_today": 9.0,       # 当日涨幅超过 9% 不追（买不到 / 次日容易低开）

    # ---- 刺激度 ----
    "atr_min_pct": 2.2,         # 平均振幅不低于 2.2%（太平的不算）
    "atr_max_pct": 9.0,
    "turnover_min": 3.0,        # 换手 3% 以上才活跃
    "turnover_max": 25.0,
    "vol_surge_min": 1.0,

    # ---- 市况 ----
    "regime_filter": True,
    "regime_ma": 20,            # 等权指数在 20 日线上方才做

    # ---- 出场 ----
    "atr_stop_mult": 2.0,
    "stop_min_pct": 4.0,
    "stop_max_pct": 9.0,
    "target_pct": 40.0,
    "hold_days": 15,
    "ma_exit": True,            # 收盘跌破 10 日线就走
    "bt_cost_pct": 0.2,
}


def load(path=CONFIG, overrides=None):
    cfg = copy.deepcopy(DEFAULTS)
    if path and os.path.exists(path):
        with io.open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        for k, v in data.items():
            if k in cfg or True:
                cfg[k] = v
    if overrides:
        cfg.update(overrides)
    return cfg
