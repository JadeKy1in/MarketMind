"""HVR cycle — Hypothesize → Verify (4-layer) → Refine loop.

Extracted from investigation_loop.py. Public entry point: run_hvr_cycle().
"""

from __future__ import annotations

import json
import logging
from typing import Any

from marketmind.config.investigation_config import MAX_PRO_CALLS_PER_SESSION
from marketmind.gateway.async_client import chat_pro
from marketmind.pipeline.investigation_types import HypothesisResult, InvestigationConfig
from marketmind.pipeline.verification_chain import VerificationResult, verify_claim

logger = logging.getLogger("marketmind.pipeline.hvr_cycle")

# ── HVR refinement prompt ───────────────────────────────────────────────────────

_HVR_REFINE_SYSTEM = """You are refining a financial hypothesis based on verification results.

Original hypothesis: {hypothesis}

Verification results:
- Market Pricing layer (0-1): {l1_score} — {l1_interpretation}
- Fundamental Data layer (0-1): {l2_score} — {l2_interpretation}
- Multi-Source News layer (0-1): {l3_score} — {l3_interpretation}
- Historical Pattern layer (0-1): {l4_score} — {l4_interpretation}
- Composite confidence: {confidence}
- Verdict: {verdict}
- Contradictions: {contradictions}

Refinement rules:
1. If confidence >= 0.80: Keep the hypothesis as-is. It is verified.
2. If confidence <= 0.30: ABANDON. State "HYPOTHESIS_ABANDONED" and explain why.
3. If 0.30 < confidence < 0.80: REFINE. Adjust the hypothesis to account for which layers supported/refuted it. Narrow the claim, add conditions, or change scope.

Return ONLY a JSON object:
{{"refined_hypothesis": "<refined text or HYPOTHESIS_ABANDONED>",
 "action": "KEEP | ABANDON | REFINE",
 "rationale": "<one sentence>"}}"""


# ── Helpers ─────────────────────────────────────────────────────────────────────


def _parse_json_strict(content: str) -> dict | None:
    """Extract JSON object from LLM response, handling markdown wrapping."""
    if not content:
        return None
    content = content.strip()
    # Strip markdown code fences
    if content.startswith("```"):
        lines = content.split("\n")
        if len(lines) > 1:
            content = "\n".join(lines[1:])
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Try to find JSON object boundaries
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(content[start : end + 1])
            except json.JSONDecodeError:
                pass
    return None


def _classify_layer_interpretation(score: float) -> str:
    """Human-readable label for a layer verification score."""
    if score >= 0.80:
        return "strongly supports"
    elif score >= 0.60:
        return "moderately supports"
    elif score >= 0.40:
        return "neutral / inconclusive"
    elif score >= 0.20:
        return "moderately contradicts"
    else:
        return "strongly contradicts"


# ── Refinement ──────────────────────────────────────────────────────────────────


async def _refine_hypothesis(
    hypothesis: str,
    verification: VerificationResult,
    config: InvestigationConfig,
    pro_calls_counter: list[int] | None = None,
) -> dict:
    """Ask Pro to refine a hypothesis based on 4-layer verification results.

    Returns dict with keys: refined_hypothesis, action (KEEP|ABANDON|REFINE), rationale.
    """
    # H-SEC-2: check Pro call cap before LLM call
    if pro_calls_counter is not None and pro_calls_counter[0] >= MAX_PRO_CALLS_PER_SESSION:
        logger.warning(
            "Refine hypothesis: Pro call cap reached (%d/%d) — keeping original",
            pro_calls_counter[0], MAX_PRO_CALLS_PER_SESSION,
        )
        return {"refined_hypothesis": hypothesis, "action": "KEEP",
                "rationale": "Pro call cap reached — keeping original"}

    contradictions = verification.contradiction_detail or "none detected"
    system = _HVR_REFINE_SYSTEM.format(
        hypothesis=hypothesis,
        l1_score=verification.layer_1_market,
        l1_interpretation=_classify_layer_interpretation(verification.layer_1_market),
        l2_score=verification.layer_2_fundamental,
        l2_interpretation=_classify_layer_interpretation(verification.layer_2_fundamental),
        l3_score=verification.layer_3_multisource,
        l3_interpretation=_classify_layer_interpretation(verification.layer_3_multisource),
        l4_score=verification.layer_4_historical,
        l4_interpretation=_classify_layer_interpretation(verification.layer_4_historical),
        confidence=verification.weighted_confidence,
        verdict=verification.verdict,
        contradictions=contradictions,
    )

    try:
        result = await chat_pro(
            system_prompt=system,
            user_prompt=f"Refine this hypothesis based on the verification data above.\nHypothesis: {hypothesis}",
            temperature=0.3,
            max_tokens=1536,
        )
        if pro_calls_counter is not None:
            pro_calls_counter[0] += 1
        content = result.get("content", "")
        parsed = _parse_json_strict(content)
        if parsed and "refined_hypothesis" in parsed:
            return parsed
        else:
            logger.warning("Refinement: could not parse response: %.200s", content)
            return {"refined_hypothesis": hypothesis, "action": "KEEP",
                    "rationale": "parse failed — keeping original"}
    except Exception as e:
        logger.error("HVR refinement call failed: %s", e)
        return {"refined_hypothesis": hypothesis, "action": "KEEP",
                "rationale": f"API error: {e}"}


# ── Main HVR cycle ──────────────────────────────────────────────────────────────


async def run_hvr_cycle(
    hypothesis: str,
    max_rounds: int = 3,
    config: InvestigationConfig | None = None,
    pro_calls_counter: list[int] | None = None,
) -> HypothesisResult:
    """HVR: Hypothesize → Verify (4-layer) → Refine (repeat if gain > 5%).

    The audit finding (Druckenmiller discipline): "Failure to confirm" is NOT
    "refine." If verification confidence drops below 0.30, we ABANDON rather
    than refining to a weaker version.

    Args:
        hypothesis: Initial hypothesis string.
        max_rounds: Maximum refinement rounds (default 3, from config).
        config: InvestigationConfig with thresholds.
        pro_calls_counter: Mutable [int] counter for per-session Pro call cap.

    Returns:
        HypothesisResult with final hypothesis, verification, logic chain.
    """
    cfg = config or InvestigationConfig()
    current_hypothesis = hypothesis
    logic_chain: list[str] = []
    last_confidence = 0.0
    final_verification: VerificationResult | None = None
    api_calls_used = 0

    # H-SEC-2: check Pro call cap before initial verification
    if pro_calls_counter is not None and pro_calls_counter[0] >= MAX_PRO_CALLS_PER_SESSION:
        logger.warning(
            "HVR cycle: Pro call cap reached (%d/%d) — returning unverified result",
            pro_calls_counter[0], MAX_PRO_CALLS_PER_SESSION,
        )
        return HypothesisResult(
            hypothesis=hypothesis,
            expectation_gap=0.0,
            verification=VerificationResult(
                claim=hypothesis,
                layer_1_market=0.50,
                layer_2_fundamental=0.50,
                layer_3_multisource=0.50,
                layer_4_historical=0.50,
                weighted_confidence=0.0,
                verdict="UNVERIFIED",
            ),
            refined_hypothesis=hypothesis,
            confidence=0.0,
            bear_case="",
            bear_case_confidence=0.0,
            verdict="DISCARD",
            logic_chain=["Pro call cap reached — HVR cycle skipped"],
        )

    # Initial verification before entering refinement loop
    verification = await verify_claim(claim=current_hypothesis)
    api_calls_used += 1
    if pro_calls_counter is not None:
        pro_calls_counter[0] += 1
    final_verification = verification
    last_confidence = verification.weighted_confidence
    logic_chain.append(
        f"R0 (initial): hypothesis='{current_hypothesis[:100]}', "
        f"confidence={verification.weighted_confidence:.3f}, "
        f"verdict={verification.verdict}"
    )

    # If already strong — done
    if verification.weighted_confidence >= cfg.confidence_action:
        logger.info(
            "HVR: hypothesis verified on first pass (conf=%.3f)", verification.weighted_confidence
        )
    else:
        # Refinement loop
        for round_num in range(1, max_rounds + 1):
            if api_calls_used >= cfg.max_api_calls:
                logger.warning("HVR: max API calls (%d) reached, stopping", cfg.max_api_calls)
                break

            # H-SEC-2: check Pro call cap before refinement call
            if pro_calls_counter is not None and pro_calls_counter[0] >= MAX_PRO_CALLS_PER_SESSION:
                logger.warning(
                    "HVR: Pro call cap reached (%d/%d) — stopping refinement",
                    pro_calls_counter[0], MAX_PRO_CALLS_PER_SESSION,
                )
                break

            # Check: is current confidence too low? Abandon rather than refine.
            if verification.weighted_confidence < 0.30:
                logger.info(
                    "HVR: confidence below abandon threshold (%.3f < 0.30) — abandoning",
                    verification.weighted_confidence,
                )
                logic_chain.append(
                    f"R{round_num}: ABANDONED — confidence={verification.weighted_confidence:.3f} "
                    f"below 0.30 threshold. Not refining a contradicted thesis."
                )
                break

            # Refine: ask Pro to update the hypothesis based on verification
            refined = await _refine_hypothesis(
                current_hypothesis, verification, cfg, pro_calls_counter
            )
            api_calls_used += 1

            action = refined.get("action", "REFINE")
            if action == "ABANDON":
                logic_chain.append(
                    f"R{round_num}: ABANDONED by refinement agent — {refined.get('rationale', '')}"
                )
                break
            elif action == "KEEP":
                logic_chain.append(f"R{round_num}: KEPT — hypothesis verified, no changes needed")
                break

            # REFINE: update hypothesis and re-verify
            current_hypothesis = refined.get("refined_hypothesis", current_hypothesis)

            # H-SEC-2: check Pro call cap before re-verify
            if pro_calls_counter is not None and pro_calls_counter[0] >= MAX_PRO_CALLS_PER_SESSION:
                logger.warning(
                    "HVR: Pro call cap reached (%d/%d) — stopping after refine",
                    pro_calls_counter[0], MAX_PRO_CALLS_PER_SESSION,
                )
                break

            verification = await verify_claim(claim=current_hypothesis)
            api_calls_used += 1
            if pro_calls_counter is not None:
                pro_calls_counter[0] += 1
            final_verification = verification

            gain = verification.weighted_confidence - last_confidence
            logic_chain.append(
                f"R{round_num}: refined hypothesis, "
                f"confidence={verification.weighted_confidence:.3f} "
                f"(gain={gain:+.3f}), verdict={verification.verdict}"
            )

            # Diminishing returns check
            if abs(gain) < cfg.diminishing_threshold:
                logger.info(
                    "HVR: diminishing returns (gain=%.3f < %.3f) — stopping refinement",
                    abs(gain),
                    cfg.diminishing_threshold,
                )
                break

            last_confidence = verification.weighted_confidence

            # If refined to high confidence — done
            if verification.weighted_confidence >= cfg.confidence_action:
                logger.info("HVR: refined to actionable confidence (%.3f)", verification.weighted_confidence)
                break

    confidence = final_verification.weighted_confidence if final_verification else 0.0

    return HypothesisResult(
        hypothesis=hypothesis,
        expectation_gap=0.0,              # filled in by caller
        verification=final_verification or VerificationResult(
            claim=hypothesis,
            layer_1_market=0.50,
            layer_2_fundamental=0.50,
            layer_3_multisource=0.50,
            layer_4_historical=0.50,
            weighted_confidence=0.0,
            verdict="UNVERIFIED",
        ),
        refined_hypothesis=current_hypothesis,
        confidence=confidence,
        bear_case="",                     # filled in by caller
        bear_case_confidence=0.0,         # filled in by caller
        verdict="DISCARD",                # filled in by caller
        logic_chain=logic_chain,
    )
