"""
QuantV3 配置
按 8 模块架构拆分：data / factors / alpha / portfolio / risk / backtest / execution / dashboard
"""

import os
from dataclasses import dataclass, field

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


@dataclass
class DataConfig:
    """数据引擎配置"""
    cache_dir: str = os.path.join(_PROJECT_DIR, "data_cache")
    start_date: str = "20180101"            # 历史数据起点
    stock_pool: str = "hs300+zz500"         # 点对点成分股（沪深300 + 中证500）
    exclude_star: bool = True               # 排除科创板 688（数据源限制）
    cache_ttl_days: int = 1


@dataclass
class FactorConfig:
    """因子层配置"""
    winsorize_sigma: float = 3.0            # 去极值（MAD/分位数）
    min_ic_months: int = 8                  # IC 检验最少月数
    ic_lookback: int = 18                   # 滚动 IC 加权的回看月数
    min_t_stat: float = 2.0                 # 初筛门槛
    select_t_stat: float = 3.0              # 进组合门槛（Harvey 严格检验）
    sign_stability: float = 0.55            # 符号稳定性下限
    max_factor_corr: float = 0.85           # 因子相关性去重阈值
    neutralize: bool = True                 # 行业/市值中性化


@dataclass
class PortfolioConfig:
    """组合层配置"""
    top_n: int = 40                         # 目标持仓数量（30~50 折中）
    max_single_weight: float = 0.05         # 单票权重上限 5%
    max_industry_weight: float = 0.15       # 行业权重上限 15%
    max_turnover: float = 0.30              # 单次换手上限 30%
    exclude_st: bool = True
    min_listed_days: int = 120              # 排除次新股
    # 小资金版（资金少时的跟单建议）
    small_capital_top: int = 5              # 建议跟几只
    small_capital_budget: float = 10000.0   # 练手仓总预算（元，Top5 每只约2000元）
    small_min_amount: float = 3e7           # 单只最低成交额（元），过滤流动性差的


@dataclass
class BacktestConfig:
    """回测层配置"""
    start_date: str = "20180701"
    end_date: str = ""                      # 空 = 至今
    initial_capital: float = 1_000_000.0
    commission: float = 0.00025             # 双边手续费（万2.5）
    slippage: float = 0.001
    stamp_duty: float = 0.001               # 卖出印花税（千1）
    t_plus_one: bool = True
    limit_up_down: bool = True              # 涨停买不进/跌停卖不出
    rebalance: str = "monthly"


@dataclass
class PushConfig:
    """移动端推送配置（钥匙优先放 push_settings.json，由手机网页设置页维护）"""
    wechat_webhook: str = ""                # 企业微信群机器人
    serverchan_key: str = ""                # Server酱 SendKey
    pushplus_token: str = ""                # PushPlus token
    bark_key: str = ""                      # Bark（iPhone 专用，备用）
    web_token: str = ""                     # 手机网页管理口令
    web_port: int = 8080


@dataclass
class SystemConfig:
    data: DataConfig = field(default_factory=DataConfig)
    factor: FactorConfig = field(default_factory=FactorConfig)
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    push: PushConfig = field(default_factory=PushConfig)


cfg = SystemConfig()
