"""Causal decomposition of investment hypotheses by asset class lens.
Phase H-1 Module 1 — decomposes hypotheses into directional factors using
the correct decomposition lens based on asset class routing.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from marketmind.config.asset_class_routing import ASSET_CLASSES, route_asset_class
from marketmind.config.investigation_config import MAX_PRO_CALLS_PER_SESSION
from marketmind.gateway.async_client import chat_pro, get_budget
from marketmind.pipeline.investigation_types import HypothesisResult

logger = logging.getLogger(__name__)

# ── CausalDecomposition dataclass ──────────────────────────────────────────────

@dataclass
class CausalDecomposition:
    hypothesis: str
    asset_class: str                     # class_id from routing
    decomposition_lens: str             # which method was used
    factors: list[tuple[str, float]]    # [(factor_name, impact -1 to +1)]
    net_directional_force: float        # -1 to +1, meaning depends on asset_class
    mechanism_chain: list[str]           # causal chain steps
    confidence: float                    # 0-1 how confident the decomposition is


# ── Decomposition system prompts by lens ──────────────────────────────────────

_DECOMPOSITION_PROMPTS: dict[str, str] = {
    "balance_sheet": (
        "Decompose into asset-side and liability-side factors on the Fed balance sheet: "
        "Treasury supply (UST issuance, TGA balance), RRP drain, Fed holdings trajectory "
        "(QT/QE), bank reserve levels, and foreign official demand. Direction: -1 means "
        "bearish for US fixed income (yields up, prices down), +1 means bullish "
        "(yields down, prices up)."
    ),
    "earnings_discount_rate": (
        "Decompose into earnings drivers (revenue growth, margin trends, buyback activity), "
        "discount rate factors (risk-free rate, equity risk premium, credit spreads), and "
        "fund flow components (retail flows, institutional positioning, foreign flows). "
        "Direction: -1 means bearish for US equities, +1 means bullish."
    ),
    "supply_demand_inventory": (
        "Decompose into supply factors (production levels, OPEC+ quotas, shale output), "
        "demand factors (global GDP, industrial activity, seasonal patterns), inventory "
        "levels (EIA stocks, SPR, exchange warehouses), and geopolitical risk premia. "
        "Direction: -1 means bearish for commodity prices, +1 means bullish."
    ),
    "dual_central_bank_carry": (
        "Decompose into Central Bank A policy trajectory (rate path, forward guidance), "
        "Central Bank B policy trajectory, carry trade dynamics (rate differential, "
        "volatility regime), corporate hedging flows, and sovereign fund activity. "
        "Direction: -1 means bearish for the base currency (first in pair), +1 means bullish."
    ),
    "onchain_offchain": (
        "Decompose into on-chain factors (hash rate, active addresses, exchange reserves, "
        "miner flows, staking yields) and off-chain factors (ETF flows, regulatory "
        "developments, institutional custody, macro correlation, stablecoin issuance). "
        "Direction: -1 means bearish for the crypto asset, +1 means bullish."
    ),
    "ecb_policy_earnings": (
        "Decompose into ECB policy factors (rate path, PEPP reinvestment, TPI readiness), "
        "European earnings drivers (export competitiveness, energy costs, EU fiscal "
        "coordination), and global allocator flows into European equities. "
        "Direction: -1 means bearish for European equities, +1 means bullish."
    ),
    "boj_gpif_carry": (
        "Decompose into BOJ policy factors (rate path, YCC trajectory, JGB purchase pace), "
        "GPIF allocation shifts, yen carry trade dynamics (funding currency flows), "
        "corporate governance reform premium, and foreign hedge fund positioning. "
        "Direction: -1 means bearish for Japanese equities, +1 means bullish."
    ),
    "dollar_cycle_capital_flow": (
        "Decompose into DXY cycle positioning, EM capital flow pressures (EPFR flows, "
        "bond fund flows), sovereign credit conditions (EMBI spreads, IMF program status), "
        "China credit impulse transmission, and commodity price pass-through for EM terms of trade. "
        "Direction: -1 means bearish for EM assets (capital outflow pressure), +1 means bullish (inflow)."
    ),
    "capital_controls_carry_reserve": (
        "Decompose into carry attractiveness (rate differential vs USD), capital control "
        "risk (repatriation restrictions, NDF market premia), reserve adequacy metrics "
        "(IMF ARA, import cover), sovereign default risk, and speculative positioning. "
        "Direction: -1 means bearish for the EM currency (depreciation pressure), +1 means bullish."
    ),
}

_DEFAULT_DECOMPOSITION_PROMPT = (
    "Decompose into structural drivers (long-term trends, institutional changes, demographic "
    "shifts) and cyclical drivers (business cycle phase, monetary policy stance, sentiment "
    "extremes). Direction: -1 means bearish, +1 means bullish."
)


def _extract_tickers(text: str) -> list[str]:
    """Extract known ticker symbols from hypothesis text."""
    ticker_set: set[str] = set()
    text_upper = text.upper()
    for config in ASSET_CLASSES.values():
        for ticker in config.tickers:
            if ticker.upper() in text_upper:
                ticker_set.add(ticker)
    return list(ticker_set) if ticker_set else []


def _clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _parse_decomposition_json(content: str) -> dict | None:
    """Parse Pro JSON response into dict with factors, mechanism_chain, etc."""
    if not content:
        return None
    content = content.strip()
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
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(content[start:end + 1])
            except json.JSONDecodeError:
                pass
    return None


# ── Main function ─────────────────────────────────────────────────────────────

async def decompose_hypothesis(
    hypothesis: HypothesisResult,
) -> CausalDecomposition | None:
    """Decompose a HypothesisResult into directional factors using the
    asset-class-appropriate decomposition lens.

    Returns None if asset class routing fails, budget is exhausted, or
    the Pro response cannot be parsed.
    """
    text = hypothesis.refined_hypothesis or hypothesis.hypothesis
    tickers = _extract_tickers(text)

    config, confidence = route_asset_class(text, tickers)
    if config is None or confidence < 0.3:
        logger.info(
            "Causal decomposition skipped: asset class routing failed "
            "(confidence=%.2f, text=%s)", confidence, text[:80]
        )
        return None

    decomposition_lens = config.decomposition_lens
    system_base = _DECOMPOSITION_PROMPTS.get(
        decomposition_lens, _DEFAULT_DECOMPOSITION_PROMPT
    )

    system_prompt = (
        f"{system_base}\n\n"
        "Return a single JSON object with these keys:\n"
        '  "factors": list of {{"name": str, "impact": float}} (3-5 items, -1 to +1)\n'
        '  "net_directional_force": float (-1 to +1, the overall directional signal)\n'
        '  "mechanism_chain": list of strings (causal steps connecting factors)\n'
        '  "confidence": float (0-1, how confident you are in this decomposition)\n'
        "Output ONLY the JSON object, no markdown, no explanation."
    )

    user_prompt = (
        f"Hypothesis: {text}\n"
        f"Asset class: {config.name} ({config.class_id})\n"
        f"Decomposition lens: {decomposition_lens}\n"
        f"Directional meaning: {config.net_directional_force}\n"
        f"Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
    )

    # Budget check
    try:
        budget = await get_budget()
        if not budget.can_call_pro():
            logger.warning(
                "Causal decomposition skipped: Pro call budget exhausted "
                "(remaining=%d, limit=%d)",
                budget.pro_calls_remaining, MAX_PRO_CALLS_PER_SESSION,
            )
            return None
    except RuntimeError:
        logger.debug("Budget not initialized, proceeding with chat_pro")

    response = await chat_pro(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.3,
        max_tokens=1024,
    )

    if response.get("error"):
        logger.warning("Causal decomposition: chat_pro error: %s", response["error"])
        return None

    content = response.get("content", "")
    parsed = _parse_decomposition_json(content)
    if parsed is None:
        logger.warning("Causal decomposition: failed to parse Pro response JSON")
        return None

    try:
        raw_factors: list[dict] = parsed.get("factors", [])
        factors: list[tuple[str, float]] = [
            (f["name"], _clamp(float(f["impact"])))
            for f in raw_factors
            if f.get("name")
        ]

        net_directional_force = _clamp(float(parsed.get("net_directional_force", 0)))
        mechanism_chain: list[str] = parsed.get("mechanism_chain", [])
        parsed_confidence = _clamp(float(parsed.get("confidence", 0.5)), 0.0, 1.0)
    except (KeyError, TypeError, ValueError) as e:
        logger.warning("Causal decomposition: invalid JSON structure: %s", e)
        return None

    if len(factors) < 2:
        logger.warning("Causal decomposition: insufficient factors (%d)", len(factors))
        return None

    return CausalDecomposition(
        hypothesis=text,
        asset_class=config.class_id,
        decomposition_lens=decomposition_lens,
        factors=factors,
        net_directional_force=net_directional_force,
        mechanism_chain=mechanism_chain,
        confidence=parsed_confidence,
    )
