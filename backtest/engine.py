"""
回测引擎

规则：
  - 月末生成组合，下月首个交易日开盘执行（T+1）
  - 手续费/滑点/印花税
  - 涨停买不进、跌停卖不出（按主板 10%/ST 5%/创业板 20%）
  - 停牌不交易、继续持有
  - 整手买入（100 股）
"""

from typing import Dict, Optional

import numpy as np
import pandas as pd


def _limit_pct(code, name: str = "") -> float:
    if "ST" in str(name).upper():
        return 0.05
    if str(code).startswith(("300", "301", "688")):
        return 0.20
    return 0.10


def run_backtest(daily: pd.DataFrame,
                 portfolios: pd.DataFrame,
                 benchmark: Optional[pd.DataFrame] = None,
                 initial_capital: float = 1_000_000.0,
                 commission: float = 0.00025,
                 slippage: float = 0.001,
                 stamp_duty: float = 0.001,
                 limit_up_down: bool = True) -> Dict:
    daily = daily.copy()
    daily["code"] = daily["code"].astype(str)
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values(["code", "date"])

    open_map = daily.pivot_table(index="date", columns="code", values="open")
    close_map = daily.pivot_table(index="date", columns="code", values="close")
    # 停牌日无收盘价：用最后已知价估值，避免净值人为跳水
    close_ff = close_map.ffill()
    prev_close_map = close_map.shift(1)
    name_map = daily[["code", "name"]].drop_duplicates("code").set_index("code")["name"]
    all_dates = sorted(open_map.index)

    cash = initial_capital
    positions: Dict[str, int] = {}
    nav_prev = initial_capital
    nav_records = []
    holdings_count = []
    turnover_pcts = []
    stats = {"limit_up_skip": 0, "limit_down_skip": 0, "suspend_skip": 0,
             "trades": 0, "turnover_sum": 0.0}

    if len(portfolios) == 0:
        return {"error": "无组合数据", "nav": pd.DataFrame()}

    rebalances = sorted(portfolios["exec_date"].unique())
    first_date = None

    for exec_date in rebalances:
        sub = portfolios[portfolios["exec_date"] == exec_date]
        target: Dict[str, float] = {}
        for _, r in sub.iterrows():
            target[r["code"]] = float(r["weight"])
        turnover_this = 0.0

        # ---- 卖出（先卖后买）----
        for code, shares in list(positions.items()):
            if code in target:
                continue
            if code not in open_map.columns:
                stats["suspend_skip"] += 1
                continue
            px_open = float(open_map.loc[exec_date, code])
            if np.isnan(px_open):
                stats["suspend_skip"] += 1
                continue
            if limit_up_down:
                prev = float(prev_close_map.loc[exec_date, code])
                if not np.isnan(prev):
                    lmt = _limit_pct(code, str(name_map.get(code, "")))
                    if px_open <= round(prev * (1 - lmt), 2) + 1e-6:
                        stats["limit_down_skip"] += 1
                        continue  # 跌停卖不出，继续持有
            px = px_open * (1 - slippage)
            proceeds = shares * px
            fee = proceeds * commission + proceeds * stamp_duty
            cash += proceeds - fee
            turnover_this += proceeds
            stats["trades"] += 1
            stats["turnover_sum"] += proceeds
            del positions[code]

        # ---- 买入 ----
        for code, w in target.items():
            if code in positions:
                continue
            if code not in open_map.columns:
                stats["suspend_skip"] += 1
                continue
            px_open = float(open_map.loc[exec_date, code])
            if np.isnan(px_open):
                stats["suspend_skip"] += 1
                continue
            if limit_up_down:
                prev = float(prev_close_map.loc[exec_date, code])
                if not np.isnan(prev):
                    lmt = _limit_pct(code, str(name_map.get(code, "")))
                    if px_open >= round(prev * (1 + lmt), 2) - 1e-6:
                        stats["limit_up_skip"] += 1
                        continue  # 涨停买不进
            budget = min(nav_prev * w, cash)
            if budget <= 0:
                continue
            px_in = px_open * (1 + slippage)
            shares = int(budget / (px_in * 100)) * 100
            if shares <= 0:
                continue
            cost = shares * px_in
            fee = cost * commission
            if cost + fee > cash:
                shares = int(cash / (px_in * 100)) * 100
                if shares <= 0:
                    continue
                cost = shares * px_in
                fee = cost * commission
            cash -= cost + fee
            positions[code] = shares
            turnover_this += cost
            stats["trades"] += 1
            stats["turnover_sum"] += cost

        # 当日收盘净值
        value = cash
        for code, shares in positions.items():
            px = float(close_ff.loc[exec_date, code]) if code in close_ff.columns else np.nan
            if not np.isnan(px):
                value += shares * px
        if first_date is None:
            first_date = exec_date
        nav_prev = value
        holdings_count.append(len(positions))
        turnover_pcts.append(turnover_this / max(nav_prev, 1e-9) * 100)
        nav_records.append((exec_date, value))

    # ---- 逐日净值 ----
    if first_date is None:
        return {"error": "无调仓日", "nav": pd.DataFrame()}
    daily_nav = []
    for d in all_dates:
        if d < first_date:
            continue
        value = cash
        for code, shares in positions.items():
            px = float(close_ff.loc[d, code]) if code in close_ff.columns else np.nan
            if not np.isnan(px):
                value += shares * px
        daily_nav.append({"date": d, "nav": value})
    nav = pd.DataFrame(daily_nav).set_index("date")["nav"]
    if len(nav) < 2:
        return {"error": "净值序列过短", "nav": nav}

    # ---- 指标 ----
    rets = nav.pct_change().dropna()
    total = nav.iloc[-1] / nav.iloc[0] - 1
    years = len(nav) / 252.0
    annual = (1 + total) ** (1 / years) - 1 if years > 0 else np.nan
    vol = rets.std() * np.sqrt(252) if len(rets) > 1 else np.nan
    sharpe = annual / vol if vol and vol > 1e-12 else np.nan
    dd = (nav / nav.cummax() - 1).min()
    monthly = nav.resample("ME").last().pct_change().dropna()
    win_rate = float((monthly > 0).mean()) * 100 if len(monthly) else np.nan
    calmar = annual / abs(dd) if dd and abs(dd) > 1e-12 else np.nan

    bench_ret = np.nan
    excess = np.nan
    ir = np.nan
    if benchmark is not None and len(benchmark) > 0:
        bench = benchmark.copy()
        bench["date"] = pd.to_datetime(bench["date"])
        bench = bench.set_index("date")["close"].sort_index()
        bench = bench.reindex(nav.index).ffill().bfill()
        bench = bench / bench.iloc[0]
        bench_ret = bench.iloc[-1] - 1
        excess = total - bench_ret
        er = nav.pct_change() - bench.pct_change()
        er = er.dropna()
        ir = er.mean() / (er.std() + 1e-10) * np.sqrt(252) if len(er) > 2 else np.nan

    return {
        "nav": nav,
        "total_return": round(float(total) * 100, 2),
        "annual_return": round(float(annual) * 100, 2),
        "annual_vol": round(float(vol) * 100, 2),
        "sharpe": round(float(sharpe), 3),
        "max_drawdown": round(float(dd) * 100, 2),
        "calmar": round(float(calmar), 3),
        "monthly_win_rate": round(float(win_rate), 1),
        "benchmark_return": round(float(bench_ret) * 100, 2),
        "excess_return": round(float(excess) * 100, 2),
        "info_ratio": round(float(ir), 3),
        "avg_holdings": round(float(np.mean(holdings_count)), 1),
        "months": int(monthly.shape[0]),
        "trades": stats["trades"],
        "turnover_avg": round(float(np.mean(turnover_pcts)), 1),
        "limit_up_skip": stats["limit_up_skip"],
        "limit_down_skip": stats["limit_down_skip"],
        "suspend_skip": stats["suspend_skip"],
    }
