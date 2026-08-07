"""
月度因子面板构建
  1. 逐股计算价量因子（Alpha158 子集）
  2. 取每月最后一个交易日为月度截面
  3. 合并财务/估值（含 45 天披露延迟，防止用未来财报）
  4. 计算下一月收益 fwd_ret（IC 检验的标签）
"""

from typing import Optional

import numpy as np
import pandas as pd

from factors.library import PRICE_FACTORS, FUNDAMENTAL_FACTORS, compute_price_factors


def build_monthly_panel(daily: pd.DataFrame,
                        valuation: Optional[pd.DataFrame] = None,
                        financial: Optional[pd.DataFrame] = None,
                        disclosure_delay_days: int = 45) -> pd.DataFrame:
    daily = daily.copy()
    daily["code"] = daily["code"].astype(str)
    daily["date"] = pd.to_datetime(daily["date"])

    # 1) 价量因子 + 月度截面
    fac = compute_price_factors(daily)
    fac = fac.reset_index()
    fac["month"] = fac["date"].dt.to_period("M")
    fac = fac.sort_values(["code", "date"])
    panel = (fac.groupby(["code", "month"], sort=False)
             .tail(1)
             .drop(columns=["date"])
             .set_index(["code", "month"]))

    # 2) 下一月收益（IC 标签）
    # 注意：分组键必须显式命名，否则 MultiIndex 层级名错乱会导致 join 放大行数
    keys = [daily["code"].rename("code"),
            daily["date"].dt.to_period("M").rename("month")]
    me_close = daily.groupby(keys)["close"].last().rename("me_close")
    me2 = me_close.reset_index().sort_values(["code", "month"])
    # 未来收益：月末 m 对应 m -> m+1 的收益（必须在组内 shift，防止跨股票串位）
    me2["fwd_ret"] = (me2.groupby("code", sort=False)["me_close"]
                      .transform(lambda s: s.pct_change().shift(-1)))
    fwd = me2.set_index(["code", "month"])["fwd_ret"]
    panel = panel.join(fwd)

    # 3) 估值 -> EP/BP/市值
    if valuation is not None and len(valuation) > 0:
        val = valuation.copy()
        val["code"] = val["code"].astype(str)
        val["date"] = pd.to_datetime(val["date"])
        val["month"] = val["date"].dt.to_period("M")
        val_me = (val.sort_values("date")
                  .groupby(["code", "month"], sort=False)
                  .tail(1))
        val_map = val_me.set_index(["code", "month"])[["pe", "pb", "total_mv"]]
        panel = panel.join(val_map)
        panel["f_ep"] = 1.0 / panel["pe"].replace(0, np.nan)
        panel["f_bp"] = 1.0 / panel["pb"].replace(0, np.nan)
        panel["f_log_mv"] = np.log(panel["total_mv"])

    # 4) 财务（披露延迟 45 天）
    if financial is not None and len(financial) > 0:
        fin = financial.copy()
        fin["code"] = fin["code"].astype(str)
        fin["date"] = pd.to_datetime(fin["date"])
        fin["eff_date"] = fin["date"] + pd.Timedelta(days=disclosure_delay_days)
        fin = fin.sort_values(["code", "eff_date"])
        roe = _latest_financial(panel, fin, "roe")
        growth = _latest_financial(panel, fin, "profit_growth")
        panel["f_roe"] = roe
        panel["f_profit_growth"] = growth

    panel = panel.reset_index().set_index(["month", "code"]).sort_index()
    panel = panel.dropna(subset=["fwd_ret"])
    return panel


def _latest_financial(panel: pd.DataFrame, fin: pd.DataFrame, col: str) -> pd.Series:
    """每只股票每月末：取披露日 <= 月末 的最新财务值（前向填充）"""
    fin_code = fin[["code", "eff_date", col]].copy()
    fin_code[col] = pd.to_numeric(fin_code[col], errors="coerce")
    fin_code = fin_code.dropna(subset=[col]).sort_values(["eff_date"])
    pe = panel.reset_index()[["code", "month"]].drop_duplicates()
    pe["month_end"] = pe["month"].dt.to_timestamp(how="end")
    vals = np.full(len(pe), np.nan)
    for code, g in pe.groupby("code", sort=False):
        fc = fin_code[fin_code["code"] == code]
        if len(fc) == 0:
            continue
        ed = fc["eff_date"].to_numpy(dtype="datetime64[ns]")
        me = g["month_end"].to_numpy(dtype="datetime64[ns]")
        idx = np.searchsorted(ed, me, side="right") - 1
        ok = idx >= 0
        if ok.any():
            vals[g.index.values[ok]] = fc[col].to_numpy()[idx[ok]]
    tmp = pd.Series(vals, index=pe.set_index(["code", "month"]).index)
    return tmp.reindex(panel.index)
