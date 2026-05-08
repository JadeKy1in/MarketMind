"""
optimizer.py — Sprint 3: 一键调仓算法（Rebalance Optimizer）

核心算法引擎：
  1. 信念权重评分 — 将 BeliefStateManager 的活跃信念映射到各仓位的加权评分
  2. 漂移检测 — 检测当前仓位 weight 与目标 weight 的差异是否超过阈值
  3. 建议生成 — 输出 RebalanceSuggestion 列表（可被 UI 渲染）

设计原则：
  - 纯函数式：输入 Position[] + BeliefSnapshot[] → RebalanceSuggestion[]
  - 无副作用：不修改任何状态，仅生成建议
  - 可测试：所有逻辑可通过单元测试覆盖

SPARC:
  Specification: V2.0 Sprint 3 — 一键调仓 + 漂移检测
  Pseudocode: positions → belief_weighted_scoring → drift_detection → suggestions
  Architecture: 纯数据变换层，无 I/O
  Refinement: 权重归一化，超额配置惩罚
  Completion: 测试覆盖率 ≥ 85%
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from projects.command_center.models.position import (
    Position,
    RebalanceSuggestion,
    UrgencyLevel,
)

logger = logging.getLogger(__name__)


# ============================================================
# 配置
# ============================================================


@dataclass
class OptimizerConfig:
    """调仓优化器配置。

    Attributes:
        drift_threshold: 漂移触发阈值（权重差异超过此值触发建议，默认 0.03 = 3%）
        max_suggestions: 最大建议数（默认 10）
        min_belief_weight: 最低信念权重（低于此值忽略该信念，默认 0.1）
        default_target_weight: 无信念时的默认目标权重（默认 0.1）
        max_single_position_weight: 单一仓位的最大权重上限（默认 0.3）
        volatility_buffer: 波动率缓冲（超额配置容差，默认 0.02 = 2%）
        cash_weight_floor: 现金仓位的权重地板（默认 0.05 = 5%）
    """
    drift_threshold: float = 0.03
    max_suggestions: int = 10
    min_belief_weight: float = 0.1
    default_target_weight: float = 0.1
    max_single_position_weight: float = 0.3
    volatility_buffer: float = 0.02
    cash_weight_floor: float = 0.05


# ============================================================
# 信念权重映射表（ticker ↔ proposition 映射）
# ============================================================

# 默认的 ticker → proposition 映射关系
# 在真实环境中，这应该来自 config 或 BeliefStateManager 的元数据
DEFAULT_TICKER_BELIEF_MAP: Dict[str, List[str]] = {
    # 大盘指数 ETF
    "SPY": ["macro_us_recession_risk", "sentiment_market_greed"],
    "QQQ": ["sector_tech_outperform", "sentiment_market_greed"],
    "IWM": ["macro_us_recession_risk", "sentiment_market_greed"],
    # 板块 ETF
    "XLF": ["sector_financial_stress", "macro_fed_rate_path"],
    "XLK": ["sector_tech_outperform"],
    "XLV": ["macro_inflation_trend"],
    "XLE": ["sector_energy_weakness"],
    "TLT": ["macro_fed_rate_path", "macro_inflation_trend"],
    "GLD": ["macro_inflation_trend", "macro_us_recession_risk"],
    # 行业代表性
    "AAPL": ["sector_tech_outperform"],
    "MSFT": ["sector_tech_outperform"],
    "TSLA": ["sector_tech_outperform"],
    "JPM": ["sector_financial_stress", "macro_fed_rate_path"],
    "BRK.B": ["sector_financial_stress"],
}


# ============================================================
# DriftRecord
# ============================================================


@dataclass(frozen=True)
class DriftRecord:
    """单个仓位的漂移检测记录。

    Attributes:
        ticker: 标的代码
        current_weight: 当前权重
        target_weight: 目标权重
        drift: 漂移值（current - target）
        exceeds_threshold: 是否超过漂移阈值
        belief_score: 信念加权评分 [0, 1]
    """
    ticker: str
    current_weight: float
    target_weight: float
    drift: float
    exceeds_threshold: bool
    belief_score: float = 0.5


# ============================================================
# OptimizerResult
# ============================================================


@dataclass
class OptimizerResult:
    """调仓优化结果。

    Attributes:
        suggestions: 调仓建议列表
        drifts: 所有仓位的漂移检测记录
        total_portfolio_value: 总市值
        belief_scores: ticker → belief_score 映射
        suggestion_count: 建议数量
        high_urgency_count: 高优先级建议数量
    """
    suggestions: List[RebalanceSuggestion] = field(default_factory=list)
    drifts: List[DriftRecord] = field(default_factory=list)
    total_portfolio_value: float = 0.0
    belief_scores: Dict[str, float] = field(default_factory=dict)
    suggestion_count: int = 0
    high_urgency_count: int = 0

    @property
    def summary(self) -> str:
        return (
            f"OptimizerResult: {self.suggestion_count} suggestions "
            f"({self.high_urgency_count} high urgency), "
            f"portfolio=${self.total_portfolio_value:,.2f}"
        )


# ============================================================
# Optimizer — 调仓优化器
# ============================================================


class Optimizer:
    """一键调仓算法引擎。

    工作流：
      1. compute_belief_scores() — 将 BeliefSnapshot 映射到 ticker 级评分
      2. detect_drifts() — 检测每个仓位的权重漂移
      3. generate_suggestions() — 生成可执行的调仓建议

    用法:
        optimizer = Optimizer()
        result = optimizer.optimize(positions, belief_snapshots)
        for suggestion in result.suggestions:
            print(suggestion.ticker, suggestion.delta_shares)
    """

    def __init__(
        self,
        config: Optional[OptimizerConfig] = None,
        ticker_belief_map: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        """初始化调仓优化器。

        Args:
            config: 配置覆盖
            ticker_belief_map: 自定义 ticker → proposition_id 映射
        """
        self._config = config or OptimizerConfig()
        self._ticker_map = ticker_belief_map or DEFAULT_TICKER_BELIEF_MAP
        logger.info(
            "Optimizer initialized: drift_threshold=%.2f, max_weight=%.2f",
            self._config.drift_threshold,
            self._config.max_single_position_weight,
        )

    # ============================================================
    # 公共 API
    # ============================================================

    def optimize(
        self,
        positions: List[Position],
        belief_snapshots: Optional[List[Any]] = None,
    ) -> OptimizerResult:
        """执行一键调仓计算。

        Args:
            positions: 当前仓位列表
            belief_snapshots: 可选，BeliefSnapshot 列表（来自 BeliefStateManager）

        Returns:
            OptimizerResult: 调仓建议 + 漂移报告
        """
        # Step 1: 计算信念评分
        belief_scores = self.compute_belief_scores(belief_snapshots)

        # Step 2: 计算总市值
        total_value = sum(p.market_value for p in positions if p.status == "ACTIVE")
        if total_value <= 0:
            total_value = 1.0  # 防止除零

        # Step 3: 计算每个仓位的目标权重
        target_weights = self._compute_target_weights(positions, belief_scores)

        # Step 4: 漂移检测
        drifts = self._detect_drifts(positions, target_weights, total_value)

        # Step 5: 生成建议
        suggestions = self._generate_suggestions(positions, drifts, belief_scores, total_value)

        # Step 6: 统计
        high_count = sum(
            1 for s in suggestions if s.urgency == UrgencyLevel.HIGH
        )

        return OptimizerResult(
            suggestions=suggestions,
            drifts=drifts,
            total_portfolio_value=total_value,
            belief_scores={p.ticker: belief_scores.get(p.ticker, 0.5) for p in positions},
            suggestion_count=len(suggestions),
            high_urgency_count=high_count,
        )

    # ============================================================
    # Step 1: 信念加权评分
    # ============================================================

    def compute_belief_scores(
        self,
        belief_snapshots: Optional[List[Any]],
    ) -> Dict[str, float]:
        """将 BeliefSnapshot 列表转换为 ticker 级信念评分。

        Args:
            belief_snapshots: BeliefSnapshot 列表（来自 BeliefStateManager）

        Returns:
            Dict[ticker, score]: 每个 ticker 的综合信念评分 [0, 1]
        """
        # 如果没有提供信念数据，返回默认评分
        if not belief_snapshots:
            return {}

        # 构建 proposition_id → score 的查找表
        prop_scores: Dict[str, float] = {}
        for snap in belief_snapshots:
            score = self._safe_get(snap, "score", 0.5)
            prop_id = self._safe_get(snap, "proposition_id", "")
            if prop_id:
                prop_scores[prop_id] = float(score)

        # 将命题评分映射到 ticker
        ticker_scores: Dict[str, float] = {}
        for ticker, prop_ids in self._ticker_map.items():
            scores = [prop_scores.get(pid, 0.5) for pid in prop_ids]
            # 取平均分（所有相关命题的综合评分）
            avg_score = sum(scores) / len(scores) if scores else 0.5
            ticker_scores[ticker] = avg_score

        return ticker_scores

    # ============================================================
    # Step 2: 目标权重计算
    # ============================================================

    def _compute_target_weights(
        self,
        positions: List[Position],
        belief_scores: Dict[str, float],
    ) -> Dict[str, float]:
        """计算每个仓位的最优目标权重。

        算法：
          1. 活跃仓位按 belief_score 比例分配权重
          2. 无信念的仓位使用 default_target_weight
          3. 权重归一化确保总和为 1.0
          4. 受 max_single_position_weight 约束

        Args:
            positions: 仓位列表
            belief_scores: ticker → score 映射

        Returns:
            Dict[ticker, target_weight]: 建议权重
        """
        active_positions = [p for p in positions if p.status == "ACTIVE"]
        if not active_positions:
            return {}

        raw_weights: Dict[str, float] = {}

        for pos in active_positions:
            score = belief_scores.get(pos.ticker, self._config.default_target_weight)
            # 使用信心权重 + 原始 target_weight 的混合
            blended = (score * 0.7 + pos.target_weight * 0.3)
            raw_weights[pos.ticker] = max(
                self._config.cash_weight_floor,
                min(self._config.max_single_position_weight, blended),
            )

        # 归一化
        total_raw = sum(raw_weights.values())
        if total_raw <= 0:
            return {p.ticker: self._config.default_target_weight for p in active_positions}

        normalized: Dict[str, float] = {
            ticker: w / total_raw for ticker, w in raw_weights.items()
        }
        return normalized

    # ============================================================
    # Step 3: 漂移检测
    # ============================================================

    def _detect_drifts(
        self,
        positions: List[Position],
        target_weights: Dict[str, float],
        total_value: float,
    ) -> List[DriftRecord]:
        """检测仓位权重漂移。

        Args:
            positions: 仓位列表
            target_weights: 目标权重字典
            total_value: 总市值

        Returns:
            List[DriftRecord]: 漂移检测记录
        """
        drifts: List[DriftRecord] = []

        for pos in positions:
            if pos.status != "ACTIVE":
                continue

            current_w = pos.current_weight
            target_w = target_weights.get(pos.ticker, pos.target_weight)
            drift = current_w - target_w
            exceeds = abs(drift) > self._config.drift_threshold

            drifts.append(DriftRecord(
                ticker=pos.ticker,
                current_weight=round(current_w, 4),
                target_weight=round(target_w, 4),
                drift=round(drift, 4),
                exceeds_threshold=exceeds,
            ))

        # 按漂移绝对值降序排列
        drifts.sort(key=lambda d: abs(d.drift), reverse=True)
        return drifts

    # ============================================================
    # Step 4: 建议生成
    # ============================================================

    def _generate_suggestions(
        self,
        positions: List[Position],
        drifts: List[DriftRecord],
        belief_scores: Dict[str, float],
        total_value: float,
    ) -> List[RebalanceSuggestion]:
        """根据漂移检测结果生成调仓建议。

        Args:
            positions: 仓位列表
            drifts: 漂移记录
            belief_scores: 信念评分
            total_value: 总市值

        Returns:
            List[RebalanceSuggestion]: 调仓建议
        """
        # 构建 position 查找表
        pos_map = {p.ticker: p for p in positions}
        suggestions: List[RebalanceSuggestion] = []

        for drift in drifts:
            if not drift.exceeds_threshold:
                continue

            pos = pos_map.get(drift.ticker)
            if pos is None:
                continue

            # 计算需要买卖的股数
            # target_value = total_value * drift.target_weight
            # 需要调整到 target_value，delta = target_value - current_value
            target_value = total_value * drift.target_weight
            current_value = pos.market_value
            value_delta = target_value - current_value

            # 转换为股数
            if pos.current_price > 0:
                delta_shares = round(value_delta / pos.current_price, 2)
            else:
                delta_shares = 0.0

            # 确定紧急程度
            abs_drift = abs(drift.drift)
            if abs_drift > 0.10:
                urgency = UrgencyLevel.HIGH
            elif abs_drift > 0.05:
                urgency = UrgencyLevel.MEDIUM
            else:
                urgency = UrgencyLevel.LOW

            # 构建信念命题描述
            belief_weight = belief_scores.get(drift.ticker, 0.5)
            prop_ids = self._ticker_map.get(drift.ticker, [])
            prop_desc = "; ".join(prop_ids) if prop_ids else "no specific belief"

            # 生成简短原因
            direction = "加仓" if delta_shares > 0 else "减仓"
            reason_short = (
                f"{direction} {abs(drift.drift)*100:.1f}% 权重漂移 "
                f"(目标 {drift.target_weight*100:.1f}%, "
                f"当前 {drift.current_weight*100:.1f}%)"
            )

            suggestion = RebalanceSuggestion(
                ticker=drift.ticker,
                asset_name=pos.asset_name,
                from_weight=drift.current_weight,
                to_weight=drift.target_weight,
                delta_shares=delta_shares,
                belief_weight=belief_weight,
                belief_proposition=prop_desc,
                narrative=(
                    f"信念评分 {belief_weight:.2f} 触发调仓信号: "
                    f"从 {drift.current_weight*100:.1f}% 调整至 "
                    f"{drift.target_weight*100:.1f}%"
                ),
                urgency=urgency,
                reason_short=reason_short,
            )
            suggestions.append(suggestion)

            # 限制建议数量
            if len(suggestions) >= self._config.max_suggestions:
                break

        return suggestions

    # ============================================================
    # 工具
    # ============================================================

    @staticmethod
    def _safe_get(obj: Any, key: str, default: Any = None) -> Any:
        """安全从对象或 dict 中获取属性。"""
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)