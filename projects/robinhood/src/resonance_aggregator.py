"""
resonance_aggregator.py - Layer 3 Four-Dimensional Resonance Scorer (Task 3.1)

Aggregates scores from all four Layer 2 engines (fundamental, technical,
event_driven, sentiment) using a weighted formula, enforces soft-veto
discounting, and outputs a resolved trading signal.

Key design elements:
  1. Weighted score = fundamental*0.20 + technical*0.25 + event_driven*0.30 + sentiment*0.25
  2. Soft veto: if any single dimension < 30, apply 15% discount to weighted score.
  3. Resonance threshold (PM-approved): 70. Only when 3/4 dimensions >= 70 AND
     weighted score >= 70 will the system output BUY.
  4. Sentiment engine output normalization: Positive -> 50-100, Neutral -> 40-60,
     Negative -> 0-50, using magnitude as interpolation factor.
  5. Pro model Override field: when soft veto is triggered, override_available
     is set to True and the final report must highlight it.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Weights (PM-approved: 20/25/30/25)
# ---------------------------------------------------------------------------

WEIGHTS: dict[str, float] = {
    "fundamental": 0.20,
    "technical": 0.25,
    "event_driven": 0.30,
    "sentiment": 0.25,
}

# ---------------------------------------------------------------------------
# Threshold constants (PM-approved revision: 65 -> 70)
# ---------------------------------------------------------------------------

RESONANCE_THRESHOLD: int = 70
SOFT_VETO_THRESHOLD: int = 30
SOFT_VETO_DISCOUNT: float = 0.15  # 15% discount
STRONG_BUY_THRESHOLD: int = 85

# ---------------------------------------------------------------------------
# Sentiment normalization
# ---------------------------------------------------------------------------

_SENTIMENT_CLASSES = ("Positive", "Neutral", "Negative")


def normalize_sentiment(sentiment_output: dict[str, Any]) -> int:
    """Convert sentiment engine output into a 0-100 score.

    Sentiment engine returns {sentiment, magnitude, ticker, reasoning}.
    This mapping uses magnitude as an interpolation factor:

        Positive: score = 50 + magnitude * 0.5  -> range [50, 100]
        Neutral:  score = 40 + magnitude * 0.2  -> range [40,  60]
        Negative: score = 50 - magnitude * 0.5  -> range [ 0,  50]

    Args:
        sentiment_output: Dict from sentiment_engine.analyze_sentiment().

    Returns:
        Integer score 0-100.
    """
    sentiment = str(sentiment_output.get("sentiment", "Neutral"))
    magnitude = int(sentiment_output.get("magnitude", 0))
    magnitude = max(0, min(100, magnitude))

    if sentiment == "Positive":
        raw = 50 + magnitude * 0.5
    elif sentiment == "Negative":
        raw = 50 - magnitude * 0.5
    else:  # Neutral
        raw = 40 + magnitude * 0.2

    return max(0, min(100, int(round(raw))))


# ---------------------------------------------------------------------------
# Core resonance computation
# ---------------------------------------------------------------------------

def _scores_from_engines(
    fundamental: dict[str, Any],
    technical: dict[str, Any],
    event_driven: dict[str, Any],
    sentiment_engine_output: dict[str, Any] | int,
) -> dict[str, int]:
    """Extract or normalize scores from all four engines.

    Args:
        fundamental: Dict with 'score' (0-100) and 'reasoning'.
        technical: Dict with 'score' (0-100) and 'reasoning'.
        event_driven: Dict with 'score' (0-100) and 'reasoning'.
        sentiment_engine_output: Either an int (already normalized score)
            or the raw sentiment engine dict.

    Returns:
        Dict of dimension_name -> score (0-100).
    """
    scores: dict[str, int] = {}

    # Fundamental, technical, event_driven all follow {score, reasoning} contract
    for dim, output in [
        ("fundamental", fundamental),
        ("technical", technical),
        ("event_driven", event_driven),
    ]:
        raw = output.get("score", 50) if isinstance(output, dict) else 50
        scores[dim] = max(0, min(100, int(raw)))

    # Sentiment: normalize dict or accept pre-normalized int
    if isinstance(sentiment_engine_output, dict):
        scores["sentiment"] = normalize_sentiment(sentiment_engine_output)
    else:
        scores["sentiment"] = max(0, min(100, int(sentiment_engine_output)))

    return scores


def _compute_weighted_score(scores: dict[str, int]) -> float:
    """Compute weighted average of all four dimension scores.

    Args:
        scores: Dict of dimension_name -> score (0-100).

    Returns:
        Weighted float score (0-100).
    """
    total = 0.0
    for dim, weight in WEIGHTS.items():
        total += scores.get(dim, 50) * weight
    return total


def _check_soft_veto(scores: dict[str, int]) -> bool:
    """Check if any single dimension triggers the soft veto.

    Soft veto: if ANY dimension score < SOFT_VETO_THRESHOLD (30),
    apply a 15% discount to the weighted score.

    Args:
        scores: Dict of dimension_name -> score (0-100).

    Returns:
        True if soft veto is triggered.
    """
    return any(score < SOFT_VETO_THRESHOLD for score in scores.values())


def _check_resonance_condition(scores: dict[str, int]) -> bool:
    """Check if at least 3 out of 4 dimensions meet the resonance threshold.

    Args:
        scores: Dict of dimension_name -> score (0-100).

    Returns:
        True if >= 3 dimensions have score >= RESONANCE_THRESHOLD.
    """
    count = sum(1 for score in scores.values() if score >= RESONANCE_THRESHOLD)
    return count >= 3


def _determine_signal(
    weighted_score: float,
    scores: dict[str, int],
    soft_veto: bool,
) -> str:
    """Determine the trading signal based on resonance state machine.

    State machine:
        STRONG_BUY: weighted >= 85, no veto, resonance condition met
        BUY:        weighted >= 70, resonance condition met
        SELL:       weighted <= 30 OR >= 2 dimensions <= 30
        WAIT:       soft_veto triggered OR resonance condition NOT met
        HOLD:       everything else (stable mixed signals)

    Args:
        weighted_score: Final weighted score after any discount.
        scores: Raw dimension scores for signal logic.
        soft_veto: Whether soft veto was triggered.

    Returns:
        One of "STRONG_BUY", "BUY", "SELL", "WAIT", "HOLD".
    """
    dimensions_below_threshold = sum(
        1 for s in scores.values() if s <= SOFT_VETO_THRESHOLD
    )

    # STRONG_BUY: top-tier confidence
    if (
        weighted_score >= STRONG_BUY_THRESHOLD
        and not soft_veto
        and _check_resonance_condition(scores)
    ):
        return "STRONG_BUY"

    # BUY: solid resonance
    if weighted_score >= RESONANCE_THRESHOLD and _check_resonance_condition(scores):
        return "BUY"

    # SELL: strong bearish consensus
    if weighted_score <= 30 or dimensions_below_threshold >= 2:
        return "SELL"

    # WAIT: soft veto or poor resonance
    if soft_veto or not _check_resonance_condition(scores):
        return "WAIT"

    # HOLD: default stable state
    return "HOLD"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_resonance(
    fundamental: dict[str, Any],
    technical: dict[str, Any],
    event_driven: dict[str, Any],
    sentiment_engine_output: dict[str, Any] | int,
) -> dict[str, Any]:
    """Compute four-dimensional resonance and return the resolved signal.

    This is the primary entry point for Layer 3 decision aggregation.

    Args:
        fundamental: Dict from fundamental_engine.analyze_fundamental()
                     with 'score' (0-100) and 'reasoning'.
        technical: Dict from technical_engine.analyze_technical()
                   with 'score' (0-100) and 'reasoning'.
        event_driven: Dict from event_engine.analyze_event_driven()
                      with 'score' (0-100) and 'reasoning'.
        sentiment_engine_output: Either a dict from
            sentiment_engine.analyze_sentiment() (with 'sentiment',
            'magnitude', 'reasoning') OR a pre-normalized int 0-100.

    Returns:
        Dict with the following structure:
        {
            "signal": <"STRONG_BUY" | "BUY" | "SELL" | "HOLD" | "WAIT">,
            "weighted_score": <float 0-100>,
            "dimension_scores": {
                "fundamental": <int>,
                "technical": <int>,
                "event_driven": <int>,
                "sentiment": <int>
            },
            "dimension_details": {
                "fundamental": {"score": <int>, "reasoning": <str>},
                "technical": {"score": <int>, "reasoning": <str>},
                "event_driven": {"score": <int>, "reasoning": <str>},
                "sentiment": {"score": <int>, "reasoning": <str>}
            },
            "soft_veto_triggered": <bool>,
            "override_available": <bool>,
            "resonance_condition_met": <bool>,
            "reasoning": <str>
        }
    """
    # Step 1: Extract/normalize all four scores
    scores = _scores_from_engines(
        fundamental, technical, event_driven, sentiment_engine_output,
    )

    # Step 2: Compute weighted score
    weighted_raw = _compute_weighted_score(scores)

    # Step 3: Soft veto check
    soft_veto = _check_soft_veto(scores)

    # Step 4: Apply discount if veto triggered
    if soft_veto:
        weighted_score = weighted_raw * (1.0 - SOFT_VETO_DISCOUNT)
    else:
        weighted_score = weighted_raw
    weighted_score = max(0.0, min(100.0, weighted_score))

    # Step 5: Resonance condition
    resonance_met = _check_resonance_condition(scores)

    # Step 6: Determine signal
    signal = _determine_signal(weighted_score, scores, soft_veto)

    # Step 7: Build reasoning text
    parts = [
        f"Weighted score: {weighted_score:.1f}/100 "
        f"(F={scores['fundamental']}*0.20 + T={scores['technical']}*0.25 "
        f"+ E={scores['event_driven']}*0.30 + S={scores['sentiment']}*0.25)",
    ]

    if soft_veto:
        vetoed_dims = [
            dim for dim, sc in scores.items() if sc < SOFT_VETO_THRESHOLD
        ]
        parts.append(
            f"Soft veto triggered by dimension(s): {', '.join(vetoed_dims)} "
            f"(score < {SOFT_VETO_THRESHOLD}). "
            f"Applied {SOFT_VETO_DISCOUNT*100:.0f}% discount."
        )

    if resonance_met:
        parts.append("Resonance condition met: >= 3 dimensions >= 70.")
    else:
        parts.append("Resonance condition NOT met.")

    parts.append(f"Final signal: {signal}")

    # Step 8: Build dimension_details with reasoning
    dim_outputs = {
        "fundamental": fundamental,
        "technical": technical,
        "event_driven": event_driven,
    }

    # Extract sentiment reasoning
    if isinstance(sentiment_engine_output, dict):
        sent_reasoning = str(sentiment_engine_output.get("reasoning", ""))
    else:
        sent_reasoning = "Pre-normalized score (raw dict not available)"

    dimension_details: dict[str, dict[str, Any]] = {}
    for dim_key in ("fundamental", "technical", "event_driven"):
        out = dim_outputs[dim_key]
        dimension_details[dim_key] = {
            "score": scores[dim_key],
            "reasoning": out.get("reasoning", ""),
        }
    dimension_details["sentiment"] = {
        "score": scores["sentiment"],
        "reasoning": sent_reasoning,
    }

    return {
        "signal": signal,
        "weighted_score": round(weighted_score, 1),
        "dimension_scores": scores,
        "dimension_details": dimension_details,
        "soft_veto_triggered": soft_veto,
        "override_available": soft_veto,  # Override is available when veto exists
        "resonance_condition_met": resonance_met,
        "reasoning": " | ".join(parts),
    }