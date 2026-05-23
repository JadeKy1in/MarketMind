"""L1 Bias Check — H8 PMV pattern-based bias detection (no LLM call).

Extracted from layer1_interactive.py per modular architecture rules (§3.1).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from marketmind.pipeline.layer1_interactive import InteractiveState


def run_bias_check(state: "InteractiveState") -> None:
    """H8 PMV: Quick bias check on L1 interaction — no LLM call, pattern-based."""
    warnings: list[str] = []

    # 1. Confirmation bias: AI agrees too readily
    agree_markers = ["同意", "支持", "合理", "有道理", "agree", "correct", "valid"]
    if state.ai_evaluations:
        agree_count = sum(
            1 for resp in state.ai_evaluations
            if any(m in resp.lower() for m in agree_markers)
        )
        if agree_count >= len(state.ai_evaluations) * 0.8 and len(state.ai_evaluations) >= 2:
            warnings.append("[偏差预警] AI 同意率过高 — 可能存在阿谀偏差 (sycophancy)")

    # 2. Counterfactual check
    counterfactual_phrases = ["如果", "万一", "反过来", "what if", "相反"]
    if state.user_ideas:
        has_cf = any(
            any(p in idea.lower() for p in counterfactual_phrases)
            for idea in state.user_ideas
        )
        if not has_cf and len(state.user_ideas) >= 2:
            warnings.append("[偏差预警] 未探索反向情景 — 建议考虑'如果判断错误会怎样'")

    if warnings:
        print(f"\n[Red Team 后台]")
        for w in warnings:
            print(f"  {w}")
