"""
阶段 3 自检：组合构建 + 回测（与旧系统对比）
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
from portfolio.builder import build_portfolios
from backtest.engine import run_backtest


def main() -> None:
    print("=" * 56)
    print("QuantV3 阶段 3 自检：组合层 + 回测层")
    print("=" * 56)

    engine = DataEngine()
    daily = engine.get_price()
    sector = engine._load("sector.parquet")
    scores_path = os.path.join(PROJECT_ROOT, "output", "scores_v3.parquet")
    if not os.path.exists(scores_path):
        print("[ERROR] 未找到 scores_v3.parquet，请先运行 python scripts/smoke_factors.py")
        return
    scores = _load_scores(scores_path)
    print(f"合成得分: {len(scores)} 行, "
          f"{scores.index.get_level_values('month').nunique()} 个月")

    print("\n[1] 点对点成分池（逐月）...")
    months = sorted(scores.index.get_level_values("month").unique())
    pool_rows = []
    for m in months:
        df = universe.pool_at(m.to_timestamp())
        df["month"] = m
        pool_rows.append(df[["month", "code"]])
    pool_by_month = pd.concat(pool_rows, ignore_index=True)
    print(f"   池记录: {len(pool_by_month)} 条")

    print(f"\n[2] 组合构建（top_n={cfg.portfolio.top_n}，行业/单票/换手约束）...")
    pf = build_portfolios(
        scores, daily, sector=sector, pool_by_month=pool_by_month,
        top_n=cfg.portfolio.top_n,
        max_single_weight=cfg.portfolio.max_single_weight,
        max_industry_weight=cfg.portfolio.max_industry_weight,
        max_turnover=cfg.portfolio.max_turnover,
        min_listed_days=cfg.portfolio.min_listed_days)
    print(f"   调仓记录: {len(pf)} 条, {pf['exec_date'].nunique()} 次调仓")
    avg_hold = pf.groupby("exec_date").size().mean()
    print(f"   平均持仓: {avg_hold:.1f} 只")
    ind = pf.groupby("exec_date")["industry"].nunique()
    print(f"   平均行业数: {ind.mean():.1f}")

    print("\n[3] 回测（T+1 开盘成交 + 费用 + 涨跌停约束）...")
    bench = None
    pool_bench = None
    index_path = os.path.join(PROJECT_ROOT, "data_cache", "index.parquet")
    if not os.path.exists(index_path):
        legacy_index = r"E:\quant_trader\data_cache\index_cache.parquet"
        if os.path.exists(legacy_index):
            b = pd.read_parquet(legacy_index)
            engine._save("index.parquet", b)
    if os.path.exists(index_path):
        bench = pd.read_parquet(index_path)
    print("   构建等权池基准（点对点成分，沪深300+中证500）...")
    pool_bench = _pool_benchmark(daily, pool_by_month)

    bt = run_backtest(
        daily, pf, benchmark=bench,
        initial_capital=cfg.backtest.initial_capital,
        commission=cfg.backtest.commission,
        slippage=cfg.backtest.slippage,
        stamp_duty=cfg.backtest.stamp_duty,
        limit_up_down=cfg.backtest.limit_up_down)

    if "error" in bt:
        print(f"[ERROR] {bt['error']}")
        return
    print(f"   总收益率: {bt['total_return']}%  |  年化: {bt['annual_return']}%")
    print(f"   夏普: {bt['sharpe']}  |  最大回撤: {bt['max_drawdown']}%  |  Calmar: {bt['calmar']}")
    print(f"   月胜率: {bt['monthly_win_rate']}%  |  平均持仓: {bt['avg_holdings']} 只")
    print(f"   基准(沪深300): {bt['benchmark_return']}%  |  超额: {bt['excess_return']}%  |  IR: {bt['info_ratio']}")
    print(f"   交易: {bt['trades']} 笔  |  平均换手/期: {bt['turnover_avg']}%")
    print(f"   约束执行: 涨停买不进 {bt['limit_up_skip']} 次, 跌停卖不出 {bt['limit_down_skip']} 次, "
          f"停牌 {bt['suspend_skip']} 次")

    print("\n[3.5] 对比等权池基准（更公平的超额度量）...")
    bt_pool = run_backtest(
        daily, pf, benchmark=pool_bench,
        initial_capital=cfg.backtest.initial_capital,
        commission=cfg.backtest.commission,
        slippage=cfg.backtest.slippage,
        stamp_duty=cfg.backtest.stamp_duty,
        limit_up_down=cfg.backtest.limit_up_down)
    if "error" not in bt_pool:
        print(f"   等权池基准: {bt_pool['benchmark_return']}%  |  超额: {bt_pool['excess_return']}%  |  IR: {bt_pool['info_ratio']}")
    else:
        print(f"   [WARN] {bt_pool['error']}")

    out_dir = os.path.join(PROJECT_ROOT, "output")
    os.makedirs(out_dir, exist_ok=True)
    pf.to_csv(os.path.join(out_dir, "portfolios_v3.csv"), index=False, encoding="utf-8-sig")
    bt["nav"].to_csv(os.path.join(out_dir, "nav_v3.csv"), encoding="utf-8-sig")
    with open(os.path.join(out_dir, "backtest_report_v3.txt"), "w", encoding="utf-8") as f:
        f.write("=== QuantV3 回测报告（40 只 / 点对点成分 / 真实成交约束）===\n\n")
        for k, v in bt.items():
            if k != "nav":
                f.write(f"  {k}: {v}\n")
        f.write("\n=== 对等权池基准 ===\n")
        if "error" not in bt_pool:
            f.write(f"  等权池基准收益: {bt_pool['benchmark_return']}%\n")
            f.write(f"  超额: {bt_pool['excess_return']}%\n")
            f.write(f"  InfoRatio: {bt_pool['info_ratio']}\n")
    print(f"\n[OK] 报告已保存: output/backtest_report_v3.txt")

    # 与旧系统对比
    print("\n[4] 与旧系统对比（旧版：Top-8、幸存者偏差、无涨跌停约束）")
    print("   旧版: 年化 3.29%, 夏普 0.09, 平均持仓 0.9 只")
    print(f"   v3  : 年化 {bt['annual_return']}%, 夏普 {bt['sharpe']}, 平均持仓 {bt['avg_holdings']} 只")


def _load_scores(path: str) -> pd.DataFrame:
    d = pd.read_parquet(path)
    d["month"] = pd.PeriodIndex(d["month"], freq="M")
    return d.set_index(["month", "code"]).sort_index()


def _pool_benchmark(daily: pd.DataFrame, pool_by_month: pd.DataFrame) -> pd.DataFrame:
    """等权池基准：用上月末的池子，当月等权收益链成净值"""
    daily = daily.copy()
    daily["code"] = daily["code"].astype(str)
    daily["date"] = pd.to_datetime(daily["date"])
    keys = [daily["code"].rename("code"),
            daily["date"].dt.to_period("M").rename("month")]
    me = daily.groupby(keys)["close"].last().rename("close")
    mef = me.reset_index().sort_values(["code", "month"])
    mef["ret"] = mef.groupby("code", sort=False)["close"].pct_change()

    months = sorted(pool_by_month["month"].unique())
    pool_map = {m: set(g["code"].astype(str))
                for m, g in pool_by_month.groupby("month")}
    rows = []
    for i, m in enumerate(months):
        if i == 0:
            continue
        codes = pool_map[months[i - 1]]
        sub = mef[(mef["month"] == m) & (mef["code"].isin(codes))]
        r = sub["ret"].mean()
        if np.isfinite(r):
            rows.append({"month": m, "ret": r})
    bm = pd.DataFrame(rows)
    if len(bm) == 0:
        return pd.DataFrame()
    bm["nav"] = (1 + bm["ret"]).cumprod()
    bm["date"] = bm["month"].dt.to_timestamp(how="end").dt.normalize()
    return bm[["date", "nav"]].rename(columns={"nav": "close"})


if __name__ == "__main__":
    main()
