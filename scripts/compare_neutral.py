"""
对照实验：市值中性化 vs 保留市值敞口
同一套因子流水线，只改一个变量，比较回测结果。
"""

import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from config import cfg
from data import universe
from data.data_engine import DataEngine
from factors.library import PRICE_FACTORS, FUNDAMENTAL_FACTORS
from factors.panel import build_monthly_panel
from factors.pipeline import run_pipeline
from factors.validation import monthly_ic
from alpha.composite import build_composite
from portfolio.builder import build_portfolios
from backtest.engine import run_backtest


def main() -> None:
    print("=" * 60)
    print("对照实验：市值中性化开关（其余完全一致）")
    print("=" * 60)

    engine = DataEngine()
    daily = engine.get_price()
    sector = engine._load("sector.parquet")
    valuation = engine._load("valuation.parquet")
    financial = engine._load("financial.parquet")

    print("\n[1] 构建月度面板（一次，两版共用）...")
    panel = build_monthly_panel(daily, valuation, financial)
    factor_cols = [c for c in PRICE_FACTORS + FUNDAMENTAL_FACTORS if c in panel.columns]
    months = sorted(panel.index.get_level_values("month").unique())

    pool_rows = []
    for m in months:
        df = universe.pool_at(m.to_timestamp())
        df["month"] = m
        pool_rows.append(df[["month", "code"]])
    pool_by_month = pd.concat(pool_rows, ignore_index=True)

    bench_index = _load_index_benchmark(engine)
    pool_bench = _filtered_pool_benchmark(daily, pool_by_month, months)

    results = []
    for size_on in (True, False):
        tag = "市值中性化" if size_on else "保留市值敞口"
        print(f"\n[2] {tag}：预处理 -> 合成 -> 组合 -> 回测 ...")
        piped = run_pipeline(panel, factor_cols, sector,
                             winsorize_sigma=cfg.factor.winsorize_sigma,
                             neutralize_enabled=True,
                             neutralize_size=size_on)
        ic_long = monthly_ic(piped, factor_cols)
        scores, _ = build_composite(
            piped, ic_long, factor_cols,
            ic_lookback=cfg.factor.ic_lookback,
            min_ic_months=cfg.factor.min_ic_months,
            min_t=cfg.factor.min_t_stat,
            sign_stability=cfg.factor.sign_stability)
        pf = build_portfolios(
            scores, daily, sector=sector, pool_by_month=pool_by_month,
            top_n=cfg.portfolio.top_n,
            max_single_weight=cfg.portfolio.max_single_weight,
            max_industry_weight=cfg.portfolio.max_industry_weight,
            max_turnover=cfg.portfolio.max_turnover,
            min_listed_days=cfg.portfolio.min_listed_days)
        bt = run_backtest(daily, pf, benchmark=bench_index,
                          initial_capital=cfg.backtest.initial_capital,
                          commission=cfg.backtest.commission,
                          slippage=cfg.backtest.slippage,
                          stamp_duty=cfg.backtest.stamp_duty,
                          limit_up_down=cfg.backtest.limit_up_down)
        bt_pool = run_backtest(daily, pf, benchmark=pool_bench,
                               initial_capital=cfg.backtest.initial_capital,
                               commission=cfg.backtest.commission,
                               slippage=cfg.backtest.slippage,
                               stamp_duty=cfg.backtest.stamp_duty,
                               limit_up_down=cfg.backtest.limit_up_down)
        print(f"   {tag}: 年化 {bt['annual_return']}% | 夏普 {bt['sharpe']} | "
              f"回撤 {bt['max_drawdown']}% | vs300超额 {bt['excess_return']}% | "
              f"vs过滤池超额 {bt_pool['excess_return']}% | IR_pool {bt_pool['info_ratio']}")
        results.append({"version": tag, "annual": bt["annual_return"],
                        "sharpe": bt["sharpe"], "maxdd": bt["max_drawdown"],
                        "excess_300": bt["excess_return"],
                        "excess_pool": bt_pool["excess_return"],
                        "ir_pool": bt_pool["info_ratio"]})

    print("\n[3] 对比汇总")
    print(pd.DataFrame(results).to_string(index=False))


def _load_index_benchmark(engine) -> pd.DataFrame:
    p = os.path.join(PROJECT_ROOT, "data_cache", "index.parquet")
    if not os.path.exists(p):
        legacy = r"E:\quant_trader\data_cache\index_cache.parquet"
        if os.path.exists(legacy):
            engine._save("index.parquet", pd.read_parquet(legacy))
    if os.path.exists(p):
        return pd.read_parquet(p)
    return None


def _filtered_pool_benchmark(daily, pool_by_month, months) -> pd.DataFrame:
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
    bm["nav"] = (1 + bm["ret"]).cumprod()
    bm["date"] = bm["m"].dt.to_timestamp(how="end").dt.normalize()
    return bm[["date", "nav"]].rename(columns={"nav": "close"})


if __name__ == "__main__":
    main()
