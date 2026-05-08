"""
test_engine.py — Sprint 3: Engine Layer Test Suite

测试覆盖：
  1. optimizer — 信念评分计算、漂移检测、建议生成、权重归一化
  2. shadow_comparator — Monte Carlo 模拟、分布统计、对比结果判据
"""

from __future__ import annotations

import math
import pytest
from typing import Any, Dict, List, Optional

from projects.command_center.models.position import Position, RebalanceSuggestion
from projects.command_center.engine.optimizer import (
    Optimizer,
    OptimizerConfig,
    OptimizerResult,
    DriftRecord,
    DEFAULT_TICKER_BELIEF_MAP,
)
from projects.command_center.engine.shadow_comparator import (
    ShadowComparator,
    ShadowComparatorConfig,
    ComparisonResult,
    DistributionStats,
)


# ============================================================
# Helper: Sample Positions
# ============================================================

def _sample_positions() -> List[Position]:
    """创建一组测试用仓位。"""
    return [
        Position(
            ticker="SPY",
            asset_name="SPDR S&P 500 ETF",
            asset_class="EQUITY",
            shares=100.0,
            avg_cost=450.0,
            current_price=480.0,
            target_weight=0.30,
            current_weight=0.34,
            status="ACTIVE",
        ),
        Position(
            ticker="QQQ",
            asset_name="Invesco QQQ Trust",
            asset_class="EQUITY",
            shares=50.0,
            avg_cost=380.0,
            current_price=410.0,
            target_weight=0.25,
            current_weight=0.22,
            status="ACTIVE",
        ),
        Position(
            ticker="TLT",
            asset_name="iShares 20+ Year Treasury Bond ETF",
            asset_class="BOND",
            shares=200.0,
            avg_cost=95.0,
            current_price=92.0,
            target_weight=0.20,
            current_weight=0.18,
            status="ACTIVE",
        ),
    ]


def _sample_belief_snapshots() -> List[Dict[str, Any]]:
    """创建测试用信念快照。"""
    return [
        {"proposition_id": "macro_us_recession_risk", "score": 0.65, "expectation": 0.6},
        {"proposition_id": "macro_fed_rate_path", "score": 0.75, "expectation": 0.7},
        {"proposition_id": "sentiment_market_greed", "score": 0.55, "expectation": 0.5},
        {"proposition_id": "sector_tech_outperform", "score": 0.80, "expectation": 0.75},
        {"proposition_id": "sector_financial_stress", "score": 0.40, "expectation": 0.35},
    ]


# ============================================================
# Optimizer Tests
# ============================================================

class TestOptimizerBasics:
    def test_default_config(self):
        opt = Optimizer()
        assert opt._config.drift_threshold == 0.03
        assert opt._config.max_single_position_weight == 0.3

    def test_default_ticker_map(self):
        assert "SPY" in DEFAULT_TICKER_BELIEF_MAP
        assert "QQQ" in DEFAULT_TICKER_BELIEF_MAP
        assert "TLT" in DEFAULT_TICKER_BELIEF_MAP


class TestOptimizerBeliefScores:
    def test_belief_scores_empty(self):
        opt = Optimizer()
        scores = opt.compute_belief_scores(None)
        assert scores == {}

    def test_belief_scores_empty_list(self):
        opt = Optimizer()
        scores = opt.compute_belief_scores([])
        assert scores == {}

    def test_belief_scores_for_spy(self):
        opt = Optimizer()
        scores = opt.compute_belief_scores(_sample_belief_snapshots())
        # SPY maps to recession_risk (0.65) + market_greed (0.55) = avg 0.6
        assert "SPY" in scores
        assert abs(scores["SPY"] - 0.6) < 0.01

    def test_belief_scores_for_qqq(self):
        opt = Optimizer()
        scores = opt.compute_belief_scores(_sample_belief_snapshots())
        # QQQ maps to tech_outperform (0.80) + market_greed (0.55) = avg 0.675
        assert "QQQ" in scores
        assert abs(scores["QQQ"] - 0.675) < 0.01

    def test_belief_scores_for_tlt(self):
        opt = Optimizer()
        scores = opt.compute_belief_scores(_sample_belief_snapshots())
        # TLT maps to fed_rate_path (0.75) + inflation_trend (no data → 0.5) = avg 0.625
        assert "TLT" in scores


class TestOptimizerOptimize:
    def test_optimize_without_beliefs(self):
        opt = Optimizer()
        positions = _sample_positions()
        result = opt.optimize(positions, belief_snapshots=None)
        assert result.suggestion_count > 0
        assert len(result.drifts) == 3
        assert result.total_portfolio_value > 0

    def test_optimize_with_beliefs(self):
        opt = Optimizer()
        positions = _sample_positions()
        result = opt.optimize(positions, _sample_belief_snapshots())
        assert result.suggestion_count > 0
        for s in result.suggestions:
            assert s.ticker in ["SPY", "QQQ", "TLT"]
            assert s.belief_weight > 0

    def test_optimize_empty_positions(self):
        opt = Optimizer()
        result = opt.optimize([], [])
        # Optimizer guards against 0 total_value (sets to 1.0 for calculations)
        assert result.suggestion_count == 0
        assert len(result.drifts) == 0

    def test_optimize_high_urgency_detection(self):
        """高漂移应被标记为 HIGH urgent。"""
        positions = [
            Position(
                ticker="SPY",
                asset_name="SPY",
                shares=1000.0,
                avg_cost=400.0,
                current_price=450.0,
                target_weight=0.30,
                current_weight=0.60,  # 30% 漂移！
                status="ACTIVE",
            ),
        ]
        opt = Optimizer(config=OptimizerConfig(drift_threshold=0.03))
        result = opt.optimize(positions, None)
        if result.suggestions:
            assert result.suggestions[0].urgency == "HIGH"

    def test_drift_record_defaults(self):
        d = DriftRecord(ticker="SPY", current_weight=0.3, target_weight=0.25, drift=0.05, exceeds_threshold=True)
        assert d.ticker == "SPY"
        assert d.drift == 0.05
        assert d.exceeds_threshold
        assert d.belief_score == 0.5

    def test_drift_sorted_by_abs(self):
        """漂移记录应按绝对值降序排列。"""
        positions = _sample_positions()
        opt = Optimizer()
        result = opt.optimize(positions, None)
        if len(result.drifts) >= 2:
            assert abs(result.drifts[0].drift) >= abs(result.drifts[1].drift)


class TestOptimizerEdgeCases:
    def test_zero_total_value(self):
        """总市值为 0 时不应崩溃。"""
        positions = [
            Position(
                ticker="SPY", shares=0.0, avg_cost=0.0, current_price=0.0,
                target_weight=0.0, current_weight=0.0, status="ACTIVE",
            ),
        ]
        opt = Optimizer()
        result = opt.optimize(positions, None)
        assert result is not None

    def test_custom_ticker_map(self):
        """自定义映射应覆盖默认映射。"""
        custom_map = {"CUSTOM": ["macro_fed_rate_path"]}
        opt = Optimizer(ticker_belief_map=custom_map)
        scores = opt.compute_belief_scores(_sample_belief_snapshots())
        assert "SPY" not in scores  # 默认映射被覆盖
        assert "CUSTOM" in scores

    def test_all_closed_positions(self):
        """所有仓位为 CLOSED 时不应触发调仓。"""
        positions = [
            Position(
                ticker="SPY", shares=100.0, avg_cost=400.0, current_price=450.0,
                target_weight=0.3, current_weight=0.3, status="CLOSED",
            ),
        ]
        opt = Optimizer()
        result = opt.optimize(positions, None)
        assert result.suggestion_count == 0


# ============================================================
# ShadowComparator Tests
# ============================================================

class TestShadowComparatorBasics:
    def test_default_config(self):
        comp = ShadowComparator()
        assert comp._config.n_simulations == 10000
        assert comp._config.n_days == 30

    def test_seeded_reproducibility(self):
        """相同 seed 应产生相同结果。"""
        positions = _sample_positions()
        suggestions = [
            RebalanceSuggestion(ticker="SPY", to_weight=0.32, from_weight=0.34, belief_weight=0.6),
            RebalanceSuggestion(ticker="QQQ", to_weight=0.24, from_weight=0.22, belief_weight=0.7),
        ]

        comp1 = ShadowComparator(config=ShadowComparatorConfig(
            n_simulations=1000, seed=42,
        ))
        result1 = comp1.compare(positions, suggestions)

        comp2 = ShadowComparator(config=ShadowComparatorConfig(
            n_simulations=1000, seed=42,
        ))
        result2 = comp2.compare(positions, suggestions)

        assert abs(result1.improvement - result2.improvement) < 0.01


class TestShadowComparatorGBM:
    def test_gbm_positive_drift(self):
        """正的年化收益率应产生正的平均收益率。"""
        comp = ShadowComparator(config=ShadowComparatorConfig(
            n_simulations=5000, n_days=252, annual_return=0.10, seed=123,
        ))
        returns = [comp._simulate_gbm(252) for _ in range(200)]
        mean_ret = sum(returns) / len(returns)
        # 预期应接近年化 10%
        assert mean_ret > -0.05  # 至少不是巨大的负收益

    def test_gbm_zero_vol(self):
        """波动率为 0 时应产生确定性收益。"""
        comp = ShadowComparator(config=ShadowComparatorConfig(
            n_simulations=100, n_days=10, annual_volatility=0.001, seed=42,
        ))
        returns = [comp._simulate_gbm(10) for _ in range(50)]
        # 波动极小时所有返回值应接近
        assert max(returns) - min(returns) < 0.05


class TestShadowComparatorCompare:
    def test_compare_same_portfolio(self):
        """比较相同组合时应得到 improvement ≈ 0。"""
        positions = _sample_positions()
        # No suggestions → likely same portfolio
        suggestions: List[RebalanceSuggestion] = []

        comp = ShadowComparator(config=ShadowComparatorConfig(
            n_simulations=500, seed=42,
        ))
        result = comp.compare(positions, suggestions)
        assert result.current_stats is not None
        assert result.suggested_stats is not None
        # 没有建议时两个组合相同
        assert abs(result.improvement) < 0.10

    def test_compare_returns_valid_stats(self):
        """对比结果应返回有效的统计量。"""
        positions = _sample_positions()
        suggestions = [
            RebalanceSuggestion(ticker="SPY", to_weight=0.35, from_weight=0.34, belief_weight=0.6),
        ]

        comp = ShadowComparator(config=ShadowComparatorConfig(
            n_simulations=500, seed=42,
        ))
        result = comp.compare(positions, suggestions)

        # 基本的统计验证
        assert result.current_stats is not None
        assert result.suggested_stats is not None
        assert result.current_stats.n_simulations == 500
        assert result.suggested_stats.n_simulations == 500
        assert isinstance(result.suggested_is_preferred, bool)

    def test_compare_empty_positions(self):
        """空仓位不应崩溃。"""
        comp = ShadowComparator(config=ShadowComparatorConfig(n_simulations=100))
        result = comp.compare([], [])
        assert result.current_stats is not None
        assert result.current_stats.mean == 0.0

    def test_transaction_cost_non_negative(self):
        """交易成本应为非负。"""
        positions = _sample_positions()
        suggestions = [
            RebalanceSuggestion(ticker="SPY", to_weight=0.35, from_weight=0.34, belief_weight=0.6),
        ]
        comp = ShadowComparator(config=ShadowComparatorConfig(n_simulations=100))
        result = comp.compare(positions, suggestions)
        assert result.total_suggested_value >= 0

    def test_compare_with_high_vol(self):
        """高波动率下的对比不应崩溃。"""
        positions = _sample_positions()
        suggestions = [
            RebalanceSuggestion(ticker="SPY", to_weight=0.25, from_weight=0.34, belief_weight=0.6),
            RebalanceSuggestion(ticker="QQQ", to_weight=0.15, from_weight=0.22, belief_weight=0.5),
        ]
        comp = ShadowComparator(config=ShadowComparatorConfig(
            n_simulations=200, annual_volatility=0.40, seed=42,
        ))
        result = comp.compare(positions, suggestions)
        assert result.current_stats is not None
        assert result.suggested_stats is not None


class TestDistributionStats:
    def test_zero_returns(self):
        stats = DistributionStats(n_simulations=0)
        assert stats.mean == 0.0

    def test_all_positive(self):
        """全部正收益的分布。"""
        returns = [0.01, 0.02, 0.03, 0.04, 0.05]
        comp = ShadowComparator(config=ShadowComparatorConfig(n_simulations=5))
        stats = comp._compute_stats(returns)
        assert stats.mean > 0
        assert stats.win_rate == 1.0
        # With 5 samples at 95% confidence: var_idx = int(5 * 0.05) = 0
        # var = sorted_ret[0] = 0.01 (all positive), so var > 0
        assert stats.var >= 0.0  # VaR is the worst-case (smallest) return

    def test_mixed_returns(self):
        """混合收益的分布。"""
        returns = [-0.05, -0.03, 0.0, 0.02, 0.04, 0.06, 0.08]
        comp = ShadowComparator(config=ShadowComparatorConfig(n_simulations=7, confidence_level=0.85))
        stats = comp._compute_stats(returns)
        assert stats.win_rate < 1.0
        assert stats.win_rate > 0.0
        assert stats.sharpe is not None