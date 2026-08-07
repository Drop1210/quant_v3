"""
研究流水线（一次跑完因子面板 -> 四关检验 -> 合成 -> 报告）
供 smoke_factors 与 daily_run 复用。
"""

import os
from typing import Optional, Tuple

import pandas as pd

from config import cfg
from factors.library import FACTOR_DEFS, PRICE_FACTORS, FUNDAMENTAL_FACTORS
from factors.panel import build_monthly_panel
from factors.pipeline import run_pipeline
from factors.validation import (monthly_ic, ic_report, grouped_returns,
                                dedup_factors, out_of_sample_check)
from alpha.composite import build_composite


def run_research(daily: pd.DataFrame,
                 valuation: Optional[pd.DataFrame],
                 financial: Optional[pd.DataFrame],
                 sector: Optional[pd.DataFrame],
                 out_dir: Optional[str] = None):
    """返回 (piped, ic_long, scores, weights, rep, gr, kept, oos)"""
    panel = build_monthly_panel(daily, valuation, financial)
    factor_cols = [c for c in PRICE_FACTORS + FUNDAMENTAL_FACTORS if c in panel.columns]
    piped = run_pipeline(panel, factor_cols, sector,
                         winsorize_sigma=cfg.factor.winsorize_sigma,
                         neutralize_enabled=cfg.factor.neutralize)
    ic_long = monthly_ic(piped, factor_cols)
    rep = ic_report(ic_long, min_months=cfg.factor.min_ic_months,
                    min_t=cfg.factor.min_t_stat)
    gr = grouped_returns(piped, factor_cols)
    kept = dedup_factors(rep, ic_long, max_corr=cfg.factor.max_factor_corr)
    oos = out_of_sample_check(rep, ic_long)
    scores, weights = build_composite(
        piped, ic_long, factor_cols,
        ic_lookback=cfg.factor.ic_lookback,
        min_ic_months=cfg.factor.min_ic_months,
        min_t=cfg.factor.min_t_stat,
        sign_stability=cfg.factor.sign_stability)

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "factor_report_v3.txt"), "w", encoding="utf-8") as f:
            f.write("=== 因子有效性检验（v3，中性化后）===\n\n")
            f.write(rep.to_string(index=False) + "\n\n")
            f.write("=== 分组收益（5组多空）===\n\n")
            f.write(gr.head(20).to_string(index=False) + "\n\n")
            f.write(f"=== 相关性去重后保留: {kept} ===\n\n")
            f.write("=== 样本外一致性 ===\n\n")
            f.write(oos.to_string(index=False) + "\n")
            if len(weights) > 0:
                f.write("\n=== 最近一期滚动权重 ===\n")
                for k, w in weights.sort_values(ascending=False).items():
                    f.write(f"  {FACTOR_DEFS.get(k, k)} ({k}) {w * 100:.1f}%\n")
        _save_panel(piped, os.path.join(out_dir, "panel_piped_v3.parquet"))
        _save_panel(ic_long, os.path.join(out_dir, "ic_long_v3.parquet"))
        _save_panel(scores, os.path.join(out_dir, "scores_v3.parquet"))
    return piped, ic_long, scores, weights, rep, gr, kept, oos


def _save_panel(df: pd.DataFrame, path: str) -> None:
    d = df.reset_index()
    if "month" in d.columns:
        d["month"] = d["month"].astype(str)
    d.to_parquet(path, index=False)
