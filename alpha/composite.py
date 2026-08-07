"""
滚动 IC 加权合成（v1 信号模型）

逐月只用"截至上月末"的已实现 IC 决定权重与方向（严格无未来函数）：
  - 因子需 |t| >= min_t 且符号稳定性 >= sign_stability
  - 不足 3 个达标因子时取 |t| 前 3，避免组合过度集中
  - 单因子权重上限 40%
"""

from typing import List, Optional, Tuple

import numpy as np
import pandas as pd


def build_composite(panel: pd.DataFrame,
                    ic_long: pd.DataFrame,
                    factor_cols: List[str],
                    ic_lookback: int = 18,
                    min_ic_months: int = 8,
                    min_t: float = 2.0,
                    sign_stability: float = 0.55,
                    cap: float = 0.40) -> Tuple[pd.DataFrame, pd.Series]:
    months = sorted(panel.index.get_level_values("month").unique())
    scores = panel.copy()
    scores["composite"] = np.nan
    latest_weights: pd.Series = pd.Series(dtype=float)

    for i, m in enumerate(months):
        if i < min_ic_months:
            continue
        hist = ic_long[(ic_long["month"] < m)]
        if len(hist) == 0:
            continue
        hist = hist[hist["month"] >= months[max(0, i - ic_lookback)]]
        stats = []
        for f, g in hist.groupby("factor"):
            arr = g["ic"].dropna().values
            if len(arr) < min_ic_months:
                continue
            mean = arr.mean()
            sd = arr.std(ddof=1)
            if sd <= 1e-12:
                continue
            t = mean / sd * np.sqrt(len(arr))
            win_sign = max((arr > 0).mean(), (arr < 0).mean())
            stats.append({"factor": f, "ir": mean / sd, "t": t, "win": win_sign})
        if not stats:
            continue
        ok = [s for s in stats if abs(s["t"]) >= min_t and s["win"] >= sign_stability]
        if len(ok) < 3:
            ok = sorted(stats, key=lambda s: abs(s["t"]), reverse=True)[:3]
        if not ok:
            continue
        w = pd.Series({s["factor"]: s["ir"] for s in ok})
        if w.abs().max() > cap:
            w = w / w.abs().max() * cap
        total = w.abs().sum()
        if total <= 1e-10:
            continue
        w = w / total
        sub = panel.xs(m, level="month")
        comp = pd.Series(0.0, index=sub.index)
        for f, wv in w.items():
            if f in sub.columns:
                comp += sub[f].fillna(0).astype(float) * wv
        mask = scores.index.get_level_values("month") == m
        scores.loc[mask, "composite"] = comp.values
        latest_weights = w

    return scores.dropna(subset=["composite"]), latest_weights
