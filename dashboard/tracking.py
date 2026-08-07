"""
选股跟踪与每周自检

每次运行把当日选股记入 pick_history.csv（随仓库保存）；
批次满 5 个交易日后自动统计实际表现（平均收益/上涨比例/对比沪深300与中证500），
推送到微信并在手机网页展示。已报告的批次记录在 weekly_report_history.json，不会重复。
"""

import json
import os
from datetime import datetime
from typing import List, Optional

import numpy as np
import pandas as pd

PICK_HISTORY = "pick_history.csv"
REPORT_HISTORY = "weekly_report_history.json"


def record_picks(picks: List[dict], out_dir: str) -> pd.DataFrame:
    """把今日选股追加进历史（同日去重）"""
    today = datetime.now().strftime("%Y-%m-%d")
    new = pd.DataFrame([{
        "date": today,
        "code": p["code"],
        "name": p["name"],
        "score": p.get("score"),
        "close": p.get("close"),
    } for p in picks])
    path = os.path.join(out_dir, PICK_HISTORY)
    if os.path.exists(path):
        old = pd.read_csv(path, dtype={"code": str})
        old = old[old["date"] != today]
        df = pd.concat([old, new], ignore_index=True)
    else:
        df = new
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return df


def _load_history(out_dir: str) -> pd.DataFrame:
    path = os.path.join(out_dir, PICK_HISTORY)
    if not os.path.exists(path):
        return pd.DataFrame(columns=["date", "code", "name", "score", "close"])
    return pd.read_csv(path, dtype={"code": str})


def _load_reported(out_dir: str) -> set:
    path = os.path.join(out_dir, REPORT_HISTORY)
    if not os.path.exists(path):
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            return set(json.load(f).get("reported", []))
    except Exception:
        return set()


def _save_reported(out_dir: str, reported: set) -> None:
    path = os.path.join(out_dir, REPORT_HISTORY)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"reported": sorted(reported)}, f, ensure_ascii=False, indent=2)


def _bench_ret(index_df: Optional[pd.DataFrame], d0: pd.Timestamp,
               latest: pd.Timestamp) -> Optional[float]:
    """指数从 d0 到 latest 的收益（用收盘价）"""
    if index_df is None or len(index_df) == 0:
        return None
    b = index_df.copy()
    b["date"] = pd.to_datetime(b["date"])
    b = b.set_index("date")["close"].sort_index()
    b = b[b.index <= latest]
    if len(b) == 0:
        return None
    idx = b.index.searchsorted(d0, side="right") - 1
    if idx < 0:
        return None
    p0, p1 = float(b.iloc[idx]), float(b.iloc[-1])
    return float(p1 / p0 - 1) if p0 and p0 > 0 else None


def evaluate_picks(daily: pd.DataFrame,
                   index300: Optional[pd.DataFrame],
                   index500: Optional[pd.DataFrame],
                   out_dir: str,
                   min_gap_days: int = 5) -> List[dict]:
    """找出到期且未报告的选股批次，计算实际表现并标记已报告"""
    history = _load_history(out_dir)
    if len(history) == 0:
        return []
    daily = daily.copy()
    daily["code"] = daily["code"].astype(str)
    daily["date"] = pd.to_datetime(daily["date"])
    latest_date = daily["date"].max()
    trading_days = sorted(daily["date"].unique())
    close_pivot = daily.pivot_table(index="date", columns="code", values="close")
    reported = _load_reported(out_dir)
    reports: List[dict] = []

    for pick_date, grp in history.groupby("date"):
        if pick_date in reported:
            continue
        d0 = pd.Timestamp(pick_date)
        if d0 >= latest_date:
            continue
        gap = len([d for d in trading_days if d > d0])
        if gap < min_gap_days:
            continue

        rets, names = [], []
        for _, r in grp.iterrows():
            code = str(r["code"])
            if code not in close_pivot.columns:
                continue
            series = close_pivot[code].dropna()
            if len(series) == 0:
                continue
            idx = series.index.searchsorted(d0, side="right") - 1
            if idx < 0:
                continue
            p0, p1 = float(series.iloc[idx]), float(series.iloc[-1])
            if p0 and p0 > 0 and p1 and p1 > 0:
                rets.append(p1 / p0 - 1)
                names.append(str(r["name"]))
        if not rets:
            continue
        arr = np.asarray(rets)
        avg = float(arr.mean())
        win = float((arr > 0).mean()) * 100
        bi, wi = int(np.argmax(arr)), int(np.argmin(arr))
        r300 = _bench_ret(index300, d0, latest_date)
        r500 = _bench_ret(index500, d0, latest_date)
        reports.append({
            "pick_date": pick_date,
            "eval_date": str(latest_date.date()),
            "n": len(arr),
            "avg_return": round(avg * 100, 2),
            "win_rate": round(win, 1),
            "best": (names[bi], float(round(arr[bi] * 100, 2))),
            "worst": (names[wi], float(round(arr[wi] * 100, 2))),
            "bench300": round(r300 * 100, 2) if r300 is not None else None,
            "bench500": round(r500 * 100, 2) if r500 is not None else None,
            "excess300": round((avg - r300) * 100, 2) if r300 is not None else None,
            "excess500": round((avg - r500) * 100, 2) if r500 is not None else None,
        })
        reported.add(pick_date)
    if reports:
        _save_reported(out_dir, reported)
    return reports


def format_weekly(report: dict) -> str:
    lines = [
        f"选股自检：{report['pick_date']} 选的 {report['n']} 只",
        f"平均收益 {report['avg_return']:+.2f}% ｜ 上涨比例 {report['win_rate']:.0f}%",
    ]
    if report.get("bench300") is not None:
        lines.append(f"同期沪深300 {report['bench300']:+.2f}% ｜ 跑赢 {report['excess300']:+.2f}%")
    if report.get("bench500") is not None:
        lines.append(f"同期中证500 {report['bench500']:+.2f}% ｜ 跑赢 {report['excess500']:+.2f}%")
    lines.append(f"最好：{report['best'][0]} {report['best'][1]:+.2f}%")
    lines.append(f"最差：{report['worst'][0]} {report['worst'][1]:+.2f}%")
    lines.append("")
    lines.append("仅供参考，不构成投资建议")
    return "\n".join(lines)
