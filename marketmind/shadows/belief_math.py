"""
belief_math.py — Phase 8.3.1 β-Bernoulli 信念状态数学内核

纯 Python 实现，零外部依赖（无 NumPy/SciPy）。
实现了 Silent Scholar (arXiv 2504.18924) 论文的 β-Bernoulli 信念框架，
包含 γ=0.95 遗忘因子的衰减基准修正，防止退化为 U 型分布。

修正 (PM 2026-05-07):
  1. 衰减基准: α' = 1.0 + (α - 1.0) * γ^steps，防止 Beta 分布 U 型退化
  2. CQRS 强制: 仅提供纯数学函数，不涉及存储层

修正 (PM 2026-05-08 — Phase 8.4 红蓝对抗):
  3. β 更新对称化: β' = β + (1 - value) * confidence
     替代旧公式 β' = β + (1 - value * confidence)
     消除低置信噪音的熊市不对称偏移

SPARC:
  Specification: 纯数学函数，输入 → 输出，无副作用
  Pseudocode: 见 docstring 公式
  Architecture: 独立模块，可被 belief_state_manager.py 导入
  Refinement: 边界条件全覆盖（α+β≤0, steps≤0, obs 越界 clamp）
  Completion: 配合 test_belief_math.py 达到 100% 覆盖率
"""

from __future__ import annotations

from typing import Tuple


# ════════════════════════════════════════════════════════════════
# β-Bernoulli 共轭更新
# ════════════════════════════════════════════════════════════════

def beta_update(
    alpha: float,
    beta: float,
    value: float,
    confidence: float = 1.0,
) -> Tuple[float, float]:
    """Beta-Bernoulli 共轭后验更新（Phase 8.4 对称修正版）。

    Beta-Bernoulli 是共轭模型：
      先验: θ ~ Beta(α, β)
      似然: x|θ ~ Bernoulli(θ)
      后验: θ|x ~ Beta(α + x, β + 1 - x)

    公式 (Phase 8.4 对称修正):
      α' = α + clamp(value) × clamp(confidence)
      β' = β + (1 - clamp(value)) × clamp(confidence)

    修正理由：旧公式 β' = β + 1 - value × confidence 导致低置信噪音
    的 (1 - conf) 质量全部流向 β，产生系统性熊市偏移。
    新公式使低置信观测向两个方向的质量贡献对称减少。

    Args:
        alpha: Beta 分布 α 参数（先验成功计数）
        beta: Beta 分布 β 参数（先验失败计数）
        value: 观测值，取值范围 [0.0, 1.0]
               1.0 = strong positive, 0.0 = strong negative
        confidence: 观测置信度 [0.0, 1.0]。默认 1.0。

    Returns:
        (alpha_post, beta_post): 后验参数元组

    Raises:
        ValueError: 如果 alpha < 0 或 beta < 0

    Example:
        >>> beta_update(1.0, 1.0, 1.0)   # 成功后验
        (2.0, 1.0)
        >>> beta_update(5.0, 3.0, 0.0)   # 失败后验
        (5.0, 4.0)
        >>> beta_update(1.0, 1.0, 0.7)   # 加权观测
        (1.7, 1.3)
        >>> beta_update(1.0, 1.0, 0.5, confidence=0.01)  # 低置信中性
        (1.005, 1.005)                    # 对称微量更新
    """
    if alpha < 0.0:
        raise ValueError(f"alpha must be >= 0; got {alpha}")
    if beta < 0.0:
        raise ValueError(f"beta must be >= 0; got {beta}")

    # Clamp value and confidence to [0.0, 1.0]
    v = max(0.0, min(1.0, value))
    c = max(0.0, min(1.0, confidence))

    # Phase 8.4 对称修正: β 也乘以 confidence
    return (alpha + v * c, beta + (1.0 - v) * c)


# ════════════════════════════════════════════════════════════════
# γ 遗忘因子衰减（基准修正版）
# ════════════════════════════════════════════════════════════════

def gamma_decay(
    alpha: float,
    beta: float,
    gamma: float = 0.95,
    steps: int = 1,
) -> Tuple[float, float]:
    """γ 遗忘因子衰减——向均匀先验回归。

    原始公式（Silent Scholar）:
      α' = α · γ^steps,  β' = β · γ^steps

    修正公式（PM 2026-05-07 Approve）:
      α' = 1.0 + (α - 1.0) · γ^steps
      β' = 1.0 + (β - 1.0) · γ^steps

    修正理由: 直接 α * d 会导致参数 < 1，使 Beta 分布退化为
    U 型分布（两端高中间低），产生极端确信的错误。
    修正使衰减向均匀先验 Beta(1,1) 回归，保持分布的合理性。

    Args:
        alpha: Beta 分布 α 参数
        beta: Beta 分布 β 参数
        gamma: 遗忘因子，取值范围 (0, 1]。γ=1 表示无遗忘。
               蓝图校准值 γ=0.95（来自 Silent Scholar arXiv:2504.18924）
        steps: 衰减步数。steps=0 表示无衰减。

    Returns:
        (alpha_decayed, beta_decayed): 衰减后的参数元组

    Raises:
        ValueError: 如果 gamma 不在 (0, 1] 范围内

    Example:
        >>> gamma_decay(10.0, 8.0, gamma=0.95, steps=1)
        (9.55, 7.65)     # 10 → 1 + 9*0.95, 8 → 1 + 7*0.95
        >>> gamma_decay(1.0, 1.0, gamma=0.95, steps=10)
        (1.0, 1.0)       # 均匀先验不受衰减影响
        >>> gamma_decay(5.0, 3.0, gamma=0.5, steps=0)
        (5.0, 3.0)       # steps=0 → 无衰减
    """
    if gamma <= 0.0 or gamma > 1.0:
        raise ValueError(f"gamma must be in (0, 1]; got {gamma}")
    if steps < 0:
        raise ValueError(f"steps must be >= 0; got {steps}")

    if steps == 0:
        return (alpha, beta)

    decay = gamma ** steps  # Python 内置幂运算符，O(1) 数学运算

    # 修正公式: 向 Beta(1,1) 均匀先验回归
    alpha_new = 1.0 + (alpha - 1.0) * decay
    beta_new = 1.0 + (beta - 1.0) * decay

    return (alpha_new, beta_new)


# ════════════════════════════════════════════════════════════════
# Beta 分布统计量
# ════════════════════════════════════════════════════════════════

def beta_uncertainty(alpha: float, beta: float) -> float:
    """认知不确定性——Beta 分布的方差 Var[θ]。

    公式:
      Var[θ] = (α·β) / ((α+β)² · (α+β+1))

    该值衡量信念的"认知不确定性"（epistemic uncertainty）：
      - 接近 1.0: 几乎无信息（接近均匀分布）
      - 接近 0.0: 信念高度确定（后验密度尖锐）

    Args:
        alpha: Beta 分布 α 参数
        beta: Beta 分布 β 参数

    Returns:
        float: 方差值 [0, 1] 范围

    Example:
        >>> beta_uncertainty(1.0, 1.0)   # 均匀先验 → 最大不确定性
        0.08333...
        >>> beta_uncertainty(100.0, 1.0)  # 强确信
        0.00965...
        >>> beta_uncertainty(0.0, 0.0)   # 退化边界
        1.0
    """
    s = alpha + beta
    if s <= 0.0:
        return 1.0  # 无信息 → 最大不确定性

    return (alpha * beta) / ((s ** 2) * (s + 1.0))


def beta_expectation(alpha: float, beta: float) -> float:
    """信念期望——Beta 分布的均值 E[θ]。

    公式:
      E[θ] = α / (α + β)

    信念期望是后验概率的点估计，取值范围 [0, 1]。

    Args:
        alpha: Beta 分布 α 参数
        beta: Beta 分布 β 参数

    Returns:
        float: 期望值 [0, 1] 范围

    Example:
        >>> beta_expectation(2.0, 1.0)    # 2/3 ≈ 0.666...
        0.66666...
        >>> beta_expectation(1.0, 1.0)    # 均匀先验 → 0.5
        0.5
        >>> beta_expectation(0.0, 0.0)    # 退化边界
        0.5
    """
    s = alpha + beta
    if s <= 0.0:
        return 0.5  # 最大熵点

    return alpha / s


def confidence_score(alpha: float, beta: float) -> float:
    """综合置信度评分——用于冲突解决。

    公式:
      score = E[θ] / (1 + Var[θ])

    评分考量了信念期望与认知不确定性的权衡：
      高期望 + 低不确定性 → 高分（值得信任）
      低期望 + 高不确定性 → 低分（不可靠）

    Args:
        alpha: Beta 分布 α 参数
        beta: Beta 分布 β 参数

    Returns:
        float: 置信度评分 [0, 1] 范围

    Example:
        >>> confidence_score(100.0, 1.0)   # 高确信
        0.990...
        >>> confidence_score(1.0, 1.0)     # 均匀先验
        0.461...
    """
    exp = beta_expectation(alpha, beta)
    unc = beta_uncertainty(alpha, beta)
    return exp / (1.0 + unc)