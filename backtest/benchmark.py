"""基准构建：沪深300 / 等权池基准（与策略同过滤）"""

import os
from typing import Optional

import numpy as np
import pandas as pd


def load_index_benchmark(engine, project_root: str,
                         legacy_path: Optional[str] = None) -> Optional[pd.DataFrame]:
    p = os.path.join(project_root, "data_cache", "index.parquet")
    if not os.path.exists(p) and legacy_path and os.path.exists(legacy_path):
        engine._save("index.parquet", pd.read_parquet(legacy_path))
    if os.path.exists(p):
        return pd.read_parquet(p)
    return None


def filtered_pool_benchmark(daily: pd.DataFrame, pool_by_month: pd.DataFrame,
                            months) -> pd.DataFrame:
    """等权池基准：上月末池子（剔除 ST/次新），当月等权收益链成净值"""
    daily = daily.copy()
    daily["code"] = daily["code"].astype(str)
    daily["date"] = pd.to_datetime(daily["date"])
    name_map = daily[["code", "name"]].drop_duplicates("code").set_index("code")["name"]
    first_day = daily.groupby("code")["date"].min()
    keys = [daily["code"].rename("code"),
            daily["date"].dt.to_period("M").rename("month")]
    me = daily.groupby(keys)["close"].last().rename("close")
    mef = me.reset_index().sort_values(["code", "month"])
    mef["ret"] = mef.groupby("code", sort=False)["close"].pct_change()
    pool_map = {m: set(g["code"].astype(str))
                for m, g in pool_by_month.groupby("month")}
    rows = []
    for i, m in enumerate(months):
        if i == 0:
            continue
        m_prev = months[i - 1]
        codes = pool_map.get(m_prev, set())
        sub = mef[(mef["month"] == m) & (mef["code"].isin(codes))].copy()
        sub["name"] = sub["code"].map(name_map)
        sub["first"] = sub["code"].map(first_day)
        sub = sub[~sub["name"].astype(str).str.contains("ST", case=False, na=False)]
        sub = sub[(sub["first"].notna())
                  & ((m_prev.to_timestamp(how="end") - sub["first"]).dt.days >= 120)]
        r = sub["ret"].mean()
        if np.isfinite(r):
            rows.append({"m": m, "ret": r})
    bm = pd.DataFrame(rows)
    if len(bm) == 0:
        return pd.DataFrame()
    bm["nav"] = (1 + bm["ret"]).cumprod()
    bm["date"] = bm["m"].dt.to_timestamp(how="end").dt.normalize()
    return bm[["date", "nav"]].rename(columns={"nav": "close"})
