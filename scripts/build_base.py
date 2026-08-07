"""
一次性任务：下载全部历史成分股（ever-members）日线，重建基础快照
请在 GitHub Actions 的 build-base 工作流中手动触发（美国机房可直连东财，数据质量最好）
"""

import os
import sys
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd

from data import universe
from data.data_engine import DataEngine


def main() -> None:
    eng = DataEngine()
    codes = sorted(c for c in universe.ever_members()
                   if not str(c).startswith("688"))
    print(f"历史成分股: {len(codes)} 只，开始全量下载（约 30~50 分钟）", flush=True)
    df = eng._fetch_many(codes, "20180101",
                         datetime.now().strftime("%Y%m%d"))
    if df is None or len(df) == 0:
        raise SystemExit("下载失败：没有得到任何数据")
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["date"] = pd.to_datetime(df["date"])
    names = {}
    for idx in ("csi300", "csi500"):
        h = universe.history(idx)
        for _, r in h.iterrows():
            digits = "".join(ch for ch in str(r["symbol"]) if ch.isdigit())
            names[digits[-6:]] = str(r["name"])
    df["name"] = df["code"].map(names).fillna("")
    df = (df.drop_duplicates(["code", "date"], keep="last")
            .sort_values(["code", "date"])
            .reset_index(drop=True))
    eng._save("daily.parquet", df)
    size = os.path.getsize(os.path.join(eng.cfg.cache_dir, "daily.parquet")) / 1e6
    print(f"完成: {len(df)} 行, {df['code'].nunique()} 只, {size:.0f}MB", flush=True)


if __name__ == "__main__":
    main()
