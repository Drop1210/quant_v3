"""
阶段 2 自检：因子面板 + 四关检验 + 滚动 IC 加权
"""

import os
import sys
import time

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from config import cfg
from data.data_engine import DataEngine
from factors.library import FACTOR_DEFS, PRICE_FACTORS, FUNDAMENTAL_FACTORS
from factors.panel import build_monthly_panel
from factors.pipeline import run_pipeline
from factors.validation import (monthly_ic, ic_report, grouped_returns,
                                dedup_factors, out_of_sample_check)
from alpha.composite import build_composite


def _bootstrap_cache(engine: DataEngine, src: str, dst: str) -> None:
    """把旧系统缓存复制成 v3 缓存（仅一次）"""
    p = engine._p(dst)
    if not os.path.exists(p):
        df = pd.read_parquet(src)
        engine._save(dst, df)
        print(f"  缓存 {dst}: {df.shape}")


def main() -> None:
    t0 = time.time()

    def tick(tag: str) -> None:
        print(f"  [{time.time() - t0:6.1f}s] {tag}", flush=True)

    print("=" * 56)
    print("QuantV3 阶段 2 自检：因子面板 + 四关检验")
    print("=" * 56)

    engine = DataEngine()
    daily = engine.get_price()
    print(f"\n[1] 日线数据: {len(daily)} 行, {daily['code'].nunique()} 只")

    legacy = r"E:\quant_trader\data_cache"
    _bootstrap_cache(engine, os.path.join(legacy, "sector_cache.parquet"), "sector.parquet")
    _bootstrap_cache(engine, os.path.join(legacy, "valuation_cache.parquet"), "valuation.parquet")
    _bootstrap_cache(engine, os.path.join(legacy, "financial_cache.parquet"), "financial.parquet")
    sector = engine._load("sector.parquet")
    valuation = engine._load("valuation.parquet")
    financial = engine._load("financial.parquet")

    print("\n[2] 构建月度因子面板（价量 + 财务/估值）...")
    panel = build_monthly_panel(daily, valuation, financial)
    tick("月度面板构建完成")
    factor_cols = [c for c in PRICE_FACTORS + FUNDAMENTAL_FACTORS if c in panel.columns]
    print(f"   面板: {len(panel)} 行, {panel.index.get_level_values('month').nunique()} 个月, "
          f"{panel.index.get_level_values('code').nunique()} 只")
    print(f"   因子数: {len(factor_cols)}")

    print("\n[3] 预处理：去极值 -> Z-Score -> 行业/市值中性化 ...")
    piped = run_pipeline(panel, factor_cols, sector,
                         winsorize_sigma=cfg.factor.winsorize_sigma,
                         neutralize_enabled=cfg.factor.neutralize)
    tick("预处理完成")

    print("\n[4] 第一关：RankIC / ICIR / t 值")
    ic_long = monthly_ic(piped, factor_cols)
    tick("IC 计算完成")
    rep = ic_report(ic_long, min_months=cfg.factor.min_ic_months, min_t=cfg.factor.min_t_stat)
    show = rep.copy()
    show["因子"] = show["factor"].map(FACTOR_DEFS)
    print(show[["factor", "因子", "months", "ic_mean", "ic_ir", "t", "win_rate", "significant"]]
          .head(20).to_string(index=False))

    print("\n[5] 第二关：分组收益（5 组多空价差）")
    gr = grouped_returns(piped, factor_cols)
    tick("分组收益完成")
    print(gr.head(10).to_string(index=False))

    print("\n[6] 第三关：因子相关性去重")
    kept = dedup_factors(rep, ic_long, max_corr=cfg.factor.max_factor_corr)
    tick("相关性去重完成")
    print(f"   从 {len(rep)} 个候选中去重后保留 {len(kept)} 个：{kept}")

    print("\n[7] 第四关：样本外符号一致性")
    oos = out_of_sample_check(rep, ic_long)
    tick("样本外检验完成")
    sign_ok = oos[oos["sign_ok"]]
    print(f"   样本内/外同号的因子: {len(sign_ok)}/{len(oos)}")
    print(sign_ok.head(10).to_string(index=False))

    print("\n[8] 滚动 IC 加权合成")
    scores, weights = build_composite(
        piped, ic_long, factor_cols,
        ic_lookback=cfg.factor.ic_lookback,
        min_ic_months=cfg.factor.min_ic_months,
        min_t=cfg.factor.min_t_stat,
        sign_stability=cfg.factor.sign_stability)
    tick("合成完成")
    print(f"   有评分的月数: {scores.index.get_level_values('month').nunique()}")
    if len(weights) > 0:
        print("   最近一期权重:")
        for f, w in weights.sort_values(ascending=False).items():
            print(f"     {FACTOR_DEFS.get(f, f)} ({f}) {w * 100:.1f}%")

    out_dir = os.path.join(PROJECT_ROOT, "output")
    os.makedirs(out_dir, exist_ok=True)

    # 缓存中间结果（供回测/报告复用，避免重复计算）
    _save_panel(piped, os.path.join(out_dir, "panel_piped_v3.parquet"))
    _save_panel(ic_long, os.path.join(out_dir, "ic_long_v3.parquet"))
    _save_panel(scores, os.path.join(out_dir, "scores_v3.parquet"))

    with open(os.path.join(out_dir, "factor_report_v3.txt"), "w", encoding="utf-8") as f:
        f.write("=== 因子有效性检验（v3，中性化后）===\n\n")
        f.write(rep.to_string(index=False) + "\n\n")
        f.write("=== 分组收益（5组多空）===\n\n")
        f.write(gr.head(20).to_string(index=False) + "\n\n")
        f.write(f"=== 相关性去重后保留: {kept} ===\n\n")
        f.write("=== 样本外一致性 ===\n\n")
        f.write(oos.to_string(index=False) + "\n")
        if len(weights) > 0:
            f.write("\n=== 最近一期滚动权重 ===\n")
            for k, w in weights.sort_values(ascending=False).items():
                f.write(f"  {k} {w * 100:.1f}%\n")
    print(f"\n[OK] 报告已保存: output/factor_report_v3.txt")


def _save_panel(df: pd.DataFrame, path: str) -> None:
    """MultiIndex(month, code) 面板存成 parquet（Period 转字符串）"""
    d = df.reset_index()
    if "month" in d.columns:
        d["month"] = d["month"].astype(str)
    d.to_parquet(path, index=False)
    print(f"  缓存: {path}")


def load_panel(path: str) -> pd.DataFrame:
    """读取 _save_panel 保存的面板"""
    d = pd.read_parquet(path)
    if "month" in d.columns:
        d["month"] = pd.PeriodIndex(d["month"], freq="M")
    idx_cols = [c for c in ("month", "code") if c in d.columns]
    return d.set_index(idx_cols).sort_index()


if __name__ == "__main__":
    main()
