"""
因子预处理流水线（参考 Barra 风格）：
  去极值(MAD) → 横截面 Z-Score → 行业/市值中性化(回归取残差)
"""

from typing import List, Optional

import numpy as np
import pandas as pd


def winsorize_mad(panel: pd.DataFrame, cols: List[str], sigma: float = 3.0) -> pd.DataFrame:
    """逐月、逐因子 MAD 去极值"""
    out = panel.copy()
    months = panel.index.get_level_values("month").unique()
    for m in months:
        mask = panel.index.get_level_values("month") == m
        for c in cols:
            if c not in panel.columns:
                continue
            s = panel.loc[mask, c].astype(float)
            med = s.median()
            mad = (s - med).abs().median() * 1.4826
            if mad <= 1e-12 or np.isnan(mad):
                continue
            lo, hi = med - sigma * mad, med + sigma * mad
            out.loc[mask, c] = s.clip(lo, hi)
    return out


def zscore_cross(panel: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    """逐月横截面 Z-Score"""
    out = panel.copy()
    for m in out.index.get_level_values("month").unique():
        mask = out.index.get_level_values("month") == m
        for c in cols:
            if c not in out.columns:
                continue
            s = out.loc[mask, c].astype(float)
            mean, std = s.mean(), s.std()
            if std is None or np.isnan(std) or std <= 1e-12:
                continue
            out.loc[mask, c] = (s - mean) / std
    return out


def neutralize(panel: pd.DataFrame, cols: List[str],
               sector: Optional[pd.DataFrame] = None,
               log_mv_col: str = "f_log_mv",
               include_size: bool = True) -> pd.DataFrame:
    """
    行业 + 市值中性化：逐月对 [行业哑变量 + log市值] 回归，取残差。
    sector: DataFrame[code, sector]
    panel 需已含 f_log_mv（否则仅行业中性化）
    """
    out = panel.copy()
    if sector is None or len(sector) == 0:
        return out
    sec_map = sector.set_index("code")["sector"].to_dict()
    codes = out.index.get_level_values("code")
    sec_series = pd.Series(codes.map(sec_map), index=out.index).fillna("未知")
    for m in out.index.get_level_values("month").unique():
        mask = out.index.get_level_values("month") == m
        sub = out.loc[mask]
        secs = sec_series.loc[mask]
        dummies = pd.get_dummies(secs).astype(float)
        mv = (sub[log_mv_col].astype(float)
              if include_size and log_mv_col in sub.columns else None)
        X = dummies.copy()
        if mv is not None:
            X = X.join(mv.rename("mv"))
        X["const"] = 1.0
        X = X.fillna(0.0)
        for c in cols:
            if c not in sub.columns:
                continue
            y = sub[c].astype(float).fillna(0.0)
            try:
                beta, *_ = np.linalg.lstsq(X.values, y.values, rcond=None)
                resid = y.values - X.values @ beta
                out.loc[mask, c] = resid
            except Exception:
                continue
    return out


def run_pipeline(panel: pd.DataFrame, factor_cols: List[str],
                 sector: Optional[pd.DataFrame] = None,
                 winsorize_sigma: float = 3.0,
                 neutralize_enabled: bool = True,
                 neutralize_size: bool = True) -> pd.DataFrame:
    """完整预处理：去极值 -> Z-Score -> （可选）行业/市值中性化"""
    out = winsorize_mad(panel, factor_cols, winsorize_sigma)
    out = zscore_cross(out, factor_cols)
    if neutralize_enabled and sector is not None and len(sector) > 0:
        out = neutralize(out, factor_cols, sector,
                         include_size=neutralize_size and "f_log_mv" in factor_cols)
    return out
