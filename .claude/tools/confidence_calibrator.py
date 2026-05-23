"""
Confidence Calibrator — lightweight library for User Proxy Agent confidence calibration.

NOT a hook. This is a standalone module that provides:
  - Warmup-phase confidence clamping (max 0.70 for first 50 decisions)
  - Platt scaling calibration via sklearn logistic regression (post-warmup, if Brier > 0.05)
  - Consequence-weighted confidence adjustment
  - Brier score tracking per decision_type

Storage: .claude/state/calibration_curves.json
"""

import json
import os
import math
import copy
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_STATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state")
_CALIBRATION_PATH = os.path.join(_STATE_DIR, "calibration_curves.json")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MIN_DECISIONS_FOR_CALIBRATION = 50
BRIER_THRESHOLD = 0.05

CONSEQUENCE_WEIGHTS = {
    "cosmetic": 1.5,        # auto-execute more
    "moderate": 1.0,         # standard
    "significant": 0.7,      # auto-execute less
    "critical": 0.5,         # auto-execute rarely
}

_DEFAULT_STATE = {
    "schema_version": "1.0",
    "curves": {},
    "decision_counts": {},
    "warmup": True,
    "warmup_decisions_remaining": 50,
    "max_confidence_during_warmup": 0.70,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    """Load calibration curves from disk. Creates default if missing or corrupted."""
    try:
        with open(_CALIBRATION_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Validate essential keys exist
        for key in _DEFAULT_STATE:
            if key not in data:
                data[key] = copy.deepcopy(_DEFAULT_STATE[key])
        return data
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        return copy.deepcopy(_DEFAULT_STATE)


def _save_state(data: dict) -> None:
    """Atomically write calibration state to disk."""
    os.makedirs(_STATE_DIR, exist_ok=True)
    tmp_path = _CALIBRATION_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, _CALIBRATION_PATH)


def _compute_brier(observations: list) -> float:
    """Compute Brier score from a list of {predicted, accepted} dicts.

    Brier = (1/N) * sum((p_i - o_i)^2).  Lower is better; 0 = perfect calibration.
    """
    if not observations:
        return 0.0
    total = 0.0
    for obs in observations:
        pred = obs["predicted"]
        outcome = 1.0 if obs["accepted"] else 0.0
        total += (pred - outcome) ** 2
    return total / len(observations)


def _apply_platt_curve(raw_score: float, curve: dict) -> float:
    """Apply a stored Platt scaling curve to a raw confidence score.

    curve = { "coef_": [a], "intercept_": b }
    calibrated = 1 / (1 + exp(-(a * raw_score + b)))
    """
    a = curve["coef_"][0]
    b = curve["intercept_"][0] if isinstance(curve["intercept_"], list) else curve["intercept_"]
    logit = a * raw_score + b
    # Clip to avoid overflow
    logit = max(-50.0, min(50.0, logit))
    return 1.0 / (1.0 + math.exp(-logit))


def _fit_platt_scaling(state: dict, decision_type: str) -> None:
    """Fit Platt scaling (logistic regression) on stored observations.

    Requires sklearn. If sklearn is unavailable, calibration is skipped gracefully.
    Stores coefficients in state["curves"][decision_type].
    """
    try:
        from sklearn.linear_model import LogisticRegression
        import numpy as np
    except ImportError:
        # sklearn unavailable — calibration skipped; raw scores used as-is
        return

    observations = state["decision_counts"][decision_type]["observations"]
    if len(observations) < MIN_DECISIONS_FOR_CALIBRATION:
        return

    X = np.array([[obs["predicted"]] for obs in observations])
    y = np.array([1.0 if obs["accepted"] else 0.0 for obs in observations])

    # Ensure both classes present for logistic regression
    if len(set(y)) < 2:
        # All outcomes identical — cannot fit meaningful calibration
        return

    model = LogisticRegression(solver="lbfgs")
    model.fit(X, y)

    state["curves"][decision_type] = {
        "fitted_at_n": len(observations),
        "coef_": model.coef_.tolist(),
        "intercept_": model.intercept_.tolist(),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calibrate_confidence(raw_score: float, decision_type: str, consequence: str = "moderate") -> float:
    """Return a calibrated confidence score in [0, 1].

    Steps:
      1. During warmup: clamp max to max_confidence_during_warmup (0.70).
      2. After warmup: apply stored Platt scaling curve for decision_type if available.
      3. Apply consequence weight multiplier.
      4. Clamp to [0, 1].

    Parameters
    ----------
    raw_score : float
        Raw confidence score (0.0 to 1.0) from the proxy agent.
    decision_type : str
        Category of decision (e.g. "naming", "architecture", "dependency").
    consequence : str
        One of "cosmetic", "moderate", "significant", "critical".

    Returns
    -------
    float
        Calibrated and consequence-weighted confidence in [0, 1].
    """
    state = _load_state()

    # Step 1: warmup clamping
    if state["warmup"]:
        score = min(raw_score, state["max_confidence_during_warmup"])
    else:
        # Step 2: apply calibration curve if available
        curve = state["curves"].get(decision_type)
        if curve and "coef_" in curve and "intercept_" in curve:
            score = _apply_platt_curve(raw_score, curve)
        else:
            score = raw_score

    # Step 3: consequence weighting
    weight = CONSEQUENCE_WEIGHTS.get(consequence, 1.0)
    adjusted = score * weight

    # Step 4: final clamp
    return max(0.0, min(1.0, adjusted))


def record_outcome(decision_type: str, predicted_confidence: float, was_accepted: bool) -> None:
    """Record a decision outcome for Brier score tracking and eventual Platt scaling.

    Automatically checks whether the calibration threshold is met and fits
    Platt scaling if Brier > BRIER_THRESHOLD.

    Parameters
    ----------
    decision_type : str
        Category of the decision.
    predicted_confidence : float
        The raw (uncalibrated) confidence score that was predicted.
    was_accepted : bool
        True if the decision was accepted / correct; False otherwise.
    """
    state = _load_state()

    # Ensure entry exists
    if decision_type not in state["decision_counts"]:
        state["decision_counts"][decision_type] = {"total": 0, "observations": []}

    state["decision_counts"][decision_type]["total"] += 1
    state["decision_counts"][decision_type]["observations"].append({
        "predicted": predicted_confidence,
        "accepted": was_accepted,
    })

    # Check if we should attempt calibration
    total = state["decision_counts"][decision_type]["total"]
    if total >= MIN_DECISIONS_FOR_CALIBRATION:
        brier = _compute_brier(state["decision_counts"][decision_type]["observations"])
        if brier > BRIER_THRESHOLD:
            _fit_platt_scaling(state, decision_type)

    _save_state(state)


def check_warmup() -> bool:
    """Check whether the calibrator is still in warmup mode.

    Decrements the warmup counter. Once it reaches zero, warmup ends permanently.

    Returns
    -------
    bool
        True if still in warmup; False if warmup is complete.
    """
    state = _load_state()

    if not state["warmup"]:
        return False

    state["warmup_decisions_remaining"] -= 1
    if state["warmup_decisions_remaining"] <= 0:
        state["warmup"] = False
        state["warmup_decisions_remaining"] = 0

    _save_state(state)
    return state["warmup"]


def get_calibration_status() -> dict:
    """Return current calibration status summary.

    Returns
    -------
    dict with keys:
      - warmup: bool — whether still in warmup phase
      - decisions_collected: int — total decisions recorded across all types
      - brier_score: float — overall Brier score (0.0 if no data)
      - curves_fitted: list[str] — decision_types with fitted calibration curves
    """
    state = _load_state()

    total_decisions = sum(
        v.get("total", 0) for v in state["decision_counts"].values()
    )

    # Aggregate all observations for overall Brier
    all_obs = []
    for v in state["decision_counts"].values():
        all_obs.extend(v.get("observations", []))

    brier = _compute_brier(all_obs) if all_obs else 0.0
    curves_fitted = list(state["curves"].keys())

    return {
        "warmup": state["warmup"],
        "decisions_collected": total_decisions,
        "brier_score": round(brier, 4),
        "curves_fitted": curves_fitted,
    }


# ---------------------------------------------------------------------------
# Convenience: re-initialize (for testing / manual reset)
# ---------------------------------------------------------------------------

def reset_calibration() -> None:
    """Reset calibration state to defaults. Destroys all collected data."""
    _save_state(copy.deepcopy(_DEFAULT_STATE))
