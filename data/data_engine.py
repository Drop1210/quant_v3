"""
数据引擎（Data Engine）

统一数据 API，所有上层模块只通过这里拿数：
  get_price() / get_financial() / get_valuation() / get_universe()

特性：
  - 增量更新：历史不重下，只补最近几天
  - 多源容错：东财 -> 腾讯 -> 新浪，逐个尝试
  - 点对点股票池：见 universe.py
"""

import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from typing import List, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from config import cfg
from data import universe


def _log(msg: str) -> None:
    print(f"[data] {msg}", flush=True)


def _normalize_history(raw: pd.DataFrame, code: str) -> pd.DataFrame:
    """把不同数据源返回的行情归一化为统一 schema"""
    if raw is None or len(raw) == 0:
        return pd.DataFrame()
    df = raw.copy()
    col_map = {}
    for c in df.columns:
        c_l = str(c).lower()
        if "date" in c_l or "日期" in str(c):
            col_map[c] = "date"
        elif c_l in ("open", "开盘"):
            col_map[c] = "open"
        elif c_l in ("high", "最高"):
            col_map[c] = "high"
        elif c_l in ("low", "最低"):
            col_map[c] = "low"
        elif c_l in ("close", "收盘"):
            col_map[c] = "close"
        elif c_l in ("volume", "成交量"):
            col_map[c] = "volume"
        elif c_l in ("amount", "成交额"):
            col_map[c] = "amount"
        elif "turnover" in c_l or "换手" in str(c):
            col_map[c] = "turnover"
    df = df.rename(columns=col_map)
    keep = [c for c in ("date", "open", "high", "low", "close", "volume", "amount", "turnover") if c in df.columns]
    df = df[keep].copy()
    if "date" not in df.columns or "close" not in df.columns:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "high", "low", "close", "volume", "amount", "turnover"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["code"] = str(code).zfill(6)
    df = df.dropna(subset=["date", "close"]).drop_duplicates("date")
    return df[["code", "date", "open", "high", "low", "close", "volume", "amount", "turnover"]]


def _fetch_one(args) -> Optional[pd.DataFrame]:
    """单只股票多源抓取（模块级函数，供多进程使用）"""
    code, start, end = args
    try:
        import akshare as ak
    except Exception:
        return None
    attempts = []
    try:
        attempts.append(("eastmoney", ak.stock_zh_a_hist(
            symbol=code, period="daily",
            start_date=start, end_date=end, adjust="qfq")))
    except Exception:
        pass
    if not attempts or attempts[-1][1] is None or len(attempts[-1][1]) == 0:
        try:
            attempts.append(("tencent", ak.stock_zh_a_hist_tx(
                symbol=code, start_date=start, end_date=end, adjust="qfq")))
        except Exception:
            pass
    if not attempts or attempts[-1][1] is None or len(attempts[-1][1]) == 0:
        try:
            attempts.append(("sina", ak.stock_zh_a_daily(
                symbol=code, start_date=start, end_date=end, adjust="qfq")))
        except Exception:
            pass
    for name, raw in attempts:
        df = _normalize_history(raw, code)
        if len(df) > 0:
            df.attrs["source"] = name
            return df
    return None


class DataEngine:
    def __init__(self, config=None):
        self.cfg = config or cfg.data
        os.makedirs(self.cfg.cache_dir, exist_ok=True)

    # ---------------- 存储 ----------------
    def _p(self, name: str) -> str:
        return os.path.join(self.cfg.cache_dir, name)

    def _load(self, name: str) -> Optional[pd.DataFrame]:
        p = self._p(name)
        if not os.path.exists(p):
            return None
        try:
            return pd.read_parquet(p)
        except Exception:
            return None

    def _save(self, name: str, df: pd.DataFrame) -> None:
        p = self._p(name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        df.to_parquet(p, index=False)

    # ---------------- 统一 API ----------------
    def get_price(self, code: Optional[List[str]] = None,
                  start=None, end=None) -> pd.DataFrame:
        df = self._load("daily.parquet")
        if df is None or len(df) == 0:
            return pd.DataFrame()
        if code:
            df = df[df["code"].isin(code)]
        if start:
            df = df[df["date"] >= pd.Timestamp(start)]
        if end:
            df = df[df["date"] <= pd.Timestamp(end)]
        return df.sort_values(["code", "date"]).reset_index(drop=True)

    def get_financial(self, codes: Optional[List[str]] = None) -> pd.DataFrame:
        df = self._load("financial.parquet")
        if df is None or len(df) == 0:
            return pd.DataFrame()
        if codes:
            df = df[df["code"].isin(codes)]
        return df

    def get_valuation(self, codes: Optional[List[str]] = None) -> pd.DataFrame:
        df = self._load("valuation.parquet")
        if df is None or len(df) == 0:
            return pd.DataFrame()
        if codes:
            df = df[df["code"].isin(codes)]
        return df

    def get_universe(self, date=None) -> pd.DataFrame:
        """点对点股票池（默认 hs300+zz500 并集）"""
        return universe.pool_at(date=date, pool=self.cfg.stock_pool)

    # ---------------- 数据构建 ----------------
    def bootstrap_from_legacy(self, legacy_path: str) -> pd.DataFrame:
        """从旧系统缓存一次性导入历史日线，避免重下 8 年数据"""
        _log(f"从旧缓存导入: {legacy_path}")
        df = pd.read_parquet(legacy_path)
        keep = ["code", "name", "date", "open", "high", "low", "close",
                "volume", "amount", "turnover"]
        df = df[[c for c in keep if c in df.columns]].copy()
        df["code"] = df["code"].astype(str).str.zfill(6)
        df["date"] = pd.to_datetime(df["date"])
        df = df.drop_duplicates(["code", "date"], keep="last")
        df = df.sort_values(["code", "date"]).reset_index(drop=True)
        self._save("daily.parquet", df)
        _log(f"导入完成: {len(df)} 行, {df['code'].nunique()} 只, "
             f"{df['date'].min():%Y-%m-%d} ~ {df['date'].max():%Y-%m-%d}")
        return df

    def update(self, incremental: bool = True) -> pd.DataFrame:
        """增量/全量更新日线数据"""
        daily = self._load("daily.parquet")
        today = datetime.now().strftime("%Y%m%d")

        # 需要数据的股票 = 最新成分股 ∪ 历史上曾是成分股的股票 ∪ 缓存已有股票
        codes = set()
        try:
            codes |= set(self.get_universe(date=None)["code"])
            codes |= universe.ever_members()
        except Exception:
            pass
        if incremental and daily is not None and len(daily) > 0:
            codes |= set(daily["code"].unique())

        if not codes:
            codes = set(self.get_universe(date=None)["code"])
        codes = sorted(c for c in codes if not (self.cfg.exclude_star and str(c).startswith("688")))
        _log(f"股票池: {len(codes)} 只")

        if daily is None or len(daily) == 0:
            _log("首次全量下载，请耐心等待...")
            new = self._fetch_many(codes, self.cfg.start_date, today)
            daily = new
        elif not incremental:
            _log("全量重下...")
            daily = self._fetch_many(codes, self.cfg.start_date, today)
        else:
            latest = daily["date"].max()
            today_ts = pd.Timestamp(datetime.now().date())
            if latest >= today_ts:
                _log(f"数据已是最新（{latest:%Y-%m-%d}），跳过")
                return daily
            start = (latest - pd.Timedelta(days=10)).strftime("%Y%m%d")
            _log(f"增量下载 {start} ~ {today} ...")
            new = self._fetch_many(codes, start, today)
            if new is not None and len(new) > 0:
                daily = pd.concat([daily, new], ignore_index=True)
                daily = daily.drop_duplicates(["code", "date"], keep="last")
                daily = daily.sort_values(["code", "date"]).reset_index(drop=True)

        if daily is not None and len(daily) > 0:
            daily["code"] = daily["code"].astype(str).str.zfill(6)
            daily["date"] = pd.to_datetime(daily["date"])
            # 增量新行可能没有股票名：补上（用最新成分股名称）
            if "name" not in daily.columns or daily["name"].isna().any() \
                    or (daily["name"].astype(str).str.strip() == "").any():
                if "name" not in daily.columns:
                    daily["name"] = ""
                daily["name"] = daily["name"].replace("", np.nan)
                try:
                    uni = self.get_universe(date=None)
                    nm = uni.set_index("code")["name"]
                    daily["name"] = daily["name"].fillna(daily["code"].map(nm))
                except Exception:
                    pass
                daily["name"] = daily["name"].fillna("")
            self._save("daily.parquet", daily)
            _log(f"保存完成: {len(daily)} 行, {daily['code'].nunique()} 只")
        return daily

    def _fetch_many(self, codes: List[str], start: str, end: str) -> pd.DataFrame:
        args_list = [(c, start, end) for c in codes]
        all_dfs = []
        try:
            import multiprocessing
            n_workers = min(multiprocessing.cpu_count(), len(codes), 8)
            with ProcessPoolExecutor(max_workers=n_workers) as ex:
                for fut in as_completed([ex.submit(_fetch_one, a) for a in args_list]):
                    df = fut.result()
                    if df is not None and len(df) > 0:
                        all_dfs.append(df)
        except Exception as e:
            _log(f"多进程下载失败，降级单线程: {e}")
            for a in args_list:
                df = _fetch_one(a)
                if df is not None and len(df) > 0:
                    all_dfs.append(df)
        if not all_dfs:
            return pd.DataFrame()
        return pd.concat(all_dfs, ignore_index=True)
