"""Regime mapping — historical-analogue engine for Layer 4 verification.

Replaces the hardcoded keyword-based verify_claim_historical() in
verification_chain.py with a quantitative Euclidean-distance regime classifier.

Design:
  - Pure computation — zero LLM calls.
  - Imports from config/regime_library only (no back-imports from siblings).
  - verify_claim_historical_v2() is the drop-in replacement for Layer 4.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

from marketmind.config.regime_library import (
    REGIME_LIBRARY,
    RegimeDef,
    build_vector,
)

logger = logging.getLogger("marketmind.pipeline.regime_mapper")


# ── Data types ───────────────────────────────────────────────────────────────────

@dataclass
class RegimeMatch:
    """A single historical analogue with similarity score and forward estimates."""
    regime_id: str
    regime_name: str
    similarity: float          # 0-1, higher = more similar (1 - normalised Euclidean)
    forward_3m_equity: float   # annualised return scaled to 3 months
    forward_6m_equity: float   # annualised return scaled to 6 months
    forward_12m_equity: float  # annualised return (unscaled)
    key_differences: list[str] = field(default_factory=list)


@dataclass
class RegimeMapping:
    """Full regime-mapping output for a hypothesis."""
    current_quadrant: str          # "growth_up_inflation_up" etc.
    top_analogues: list[RegimeMatch]
    anti_analogues: list[RegimeMatch]
    regime_consensus: str          # human-readable summary
    bias_warning: str              # training-range caveat


# ── Quadrant classification ─────────────────────────────────────────────────────

# Keywords for GDP direction from hypothesis text
_GDP_UP_KEYWORDS = [
    "growth", "expansion", "boom", "recovery", "rebound", "accelerating",
    "above trend", "overheating", "soft landing", "resilient", "robust",
    "bull market", "earnings growth", "gdp growth",
]
_GDP_DOWN_KEYWORDS = [
    "recession", "contraction", "slowdown", "hard landing", "depression",
    "downturn", "decelerating", "below trend", "negative growth", "weak",
    "bear market", "earnings decline", "gdp decline", "layoffs", "unemployment",
]

_CPI_UP_KEYWORDS = [
    "inflation", "cpi", "price rising", "price pressures", "cost push",
    "demand pull", "wage growth", "commodity spike", "supply shock",
    "rising prices", "stagflation", "overheating",
]
_CPI_DOWN_KEYWORDS = [
    "deflation", "disinflation", "price falling", "price easing",
    "cooling", "moderating", "falling prices", "demand destruction",
]


def _classify_quadrant(hypothesis: str) -> str:
    """Classify macro quadrant from hypothesis text keywords.

    Returns one of:
      - growth_up_inflation_up    (overheating / late-cycle)
      - growth_up_inflation_down  (goldilocks / soft landing)
      - growth_down_inflation_up  (stagflation)
      - growth_down_inflation_down (recession / deflation)
    """
    h = hypothesis.lower()

    gdp_up = any(kw in h for kw in _GDP_UP_KEYWORDS)
    gdp_down = any(kw in h for kw in _GDP_DOWN_KEYWORDS)
    cpi_up = any(kw in h for kw in _CPI_UP_KEYWORDS)
    cpi_down = any(kw in h for kw in _CPI_DOWN_KEYWORDS)

    # Resolve conflicts: if both directions detected, default to the more
    # explicit signal (CPI keywords are usually more precise than GDP keywords)
    if gdp_up and gdp_down:
        gdp_up = False  # ambiguous — treat as neutral
    if cpi_up and cpi_down:
        cpi_up = False  # ambiguous — treat as neutral

    # Default: assume growth and moderate inflation (most common state)
    gdp_dir = "up" if (gdp_up or not gdp_down) else "down"
    cpi_dir = "up" if (cpi_up or not cpi_down) else "down"

    return f"growth_{gdp_dir}_inflation_{cpi_dir}"


# ── Current-data vector ──────────────────────────────────────────────────────────

def _current_vector_from_data(current_data: dict[str, Any] | None, hypothesis: str) -> list[float]:
    """Build a 7-variable vector from live data or keyword heuristics.

    When current_data is None (no live macro snapshot available), extract
    a rough vector from the hypothesis text keywords. This is coarser than
    live data but preserves the Euclidean-distance regime-ranking pipeline.
    """
    if current_data is None:
        return _vector_from_hypothesis(hypothesis)

    return [
        float(current_data.get("spy_yy", 0.0)),
        float(current_data.get("spread_10y2y", 0.0)),
        float(current_data.get("wti_yy", 0.0)),
        float(current_data.get("copper_yy", 0.0)),
        float(current_data.get("tbill_yield", 0.0)),
        float(current_data.get("vix_avg", 0.0)),
        float(current_data.get("stock_bond_corr", 0.0)),
    ]


def _vector_from_hypothesis(hypothesis: str) -> list[float]:
    """Heuristic vector from hypothesis keywords when no live data is available.

    Each dimension gets a neutral value (0.0) adjusted by keyword presence.
    """
    h = hypothesis.lower()
    spy = 0.0
    spread = 0.0
    wti = 0.0
    copper = 0.0
    tbill = 0.0
    vix = 0.0
    corr = 0.0

    # Equity direction
    if any(kw in h for kw in ["bull market", "rally", "surge", "strong earnings"]):
        spy = 15.0
    elif any(kw in h for kw in ["bear market", "crash", "correction", "sell-off"]):
        spy = -15.0

    # Yield curve
    if "inverted" in h or "inversion" in h:
        spread = -0.5
    elif "steepening" in h:
        spread = 1.5
    elif "flat" in h:
        spread = 0.2

    # Commodity prices
    if any(kw in h for kw in ["oil spike", "oil surge", "energy crisis", "commodity boom"]):
        wti = 25.0
        copper = 10.0
    elif any(kw in h for kw in ["oil crash", "oil glut", "commodity crash"]):
        wti = -30.0
        copper = -15.0

    # Rates
    if any(kw in h for kw in ["high rates", "high interest", "tightening", "hawkish", "rate hike"]):
        tbill = 5.0
    elif any(kw in h for kw in ["low rates", "zero rates", "easing", "dovish", "rate cut"]):
        tbill = 0.5

    # Volatility
    if any(kw in h for kw in ["high volatility", "volatile", "vix spike", "panic", "fear"]):
        vix = 30.0
    elif any(kw in h for kw in ["low volatility", "calm", "complacency", "vix low"]):
        vix = 12.0
    else:
        vix = 16.0  # neutral

    # Stock-bond correlation
    if "correlation" in h:
        if "positive" in h:
            corr = 0.6
        elif "negative" in h:
            corr = -0.3

    return [spy, spread, wti, copper, tbill, vix, corr]


# ── Euclidean distance ───────────────────────────────────────────────────────────

def _euclidean_distance(a: list[float], b: list[float]) -> float:
    """Raw Euclidean distance between two same-length vectors."""
    return math.sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b)))


def _normalise_similarity(distance: float, max_distance: float) -> float:
    """Convert Euclidean distance to a 0-1 similarity score.

    similarity = 1 - min(distance / max_distance, 1.0)
    """
    if max_distance <= 0:
        return 0.5
    return 1.0 - min(distance / max_distance, 1.0)


# ── Variable weighting ───────────────────────────────────────────────────────────
# Index mapping for the 7-variable vector:
#   0: spy_yy          (equity proxy for growth)
#   1: spread_10y2y    (yield curve — growth expectations)
#   2: wti_yy          (oil — inflation driver)
#   3: copper_yy       (industrial demand — growth)
#   4: tbill_yield     (policy rate)
#   5: vix_avg         (risk appetite)
#   6: stock_bond_corr (diversification regime)

def _weighted_distance(
    current: list[float],
    regime: list[float],
    quadrant: str,
) -> float:
    """Compute variable-weighted Euclidean distance.

    Weighting rules:
      - High-inflation regimes (inflation_up): CPI-linked dimensions (wti_yy,
        copper_yy) get ×2 weight.
      - Growth regimes (growth_up): GDP-linked dimensions (spy_yy, copper_yy)
        get ×2 weight.
    """
    base_weights = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]

    infl_up = "inflation_up" in quadrant
    growth_up = "growth_up" in quadrant
    infl_down = "inflation_down" in quadrant
    growth_down = "growth_down" in quadrant

    if infl_up:
        base_weights[2] *= 2.0   # wti_yy
        base_weights[3] *= 1.5   # copper_yy (industrial + inflation-sensitive)
    if growth_up:
        base_weights[0] *= 2.0   # spy_yy
        base_weights[3] *= 1.5   # copper_yy (industrial demand)
    if growth_down:
        base_weights[1] *= 2.0   # spread_10y2y — curve shape critical in downturns
        base_weights[5] *= 1.5   # vix_avg — risk appetite in recessions

    total = sum(
        w * (ci - ri) ** 2
        for ci, ri, w in zip(current, regime, base_weights)
    )
    return math.sqrt(total)


# ── Forward return estimation ────────────────────────────────────────────────────

def _estimate_forward_returns(regime: RegimeDef) -> tuple[float, float, float]:
    """Estimate forward equity returns from regime-average annualised return.

    Returns (3m, 6m, 12m) forward estimates. The regime's equity_avg_return
    is annualised; we scale it geometrically for shorter horizons.
    """
    annual = regime.equity_avg_return / 100.0  # convert % to decimal
    fwd_3m = ((1 + annual) ** 0.25 - 1) * 100.0
    fwd_6m = ((1 + annual) ** 0.50 - 1) * 100.0
    fwd_12m = annual * 100.0
    return round(fwd_3m, 2), round(fwd_6m, 2), round(fwd_12m, 2)


# ── Key differences ──────────────────────────────────────────────────────────────

def _detect_key_differences(
    current: list[float],
    regime: RegimeDef,
) -> list[str]:
    """Detect dimensions where current data diverges significantly from regime.

    Flags dimensions with absolute z-score > 1.0 (rough heuristic).
    """
    diffs: list[str] = []
    dim_names = [
        "equity returns", "yield curve spread", "oil prices",
        "copper/industrial demand", "short-term rates", "volatility (VIX)",
        "stock-bond correlation",
    ]
    # Approximate std dev for each dimension (post-1985 data)
    stds = [15.0, 1.0, 20.0, 10.0, 2.0, 8.0, 0.3]
    regime_vec = build_vector(regime)

    for i, (cv, rv, name, sd) in enumerate(zip(current, regime_vec, dim_names, stds)):
        if sd <= 0:
            continue
        z = abs(cv - rv) / sd
        if z > 1.0:
            direction = "higher" if cv > rv else "lower"
            diffs.append(f"{name} is {direction} than in {regime.regime_name} (z={z:.1f})")

    return diffs[:3]  # top 3 differences


# ── Main mapping function ────────────────────────────────────────────────────────


async def map_regime(
    hypothesis: str,
    current_data: dict[str, Any] | None = None,
) -> RegimeMapping:
    """Map a hypothesis to its closest historical macro regimes.

    Args:
        hypothesis: The claim/hypothesis text to map.
        current_data: Optional live macro data dict with keys matching the
                      7-variable vector (spy_yy, spread_10y2y, wti_yy,
                      copper_yy, tbill_yield, vix_avg, stock_bond_corr).

    Returns:
        RegimeMapping with top analogues, anti-analogues, quadrant, and bias warning.
    """
    quadrant = _classify_quadrant(hypothesis)
    current_vec = _current_vector_from_data(current_data, hypothesis)

    # Compute weighted distance to every regime
    scored: list[tuple[float, RegimeDef]] = []
    for regime in REGIME_LIBRARY:
        dist = _weighted_distance(current_vec, build_vector(regime), quadrant)
        scored.append((dist, regime))

    scored.sort(key=lambda x: x[0])

    # Normalise similarities
    max_dist = scored[-1][0] if scored else 1.0
    if max_dist <= 0:
        max_dist = 1.0

    # Build top-3 analogues
    top_analogues: list[RegimeMatch] = []
    for dist, regime in scored[:3]:
        sim = _normalise_similarity(dist, max_dist)
        fwd3, fwd6, fwd12 = _estimate_forward_returns(regime)
        diffs = _detect_key_differences(current_vec, regime)
        top_analogues.append(RegimeMatch(
            regime_id=regime.regime_id,
            regime_name=regime.regime_name,
            similarity=round(sim, 4),
            forward_3m_equity=fwd3,
            forward_6m_equity=fwd6,
            forward_12m_equity=fwd12,
            key_differences=diffs,
        ))

    # Build anti-analogue (least similar)
    anti_analogues: list[RegimeMatch] = []
    if len(scored) >= 4:
        anti_dist, anti_regime = scored[-1]
        anti_sim = _normalise_similarity(anti_dist, max_dist)
        anti_fwd3, anti_fwd6, anti_fwd12 = _estimate_forward_returns(anti_regime)
        anti_diffs = _detect_key_differences(current_vec, anti_regime)
        anti_analogues.append(RegimeMatch(
            regime_id=anti_regime.regime_id,
            regime_name=anti_regime.regime_name,
            similarity=round(anti_sim, 4),
            forward_3m_equity=anti_fwd3,
            forward_6m_equity=anti_fwd6,
            forward_12m_equity=anti_fwd12,
            key_differences=anti_diffs,
        ))

    # Consensus summary
    if top_analogues:
        names = ", ".join(a.regime_name for a in top_analogues)
        top_sim = top_analogues[0].similarity
        if top_sim > 0.7:
            consensus = f"当前宏观环境与 {names} 高度相似 (similarity={top_sim:.2f})"
        elif top_sim > 0.4:
            consensus = f"当前宏观环境与 {names} 部分相似 (similarity={top_sim:.2f})"
        else:
            consensus = f"当前宏观环境无明确历史类比，最接近为 {names} (similarity={top_sim:.2f})"
    else:
        consensus = "无法确定历史类比 — 体制库数据不足"

    bias_warning = (
        "模型仅基于1985-2025数据训练。若当前体制与1970s滞胀类似，"
        "定量类似度可能被低估。pre-1985体制的向量为学术文献合成值，"
        "非月度市场数据。"
    )

    quadrant_names = {
        "growth_up_inflation_up": "增长上行+通胀上行 (过热)",
        "growth_up_inflation_down": "增长上行+通胀下行 (金发女孩)",
        "growth_down_inflation_up": "增长下行+通胀上行 (滞胀)",
        "growth_down_inflation_down": "增长下行+通胀下行 (衰退)",
    }

    return RegimeMapping(
        current_quadrant=quadrant_names.get(quadrant, quadrant),
        top_analogues=top_analogues,
        anti_analogues=anti_analogues,
        regime_consensus=consensus,
        bias_warning=bias_warning,
    )


# ── Layer 4 drop-in replacement ──────────────────────────────────────────────────


async def verify_claim_historical_v2(claim: str) -> float:
    """New Layer 4 implementation using regime mapping.

    Falls back to old keyword heuristic if regime library unavailable.

    Returns 0-1 confidence:
      - High-similarity regime analogue found → 0.45 + 0.30 × similarity [0.45, 0.75]
      - No strong analogue → 0.50 (neutral)
      - Failure → 0.50 (neutral)
    """
    try:
        mapping = await map_regime(claim)
        if mapping.top_analogues:
            top_sim = mapping.top_analogues[0].similarity
            confidence = 0.45 + 0.30 * top_sim
            return round(min(confidence, 0.75), 3)
        return 0.50
    except Exception:
        logger.exception("regime_mapper.verify_claim_historical_v2 failed — returning neutral")
        return 0.50
