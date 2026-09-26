"""Platt scaling for LLM confidence calibration.

Reference: Platt, J. (1999) "Probabilistic Outputs for Support Vector Machines."
Applied to LLM confidence scores per KalshiBench findings (Nel, 2025):
all frontier LLMs are systematically overconfident at >=90% confidence.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class PlattCoefficients:
    a: float  # scale parameter
    b: float  # shift parameter
    fitted_at: str
    n_samples: int
    pre_calibration_ece: float
    post_calibration_ece: float


def fit_platt_scaling(
    confidences: list[float],
    outcomes: list[int],  # 1 = success, 0 = failure
    max_iter: int = 100,
) -> PlattCoefficients:
    """Fit Platt scaling coefficients using Newton's method.

    Platt scaling fits: P(correct | confidence=x) = 1 / (1 + exp(-(a*x + b)))

    Args:
        confidences: Raw model confidence scores [0, 1]
        outcomes: Binary outcomes (1=correct, 0=wrong)
        max_iter: Maximum Newton iterations

    Returns:
        PlattCoefficients with fitted a, b parameters
    """
    if len(confidences) != len(outcomes) or len(confidences) < 10:
        raise ValueError("Need at least 10 samples with matching confidence/outcome lists")

    # Initialize: a=0 (no scaling), b=0 (no shift)
    a, b = 0.0, 0.0
    lr = 0.5
    reg = 1e-3  # L2 regularization prevents divergence on clustered data

    for _ in range(max_iter):
        # Compute current predictions
        preds = [_sigmoid(a * x + b) for x in confidences]

        # Gradient
        errors = [outcomes[i] - preds[i] for i in range(len(confidences))]
        grad_a = sum(errors[i] * confidences[i] for i in range(len(confidences)))
        grad_b = sum(errors)

        # Full 2x2 Hessian (Fisher information) with L2 penalty
        weights = [preds[i] * (1 - preds[i]) for i in range(len(confidences))]
        h_aa = -(sum(weights[i] * confidences[i] * confidences[i] for i in range(len(confidences))) + reg)
        h_ab = -(sum(weights[i] * confidences[i] for i in range(len(confidences))))
        h_bb = -(sum(weights) + reg)

        # Newton step: H_inv * grad
        det = h_aa * h_bb - h_ab * h_ab
        if det == 0:
            break
        da = (h_bb * grad_a - h_ab * grad_b) / det
        db = (h_aa * grad_b - h_ab * grad_a) / det

        # Update with learning rate
        a -= lr * da
        b -= lr * db

        # Convergence check
        if abs(grad_a) < 1e-6 and abs(grad_b) < 1e-6:
            break

    # Compute ECE before and after
    pre_ece = _compute_ece(confidences, outcomes)
    calibrated = [_sigmoid(a * x + b) for x in confidences]
    post_ece = _compute_ece(calibrated, outcomes)

    return PlattCoefficients(
        a=a, b=b,
        fitted_at=datetime.now(timezone.utc).isoformat(),
        n_samples=len(confidences),
        pre_calibration_ece=pre_ece,
        post_calibration_ece=post_ece,
    )


def apply_platt_scaling(confidence: float, coeffs: PlattCoefficients) -> float:
    """Apply fitted Platt scaling to a raw confidence score.

    Returns calibrated probability in [0, 1].
    """
    return _sigmoid(coeffs.a * confidence + coeffs.b)


def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    else:
        exp_x = math.exp(x)
        return exp_x / (1.0 + exp_x)


def _compute_ece(confidences: list[float], outcomes: list[int], n_buckets: int = 10) -> float:
    """Expected Calibration Error."""
    buckets = {i: {"sum_conf": 0.0, "sum_outcome": 0, "count": 0} for i in range(n_buckets)}
    for conf, out in zip(confidences, outcomes):
        bucket = min(int(conf * n_buckets), n_buckets - 1)
        buckets[bucket]["sum_conf"] += conf
        buckets[bucket]["sum_outcome"] += out
        buckets[bucket]["count"] += 1

    total = len(confidences)
    ece = 0.0
    for b in buckets.values():
        if b["count"] == 0:
            continue
        acc = b["sum_outcome"] / b["count"]
        avg_conf = b["sum_conf"] / b["count"]
        ece += abs(acc - avg_conf) * (b["count"] / total)

    return ece
