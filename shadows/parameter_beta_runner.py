"""Parameter Beta Runner — quantitative tuning overlay (Phase 4, Item 9).

Quantitative parameter changes (e.g., weight adjustment ±5%) do NOT create
full Pro shadows. They run as a pure Python recalculation layer that follows
the main AI's analysis and produces a divergence log. No LLM calls.

Qualitative methodology changes (e.g., "add supply chain analysis") still
create 1-2 full Beta shadows with Pro. Max 2 concurrent qualitative hypotheses.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

logger = logging.getLogger("marketmind.shadows.parameter_beta_runner")


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class ParameterVariant:
    """A single parameter variant being tested."""
    variant_id: str
    description: str                    # e.g., "WinRate weight 15% instead of 20%"
    parameter_overrides: dict[str, float]  # e.g., {"composite_weights.win_rate": 0.15}
    days_active: int = 0
    divergence_count: int = 0           # how often Beta disagrees with main AI
    beta_better_count: int = 0          # when Beta was right, main AI was wrong
    main_better_count: int = 0          # when main AI was right, Beta was wrong
    created_at: str = ""


@dataclass
class DivergenceRecord:
    """Records when Beta and main AI disagree on a decision."""
    date: str
    ticker: str
    variant_id: str
    main_ai_decision: str      # "buy" | "sell" | "abstain"
    beta_decision: str
    main_ai_score: float
    beta_score: float
    reason: str = ""


# ── Runner ───────────────────────────────────────────────────────────────────

class ParameterBetaRunner:
    """Manages quantitative parameter testing without Pro calls."""

    MAX_CONCURRENT_VARIANTS = 10  # quantitative variants are cheap

    def __init__(self):
        self._variants: dict[str, ParameterVariant] = {}
        self._divergences: list[DivergenceRecord] = []

    def create_variant(
        self, description: str, parameter_overrides: dict[str, float]
    ) -> ParameterVariant:
        """Register a new parameter variant for testing."""
        variant_id = f"param_beta:{datetime.now(timezone.utc).strftime('%Y%m%d')}:{len(self._variants)}"
        variant = ParameterVariant(
            variant_id=variant_id,
            description=description,
            parameter_overrides=parameter_overrides,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._variants[variant_id] = variant
        logger.info("Created parameter variant: %s", description)
        return variant

    def apply_override(
        self, base_weights: dict[str, float], overrides: dict[str, float]
    ) -> dict[str, float]:
        """Apply parameter overrides to base weights.

        Supports dot-notation keys like "composite_weights.win_rate" to override
        nested dicts. For simple flat dicts, direct key replacement.
        """
        result = dict(base_weights)
        for key, value in overrides.items():
            if "." in key:
                # Dot-notation not needed for current flat weights, but future-proof
                parts = key.split(".")
                # For now, just use the last part as the weight name
                result[parts[-1]] = value
            else:
                result[key] = value
        return result

    def compare_decision(
        self,
        variant_id: str,
        ticker: str,
        main_ai_decision: str,
        main_ai_score: float,
        beta_score: float,
        threshold: float = 0.15,  # minimum score difference to count as divergence
    ) -> DivergenceRecord | None:
        """Compare main AI decision with Beta recalculated score.

        Returns DivergenceRecord if scores differ enough to change the decision,
        or None if they agree.
        """
        if variant_id not in self._variants:
            return None

        score_diff = abs(main_ai_score - beta_score)
        beta_decision = main_ai_decision

        # Reverse decision if Beta score crosses threshold in opposite direction
        if main_ai_decision == "buy" and beta_score < main_ai_score - threshold:
            beta_decision = "abstain"
        elif main_ai_decision == "abstain" and beta_score > threshold:
            beta_decision = "buy"

        if beta_decision != main_ai_decision:
            rec = DivergenceRecord(
                date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                ticker=ticker,
                variant_id=variant_id,
                main_ai_decision=main_ai_decision,
                beta_decision=beta_decision,
                main_ai_score=main_ai_score,
                beta_score=beta_score,
            )
            self._divergences.append(rec)
            self._variants[variant_id].divergence_count += 1
            return rec
        return None

    def resolve_divergence(
        self, divergence: DivergenceRecord, actual_outcome: str, pnl: float
    ) -> None:
        """Resolve a divergence with actual market outcome."""
        if (variant_id := divergence.variant_id) not in self._variants:
            return

        variant = self._variants[divergence.variant_id]

        # Who was right?
        main_correct = (
            (divergence.main_ai_decision == "buy" and pnl > 0) or
            (divergence.main_ai_decision == "abstain")  # neutral
        )
        beta_correct = (
            (divergence.beta_decision == "buy" and pnl > 0) or
            (divergence.beta_decision == "abstain")
        )

        if beta_correct and not main_correct:
            variant.beta_better_count += 1
        elif main_correct and not beta_correct:
            variant.main_better_count += 1

        variant.days_active += 1

    def get_variant_report(self, variant_id: str) -> dict:
        """Get a summary report for a variant."""
        variant = self._variants.get(variant_id)
        if not variant:
            return {"error": "Variant not found"}

        total = max(variant.divergence_count, 1)
        return {
            "variant_id": variant_id,
            "description": variant.description,
            "days_active": variant.days_active,
            "divergence_count": variant.divergence_count,
            "beta_better_rate": variant.beta_better_count / total,
            "main_better_rate": variant.main_better_count / total,
            "verdict": (
                "PROMOTE" if variant.beta_better_count > variant.main_better_count * 1.5
                else "INCONCLUSIVE" if variant.divergence_count < 10
                else "REJECT"
            ),
        }
