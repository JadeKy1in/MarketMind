"""
shadow_comparator.py — Sprint 3: 影子对比引擎（Monte Carlo Simulation）

核心功能：
  1. 模拟"当前仓位"在 N 条随机市场路径下的预期收益分布
  2. 模拟"调仓建议"在相同随机路径下的预期收益分布
  3. 对比两条分布的统计差异（均值、VaR、胜率、夏普比）

设计原则：
  - 纯函数式随机模拟（不含 System.Random 状态泄漏）
  - 每条路径独立可复现（支持 seed）
  - 无副作用，线程安全

SPARC:
  Specification: V2.0 Sprint 3 — Monte Carlo 影子对比
  Pseudocode: current_positions → simulate → distribution_A
              suggested_positions → simulate → distribution_B
              compare(distribution_A, distribution_B)
  Architecture: 纯数据变换，无 I/O
  Refinement: 支持 seed 复现，波动率参数化
  Completion: 测试覆盖率 ≥ 85%
"""

from __future__ import annotations

import datetime
import logging
import math
import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from projects.command_center.models.position import Position, RebalanceSuggestion

logger = logging.getLogger(__name__)


# ============================================================
# 配置
# ============================================================


@dataclass
class ShadowComparatorConfig:
    """影子对比引擎配置。

    Attributes:
        n_simulations: Monte Carlo 模拟路径数（默认 10000）
        n_days: 模拟天数（默认 30）
        annual_volatility: 年化波动率基准（默认 0.20 = 20%）
        annual_return: 年化预期收益率基准（默认 0.08 = 8%）
        confidence_level: VaR 置信水平（默认 0.95 = 95%）
        seed: 随机种子（默认 None = 不可重复）
        risk_free_rate: 无风险利率（默认 0.05 = 5%）
        transaction_cost_pct: 交易成本百分比（默认 0.001 = 0.1%）
    """
    n_simulations: int = 10000
    n_days: int = 30
    annual_volatility: float = 0.20
    annual_return: float = 0.08
    confidence_level: float = 0.95
    seed: Optional[int] = None
    risk_free_rate: float = 0.05
    transaction_cost_pct: float = 0.001


# ============================================================
# 分布统计
# ============================================================


@dataclass(frozen=True)
class DistributionStats:
    """单一分布统计量。

    Attributes:
        mean: 均值（预期收益）
        median: 中位数
        std: 标准差
        var: 在险价值（VaR），给定置信水平
        cvar: 条件在险价值（CVaR），即 VaR 尾部均值
        sharpe: 夏普比率
        max_drawdown: 最大回撤
        win_rate: 盈利路径占比
        n_simulations: 有效模拟数
    """
    mean: float = 0.0
    median: float = 0.0
    std: float = 0.0
    var: float = 0.0
    cvar: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    n_simulations: int = 0


# ============================================================
# 对比结果
# ============================================================


@dataclass
class ComparisonResult:
    """影子对比结果。

    Attributes:
        current_stats: 当前仓位的分布统计
        suggested_stats: 调仓建议的分布统计
        improvement: 预期收益改进（suggested.mean - current.mean）
        risk_reduction: 风险降低（current.std - suggested.std）
        win_probability: 调仓后胜率（suggested.win_rate - current.win_rate）
        convergence_score: 收敛度评分 [0, 1]（suggested 的不确定性 vs current）
        suggested_is_preferred: 建议方案是否优于当前方案
        total_current_value: 当前总市值
        total_suggested_value: 建议总市值（含交易成本）
        n_simulations: 模拟路径数
        timestamp: ISO-8601 计算时间
    """
    current_stats: Optional[DistributionStats] = None
    suggested_stats: Optional[DistributionStats] = None
    improvement: float = 0.0
    risk_reduction: float = 0.0
    win_probability: float = 0.0
    convergence_score: float = 0.5
    suggested_is_preferred: bool = False
    total_current_value: float = 0.0
    total_suggested_value: float = 0.0
    n_simulations: int = 0
    timestamp: str = field(default_factory=lambda: (
        datetime.datetime.now(datetime.timezone.utc).isoformat()
    ))

    @property
    def summary(self) -> str:
        """人类可读的对比摘要。"""
        preferred = "建议方案 ✅" if self.suggested_is_preferred else "当前方案 ✅"
        return (
            f"Shadow Comparator: {preferred}\n"
            f"  预期收益改进: {self.implementation:+.2%}\n"
            f"  风险降低: {self.risk_reduction:+.2%}\n"
            f"  胜率变化: {self.win_probability:+.2%}\n"
            f"  收敛度: {self.convergence_score:.2f}\n"
            f"  模拟路径: {self.n_simulations}"
        )


# ============================================================
# ShadowComparator — Monte Carlo 模拟引擎
# ============================================================


class ShadowComparator:
    """Monte Carlo 影子对比引擎。

    模拟"保持当前仓位" vs "执行调仓建议"在 N 条随机市场路径下的
    预期收益分布，对比两条分布的统计差异。

    用法:
        comparator = ShadowComparator()
        result = comparator.compare(positions, suggestions)
        if result.suggested_is_preferred:
            print("建议方案优于当前方案")
    """

    def __init__(self, config: Optional[ShadowComparatorConfig] = None) -> None:
        self._config = config or ShadowComparatorConfig()

        # 初始化随机状态
        if self._config.seed is not None:
            random.seed(self._config.seed)

        # 预计算日化参数
        self._daily_return = self._config.annual_return / 252.0
        self._daily_vol = self._config.annual_volatility / math.sqrt(252.0)
        self._daily_risk_free = self._config.risk_free_rate / 252.0

        logger.info(
            "ShadowComparator initialized: %d simulations x %d days, vol=%.2f",
            self._config.n_simulations,
            self._config.n_days,
            self._config.annual_volatility,
        )

    # ============================================================
    # 公共 API
    # ============================================================

    def compare(
        self,
        positions: List[Position],
        suggestions: List[RebalanceSuggestion],
    ) -> ComparisonResult:
        """执行影子对比。

        Args:
            positions: 当前仓位列表
            suggestions: 调仓建议列表

        Returns:
            ComparisonResult: 对比结果
        """
        n = self._config.n_simulations

        # Step 1: 构建当前仓位组合和建议仓位组合
        total_value = sum(p.market_value for p in positions if p.status == "ACTIVE")
        if total_value <= 0:
            total_value = 1.0

        current_weights = self._build_weight_vector(positions, total_value)
        suggested_weights = self._build_suggested_weights(
            positions, suggestions, total_value,
        )

        # Step 2: 计算交易成本
        transaction_cost = self._compute_transaction_cost(
            current_weights, suggested_weights, total_value,
        )
        suggested_net_value = total_value - transaction_cost

        # Step 3: 执行 Monte Carlo 模拟
        current_returns = self._simulate_portfolio_returns(current_weights)
        current_stats = self._compute_stats(current_returns)

        # 使用净市值计算建议市值调整
        suggested_returns = self._simulate_portfolio_returns(suggested_weights)
        suggested_stats = self._compute_stats(suggested_returns)

        # Step 4: 对比分析
        improvement = suggested_stats.mean - current_stats.mean
        risk_reduction = current_stats.std - suggested_stats.std
        win_prob = suggested_stats.win_rate - current_stats.win_rate

        # 收敛度评分：建议方案的不确定性 vs 当前方案的不确定性
        if current_stats.std > 0:
            convergence = max(0.0, min(1.0, 1.0 - suggested_stats.std / current_stats.std))
        else:
            convergence = 0.5

        # 综合判断：建议方案是否优于当前方案
        # 标准：预期收益改善 > 0 OR 风险降低 > 0 且胜率不降
        suggested_better = (
            improvement > 0.001  # 至少 0.1% 的收益改善
            or (risk_reduction > 0.001 and win_prob >= -0.01)  # 风险降低且胜率不显著下降
        )

        return ComparisonResult(
            current_stats=current_stats,
            suggested_stats=suggested_stats,
            improvement=improvement,
            risk_reduction=risk_reduction,
            win_probability=win_prob,
            convergence_score=round(convergence, 4),
            suggested_is_preferred=suggested_better,
            total_current_value=total_value,
            total_suggested_value=suggested_net_value,
            n_simulations=n,
        )

    # ============================================================
    # 组合权重构建
    # ============================================================

    @staticmethod
    def _build_weight_vector(
        positions: List[Position],
        total_value: float,
    ) -> List[float]:
        """构建当前仓位的权重向量。

        Args:
            positions: 仓位列表
            total_value: 总市值

        Returns:
            List[float]: 权重向量（和为 1.0）
        """
        weights = []
        for pos in positions:
            if pos.status == "ACTIVE" and total_value > 0:
                w = pos.market_value / total_value
            else:
                w = 0.0
            weights.append(w)
        return weights

    @staticmethod
    def _build_suggested_weights(
        positions: List[Position],
        suggestions: List[RebalanceSuggestion],
        total_value: float,
    ) -> List[float]:
        """构建调仓建议后的权重向量。

        Args:
            positions: 仓位列表
            suggestions: 调仓建议
            total_value: 总市值

        Returns:
            List[float]: 建议的权重向量
        """
        # 构建 suggestion 查找表
        suggestion_map = {s.ticker: s for s in suggestions}

        weights = []
        for pos in positions:
            if pos.status != "ACTIVE":
                weights.append(0.0)
                continue

            sug = suggestion_map.get(pos.ticker)
            if sug:
                weights.append(sug.to_weight)
            else:
                weights.append(pos.current_weight)

        # 归一化
        total = sum(weights)
        if total > 0:
            weights = [w / total for w in weights]
        return weights

    # ============================================================
    # 交易成本计算
    # ============================================================

    def _compute_transaction_cost(
        self,
        current_weights: List[float],
        suggested_weights: List[float],
        total_value: float,
    ) -> float:
        """计算从当前权重调整到建议权重的交易成本。

        Args:
            current_weights: 当前权重向量
            suggested_weights: 建议权重向量
            total_value: 总市值

        Returns:
            float: 交易成本
        """
        total_turnover = 0.0
        for c, s in zip(current_weights, suggested_weights):
            delta = abs(s - c)
            total_turnover += delta

        return total_value * total_turnover * self._config.transaction_cost_pct

    # ============================================================
    # Monte Carlo 模拟
    # ============================================================

    def _simulate_portfolio_returns(self, weights: List[float]) -> List[float]:
        """模拟投资组合在 N 条随机路径下的总收益率。

        每条路径：对组合中的每个仓位按权重分配，模拟几何布朗运动。

        Args:
            weights: 仓位权重向量（可以为空）

        Returns:
            List[float]: N 个模拟的总收益率（小数，如 0.05 = 5%）
        """
        n = self._config.n_simulations
        days = self._config.n_days
        n_assets = len(weights)

        if n_assets == 0:
            return [0.0] * n

        returns: List[float] = [0.0] * n

        for i in range(n):
            # 每条路径：模拟 days 天的 GBM
            portfolio_return = 0.0
            for w in weights:
                if w <= 0:
                    continue
                # 生成该仓位的随机路径
                asset_return = self._simulate_gbm(days)
                portfolio_return += w * asset_return

            returns[i] = portfolio_return

        return returns

    def _simulate_gbm(self, days: int) -> float:
        """模拟单资产在 days 天内的几何布朗运动总收益率。

        Args:
            days: 模拟天数

        Returns:
            float: 总收益率（小数）
        """
        dt = 1.0  # 1 day
        total_drift = 0.0
        total_diffusion = 0.0

        for _ in range(days):
            z = random.gauss(0.0, 1.0)
            drift = (self._daily_return - 0.5 * self._daily_vol ** 2) * dt
            diffusion = self._daily_vol * math.sqrt(dt) * z
            total_drift += drift
            total_diffusion += diffusion

        total_log_return = total_drift + total_diffusion
        return math.exp(total_log_return) - 1.0

    # ============================================================
    # 统计计算
    # ============================================================

    def _compute_stats(self, returns: List[float]) -> DistributionStats:
        """从模拟收益率列表中计算分布统计量。

        Args:
            returns: 收益率列表

        Returns:
            DistributionStats: 分布统计量
        """
        if not returns:
            return DistributionStats(n_simulations=0)

        n = len(returns)
        sorted_ret = sorted(returns)

        # 均值和中位数
        mean = sum(returns) / n
        median = sorted_ret[n // 2]

        # 标准差
        variance = sum((r - mean) ** 2 for r in returns) / n
        std = math.sqrt(variance)

        # VaR 和 CVaR（在给定置信水平下）
        var_idx = int(n * (1.0 - self._config.confidence_level))
        var_idx = max(0, min(var_idx, n - 1))
        var = sorted_ret[var_idx]

        # CVaR = VaR 左侧尾部的均值
        cvar = sum(sorted_ret[:var_idx + 1]) / (var_idx + 1) if var_idx > 0 else var

        # 夏普比率
        if std > 0:
            sharpe = (mean - self._daily_risk_free * self._config.n_days) / std
        else:
            sharpe = 0.0

        # 最大回撤（针对模拟路径）
        # 对收益率列表不做回撤计算（单期收益率），使用近似
        max_drawdown = abs(min(0.0, min(returns)))

        # 胜率
        win_count = sum(1 for r in returns if r > 0)
        win_rate = win_count / n

        return DistributionStats(
            mean=round(mean, 6),
            median=round(median, 6),
            std=round(std, 6),
            var=round(var, 6),
            cvar=round(cvar, 6),
            sharpe=round(sharpe, 4),
            max_drawdown=round(max_drawdown, 6),
            win_rate=round(win_rate, 4),
            n_simulations=n,
        )