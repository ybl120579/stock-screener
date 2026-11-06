# -*- coding: utf-8 -*-
"""
全局配置：所有筛选阈值集中在此，可通过 config.json 覆盖，或命令行参数临时覆盖。
"""
import copy
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = {
    # ---------- 条件一：首板窗口 ----------
    "board_window_days": 10,        # 回溯最近 N 个交易日内的涨停
    "short_window_days": 5,         # “5天内”标签（首板距今 <= 5 个交易日）
    "first_board_lookback_days": 30,  # 首板前 N 个交易日内不得有涨停（保证是“首板”而非接力板）
    "limit_up_pct": 9.7,            # 主板涨停判定阈值（%）

    # ---------- 条件二：回落到首板左侧 ----------
    "pullback_min_pct": 3.0,        # 现价至少低于首板收盘价 N%（确认已回落）
    "left_tolerance_pct": 3.5,      # 现价与“首板左侧锚点”的允许偏离（±%）

    # ---------- 条件二的补充规则：破位风险 / 时间衰减 ----------
    # 首板后收盘曾跌破「首板前收盘 -N%」→ 视为破位反抽，剔除。默认 0（关闭）：
    # 20 天回测里打开它会多剔掉 4.5% 的候选，T+5/T+10 反而略差（-2.9%/-6.1% vs -2.8%/-6.0%），
    # 想要更保守可以设成 6。
    "break_dip_pct": 0.0,
    "time_decay_max": 4.0,          # 首板距今天数越久，冷度分最多扣 N 分
    "time_decay_start_days": 2,     # 距今 <= N 天不扣分

    # ---------- 市场环境（情绪周期）：决定"今天该不该出手" ----------
    "regime_gate": True,            # True 时环境退潮会在交易计划里给"空仓观望"
    "regime_min_zt": 30,            # 全市场涨停家数 < 此值 → 退潮
    "regime_max_zhaban_pct": 45.0,  # 炸板率 > 此值 → 退潮
    "regime_min_premium_pct": -1.5, # 昨日涨停股今日平均涨幅 < 此值 → 退潮

    # ---------- 首板质量 / 板块地位 ----------
    "min_board_quality": 0.0,       # 首板质量分下限（0 = 只展示不过滤）
    "min_industry_zt": 0,           # 首板当天同行业涨停数下限（0 = 不过滤）

    # ---------- 事件风险 ----------
    "reject_release_in_days": 5,    # 未来 N 日内有解禁 → 剔除（0 = 关闭）
    "reject_reduce_days": 30,       # 最近 N 日有减持公告 → 扣分（0 = 关闭）
    "reduce_penalty": 6.0,          # 每条减持公告扣的分（最多按 3 条算）

    # ---------- 交易计划（仓位 / 出场建议） ----------
    "plan_top_n": 5,                # 每天最多建议买几只
    "plan_position_pct": 20.0,      # 单票建议仓位（%）
    "plan_max_per_industry": 2,     # 同行业最多几只
    "plan_stop_pct": 3.0,           # 跌破左侧锚点 N% 止损
    "plan_time_stop_days": 3,       # T+N 仍不新高就减仓/离场

    # ---------- 回测口径 ----------
    "bt_entry": "open",             # 回测入场：open=次日开盘 / close=当日收盘（不现实，仅对照）
    "bt_cost_pct": 0.2,             # 单边交易成本（%，含佣金+印花税+滑点）

    # ---------- 条件三：股票池 ----------
    "exclude_st": True,
    "exclude_gem": True,            # 创业板 300/301
    "exclude_star": True,           # 科创板 688/689
    "exclude_bse": True,            # 北交所 4/8/9 开头
    "price_min": 2.0,               # 剔除仙股
    "float_mcap_min_yi": 10.0,      # 流通市值下限（亿）
    "float_mcap_max_yi": 1500.0,    # 流通市值上限（亿）
    "min_bars": 45,                 # 最少 K 线数量（次新股排除）

    # ---------- 条件四：热度 / 散户 ----------
    "turnover_today_max": 10.0,     # 今日换手率上限（%）
    "turnover_5d_max": 12.0,        # 近5日平均换手率上限（%）
    "amount_today_max_yi": 20.0,    # 今日成交额上限（亿）
    "gain60_max_pct": 60.0,         # 近60日涨幅上限（%）
    "exclude_hot_rank_top": 100,    # 东财人气榜前 N 名直接剔除（0=不启用）
    "lhb_after_penalty": 20,        # 首板之后登上龙虎榜的扣分

    # ---------- 评分 ----------
    "weights": {
        "turnover_today": 0.20,     # 今日换手率（越低越冷）
        "turnover_5d": 0.15,        # 近5日换手率
        "amount_today": 0.08,       # 今日成交额
        "vol_vs_board": 0.12,       # 今日成交量 / 首板日成交量（缩量程度）
        "avg_holding_value": 0.20,  # 户均持股市值（越高=散户越少/筹码越集中）
        "holder_change": 0.10,      # 股东户数变化（户数下降=筹码集中）
        "gain60": 0.08,             # 近60日涨幅（越低越冷）
        "retail_flow": 0.07,        # 今日小单净流入占比（散户资金，越低越好）
    },
    "score_min": 0.0,               # 入选最低冷度评分
    "top_n": 50,                    # 报告最多展示数量

    # ---------- 运行 ----------
    "output_dir": "reports",
    "cache": True,
}

def load_config(path=None, overrides=None):
    cfg = copy.deepcopy(DEFAULTS)
    cfg_path = path or os.path.join(BASE_DIR, "config.json")
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            user = json.load(f)
        for k, v in user.items():
            if k == "weights" and isinstance(v, dict):
                cfg["weights"].update(v)
            else:
                cfg[k] = v
    if overrides:
        for k, v in overrides.items():
            if v is not None:
                cfg[k] = v
    return cfg
