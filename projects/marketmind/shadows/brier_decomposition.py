"""Brier score ternary decomposition (Dimitriadis "The Triptych", arXiv:2301.10803).

Decomposes the Brier score into three interpretable components:
  - MCB (miscalibration): How well-calibrated are the predicted probabilities?
  - DSC (discrimination / resolution): How well do predictions separate outcomes?
  - UNC (uncertainty): Inherent uncertainty in the outcome distribution.

BS = MCB + DSC - UNC

Classifies into Eagle/Bull/Sloth/Mole personality types based on
miscalibration and discrimination trade-offs (Manokhin taxonomy).

Phase D Module 4 — Analysis Middleware. Zero LLM dependencies.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger("marketmind.shadows.brier_decomposition")


@dataclass
class BrierDecomposition:
    """Ternary decomposition of the Brier score.

    BS = MCB + DSC - UNC  (Dimitriadis et al., arXiv:2301.10803)

    Attributes:
        brier_score: Mean squared error between probabilities and outcomes.
        mcb: Miscalibration component (lower is better, 0 = perfect calibration).
        dsc: Discrimination component (higher is better, captures resolution).
        unc: Uncertainty component (inherent variability, base-rate dependent).
        manokhin_type: Classification — Eagle, Bull, Sloth, or Mole.
    """
    brier_score: float
    mcb: float      # miscalibration
    dsc: float      # discrimination
    unc: float      # uncertainty
    manokhin_type: str  # Eagle / Bull / Sloth / Mole


def decompose_brier(
    probabilities: list[float],
    outcomes: list[int],
    n_bins: int = 10,
) -> BrierDecomposition:
    """Decompose Brier score into MCB, DSC, UNC components.

    Uses the method from Dimitriadis et al. "The Triptych" (arXiv:2301.10803):
    - BS  = (1/N) * sum((p_i - o_i)^2)
    - MCB = (1/N) * sum_k n_k * (p_bar_k - o_bar_k)^2  (reliability)
    - DSC = (1/N) * sum_k n_k * (o_bar_k - o_bar)^2     (resolution)
    - UNC = o_bar * (1 - o_bar)                          (uncertainty)

    The identity BS = MCB + DSC - UNC holds up to binning approximation.

    Args:
        probabilities: Predicted probabilities in [0, 1].
        outcomes: Binary outcomes {0, 1}.
        n_bins: Number of bins for calibration decomposition (default 10).

    Returns:
        BrierDecomposition with all components and Manokhin classification.

    Raises:
        ValueError: If inputs have different lengths or are empty.
    """
    if len(probabilities) != len(outcomes):
        raise ValueError(
            f"probabilities and outcomes must have same length, "
            f"got {len(probabilities)} vs {len(outcomes)}"
        )
    if len(probabilities) == 0:
        raise ValueError("Input arrays must not be empty")

    probs = np.asarray(probabilities, dtype=np.float64)
    outs = np.asarray(outcomes, dtype=np.float64)

    # Overall mean outcome (base rate)
    o_bar = float(np.mean(outs))

    # Brier score: mean squared error
    bs = float(np.mean((probs - outs) ** 2))

    # Uncertainty: base-rate variance
    unc = o_bar * (1.0 - o_bar)

    # Reliability bins for MCB and DSC
    n = len(probs)
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    mcb = 0.0
    dsc = 0.0

    for k in range(n_bins):
        # Find predictions in this bin
        in_bin = (probs >= bin_edges[k]) & (probs < bin_edges[k + 1])
        # Include rightmost edge in last bin
        if k == n_bins - 1:
            in_bin = (probs >= bin_edges[k]) & (probs <= bin_edges[k + 1])

        n_k = int(np.sum(in_bin))
        if n_k == 0:
            continue

        p_bar_k = float(np.mean(probs[in_bin]))
        o_bar_k = float(np.mean(outs[in_bin]))

        # MCB: reliability — avg calibration within bin
        mcb += n_k * (p_bar_k - o_bar_k) ** 2

        # DSC: resolution — how much bin outcomes deviate from base rate
        dsc += n_k * (o_bar_k - o_bar) ** 2

    mcb /= n
    dsc /= n

    # Classify into Manokhin taxonomy
    manokhin_type = manokhin_classify(mcb, dsc)

    return BrierDecomposition(
        brier_score=round(bs, 6),
        mcb=round(mcb, 6),
        dsc=round(dsc, 6),
        unc=round(unc, 6),
        manokhin_type=manokhin_type,
    )


def manokhin_classify(
    mcb: float,
    dsc: float,
    threshold: float = 0.05,
) -> str:
    """Classify predictor into Manokhin behavioral taxonomy.

    Based on the trade-off between miscalibration (MCB) and discrimination (DSC):

    - **Eagle**: Low miscalibration, high discrimination.
      Well-calibrated AND informative — the ideal predictor.

    - **Bull**: High miscalibration, high discrimination.
      Informative but overconfident — tends to predict extreme probabilities.

    - **Sloth**: Low miscalibration, low discrimination.
      Well-calibrated but uninformative — tends toward base-rate predictions.

    - **Mole**: High miscalibration, low discrimination.
      Neither calibrated nor informative — the worst quadrant.

    Args:
        mcb: Miscalibration component (0 = perfect calibration).
        dsc: Discrimination component (higher = better separation).
        threshold: Threshold for classifying "low" vs "high" (default 0.05).

    Returns:
        One of: "Eagle", "Bull", "Sloth", "Mole".
    """
    is_low_mcb = mcb <= threshold
    is_high_dsc = dsc >= threshold

    if is_low_mcb and is_high_dsc:
        return "Eagle"
    elif not is_low_mcb and is_high_dsc:
        return "Bull"
    elif is_low_mcb and not is_high_dsc:
        return "Sloth"
    else:
        return "Mole"


def decompose_brier_componentwise(
    probabilities: list[float],
    outcomes: list[int],
) -> dict[str, float]:
    """Detailed component-wise Brier decomposition with per-bin statistics.

    Returns a dictionary with per-bin calibration error and the standard
    components. Useful for debugging and visualization.

    Args:
        probabilities: Predicted probabilities in [0, 1].
        outcomes: Binary outcomes {0, 1}.

    Returns:
        Dict with keys: brier_score, mcb, dsc, unc, bins (list of per-bin dicts).
    """
    if len(probabilities) != len(outcomes):
        raise ValueError("Length mismatch")

    probs = np.asarray(probabilities, dtype=np.float64)
    outs = np.asarray(outcomes, dtype=np.float64)

    o_bar = float(np.mean(outs))
    bs = float(np.mean((probs - outs) ** 2))
    unc = o_bar * (1.0 - o_bar)

    n_bins = 10
    n = len(probs)
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)

    bins_detail = []
    mcb = 0.0
    dsc = 0.0

    for k in range(n_bins):
        in_bin = (probs >= bin_edges[k]) & (probs < bin_edges[k + 1])
        if k == n_bins - 1:
            in_bin = (probs >= bin_edges[k]) & (probs <= bin_edges[k + 1])

        n_k = int(np.sum(in_bin))
        if n_k == 0:
            continue

        p_bar_k = float(np.mean(probs[in_bin]))
        o_bar_k = float(np.mean(outs[in_bin]))

        bin_mcb = n_k * (p_bar_k - o_bar_k) ** 2 / n
        bin_dsc = n_k * (o_bar_k - o_bar) ** 2 / n

        mcb += bin_mcb
        dsc += bin_dsc

        bins_detail.append({
            "bin": k,
            "range": f"[{bin_edges[k]:.1f}, {bin_edges[k+1]:.1f})",
            "count": n_k,
            "mean_prob": round(p_bar_k, 4),
            "mean_outcome": round(o_bar_k, 4),
            "calibration_error": round(p_bar_k - o_bar_k, 4),
            "mcb_contribution": round(bin_mcb, 6),
            "dsc_contribution": round(bin_dsc, 6),
        })

    manokhin_type = manokhin_classify(mcb, dsc)

    return {
        "brier_score": round(bs, 6),
        "mcb": round(mcb, 6),
        "dsc": round(dsc, 6),
        "unc": round(unc, 6),
        "manokhin_type": manokhin_type,
        "base_rate": round(o_bar, 4),
        "n_samples": n,
        "bins": bins_detail,
        "identity_check": round(mcb + dsc - unc, 6),
    }
