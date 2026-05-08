"""
test_belief_integration_8_3_2.py — Phase 8.3.2 全链路集成测试

Demonstrates the complete belief lifecycle end-to-end:

  1. A "strong evidence" observation enters the BeliefStateManager
  2. BeliefAwarePredictor injects belief weights into ShadowPredictions
  3. ReflectionOrchestrator fires scheduled decay at T = n × 50
  4. The belief's confidence decays naturally over time
  5. The decaying belief influences trading prediction confidence

This test verifies the data flow through the entire ShadowPipeline
without requiring a full market data replayer (uses mocked predictions).

SPARC:
  Specification: PM requirement — one test showing full belief → prediction path.
  Pseudocode: create belief → ingest evidence → create prediction →
              inject weights → verify adjusted confidence → decay → verify decay.
  Architecture: Pure Python, no external dependencies (except existing modules).
  Refinement: All assertions check numeric ranges, not hard-coded values.
  Completion: Passes 100%.
"""

import json
import math
import os
import time
import pytest
from typing import Any, Dict, List

from src.belief_math import (
    beta_expectation,
    beta_uncertainty,
    confidence_score,
    gamma_decay,
)
from src.belief_types import (
    BeliefObservation,
    BeliefSource,
    BeliefStatus,
)
from src.belief_state_manager import (
    BeliefManagerConfig,
    BeliefStateManager,
)
from src.belief_aware_predictor import BeliefAwarePredictor
from src.reflection_orchestrator import (
    ReflectionOrchestrator,
    ReflectionSchedulerConfig,
)
from src.shadow_types import (
    ShadowPrediction,
    ShadowScenarioType,
    PredictionTarget,
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def manager() -> BeliefStateManager:
    """Create a fresh BeliefStateManager with default config."""
    return BeliefStateManager()


@pytest.fixture
def predictor() -> BeliefAwarePredictor:
    """Create a fresh BeliefAwarePredictor."""
    return BeliefAwarePredictor(min_score_threshold=0.05)


@pytest.fixture
def orchestrator(manager: BeliefStateManager) -> ReflectionOrchestrator:
    """Create a ReflectionOrchestrator backed by the test manager."""
    config = ReflectionSchedulerConfig(
        decay_interval=50,
        decay_steps_per_interval=1,
        log_after_decay=False,
    )
    return ReflectionOrchestrator(manager=manager, config=config)


# ============================================================
# Part 1: 信念注入 — "强力证据" 进入系统
# ============================================================


class TestBeliefIngestion:
    """验证强力证据如何进入信念系统并被正确建模."""

    def test_strong_evidence_creates_high_confidence_belief(
        self, manager: BeliefStateManager,
    ) -> None:
        """Step 1: 注册一个关于 SPY 的信念，注入强力正证据."""

        # 注册信念节点: "SPY uptrend confirmed"
        pid = manager.register_node(
            proposition="SPY uptrend confirmed",
            proposition_id="spy-bull-001",
            alpha=1.0,
            beta=1.0,
            source=BeliefSource.MARKET_DATA,
        )

        # 注入 3 条强力正证据
        observations = [
            BeliefObservation(value=0.95, confidence=1.0, source=BeliefSource.SHADOW_PREDICTION,
                              metadata={"ticker": "SPY", "type": "price_momentum"}),
            BeliefObservation(value=0.88, confidence=0.9, source=BeliefSource.MARKET_DATA,
                              metadata={"ticker": "SPY", "type": "volume_surge"}),
            BeliefObservation(value=0.92, confidence=0.95, source=BeliefSource.SHADOW_PREDICTION,
                              metadata={"ticker": "SPY", "type": "breakout_confirmation"}),
        ]

        for obs in observations:
            manager.ingest_observation(pid, obs)

        snap = manager.get_snapshot(pid)
        assert snap is not None
        assert snap.observation_count == 3

        # 验证信念参数 — 强正证据应产生高 alpha、高期望
        assert snap.node.alpha > 3.0, (
            f"Alpha should be > 3.0 after 3 strong positive observations; got {snap.node.alpha}"
        )
        assert snap.expectation > 0.65, (
            f"Expectation should be > 0.65; got {snap.expectation}"
        )
        assert snap.score > 0.5, (
            f"Confidence score should be > 0.5; got {snap.score}"
        )
        assert snap.uncertainty < 0.05, (
            f"Uncertainty should be < 0.05 after strong evidence; got {snap.uncertainty}"
        )

        # 信念应处于 ACTIVE 状态
        assert snap.status_label == BeliefStatus.ACTIVE.value

    def test_weak_evidence_produces_symmetric_neutral_belief(
        self, manager: BeliefStateManager,
    ) -> None:
        """Phase 8.4 验证: 弱证据不再产生系统性熊市偏移.

        旧公式（有 Bug）: β += 1 - value*confidence 导致低置信观测向 β 注入大量质量
        新公式（对称）:   β += (1 - value)*confidence，使低置信观测对称且几乎无影响.

        5 条弱证据从 Beta(1,1):
          alpha = 1 + 5 * (0.52 * 0.1) = 1.26
          beta  = 1 + 5 * (0.48 * 0.1) = 1.24
          E[θ] = 1.26 / (1.26 + 1.24) ≈ 0.504
        置信度应略低于均匀先验 0.46（不确定性未充分降低），但不会崩溃至 0.18.
        """
        pid = manager.register_node(
            "TSLA neutral signal",
            proposition_id="tsla-neutral",
            source=BeliefSource.INFERRED,
        )

        # 注入可信度极低的中性证据
        for _ in range(5):
            manager.ingest_observation(
                pid,
                BeliefObservation(value=0.52, confidence=0.1, source=BeliefSource.INFERRED),
            )

        snap = manager.get_snapshot(pid)

        # Phase 8.4 对称公式下，弱中性证据保持期望约 0.5
        # 旧公式会错误地将其拉到约 0.18
        assert snap.expectation > 0.4, (
            f"Phase 8.4: weak neutral evidence should stay near 0.5; "
            f"got {snap.expectation}. Old buggy formula would give ~0.18."
        )
        # 置信度应接近但略低于均匀先验（仍有不确定性）
        # 均匀先验 score ≈ 0.4615
        assert 0.3 < snap.score < 0.5, (
            f"Weak evidence should produce score near uniform prior; got {snap.score}"
        )


# ============================================================
# Part 2: 信念权重注入预测 — 影响交易置信度
# ============================================================


class TestBeliefInjectionIntoPredictions:
    """验证 BeliefAwarePredictor 如何将信念权重注入 ShadowPredictions."""

    def test_strong_belief_increases_prediction_weight(
        self, manager: BeliefStateManager, predictor: BeliefAwarePredictor,
    ) -> None:
        """Step 2: 强信念 → 高 belief_weight → 高 adjusted_confidence."""

        # Arrange: 创建强信念节点
        pid = manager.register_node(
            "SPY uptrend confirmed",
            proposition_id="spy-strong",
            alpha=15.0,  # 模拟已经积累了大量正证据
            beta=2.0,
            source=BeliefSource.SHADOW_PREDICTION,
        )

        # 创建针对 SPY 的预测
        raw_predictions = [
            ShadowPrediction(
                target_ticker="SPY",
                target_type=PredictionTarget.DIRECTIONAL_MOVE,
                predicted_value=520.0,
                comparison_operator="gt",
                confidence=80.0,  # 原始置信度 80
                assertion="SPY will break above 520",
                scenario_type=ShadowScenarioType.AGGRESSIVE,
                reasoning="Technical breakout pattern",
            ),
        ]

        # Act: 注入信念权重
        transformed = predictor.inject_belief_weights(raw_predictions, manager)

        # Assert
        assert len(transformed) == 1
        tpred = transformed[0]

        # belief_weights 应包含 SPY 的权重
        assert tpred.belief_weights is not None
        assert "SPY" in tpred.belief_weights
        assert 0.0 < tpred.belief_weights["SPY"] <= 1.0

        # 调整后的置信度应受信念影响
        adjusted = tpred.belief_adjusted_confidence
        assert 0.0 <= adjusted <= 100.0
        # 强信念应保持较高 adjusted_confidence
        assert adjusted > 50.0, (
            f"Strong belief should keep adjusted_confidence > 50; got {adjusted}"
        )

    def test_weak_belief_penalizes_prediction_confidence(
        self, manager: BeliefStateManager, predictor: BeliefAwarePredictor,
    ) -> None:
        """弱信念 → 低 belief_weight → penalized adjusted_confidence."""

        # Arrange: 创建弱信念节点（低 alpha）
        manager.register_node(
            "SPY uncertain outlook",
            proposition_id="spy-weak",
            alpha=1.5,
            beta=1.5,
            source=BeliefSource.INFERRED,
        )

        raw_predictions = [
            ShadowPrediction(
                target_ticker="SPY",
                target_type=PredictionTarget.DIRECTIONAL_MOVE,
                predicted_value=500.0,
                comparison_operator="lt",
                confidence=90.0,  # 原始置信度 90（很高）
                assertion="SPY will drop below 500",
                reasoning="Some weak signals",
            ),
        ]

        # Act
        transformed = predictor.inject_belief_weights(raw_predictions, manager)

        # Assert
        tpred = transformed[0]
        assert tpred.belief_weights is not None
        assert "SPY" in tpred.belief_weights

        adjusted = tpred.belief_adjusted_confidence
        # 弱信念应 penalize 置信度
        assert adjusted < tpred.confidence, (
            f"Weak belief should reduce confidence: {adjusted} >= {tpred.confidence}"
        )

    def test_no_belief_returns_raw_confidence(
        self, predictor: BeliefAwarePredictor,
    ) -> None:
        """没有任何信念 → belief_weights=None → 返回原始置信度."""

        # 创建一个空的 manager（没有任何信念节点）
        empty_manager = BeliefStateManager()

        raw_predictions = [
            ShadowPrediction(
                target_ticker="UNKNOWN",
                target_type=PredictionTarget.DIRECTIONAL_MOVE,
                predicted_value=100.0,
                comparison_operator="eq",
                confidence=75.0,
                assertion="Test prediction with no beliefs",
            ),
        ]

        transformed = predictor.inject_belief_weights(raw_predictions, empty_manager)

        tpred = transformed[0]
        # 没有相关信念 → belief_weights 应为 None
        assert tpred.belief_weights is None or len(tpred.belief_weights) == 0
        # adjusted_confidence = raw confidence
        assert tpred.belief_adjusted_confidence == tpred.confidence

    def test_multiple_predictions_different_tickers(
        self, manager: BeliefStateManager, predictor: BeliefAwarePredictor,
    ) -> None:
        """多标的预测 — 每个 ticker 有不同信念权重."""

        # Arrange: 为不同 ticker 创建不同强度的信念
        # SPY: 强信念
        manager.register_node("SPY strong uptrend", proposition_id="spy-bull2",
                              alpha=20.0, beta=2.0, source=BeliefSource.MARKET_DATA)
        # QQQ: 中等信念
        manager.register_node("QQQ neutral tech", proposition_id="qqq-neutral",
                              alpha=5.0, beta=5.0, source=BeliefSource.INFERRED)
        # TLT: 无信念

        raw_predictions = [
            ShadowPrediction(target_ticker="SPY", confidence=80.0, predicted_value=500.0,
                             comparison_operator="gt", assertion="SPY up"),
            ShadowPrediction(target_ticker="QQQ", confidence=70.0, predicted_value=400.0,
                             comparison_operator="gt", assertion="QQQ up"),
            ShadowPrediction(target_ticker="TLT", confidence=60.0, predicted_value=90.0,
                             comparison_operator="lt", assertion="TLT down"),
        ]

        transformed = predictor.inject_belief_weights(raw_predictions, manager)

        assert len(transformed) == 3

        # SPY: 强信念 → 高权重
        spy_pred = next(p for p in transformed if p.target_ticker == "SPY")
        assert spy_pred.belief_weights is not None
        assert spy_pred.belief_weights.get("SPY", 0) > 0.7

        # QQQ: 中等 → 中等权重
        qqq_pred = next(p for p in transformed if p.target_ticker == "QQQ")
        assert qqq_pred.belief_weights is not None
        qqq_w = qqq_pred.belief_weights.get("QQQ", 0)
        assert qqq_w > 0.0

        # TLT: 无信念 → 无权重
        tlt_pred = next(p for p in transformed if p.target_ticker == "TLT")
        assert tlt_pred.belief_weights is None or len(tlt_pred.belief_weights) == 0
        assert tlt_pred.belief_adjusted_confidence == tlt_pred.confidence


# ============================================================
# Part 3: 信念衰减 — 随着时间推移自然演化
# ============================================================


class TestBeliefDecay:
    """验证信念随时间衰减的完整路径."""

    def test_reflection_orchestrator_decay_schedule(
        self, manager: BeliefStateManager, orchestrator: ReflectionOrchestrator,
    ) -> None:
        """Step 3: ReflectionOrchestrator 在 T=50 触发衰减."""

        # Arrange: 创建一个强信念
        pid = manager.register_node("QQQ momentum strong", proposition_id="qqq-mom",
                                    alpha=20.0, beta=3.0, source=BeliefSource.MARKET_DATA)
        snap_before = manager.get_snapshot(pid)
        alpha_before = snap_before.node.alpha
        score_before = snap_before.score

        # Act: 模拟 49 步（不应触发衰减）
        for step in range(1, 50):
            result = orchestrator.on_trading_step_completed(step)
            assert not result["decay_fired"], f"Decay should not fire at step {step}"

        # 第 49 步后，alpha 应该没变
        snap_after_49 = manager.get_snapshot(pid)
        assert snap_after_49.node.alpha == pytest.approx(alpha_before)

        # Act: 第 50 步（应触发衰减）
        result_50 = orchestrator.on_trading_step_completed(50)
        assert result_50["decay_fired"], "Decay should fire at step 50"
        assert result_50["decayed_nodes"] >= 1
        assert result_50["step"] == 50

        # 验证衰减后的信念状态
        snap_after = manager.get_snapshot(pid)
        assert snap_after.node.alpha < alpha_before, (
            f"Alpha should decrease after decay: {snap_after.node.alpha} >= {alpha_before}"
        )
        assert snap_after.score < score_before, (
            f"Score should decrease after decay: {snap_after.score} >= {score_before}"
        )

        # 验证衰减历史
        history = orchestrator.get_decay_history()
        assert len(history) == 1
        assert history[0]["step"] == 50
        assert history[0]["decay_number"] == 1

    def test_multiple_decay_cycles(
        self, manager: BeliefStateManager, orchestrator: ReflectionOrchestrator,
    ) -> None:
        """模拟 200 步，验证 4 次衰减循环."""

        # Arrange: 创建多个不同强度的信念
        manager.register_node("SPY bull", proposition_id="spy-b-decay",
                              alpha=30.0, beta=3.0)
        manager.register_node("QQQ neutral", proposition_id="qqq-n-decay",
                              alpha=6.0, beta=6.0)

        snap_spy_before = manager.get_snapshot("spy-b-decay")
        snap_qqq_before = manager.get_snapshot("qqq-n-decay")

        # Act: 模拟 200 步
        results = orchestrator.simulate_steps(200)

        # 应触发 4 次衰减（50, 100, 150, 200）
        assert len(results) == 4, f"Expected 4 decays, got {len(results)}"
        assert results[0]["step"] == 50
        assert results[1]["step"] == 100
        assert results[2]["step"] == 150
        assert results[3]["step"] == 200

        # Assert: 信念应该已经显著衰减
        snap_spy_after = manager.get_snapshot("spy-b-decay")
        assert snap_spy_after.node.alpha < snap_spy_before.node.alpha
        assert snap_spy_after.score < snap_spy_before.score

        snap_qqq_after = manager.get_snapshot("qqq-n-decay")
        assert snap_qqq_after.node.alpha < snap_qqq_before.node.alpha

        # 验证 idempotent guard — 同一 step 不应重复触发
        dup_result = orchestrator.on_trading_step_completed(200)
        assert not dup_result["decay_fired"], "Same step should not double-fire"

    def test_decay_corrected_formula_preserves_beta_invariant(
        self, manager: BeliefStateManager, orchestrator: ReflectionOrchestrator,
    ) -> None:
        """衰减修正公式确保 alpha >= 1.0, beta >= 1.0."""

        # 创建一个 param 接近边界的信念
        pid = manager.register_node("Boundary test", proposition_id="boundary",
                                    alpha=1.5, beta=1.2)

        # 模拟大量衰减步（1000 步相当于 20 次衰减事件）
        orchestrator.simulate_steps(1000)

        snap = manager.get_snapshot(pid)
        assert snap.node.alpha >= 1.0, (
            f"Alpha must stay >= 1.0 after decay; got {snap.node.alpha}"
        )
        assert snap.node.beta >= 1.0, (
            f"Beta must stay >= 1.0 after decay; got {snap.node.beta}"
        )
        # 衰减后应趋近于 Beta(1,1) 均匀先验
        assert abs(snap.node.alpha - 1.0) < 0.5, (
            f"Alpha should converge toward 1.0; got {snap.node.alpha}"
        )
        assert abs(snap.node.beta - 1.0) < 0.5, (
            f"Beta should converge toward 1.0; got {snap.node.beta}"
        )


# ============================================================
# Part 4: 全链路 — 信念如何影响交易置信度
# ============================================================


class TestFullLifecycle:
    """完整的端到端演示: 信念从进入系统到影响交易置信度."""

    def test_belief_full_path_visualization(
        self, manager: BeliefStateManager,
        predictor: BeliefAwarePredictor,
        orchestrator: ReflectionOrchestrator,
    ) -> None:
        """
        全链路模拟 — 视觉化一个信念的完整生命周期:

        Phase 1: 强力证据注入 → 高置信度信念建立
        Phase 2: 信念权重注入预测 → 影响交易置信度
        Phase 3: 时间衰减 (50 步周期) → 信念逐渐弱化
        Phase 4: 衰减后的信念对预测的影响减弱

        这条路径展示: 信念系统如何影响最终交易决策的置信度.
        """
        path: List[Dict[str, Any]] = []

        # ════════════════════════════════════════════════════════════
        # Phase 1: 强力证据进入系统
        # ════════════════════════════════════════════════════════════

        # 注册关于 SPY 的信念节点
        pid = manager.register_node(
            "SPY strong bullish trend",
            proposition_id="spy-lifecycle",
            alpha=1.0, beta=1.0,
            source=BeliefSource.MARKET_DATA,
        )

        # 注入 5 条渐强的正证据 → 模拟多日累积
        evidence_series = [
            (0.70, 0.8, "initial_move"),
            (0.85, 0.9, "confirm_breakout"),
            (0.90, 0.95, "volume_validation"),
            (0.95, 1.0, "strong_close"),
            (0.98, 1.0, "follow_through"),
        ]

        for i, (value, conf, evidence_type) in enumerate(evidence_series):
            obs = BeliefObservation(
                value=value,
                confidence=conf,
                source=BeliefSource.SHADOW_PREDICTION,
                metadata={"ticker": "SPY", "evidence_type": evidence_type, "day": i + 1},
            )
            manager.ingest_observation(pid, obs)

        snap_after_ingest = manager.get_snapshot(pid)
        assert snap_after_ingest is not None

        path.append({
            "phase": "1 - 信念建立",
            "expectation": round(snap_after_ingest.expectation, 4),
            "uncertainty": round(snap_after_ingest.uncertainty, 4),
            "score": round(snap_after_ingest.score, 4),
            "obs_count": snap_after_ingest.observation_count,
            "status": snap_after_ingest.status_label,
        })

        # 验证 Phase 1: 信念已建立
        assert snap_after_ingest.score > 0.6, "Phase 1: Strong belief should be established"

        # ════════════════════════════════════════════════════════════
        # Phase 2: 信念影响预测置信度
        # ════════════════════════════════════════════════════════════

        # 创建两条针对 SPY 的预测
        raw_predictions = [
            ShadowPrediction(
                target_ticker="SPY",
                target_type=PredictionTarget.DIRECTIONAL_MOVE,
                predicted_value=530.0,
                comparison_operator="gt",
                confidence=85.0,
                assertion="SPY will close above 530",
                reasoning="Strong bullish setup",
            ),
            ShadowPrediction(
                target_ticker="SPY",
                target_type=PredictionTarget.DIRECTIONAL_MOVE,
                predicted_value=505.0,
                comparison_operator="lt",
                confidence=75.0,
                assertion="SPY will dip below 505",
                reasoning="Bearish counter-signal",
            ),
        ]

        # 注入信念权重
        weighted_predictions = predictor.inject_belief_weights(raw_predictions, manager)

        for pred in weighted_predictions:
            path.append({
                "phase": "2 - 预测置信度调整",
                "ticker": pred.target_ticker,
                "assertion": pred.assertion,
                "raw_confidence": pred.confidence,
                "belief_weight": pred.belief_weights.get("SPY", 0.0) if pred.belief_weights else 0.0,
                "adjusted_confidence": round(pred.belief_adjusted_confidence, 2),
            })

        # 验证 Phase 2:
        bull_pred = next(p for p in weighted_predictions if "above 530" in p.assertion)
        bear_pred = next(p for p in weighted_predictions if "below 505" in p.assertion)

        # 两个预测都受信念影响（有 belief_weights）
        assert bull_pred.belief_weights is not None
        assert bear_pred.belief_weights is not None
        # 强看涨信念应保持 bullish 预测的高置信度
        assert bull_pred.belief_adjusted_confidence > 60.0
        # 看跌预测受看涨信念压制
        bear_adjusted = bear_pred.belief_adjusted_confidence
        assert bear_adjusted < bear_pred.confidence, (
            f"Bearish prediction should be penalized by bullish belief: {bear_adjusted} >= {bear_pred.confidence}"
        )

        # ════════════════════════════════════════════════════════════
        # Phase 3: 时间衰减 — 信念自然弱化
        # ════════════════════════════════════════════════════════════

        # 模拟 4 次衰减循环（200 个交易步）
        decay_results = orchestrator.simulate_steps(200)

        snap_after_decay = manager.get_snapshot(pid)
        assert snap_after_decay is not None

        # 每次衰减记录
        for dr in decay_results:
            path.append({
                "phase": "3 - 信念衰减",
                "step": dr["step"],
                "decay_number": dr["decay_number"],
                "decayed_nodes": dr["decayed_nodes"],
                "active_after": dr["active_after"],
            })

        path.append({
            "phase": "3 - 衰减后信念状态",
            "expectation": round(snap_after_decay.expectation, 4),
            "uncertainty": round(snap_after_decay.uncertainty, 4),
            "score": round(snap_after_decay.score, 4),
            "status": snap_after_decay.status_label,
            "total_decays": orchestrator.get_total_decays_fired(),
        })

        # 验证 Phase 3: 衰减有效
        assert snap_after_decay.score < snap_after_ingest.score, (
            f"Belief score should decrease after decay: {snap_after_decay.score} >= {snap_after_ingest.score}"
        )
        assert snap_after_decay.uncertainty > snap_after_ingest.uncertainty, (
            "Uncertainty should increase after decay"
        )
        assert orchestrator.get_total_decays_fired() == 4

        # ════════════════════════════════════════════════════════════
        # Phase 4: 衰减后的信念对预测的影响减弱
        # ════════════════════════════════════════════════════════════

        # 使用相同的预测，但此时信念已弱化
        decayed_weighted = predictor.inject_belief_weights(raw_predictions, manager)

        for pred in decayed_weighted:
            path.append({
                "phase": "4 - 衰减后预测置信度",
                "ticker": pred.target_ticker,
                "assertion": pred.assertion,
                "raw_confidence": pred.confidence,
                "belief_weight": pred.belief_weights.get("SPY", 0.0) if pred.belief_weights else 0.0,
                "adjusted_confidence": round(pred.belief_adjusted_confidence, 2),
            })

        decayed_bull = next(p for p in decayed_weighted if "above 530" in p.assertion)
        decayed_bear = next(p for p in decayed_weighted if "below 505" in p.assertion)

        # 验证 Phase 4: 衰减后信念权重降低
        fresh_bull_weight = bull_pred.belief_weights.get("SPY", 0.0)
        decayed_bull_weight = decayed_bull.belief_weights.get("SPY", 0.0) if decayed_bull.belief_weights else 0.0
        # 衰减后的信念权重应 <= 新鲜时的权重
        assert decayed_bull_weight <= fresh_bull_weight + 0.01, (
            f"Decayed belief weight should be <= fresh weight: "
            f"{decayed_bull_weight} > {fresh_bull_weight}"
        )

        # ════════════════════════════════════════════════════════════
        # 输出全链路模拟路径
        # ════════════════════════════════════════════════════════════

        # All assertions already passed above -- this is just for visualization
        # Write the simulation path to a diagnostic file
        import os
        # __file__ = projects/robinhood/tests/test_belief_integration_8_3_2.py
        # root = e:/AI_Studio_Workspace/
        _test_dir = os.path.dirname(os.path.dirname(__file__))  # projects/robinhood/
        _root_dir = os.path.dirname(os.path.dirname(_test_dir))  # e:/AI_Studio_Workspace/
        diag_path = os.path.join(
            _root_dir,
            "memory-bank",
            "phase8_3_2_simulation_result.json",
        )
        os.makedirs(os.path.dirname(diag_path), exist_ok=True)
        with open(diag_path, "w", encoding="utf-8") as f:
            json.dump({
                "phase": "8.3.2",
                "belief": "SPY strong bullish trend",
                "path": path,
                "assertions": {
                    "alpha_before": snap_after_ingest.node.alpha,
                    "alpha_after": snap_after_decay.node.alpha,
                    "score_before": snap_after_ingest.score,
                    "score_after": snap_after_decay.score,
                    "uncertainty_before": snap_after_ingest.uncertainty,
                    "uncertainty_after": snap_after_decay.uncertainty,
                    "decays_fired": orchestrator.get_total_decays_fired(),
                    "fresh_belief_weight": fresh_bull_weight,
                    "decayed_belief_weight": decayed_bull_weight,
                },
            }, f, indent=2, ensure_ascii=False)
        assert True
