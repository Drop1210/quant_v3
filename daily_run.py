"""
每日量化流水线（本地 / 云服务器 / GitHub Actions 通用）

用法：
  python daily_run.py                # 用已有缓存跑完整流水线
  python daily_run.py --update       # 先增量更新行情再跑
  python daily_run.py --skip-push    # 不推送到手机

环境变量：
  QUANT_START_DATE   首次全量下载起点（GitHub 上建议 20220101，省时间）
  WECHAT_WEBHOOK / SERVERCHAN_KEY / PUSHPLUS_TOKEN / BARK_KEY  推送钥匙
"""

import argparse
import json
import os
import sys
import time
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import pandas as pd

from config import cfg
from data import universe
from data.data_engine import DataEngine
from data import fundamental_fetch as ff
from factors.runner import run_research
from factors.library import FACTOR_DEFS
from portfolio.builder import build_portfolios
from backtest.engine import run_backtest
from backtest.benchmark import load_index_benchmark, filtered_pool_benchmark
from dashboard.report import generate_mobile_html
from dashboard import push
from dashboard import tracking

OUT_DIR = os.path.join(PROJECT_ROOT, "output")
LOG_FILE = os.path.join(OUT_DIR, "daily_run.log")
LEGACY_DIR = r"E:\quant_trader\data_cache"


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _bootstrap_legacy(engine: DataEngine, name: str, legacy_name: str):
    """本地开发：缺失时从旧系统缓存复制（服务器/GitHub 上不存在则跳过）"""
    df = engine._load(name)
    if df is None or len(df) == 0:
        legacy = os.path.join(LEGACY_DIR, legacy_name)
        if os.path.exists(legacy):
            engine._save(name, pd.read_parquet(legacy))
            log(f"已从旧系统导入 {name}")
            return engine._load(name)
    return df


def latest_picks(scores, piped, daily, sector, pool_by_month,
                 top_n: int = 40, use_quality: bool = True) -> list:
    """最新一期选股（与回测同规则：质量过滤 + 点对点池 + 剔除ST/次新）"""
    months = sorted(scores.index.get_level_values("month").unique())
    m = months[-1]
    sub = scores.xs(m, level="month").dropna(subset=["composite"]).copy()
    if use_quality and "f_roe" in piped.columns:
        q = piped.xs(m, level="month")["f_roe"]
        sub = sub[sub.index.isin(q[q > 0].index)]
    pool = universe.pool_at(m.to_timestamp())
    sub = sub[sub.index.isin(set(pool["code"].astype(str)))]
    name_map = daily[["code", "name"]].drop_duplicates("code").set_index("code")["name"]
    sub["name"] = sub.index.map(name_map)
    sub = sub[~sub["name"].astype(str).str.contains("ST", case=False, na=False)]
    sec_map = (sector.set_index("code")["sector"].to_dict()
               if sector is not None and len(sector) > 0 else {})
    sub["industry"] = sub.index.map(sec_map).fillna("-")
    sub = sub.sort_values("composite", ascending=False).head(top_n)

    d2 = daily.sort_values(["code", "date"])
    d2["prev_close"] = d2.groupby("code", sort=False)["close"].shift(1)
    last = d2.groupby("code").tail(1).set_index("code")
    picks = []
    for rank, (code, row) in enumerate(sub.iterrows(), 1):
        close = pct = None
        if code in last.index:
            close = float(last.loc[code, "close"])
            prev = float(last.loc[code, "prev_close"])
            if np.isfinite(prev) and prev > 0:
                pct = round((close / prev - 1) * 100, 2)
            close = round(close, 2)
        picks.append({
            "rank": rank, "code": str(code), "name": str(row["name"]),
            "score": round(float(row["composite"]), 3),
            "close": close, "pct": pct, "industry": str(row["industry"]),
        })
    return picks


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true", help="先更新行情数据")
    ap.add_argument("--skip-push", action="store_true", help="不推送手机")
    ap.add_argument("--no-quality", action="store_true", help="关闭质量过滤")
    ap.add_argument("--top", type=int, default=cfg.portfolio.top_n)
    args = ap.parse_args()
    t0 = time.time()

    start_env = os.environ.get("QUANT_START_DATE", "")
    if start_env:
        cfg.data.start_date = start_env

    engine = DataEngine()
    daily = engine.get_price()
    if (daily is None or len(daily) == 0) and not args.update:
        log("[ERROR] 没有本地数据，请先运行 python daily_run.py --update")
        return
    if args.update:
        log("更新行情数据...")
        daily = engine.update()
        if daily is None or len(daily) == 0:
            log("[ERROR] 行情更新失败")
            return
        log(f"行情: {len(daily)} 行, {daily['code'].nunique()} 只")

    valuation = _bootstrap_legacy(engine, "valuation.parquet", "valuation_cache.parquet")
    financial = _bootstrap_legacy(engine, "financial.parquet", "financial_cache.parquet")
    sector = _bootstrap_legacy(engine, "sector.parquet", "sector_cache.parquet")

    if financial is None or len(financial) == 0:
        log("拉取季度财务数据（业绩报表）...")
        financial = ff.fetch_financial_quarterly()
        if financial is not None and len(financial) > 0:
            engine._save("financial.parquet", financial)
            log(f"财务: {len(financial)} 行")
    if sector is None or len(sector) == 0:
        log("拉取行业映射...")
        sector = ff.fetch_sector_map()
        if sector is not None and len(sector) > 0:
            engine._save("sector.parquet", sector)
            log(f"行业: {len(sector)} 只")

    log("运行因子研究流水线（面板 -> 四关检验 -> 合成）...")
    piped, ic_long, scores, weights, rep, gr, kept, oos = run_research(
        daily, valuation, financial, sector, out_dir=OUT_DIR)
    months = sorted(scores.index.get_level_values("month").unique())
    log(f"面板: {len(scores)} 行, {len(months)} 个月")

    log("构建点对点股票池...")
    pool_rows = []
    for m in months:
        df = universe.pool_at(m.to_timestamp())
        df["month"] = m
        pool_rows.append(df[["month", "code"]])
    pool_by_month = pd.concat(pool_rows, ignore_index=True)

    log("构建组合 + 回测（40只/质量过滤/涨跌停约束）...")
    quality = None if args.no_quality else piped
    pf = build_portfolios(
        scores, daily, sector=sector, pool_by_month=pool_by_month,
        quality=quality, top_n=args.top,
        max_single_weight=cfg.portfolio.max_single_weight,
        max_industry_weight=cfg.portfolio.max_industry_weight,
        max_turnover=cfg.portfolio.max_turnover,
        min_listed_days=cfg.portfolio.min_listed_days)
    bench300 = load_index_benchmark(engine, PROJECT_ROOT, LEGACY_DIR)
    if bench300 is None or len(bench300) == 0:
        log("拉取沪深300指数数据...")
        try:
            bench300 = ff.fetch_index("000300", cfg.data.start_date)
        except Exception as e:
            log(f"[WARN] 沪深300拉取失败: {e}")
        if bench300 is not None and len(bench300) > 0:
            engine._save("index.parquet", bench300)
    index500 = engine._load("index500.parquet")
    if index500 is None or len(index500) == 0:
        log("拉取中证500指数数据...")
        try:
            index500 = ff.fetch_index("000905", cfg.data.start_date)
        except Exception as e:
            log(f"[WARN] 中证500拉取失败: {e}")
        if index500 is not None and len(index500) > 0:
            engine._save("index500.parquet", index500)
    pool_bench = filtered_pool_benchmark(daily, pool_by_month, months)
    bt = run_backtest(daily, pf, benchmark=bench300,
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
    log(f"回测: 年化{bt.get('annual_return','-')}% 夏普{bt.get('sharpe','-')} "
        f"vs池基准超额{bt_pool.get('excess_return','-')}%")

    log("生成今日选股...")
    picks = latest_picks(scores, piped, daily, sector, pool_by_month,
                         args.top, use_quality=not args.no_quality)
    tracking.record_picks(picks, OUT_DIR)
    log("评估历史选股表现...")
    weekly = tracking.evaluate_picks(daily, bench300, index500, OUT_DIR)
    if weekly:
        log(f"本周自检批次: {[w['pick_date'] for w in weekly]}")
    factors = []
    for _, r in rep.head(12).iterrows():
        factors.append({
            "factor": r["factor"], "name": FACTOR_DEFS.get(r["factor"], r["factor"]),
            "ic": round(float(r["ic_mean"]), 4), "t": round(float(r["t"]), 2),
            "win": round(float(r["win_rate"]), 1),
            "significant": bool(r["significant"]),
        })
    summary = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "data_date": str(daily["date"].max().date()),
        "picks": picks,
        "backtest": {k: bt.get(k) for k in (
            "annual_return", "sharpe", "max_drawdown", "monthly_win_rate",
            "benchmark_return", "excess_return", "info_ratio", "total_return")},
        "pool_bench": {k: bt_pool.get(k) for k in (
            "benchmark_return", "excess_return", "info_ratio")},
        "factors": factors,
        "weights": {FACTOR_DEFS.get(k, k): round(float(w), 3)
                    for k, w in weights.items()},
        "weekly": weekly,
        "error": None,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "daily_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    pd.DataFrame(picks).to_csv(os.path.join(OUT_DIR, "latest_picks.csv"),
                               index=False, encoding="utf-8-sig")
    generate_mobile_html(summary, os.path.join(OUT_DIR, "mobile_report.html"))
    generate_mobile_html(summary, os.path.join(OUT_DIR, "index.html"))
    log(f"报告已生成, 总用时 {time.time() - t0:.0f}s")

    if not args.skip_push:
        title = f"今日量化选股 {datetime.now():%m-%d}"
        ok = push.push_text(title, push.build_text(summary))
        log(f"推送结果: {ok if ok else '未配置通道'}")
        for w in weekly:
            push.push_text("每周选股自检", tracking.format_weekly(w))


if __name__ == "__main__":
    main()
