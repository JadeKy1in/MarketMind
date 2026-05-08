"""
test_belief_math.py — Phase 8.3.1 β-Bernoulli 数学内核单元测试

覆盖 belief_math.py 全部 5 个纯数学函数：
  - beta_update: 共轭更新 + clamp 边界 + ValueError
  - gamma_decay: 衰减公式 + 修正版 + 边界
  - beta_uncertainty: 方差计算 + 退化边界
  - beta_expectation: 期望计算 + 退化边界
  - confidence_score: 综合评分 + 极端值

SPARC:
  Specification: 所有纯数学路径、边界条件、异常路径全覆盖
  Architecture: 与 belief_math.py 一一对应，无外部依赖
  Refinement: 浮点数精度使用 pytest.approx
  Completion: 目标 100% 通过
"""

import math
import pytest

from src.belief_math import (
    beta_update,
    gamma_decay,
    beta_uncertainty,
    beta_expectation,
    confidence_score,
)


# ════════════════════════════════════════════════════════════════
# beta_update — β-Bernoulli 共轭更新
# ════════════════════════════════════════════════════════════════

class TestBetaUpdate:
    """beta_update 测试套件"""

    def test_success_observation(self):
        """观测值为 1.0 (成功) → α+1, β 不变"""
        a, b = beta_update(1.0, 1.0, 1.0)
        assert a == pytest.approx(2.0)
        assert b == pytest.approx(1.0)

    def test_failure_observation(self):
        """观测值为 0.0 (失败) → α 不变, β+1"""
        a, b = beta_update(5.0, 3.0, 0.0)
        assert a == pytest.approx(5.0)
        assert b == pytest.approx(4.0)

    def test_partial_observation(self):
        """部分置信观测 0.7 → α+0.7, β+0.3"""
        a, b = beta_update(1.0, 1.0, 0.7)
        assert a == pytest.approx(1.7)
        assert b == pytest.approx(1.3)

    def test_midpoint_observation(self):
        """中值观测 0.5 → α+0.5, β+0.5"""
        a, b = beta_update(2.0, 2.0, 0.5)
        assert a == pytest.approx(2.5)
        assert b == pytest.approx(2.5)

    def test_clamp_above_one(self):
        """当 observation > 1.0 时 clamp 到 1.0"""
        a, b = beta_update(1.0, 1.0, 1.5)
        assert a == pytest.approx(2.0)   # 1 + 1.0 (clamped)
        assert b == pytest.approx(1.0)   # 1 + 0.0

    def test_clamp_below_zero(self):
        """当 observation < 0.0 时 clamp 到 0.0"""
        a, b = beta_update(3.0, 4.0, -0.5)
        assert a == pytest.approx(3.0)   # 3 + 0.0 (clamped)
        assert b == pytest.approx(5.0)   # 4 + 1.0

    def test_exact_clamp_boundary(self):
        """边界值 0.0 和 1.0 不应被 clamp"""
        a0, b0 = beta_update(2.0, 3.0, 0.0)
        assert a0 == pytest.approx(2.0)
        assert b0 == pytest.approx(4.0)

        a1, b1 = beta_update(2.0, 3.0, 1.0)
        assert a1 == pytest.approx(3.0)
        assert b1 == pytest.approx(3.0)

    def test_confidence_scaling(self):
        """confidence 正确缩放更新量: value=0.8, conf=0.5 → α+0.4, β+0.1"""
        a, b = beta_update(1.0, 1.0, 0.8, confidence=0.5)
        assert a == pytest.approx(1.4)
        assert b == pytest.approx(1.1)

    def test_zero_confidence_no_update(self):
        """confidence=0 → 无更新"""
        a, b = beta_update(2.0, 3.0, 0.9, confidence=0.0)
        assert a == pytest.approx(2.0)
        assert b == pytest.approx(3.0)

    def test_low_confidence_symmetric_noise(self):
        """低置信中性噪音: value=0.5, conf=0.01 → α+0.005, β+0.005（对称）"""
        a, b = beta_update(5.0, 3.0, 0.5, confidence=0.01)
        assert a == pytest.approx(5.005)
        assert b == pytest.approx(3.005)

    def test_raises_on_negative_alpha(self):
        """alpha < 0 时抛出 ValueError"""
        with pytest.raises(ValueError, match="alpha"):
            beta_update(-1.0, 1.0, 0.5)

    def test_raises_on_negative_beta(self):
        """beta < 0 时抛出 ValueError"""
        with pytest.raises(ValueError, match="beta"):
            beta_update(1.0, -0.1, 0.5)

    def test_zero_alpha_and_beta(self):
        """alpha=0, beta=0 是合法的（退化情况）"""
        a, b = beta_update(0.0, 0.0, 0.5)
        assert a == pytest.approx(0.5)
        assert b == pytest.approx(0.5)

    def test_large_values(self):
        """大值情况下不溢出"""
        a, b = beta_update(1e6, 1e6, 0.3)
        assert a == pytest.approx(1e6 + 0.3)
        assert b == pytest.approx(1e6 + 0.7)


# ════════════════════════════════════════════════════════════════
# gamma_decay — γ 遗忘因子衰减
# ════════════════════════════════════════════════════════════════

class TestGammaDecay:
    """gamma_decay 测试套件"""

    def test_no_decay_when_steps_zero(self):
        """steps=0 → 无衰减，返回原始值"""
        a, b = gamma_decay(10.0, 8.0, gamma=0.5, steps=0)
        assert a == pytest.approx(10.0)
        assert b == pytest.approx(8.0)

    def test_uniform_prior_unchanged(self):
        """均匀先验 Beta(1,1) 不受γ衰减影响"""
        a, b = gamma_decay(1.0, 1.0, gamma=0.95, steps=100)
        assert a == pytest.approx(1.0)
        assert b == pytest.approx(1.0)

    def test_corrected_decay_formula(self):
        """修正公式: α' = 1 + (α-1)*γ^steps, β' = 1 + (β-1)*γ^steps"""
        # α=10, β=8, γ=0.95, steps=1
        # α' = 1 + 9*0.95 = 1 + 8.55 = 9.55
        # β' = 1 + 7*0.95 = 1 + 6.65 = 7.65
        a, b = gamma_decay(10.0, 8.0, gamma=0.95, steps=1)
        assert a == pytest.approx(9.55)
        assert b == pytest.approx(7.65)

    def test_default_gamma_is_0_95(self):
        """默认 γ=0.95 (蓝图校准值)"""
        a, b = gamma_decay(10.0, 8.0, steps=1)
        assert a == pytest.approx(9.55)
        assert b == pytest.approx(7.65)

    def test_gamma_equals_one(self):
        """γ=1.0 表示无遗忘 → 参数不变"""
        a, b = gamma_decay(10.0, 8.0, gamma=1.0, steps=10)
        assert a == pytest.approx(10.0)
        assert b == pytest.approx(8.0)

    def test_multiple_steps(self):
        """多步衰减: steps=10"""
        # α' = 1 + 9 * (0.95^10) ≈ 1 + 9*0.5987 ≈ 6.388
        # β' = 1 + 7 * (0.95^10) ≈ 1 + 7*0.5987 ≈ 5.191
        decay = 0.95 ** 10
        a, b = gamma_decay(10.0, 8.0, gamma=0.95, steps=10)
        assert a == pytest.approx(1.0 + 9.0 * decay)
        assert b == pytest.approx(1.0 + 7.0 * decay)

    def test_large_steps_approach_uniform(self):
        """steps→∞ 时参数趋近 Beta(1,1)"""
        a, b = gamma_decay(100.0, 50.0, gamma=0.95, steps=500)
        assert a == pytest.approx(1.0, abs=0.1)
        assert b == pytest.approx(1.0, abs=0.1)

    def test_raises_on_gamma_zero(self):
        """γ=0 时抛出 ValueError"""
        with pytest.raises(ValueError, match="gamma"):
            gamma_decay(1.0, 1.0, gamma=0.0, steps=1)

    def test_raises_on_gamma_above_one(self):
        """γ>1 时抛出 ValueError"""
        with pytest.raises(ValueError, match="gamma"):
            gamma_decay(1.0, 1.0, gamma=1.1, steps=1)

    def test_raises_on_gamma_negative(self):
        """γ<0 时抛出 ValueError"""
        with pytest.raises(ValueError, match="gamma"):
            gamma_decay(1.0, 1.0, gamma=-0.5, steps=1)

    def test_raises_on_negative_steps(self):
        """steps<0 时抛出 ValueError"""
        with pytest.raises(ValueError, match="steps"):
            gamma_decay(1.0, 1.0, gamma=0.95, steps=-1)

    def test_decay_preserves_ratio_for_symmetric(self):
        """对称分布 α=β 时，衰减后仍保持 α=β"""
        a, b = gamma_decay(7.0, 7.0, gamma=0.95, steps=3)
        assert a == pytest.approx(b)

    def test_decay_reduces_magnitude(self):
        """衰减后参数绝对值应小于原始值"""
        a_orig, b_orig = 20.0, 15.0
        a_new, b_new = gamma_decay(a_orig, b_orig, gamma=0.95, steps=1)
        assert a_new < a_orig
        assert b_new < b_orig

    def test_always_stays_above_one(self):
        """修正公式保证参数始终 >= 1.0（防止 U 型退化）"""
        a, b = gamma_decay(1.5, 1.3, gamma=0.95, steps=1000)
        assert a >= 1.0
        assert b >= 1.0


# ════════════════════════════════════════════════════════════════
# beta_uncertainty — 认知不确定性 Var[θ]
# ════════════════════════════════════════════════════════════════

class TestBetaUncertainty:
    """beta_uncertainty 测试套件"""

    def test_uniform_prior(self):
        """均匀先验 Beta(1,1) 的方差"""
        # Var[θ] = 1*1 / (2^2 * 3) = 1/12 ≈ 0.08333
        u = beta_uncertainty(1.0, 1.0)
        assert u == pytest.approx(1.0 / 12.0)

    def test_strong_belief(self):
        """强信念 Beta(100,1) 方差接近 0"""
        u = beta_uncertainty(100.0, 1.0)
        assert u < 0.01

    def test_degenerate_zero_sum(self):
        """退化边界 α+β=0 → 返回 1.0"""
        u = beta_uncertainty(0.0, 0.0)
        assert u == pytest.approx(1.0)

    def test_symmetric_belief(self):
        """对称信念 α=β 时方差随总计数递减"""
        u_small = beta_uncertainty(2.0, 2.0)
        u_large = beta_uncertainty(10.0, 10.0)
        assert u_large < u_small

    def test_high_alpha_low_beta(self):
        """α≫β 时 E[θ]→1, Var[θ]→0"""
        u = beta_uncertainty(1000.0, 1.0)
        assert u < 0.001

    def test_low_alpha_high_beta(self):
        """α≪β 时 E[θ]→0, Var[θ]→0"""
        u = beta_uncertainty(1.0, 1000.0)
        assert u < 0.001

    def test_uncertainty_decreases_with_evidence(self):
        """更多证据 → 更低不确定性"""
        u_less = beta_uncertainty(5.0, 5.0)
        u_more = beta_uncertainty(50.0, 50.0)
        assert u_more < u_less

    def test_non_negative(self):
        """不确定性应始终 >= 0"""
        for a, b in [(1, 1), (10, 5), (100, 50), (0.5, 0.5)]:
            u = beta_uncertainty(a, b)
            assert u >= 0.0 or u == pytest.approx(0.0)


# ════════════════════════════════════════════════════════════════
# beta_expectation — 信念期望 E[θ]
# ════════════════════════════════════════════════════════════════

class TestBetaExpectation:
    """beta_expectation 测试套件"""

    def test_uniform_prior(self):
        """均匀先验 Beta(1,1) 期望 0.5"""
        e = beta_expectation(1.0, 1.0)
        assert e == pytest.approx(0.5)

    def test_positive_evidence(self):
        """正面证据多于负面 → 期望 > 0.5"""
        e = beta_expectation(5.0, 2.0)
        assert e > 0.5

    def test_negative_evidence(self):
        """负面证据多于正面 → 期望 < 0.5"""
        e = beta_expectation(2.0, 5.0)
        assert e < 0.5

    def test_degenerate_zero_sum(self):
        """退化边界 α+β=0 → 返回 0.5"""
        e = beta_expectation(0.0, 0.0)
        assert e == pytest.approx(0.5)

    def test_all_success(self):
        """只有成功 Alpha=20, Beta=1 → E[θ] ≈ 0.952"""
        e = beta_expectation(20.0, 1.0)
        assert e == pytest.approx(20.0 / 21.0)

    def test_all_failure(self):
        """只有失败 Alpha=1, Beta=20 → E[θ] ≈ 0.048"""
        e = beta_expectation(1.0, 20.0)
        assert e == pytest.approx(1.0 / 21.0)

    def test_equal_evidence(self):
        """相等证据时期望为 0.5"""
        e = beta_expectation(10.0, 10.0)
        assert e == pytest.approx(0.5)

    def test_large_values(self):
        """大值情况下期望稳定"""
        e = beta_expectation(1e6, 2e6)
        assert e == pytest.approx(1.0 / 3.0)


# ════════════════════════════════════════════════════════════════
# confidence_score — 综合置信度评分
# ════════════════════════════════════════════════════════════════

class TestConfidenceScore:
    """confidence_score 测试套件"""

    def test_strong_confidence(self):
        """高确信 (100,1) → 评分接近 1"""
        score = confidence_score(100.0, 1.0)
        # E[θ] ≈ 0.990, Var ≈ 0.000096, score ≈ 0.990/(1+0.000096) ≈ 0.990
        assert score > 0.95

    def test_uniform_prior_score(self):
        """均匀先验 (1,1) → 评分 ≈ 0.4615"""
        score = confidence_score(1.0, 1.0)
        # E=0.5, Var=1/12≈0.0833, score=0.5/(1.0833)≈0.4615
        assert score == pytest.approx(0.5 / (1.0 + 1.0/12.0))

    def test_degenerate_zero(self):
        """退化边界 (0,0) → E=0.5, Var=1.0, score=0.5/2=0.25"""
        score = confidence_score(0.0, 0.0)
        assert score == pytest.approx(0.5 / 2.0)

    def test_high_uncertainty_penalty(self):
        """高不确定性惩罚评分"""
        score_high_unc = confidence_score(5.0, 5.0)   # Var=1/(44)≈0.0227
        score_low_unc = confidence_score(50.0, 50.0)   # Var=1/(404)≈0.00248
        assert score_low_unc > score_high_unc

    def test_score_range(self):
        """所有评分应在 [0, 1] 范围内"""
        for a, b in [(1, 1), (10, 5), (0, 0), (100, 1), (1, 100)]:
            score = confidence_score(a, b)
            assert 0.0 <= score <= 1.0

    def test_high_expectation_low_uncertainty(self):
        """高期望 + 低不确定性 → 最高分"""
        score = confidence_score(100.0, 2.0)
        assert score > 0.9

    def test_low_expectation_high_uncertainty(self):
        """低期望 + 高不确定性 → 评分不应太高"""
        score = confidence_score(1.0, 100.0)
        # E ≈ 0.0099, Var ≈ 0.000097, score ≈ 0.0099/(1.000097) ≈ 0.0099
        assert score < 0.1