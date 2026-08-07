"""
财务/行业/估值快速拉取（GitHub Actions 全新环境用）
  - 财务：ak.stock_yjbb_em（业绩报表，按季度一次返回全市场，很快）
  - 行业：东财行业板块成分（~86 个板块调用）
  - 估值：ak.stock_value_em（当前 PE/PB/总市值快照）
  - 指数：ak.index_zh_a_hist
"""

from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd


def _quarters(start_year: int = 2018) -> List[str]:
    now = datetime.now()
    qs = []
    for y in range(start_year, now.year + 1):
        for m in ("0331", "0630", "0930", "1231"):
            s = f"{y}{m}"
            if s <= now.strftime("%Y%m%d"):
                qs.append(s)
    return qs


def fetch_financial_quarterly(start_year: int = 2018) -> pd.DataFrame:
    """按季度拉取业绩报表，返回 code/date/roe/profit_growth/net_profit"""
    import akshare as ak
    rows = []
    for q in _quarters(start_year):
        try:
            df = ak.stock_yjbb_em(date=q)
        except Exception:
            continue
        if df is None or len(df) == 0:
            continue
        cols = {str(c).strip(): c for c in df.columns}
        def get(*names):
            for n in names:
                if n in cols:
                    return cols[n]
            return None
        c_code = get("股票代码", "代码")
        c_name = get("股票简称", "名称")
        c_net = get("净利润-净利润", "净利润")
        c_growth = get("净利润-同比增长", "净利润同比")
        c_roe = get("净资产收益率", "净资产收益率-净资产收益率")
        c_industry = get("所处行业")
        if c_code is None:
            continue
        extra = [c for c in (c_name, c_net, c_growth, c_roe, c_industry) if c is not None]
        sub = df[[c_code] + extra]
        ren = {c_code: "code"}
        for src, dst in ((c_name, "name"), (c_net, "net_profit"),
                         (c_growth, "profit_growth"), (c_roe, "roe"),
                         (c_industry, "sector")):
            if src is not None:
                ren[src] = dst
        sub = sub.rename(columns=ren)
        sub["date"] = pd.to_datetime(q, format="%Y%m%d")
        for c in ("net_profit", "profit_growth", "roe"):
            if c in sub.columns:
                sub[c] = pd.to_numeric(sub[c], errors="coerce")
        rows.append(sub)
    if not rows:
        return pd.DataFrame()
    df = pd.concat(rows, ignore_index=True)
    df["code"] = df["code"].astype(str).str.zfill(6)
    keep = [c for c in ("code", "date", "net_profit", "profit_growth", "roe", "sector") if c in df.columns]
    return df[keep].drop_duplicates(["code", "date"]).reset_index(drop=True)


def fetch_sector_map() -> pd.DataFrame:
    """行业映射：直接用最新一期业绩报表自带的"所处行业"（一次调用）"""
    fin = fetch_financial_quarterly(start_year=datetime.now().year)
    if len(fin) == 0 or "sector" not in fin.columns:
        return pd.DataFrame(columns=["code", "sector"])
    latest = fin.sort_values("date").groupby("code").tail(1)
    out = latest[["code", "sector"]].dropna(subset=["sector"])
    return out.drop_duplicates("code").reset_index(drop=True)


def fetch_current_valuation() -> pd.DataFrame:
    """当前估值快照（全市场一次调用），返回 code/pe/pb/total_mv/close/pct"""
    import akshare as ak
    df = ak.stock_zh_a_spot_em()
    if df is None or len(df) == 0:
        return pd.DataFrame()
    cols = {str(c).strip(): c for c in df.columns}
    def col(*names):
        for n in names:
            if n in cols:
                return cols[n]
        return None
    out = pd.DataFrame({
        "code": df[col("代码")].astype(str).str.zfill(6),
        "pe": pd.to_numeric(df[col("市盈率-动态", "市盈率")], errors="coerce"),
        "pb": pd.to_numeric(df[col("市净率")], errors="coerce"),
        "total_mv": pd.to_numeric(df[col("总市值")], errors="coerce"),
        "close": pd.to_numeric(df[col("最新价", "收盘价")], errors="coerce"),
        "pct": pd.to_numeric(df[col("涨跌幅")], errors="coerce"),
    })
    return out.dropna(subset=["code"])


def fetch_index(symbol: str = "000300",
                start_date: str = "20180101") -> pd.DataFrame:
    """指数日线，返回 date/close"""
    import akshare as ak
    df = ak.index_zh_a_hist(symbol=symbol, period="daily",
                            start_date=start_date,
                            end_date=datetime.now().strftime("%Y%m%d"))
    if df is None or len(df) == 0:
        return pd.DataFrame()
    cols = {str(c).strip(): c for c in df.columns}
    out = pd.DataFrame({
        "date": pd.to_datetime(df[cols["日期"]]),
        "close": pd.to_numeric(df[cols["收盘"]], errors="coerce"),
    })
    out["code"] = symbol
    return out[["code", "date", "close"]].dropna(subset=["date", "close"])
