"""
因子有效性四关检验：
  1. RankIC / ICIR / t 值 / 胜率
  2. 分组收益测试（多空价差）
  3. 因子相关性去重（保留低相关、高显著）
  4. 样本外符号一致性
"""

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def monthly_ic(panel: pd.DataFrame, factor_cols: List[str]) -> pd.DataFrame:
    """逐月逐因子 RankIC（Spearman，与下月收益）"""
    rows = []
    for m in panel.index.get_level_values("month").unique():
        sub = panel.xs(m, level="month")
        for c in factor_cols:
            if c not in sub.columns:
                continue
            d = sub[[c, "fwd_ret"]].dropna()
            if len(d) < 10:
                continue
            ic = d[c].corr(d["fwd_ret"], method="spearman")
            rows.append({"factor": c, "month": m, "ic": ic})
    return pd.DataFrame(rows)


def ic_report(ic_long: pd.DataFrame, min_months: int = 8,
              min_t: float = 2.0) -> pd.DataFrame:
    """汇总每因子的 IC 统计量"""
    rows = []
    for f, g in ic_long.groupby("factor"):
        arr = g["ic"].dropna().values
        if len(arr) < min_months:
            continue
        mean = arr.mean()
        sd = arr.std(ddof=1)
        t = mean / (sd + 1e-10) * np.sqrt(len(arr)) if sd > 1e-12 else 0.0
        rows.append({
            "factor": f,
            "months": len(arr),
            "ic_mean": mean,
            "ic_ir": mean / (sd + 1e-10),
            "t": t,
            "win_rate": float((arr > 0).mean()) * 100,
            "significant": bool(abs(t) >= min_t),
        })
    rep = pd.DataFrame(rows).sort_values("t", key=lambda s: s.abs(), ascending=False)
    return rep.reset_index(drop=True)


def grouped_returns(panel: pd.DataFrame, factor_cols: List[str],
                    groups: int = 5) -> pd.DataFrame:
    """分组收益：每月按因子分 5 组，多空价差 = 最高组 - 最低组"""
    spreads: Dict[str, List[float]] = {}
    for m in panel.index.get_level_values("month").unique():
        sub = panel.xs(m, level="month")
        for c in factor_cols:
            if c not in sub.columns:
                continue
            d = sub[[c, "fwd_ret"]].dropna()
            if len(d) < groups * 10:
                continue
            d["grp"] = pd.qcut(d[c].rank(method="first"), groups, labels=False)
            gmean = d.groupby("grp")["fwd_ret"].mean()
            if len(gmean) == groups:
                spreads.setdefault(c, []).append(gmean.iloc[-1] - gmean.iloc[0])
    rows = []
    for c, arr in spreads.items():
        a = np.asarray(arr)
        mean, sd = a.mean(), a.std(ddof=1)
        rows.append({
            "factor": c,
            "months": len(a),
            "spread_mean": mean,
            "spread_ir": mean / (sd + 1e-10),
            "spread_t": mean / (sd + 1e-10) * np.sqrt(len(a)),
            "spread_win": float((a > 0).mean()) * 100,
        })
    return pd.DataFrame(rows).sort_values("spread_t", key=lambda s: s.abs(), ascending=False)


def dedup_factors(rep: pd.DataFrame, ic_long: pd.DataFrame,
                  max_corr: float = 0.85) -> List[str]:
    """按 |t| 从高到低贪心保留，剔除与已选因子 IC 相关过高的因子"""
    pivot = ic_long.pivot(index="month", columns="factor", values="ic")
    ranked = rep.sort_values("t", key=lambda s: s.abs(), ascending=False)["factor"].tolist()
    kept: List[str] = []
    for f in ranked:
        if f not in pivot.columns:
            continue
        if not kept:
            kept.append(f)
            continue
        corrs = [pivot[f].corr(pivot[k]) for k in kept if pivot[k].notna().sum() > 5]
        corrs = [c for c in corrs if c is not None and not np.isnan(c)]
        if not corrs or max(corrs) < max_corr:
            kept.append(f)
    return kept


def out_of_sample_check(rep: pd.DataFrame, ic_long: pd.DataFrame,
                        split: float = 0.6) -> pd.DataFrame:
    """前 60% 样本内 / 后 40% 样本外：要求两段 IC 均值同号"""
    months = sorted(ic_long["month"].unique())
    cut = months[int(len(months) * split)]
    rows = []
    for f, g in ic_long.groupby("factor"):
        ins = g[g["month"] < cut]["ic"].mean()
        oos = g[g["month"] >= cut]["ic"].mean()
        if np.isnan(ins) or np.isnan(oos):
            continue
        rows.append({
            "factor": f,
            "is_ic": ins,
            "oos_ic": oos,
            "sign_ok": bool(ins * oos > 0),
        })
    return pd.DataFrame(rows)
