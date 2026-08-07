"""
组合构建器

输入：合成得分（month, code）-> composite
输出：每月调仓组合（40 只左右），约束：
  - 行业权重上限（默认 15%）
  - 单票权重上限（默认 5%）
  - 单次换手上限（默认 30%）
  - 剔除 ST、上市不足 120 天
  - 点对点成分股过滤（可选，防前视）
"""

from typing import Optional

import numpy as np
import pandas as pd


def build_portfolios(scores: pd.DataFrame,
                     daily: pd.DataFrame,
                     sector: Optional[pd.DataFrame] = None,
                     pool_by_month: Optional[pd.DataFrame] = None,
                     quality: Optional[pd.DataFrame] = None,
                     top_n: int = 40,
                     max_single_weight: float = 0.05,
                     max_industry_weight: float = 0.15,
                     max_turnover: float = 0.30,
                     exclude_st: bool = True,
                     min_listed_days: int = 120) -> pd.DataFrame:
    daily = daily.copy()
    daily["code"] = daily["code"].astype(str)
    daily["date"] = pd.to_datetime(daily["date"])

    first_day = daily.groupby("code")["date"].min().rename("first_date")
    name_map = daily[["code", "name"]].drop_duplicates("code").set_index("code")["name"]
    sec_map = (sector.set_index("code")["sector"].to_dict()
               if sector is not None and len(sector) > 0 else {})
    all_dates = pd.DatetimeIndex(sorted(daily["date"].unique()))

    # 点对点成分：month -> set(code)
    pool_map: dict = {}
    if pool_by_month is not None and len(pool_by_month) > 0:
        for m, g in pool_by_month.groupby("month"):
            pool_map[m] = set(g["code"].astype(str))

    max_per_industry = max(1, int(round(max_industry_weight * top_n)))
    months = sorted(scores.index.get_level_values("month").unique())
    prev_codes: list = []
    records = []

    for m in months:
        month_end = m.to_timestamp(how="end")
        future = all_dates[all_dates > month_end]
        if len(future) == 0:
            continue  # 最新一期没有执行日，留给"今日选股"单独输出
        exec_date = future[0]

        sub = scores.xs(m, level="month").copy()
        sub = sub.dropna(subset=["composite"])
        # 质量过滤（可选）：f_roe > 0 = 行业/市值调整后高于中位
        if quality is not None and "f_roe" in quality.columns:
            try:
                q = quality.xs(m, level="month")["f_roe"]
                sub = sub[sub.index.isin(q[q > 0].index)]
            except KeyError:
                pass
        sub["first_date"] = sub.index.map(first_day)
        if exclude_st:
            sub["name"] = sub.index.map(name_map)
            sub = sub[~sub["name"].astype(str).str.contains("ST", case=False, na=False)]
        listed_days = (exec_date - sub["first_date"]).dt.days
        sub = sub[sub["first_date"].notna() & (listed_days >= min_listed_days)]
        if m in pool_map:
            sub = sub[sub.index.isin(pool_map[m])]
        if len(sub) == 0:
            prev_codes = []
            continue

        sub["industry"] = sub.index.map(sec_map).fillna("未知")
        sub = sub.sort_values("composite", ascending=False)
        cand = sub.head(max(top_n * 3, 60))

        # 行业上限（贪心：按得分从高到低，行业满员则跳过）
        chosen = []
        ind_count: dict = {}
        for code, row in cand.iterrows():
            ind = row["industry"]
            if ind_count.get(ind, 0) >= max_per_industry:
                continue
            chosen.append(code)
            ind_count[ind] = ind_count.get(ind, 0) + 1
            if len(chosen) >= top_n:
                break
        if not chosen:
            prev_codes = []
            continue

        # 换手约束：强制保留上期持仓（最多 (1-max_turnover) 比例，剔除已失效的），
        # 剩余仓位用本期高分新票补满 —— 真正把换手压到上限以内
        prev_set = set(prev_codes)
        n_keep = int(top_n * (1 - max_turnover)) if prev_codes else 0
        if prev_codes:
            kept_prev = [c for c in prev_codes if c in sub.index][:n_keep]
            slots = max(0, top_n - len(kept_prev))
            final = kept_prev + [c for c in chosen if c not in set(kept_prev)][:slots]
        else:
            final = chosen[:top_n]
        final = final[:top_n]
        if not final:
            prev_codes = []
            continue

        w = pd.Series(1.0 / len(final), index=final)
        if w.max() > max_single_weight:
            w = w * (max_single_weight / w.max())
        prev_codes = final
        for rank, code in enumerate(final, 1):
            records.append({
                "month": m, "exec_date": exec_date, "code": code,
                "weight": float(w[code]), "industry": sub.loc[code, "industry"],
                "rank": rank,
            })

    return pd.DataFrame(records)
