"""
阶段 1 自检：数据引擎 + 点对点股票池
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from data import universe
from data.data_engine import DataEngine


def main() -> None:
    print("=" * 56)
    print("QuantV3 阶段 1 自检：数据引擎 + 点对点股票池")
    print("=" * 56)

    # 1. 点对点股票池
    print("\n[1] 点对点股票池（index-constitution）")
    print(f"    包可用: {universe.available()}")
    if universe.available():
        latest = universe.latest("csi300")
        print(f"    最新沪深300成分: {len(latest)} 只")
        at2020 = universe.constituents_at("csi300", "2020-06-30")
        print(f"    2020-06-30 沪深300成分: {len(at2020)} 只")
        latest_codes = set(latest["code"])
        old_codes = set(at2020["code"])
        later = sorted(latest_codes - old_codes)
        print(f"    现在是成分、2020年不是的股票（前视偏差样本）: {len(later)} 只")
        print(f"    示例: {later[:5]}")
        for code in ("600519", "000001"):
            if code in old_codes:
                print(f"    校验通过: {code} 在 2020-06-30 成分中")
        pool = universe.pool_at("2020-06-30")
        print(f"    2020-06-30 沪深300+中证500 并集: {len(pool)} 只")
        ever = universe.ever_members()
        print(f"    历史上曾入池的股票总数: {len(ever)} 只")

    # 2. 数据引擎
    print("\n[2] 数据引擎")
    engine = DataEngine()
    legacy = r"E:\quant_trader\data_cache\daily_cache.parquet"
    if os.path.exists(legacy):
        daily = engine.bootstrap_from_legacy(legacy)
        print(f"    最新交易日: {daily['date'].max():%Y-%m-%d}")
        print(f"    最早交易日: {daily['date'].min():%Y-%m-%d}")
        print(f"    股票数量: {daily['code'].nunique()}")
        print(f"    字段: {list(daily.columns)}")
    else:
        print("    未找到旧缓存，跳过导入（首次运行需执行 update() 全量下载）")

    print("\n阶段 1 自检完成。")


if __name__ == "__main__":
    main()
