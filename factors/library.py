"""
因子库（v1）：Alpha158 价量因子子集 + 财务/估值因子

参考：Qlib Alpha158（158 个标准价量因子，此处取其核心子集）
方向约定：因子原始值不强制方向，由滚动 IC 加权自动决定正/反向。
"""

from typing import Dict, List

import numpy as np
import pandas as pd

FACTOR_DEFS: Dict[str, str] = {
    # 反转 / 动量
    "f_rev5": "5日反转",
    "f_rev10": "10日反转",
    "f_mom20": "20日动量",
    "f_mom60": "60日动量",
    "f_mom120": "120日动量",
    # 波动 / 分布
    "f_vol20": "20日波动率",
    "f_vol60": "60日波动率",
    "f_maxret20": "20日最大涨幅",
    "f_minret20": "20日最大跌幅",
    "f_skew20": "20日收益偏度",
    # 价格形态
    "f_dist_high20": "距20日高点",
    "f_dist_high60": "距60日高点",
    "f_dist_low20": "距20日低点",
    "f_rsi14": "RSI(14)",
    "f_macd_hist": "MACD柱",
    "f_trend_persist20": "20日趋势持续性",
    "f_ma_bias20": "20日均线乖离",
    "f_ma_bias60": "60日均线乖离",
    "f_ma5_ma60": "短长均线比",
    "f_hl_pos20": "20日区间位置",
    # 量价
    "f_turn20": "20日换手率",
    "f_turn_std20": "20日换手率波动",
    "f_amt20": "20日成交额(log)",
    "f_amt_chg5": "5日成交额变化",
    "f_volratio20_60": "20/60日量比",
    "f_amihud20": "Amihud非流动性",
    "f_vp_corr20": "量价相关(20)",
    "f_turn_ret_corr20": "换手收益相关(20)",
    "f_updown20": "20日涨跌量比",
    "f_vwap_bias20": "VWAP乖离",
    # 财务 / 估值
    "f_ep": "EP(1/PE)",
    "f_bp": "BP(1/PB)",
    "f_log_mv": "总市值(log)",
    "f_roe": "ROE",
    "f_profit_growth": "净利润同比增速",
}

PRICE_FACTORS: List[str] = [
    "f_rev5", "f_rev10", "f_mom20", "f_mom60", "f_mom120",
    "f_vol20", "f_vol60", "f_maxret20", "f_minret20", "f_skew20",
    "f_dist_high20", "f_dist_high60", "f_dist_low20", "f_rsi14",
    "f_macd_hist", "f_trend_persist20", "f_ma_bias20", "f_ma_bias60",
    "f_ma5_ma60", "f_hl_pos20",
    "f_turn20", "f_turn_std20", "f_amt20", "f_amt_chg5",
    "f_volratio20_60", "f_amihud20", "f_vp_corr20", "f_turn_ret_corr20",
    "f_updown20", "f_vwap_bias20",
]

FUNDAMENTAL_FACTORS: List[str] = ["f_ep", "f_bp", "f_log_mv", "f_roe", "f_profit_growth"]


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).rolling(n).mean()
    down = (-delta.clip(upper=0)).rolling(n).mean()
    rs = up / down.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def _trend_persist(close: pd.Series, n: int = 20) -> pd.Series:
    """20日线性趋势的 R²（带方向）"""
    logc = np.log(close)
    t = pd.Series(np.arange(len(close)), index=close.index)
    corr = logc.rolling(n).corr(t)
    slope = logc.rolling(n).cov(t) / t.rolling(n).var()
    return (corr ** 2) * np.sign(slope)


def compute_price_factors(daily: pd.DataFrame) -> pd.DataFrame:
    """
    输入：统一 schema 日线（code,date,open,high,low,close,volume,amount,turnover）
    输出：因子表，MultiIndex (code, date)
    """
    rows = []
    groups = list(daily.sort_values("date").groupby("code"))
    for i, (code, g) in enumerate(groups):
        if i % 100 == 0:
            print(f"      价量因子进度: {i}/{len(groups)}", flush=True)
        g = g.set_index("date").sort_index()
        close = g["close"].astype(float)
        ret = close.pct_change()
        vol = g["volume"].astype(float)
        amt = g["amount"].astype(float)
        turn = g["turnover"].astype(float) if "turnover" in g.columns else pd.Series(np.nan, index=g.index)

        out = pd.DataFrame(index=g.index)
        out["f_rev5"] = close / close.shift(5) - 1
        out["f_rev10"] = close / close.shift(10) - 1
        out["f_mom20"] = close / close.shift(20) - 1
        out["f_mom60"] = close / close.shift(60) - 1
        out["f_mom120"] = close / close.shift(120) - 1
        out["f_vol20"] = ret.rolling(20).std() * np.sqrt(252)
        out["f_vol60"] = ret.rolling(60).std() * np.sqrt(252)
        out["f_maxret20"] = ret.rolling(20).max()
        out["f_minret20"] = ret.rolling(20).min()
        out["f_skew20"] = ret.rolling(20).skew()
        roll_max20 = close.rolling(20).max()
        roll_min20 = close.rolling(20).min()
        out["f_dist_high20"] = close / roll_max20 - 1
        out["f_dist_high60"] = close / close.rolling(60).max() - 1
        out["f_dist_low20"] = close / roll_min20 - 1
        out["f_rsi14"] = _rsi(close, 14)
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        out["f_macd_hist"] = dif - dif.ewm(span=9, adjust=False).mean()
        out["f_trend_persist20"] = _trend_persist(close, 20)
        out["f_ma_bias20"] = close / close.rolling(20).mean() - 1
        out["f_ma_bias60"] = close / close.rolling(60).mean() - 1
        out["f_ma5_ma60"] = close.rolling(5).mean() / close.rolling(60).mean() - 1
        out["f_hl_pos20"] = (close - roll_min20) / (roll_max20 - roll_min20).replace(0, np.nan)
        out["f_turn20"] = turn.rolling(20).mean()
        out["f_turn_std20"] = turn.rolling(20).std()
        out["f_amt20"] = np.log(amt.rolling(20).mean())
        out["f_amt_chg5"] = amt.rolling(5).mean() / amt.shift(5).rolling(5).mean() - 1
        out["f_volratio20_60"] = vol.rolling(20).mean() / vol.rolling(60).mean()
        out["f_amihud20"] = (ret.abs() / amt).rolling(20).mean() * 1e8
        out["f_vp_corr20"] = ret.rolling(20).corr(vol.pct_change())
        out["f_turn_ret_corr20"] = ret.rolling(20).corr(turn.pct_change())
        up_vol = vol.where(ret > 0, 0).rolling(20).sum()
        dn_vol = vol.where(ret < 0, 0).rolling(20).sum()
        out["f_updown20"] = up_vol / dn_vol.replace(0, np.nan)
        vwap = (amt / vol.replace(0, np.nan))
        out["f_vwap_bias20"] = (close / vwap - 1).rolling(20).mean()
        out["code"] = code
        out = out.reset_index()
        rows.append(out)
    if not rows:
        return pd.DataFrame()
    df = pd.concat(rows, ignore_index=True)
    df["code"] = df["code"].astype(str)
    return df.set_index(["code", "date"]).sort_index()
