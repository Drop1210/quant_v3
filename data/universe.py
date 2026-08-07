"""
点对点（point-in-time）股票池

数据内置自 unliftedq/index-constitution（MIT License）：
  universe_data/history/csi300.csv、csi500.csv —— 每只股票入池/出池日期
  universe_data/latest/  —— 最新成分

作用：避免两类回测偏差
  1. 幸存者偏差：用"今天的成分股"回测过去 = 穿越回去买后来才入选的股票
  2. 前视偏差：在股票入选指数之前就"买入"它
"""

import os
from typing import Optional, Set

import pandas as pd

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "universe_data")
INDICES = ("csi300", "csi500")


def _read_csv(flavor: str, index: str) -> pd.DataFrame:
    path = os.path.join(_DATA_DIR, flavor, f"{index}.csv")
    df = None
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            df = pd.read_csv(path, encoding=enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if df is None:
        df = pd.read_csv(path, encoding="utf-8", errors="replace")
    df.columns = [str(c).strip().lower().replace("-", "_") for c in df.columns]
    return df


def _norm(raw) -> str:
    """'SZ000001' -> '000001'"""
    s = str(raw).strip().upper()
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits[-6:] if len(digits) >= 6 else digits.zfill(6)


def _to_frame(df: pd.DataFrame, index: Optional[str] = None) -> pd.DataFrame:
    out = pd.DataFrame({
        "code": df["symbol"].map(_norm),
        "name": df["name"].astype(str),
    })
    if index:
        out["index"] = index
    return out.drop_duplicates("code").reset_index(drop=True)


def available() -> bool:
    return os.path.isdir(_DATA_DIR)


def latest(index: str = "csi300") -> pd.DataFrame:
    """最新成分股"""
    return _to_frame(_read_csv("latest", index), index)


def history(index: str = "csi300") -> pd.DataFrame:
    """完整入退成分历史（含 opt_in / opt_out 日期）"""
    df = _read_csv("history", index)
    df["opt_in"] = pd.to_datetime(df["opt_in"], errors="coerce")
    df["opt_out"] = pd.to_datetime(df["opt_out"], errors="coerce")
    return df


def constituents_at(index: str, date) -> pd.DataFrame:
    """某一天的成分股（严格点对点，不含前视）"""
    h = history(index)
    ts = pd.Timestamp(date).normalize()
    mask = (h["opt_in"].notna() & (h["opt_in"] <= ts)
            & (h["opt_out"].isna() | (h["opt_out"] > ts)))
    return _to_frame(h.loc[mask], index)


def pool_at(date=None, pool: str = "hs300+zz500") -> pd.DataFrame:
    """组合股票池在某一日的点对点成分（沪深300 + 中证500 并集）"""
    frames = [latest(i) if date is None else constituents_at(i, date)
              for i in INDICES]
    return (pd.concat(frames, ignore_index=True)
            .drop_duplicates("code", keep="first")
            .reset_index(drop=True))


def ever_members(pool: str = "hs300+zz500") -> Set[str]:
    """历史上曾进入过该股票池的所有代码（决定需要下载哪些股票的数据）"""
    codes: Set[str] = set()
    for i in INDICES:
        codes |= set(history(i)["symbol"].map(_norm))
    return codes
