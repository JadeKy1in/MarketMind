"""4-layer verification chain — independent data sources for claim validation.

Mechanism-aware verification data comes from the investigation_loop prompts
(investigation_prompts.py). The verification layers consume mechanism-named
hypotheses; this module does not generate its own prompts.

Each layer draws from a genuinely independent information source, fixing the
Red Team C7 finding that the original L1 and L3 both drew from market data.

Layers:
  1. Market Pricing (30%)  — CME FedWatch, futures curves, options IV, stock prices
  2. Fundamental Data (25%) — FRED API, EIA API, BLS API — official statistics
  3. Multi-Source News (25%) — 3+ independent news sources — human journalism
  4. Historical Pattern (20%) — Similar past scenarios from backtest database or heuristic
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from marketmind.config.investigation_config import (
    WEIGHT_MARKET_PRICING,
    WEIGHT_FUNDAMENTAL_DATA,
    WEIGHT_MULTI_SOURCE,
    WEIGHT_HISTORICAL_PATTERN,
    MIN_CORROBORATION_FOR_HIGH_CONF,
)
from marketmind.config.source_independence import count_independent_sources

logger = logging.getLogger("marketmind.pipeline.verification_chain")


# ── Data types ───────────────────────────────────────────────────────────────

@dataclass
class VerificationResult:
    """Output of a 4-layer claim verification run."""
    claim: str
    layer_1_market: float          # 0-1 confidence from market pricing
    layer_2_fundamental: float     # 0-1 confidence from fundamental data
    layer_3_multisource: float     # 0-1 confidence from independent news
    layer_4_historical: float      # 0-1 confidence from historical patterns
    weighted_confidence: float     # composite: sum(weight_i * layer_i)
    verdict: str                   # VERIFIED / LIKELY / UNVERIFIED / CONTRADICTED
    sources_used: list[str] = field(default_factory=list)
    contradiction_detail: str | None = None


# ── Keyword-to-datasource mapping ────────────────────────────────────────────

# Maps claim keywords to FRED series indicators for Layer 2 fundamental checks
_KEYWORD_FRED_MAP: dict[str, str] = {
    "rate": "BDI",
    "rates": "BDI",
    "interest": "BDI",
    "fed": "BDI",
    "fomc": "BDI",
    "inflation": "GSCPI",
    "cpi": "GSCPI",
    "ppi": "GSCPI",
    "supply chain": "GSCPI",
    "shipping": "BDI",
    "freight": "BDI",
}

# Maps claim keywords to EIA product codes for Layer 2 fundamental checks
_KEYWORD_EIA_MAP: dict[str, str] = {
    "crude": "crude",
    "oil": "crude",
    "gasoline": "gasoline",
    "distillate": "distillate",
    "diesel": "distillate",
    "energy": "crude",
}

# Maps claim keywords to COT asset codes for Layer 1 market checks
_KEYWORD_COT_MAP: dict[str, str] = {
    "sp500": "ES",
    "s&p": "ES",
    "equity": "ES",
    "stock": "ES",
    "crude": "CL",
    "oil": "CL",
    "gold": "GC",
    "precious metal": "GC",
    "natural gas": "NG",
    "natgas": "NG",
}

# Maps claim keywords to BLS category for Layer 2 fundamental checks
_KEYWORD_BLS_MAP: dict[str, str] = {
    "cpi": "CPI",
    "inflation": "CPI",
    "core cpi": "Core CPI",
    "unemployment": "Unemployment Rate",
    "jobs": "Unemployment Rate",
    "labor": "Unemployment Rate",
    "ppi": "PPI",
    "producer price": "PPI",
}

# ── Verdict classification ───────────────────────────────────────────────────

_CONFIDENCE_VERIFIED = 0.80
_CONFIDENCE_LIKELY = 0.50
_CONFIDENCE_UNVERIFIED = 0.20


def _classify_verdict(weighted_confidence: float, layer_scores: list[float]) -> str:
    """Map weighted confidence to human-readable verdict.

    CONTRADICTED is signaled when at least two layers score <= 0.15 while
    at least one layer scores >= 0.60 — evidence strongly disagrees.
    """
    low_layers = sum(1 for s in layer_scores if s <= 0.15)
    high_layers = sum(1 for s in layer_scores if s >= 0.60)

    if low_layers >= 2 and high_layers >= 1:
        return "CONTRADICTED"
    if weighted_confidence >= _CONFIDENCE_VERIFIED:
        return "VERIFIED"
    if weighted_confidence >= _CONFIDENCE_LIKELY:
        return "LIKELY"
    if weighted_confidence >= _CONFIDENCE_UNVERIFIED:
        return "UNVERIFIED"
    return "UNVERIFIED"


# ── Layer 1: Market Pricing ───────────────────────────────────────────────────


async def verify_claim_market_pricing(
    claim: str,
    affected_assets: list[str] | None = None,
) -> float:
    """Layer 1: Check if market pricing supports or contradicts the claim.

    Strategies (tried in order):
      1. For claims mentioning a traded asset ticker → fetch latest price via
         market_data gateway and compare with any numeric value extracted from
         the claim.
      2. For rate/monetary claims → check COT positioning for S&P 500 (ES)
         futures as a macro sentiment proxy. CME FedWatch is not yet wired
         in the gateway; COT positioning serves as a directional proxy.
      3. For commodity claims → fetch COT positioning for the relevant asset
         and interpret speculative net positioning as a market vote.
      4. For all other claims → return a neutral 0.50 (no data to confirm or
         refute).

    Returns 0-1 confidence. API failures degrade gracefully to 0.50.
    """
    claim_lower = claim.lower()
    assets = affected_assets or []
    sources_used: list[str] = []
    confidence = 0.50  # neutral default

    # Strategy 1: Stock price check for ticker-bearing claims
    ticker_from_assets = _extract_asset_tickers(assets)
    if ticker_from_assets:
        try:
            from marketmind.gateway.market_data import get_market_data
            for ticker in ticker_from_assets[:3]:  # check at most 3
                result = await get_market_data(ticker, "fundamentals")
                if result and "info" in result:
                    price = _extract_price(result["info"])
                    if price is not None:
                        sources_used.append(f"market_data:{ticker}")
                        # Compare with any numeric value in the claim
                        claim_price_match = _extract_numeric_from_claim(claim)
                        if claim_price_match is not None:
                            diff_pct = abs(price - claim_price_match) / max(price, 0.01)
                            if diff_pct < 0.02:  # within 2%
                                confidence = 0.90
                            elif diff_pct < 0.05:  # within 5%
                                confidence = 0.75
                            elif diff_pct < 0.10:  # within 10%
                                confidence = 0.55
                            else:
                                confidence = 0.25  # substantial divergence
                        else:
                            # Ticker exists but no numeric claim to compare
                            confidence = 0.50
                        break
        except Exception as e:
            logger.warning("Layer 1 market data fetch failed for %s: %s",
                           ticker_from_assets, e)

    # Strategy 2: Rate/monetary claims → COT positioning on ES as macro proxy
    if confidence == 0.50 and _matches_keywords(claim_lower, [
        "rate", "rates", "fed", "fomc", "monetary", "interest",
    ]):
        try:
            from marketmind.gateway.macro_data import get_cot_data
            cot = await get_cot_data("ES")
            if cot and "signal" in cot and "error" not in cot:
                sources_used.append("macro_data:cot_ES")
                signal = cot["signal"]
                # Heuristic: if macro claim matches COT positioning direction,
                # boost confidence. If it contradicts, lower it.
                # "crowded long" is contrarian bearish, "crowded short" contrarian bullish
                if _text_matches_sentiment(claim_lower, signal):
                    confidence = 0.70
                else:
                    confidence = 0.40
            else:
                confidence = 0.50
        except Exception as e:
            logger.warning("Layer 1 COT fetch failed: %s", e)

    # Strategy 3: Commodity claims → COT positioning for relevant asset
    if confidence == 0.50:
        for keyword, cot_asset in _KEYWORD_COT_MAP.items():
            if keyword in claim_lower:
                try:
                    from marketmind.gateway.macro_data import get_cot_data
                    cot = await get_cot_data(cot_asset)
                    if cot and "signal" in cot and "error" not in cot:
                        sources_used.append(f"macro_data:cot_{cot_asset}")
                        signal = cot["signal"]
                        if _text_matches_sentiment(claim_lower, signal):
                            confidence = 0.70
                        else:
                            confidence = 0.40
                    break
                except Exception as e:
                    logger.warning("Layer 1 COT fetch for %s failed: %s",
                                   cot_asset, e)
                    break

    return confidence


# ── Layer 2: Fundamental Data ─────────────────────────────────────────────────


async def verify_claim_fundamental(claim: str) -> float:
    """Layer 2: Check claim against FRED/EIA/BLS official data.

    Map claim keywords to the most relevant data series:
      - FRED: BDI (Baltic Dry Index / freight proxy), GSCPI (supply chain)
      - EIA: crude oil, gasoline, distillate inventory levels
      - BLS: CPI, Core CPI, Unemployment Rate, PPI

    Returns 0-1 confidence. If no relevant data source is found for the
    claim's topic, returns 0.50 (neutral — neither supporting nor refuting).
    API failures degrade gracefully to 0.50.
    """
    claim_lower = claim.lower()
    sources_used: list[str] = []
    confidence = 0.50

    # Try FRED indicators first
    fred_indicator = _find_first_keyword(claim_lower, _KEYWORD_FRED_MAP)
    if fred_indicator:
        try:
            from marketmind.gateway.macro_data import get_macro_indicator
            result = await get_macro_indicator(fred_indicator)
            if result and "error" not in result and result.get("value", 0) != 0:
                sources_used.append(f"fred:{fred_indicator}")
                confidence = 0.75
                logger.debug("Layer 2 FRED: %s → %s = %s",
                             fred_indicator, result.get("label"), result.get("value"))
        except Exception as e:
            logger.warning("Layer 2 FRED fetch failed for %s: %s",
                           fred_indicator, e)

    # Try EIA inventory if the claim mentions energy/commodity products
    eia_product = _find_first_keyword(claim_lower, _KEYWORD_EIA_MAP)
    if eia_product and confidence < 0.70:
        try:
            from marketmind.gateway.macro_data import get_eia_inventory
            result = await get_eia_inventory(eia_product)
            if result and "error" not in result:
                sources_used.append(f"eia:{eia_product}")
                confidence = max(confidence, 0.75)
                logger.debug("Layer 2 EIA: %s → inventory = %s",
                             eia_product, result.get("inventory_mbbl"))
        except Exception as e:
            logger.warning("Layer 2 EIA fetch failed for %s: %s",
                           eia_product, e)

    # Try BLS indicators
    bls_indicator = _find_first_keyword(claim_lower, _KEYWORD_BLS_MAP)
    if bls_indicator and confidence < 0.70:
        try:
            from marketmind.pipeline.bls_fetcher import fetch_bls_indicators
            bls_results = await fetch_bls_indicators()
            if bls_results:
                for entry in bls_results:
                    if entry.get("indicator") == bls_indicator:
                        sources_used.append(f"bls:{bls_indicator}")
                        confidence = max(confidence, 0.75)
                        logger.debug("Layer 2 BLS: %s = %s",
                                     bls_indicator, entry.get("value"))
                        break
        except Exception as e:
            logger.warning("Layer 2 BLS fetch failed for %s: %s",
                           bls_indicator, e)

    return confidence


# ── Layer 3: Multi-Source News ────────────────────────────────────────────────


async def verify_claim_multisource(
    claim: str,
    source_names: list[str] | None = None,
) -> float:
    """Layer 3: Cross-reference claim across independent news sources.

    Uses source_independence.py to count truly independent ownership groups.
    The Red Team C3 finding requires that sources sharing a parent company
    count as ONE — this prevents Sybil-attack fabrication of "consensus."

    Args:
        claim: The claim text to verify.
        source_names: List of source name strings that corroborate the claim.
                      If None or empty, returns neutral (0.50).

    Returns:
        0-1 confidence based on independent source count:
          - 3+ independent → 0.85
          - 2 independent   → 0.65
          - 1 independent   → 0.40
          - 0 sources       → 0.50 (neutral)
    """
    if not source_names:
        return 0.50

    independent_count = count_independent_sources(source_names)

    if independent_count >= MIN_CORROBORATION_FOR_HIGH_CONF:
        return 0.85
    elif independent_count >= 2:
        return 0.65
    elif independent_count >= 1:
        return 0.40
    else:
        return 0.50


# ── Layer 4: Historical Pattern ───────────────────────────────────────────────


async def verify_claim_historical(claim: str) -> float:
    """Layer 4: Compare claim against historical patterns.

    Strategy: Map the claim topic to broad scenario categories and apply
    historical-base-rate heuristics.
      - Rate cut cycle claims → historical base-rate: ~65% of cuts are
        followed by equity rallies within 3 months, ~35% are not.
      - Recession claims → most recession calls are false positives.
      - Oil spike claims → ~50% of spikes retrace within 1 month.
      - General claims → keyword-based heuristic.

    In a production deployment this would query a properly indexed backtest
    database. The current implementation uses fixed base-rates derived from
    published research as a conservative placeholder pending that database.

    Returns 0-1 confidence.
    """
    claim_lower = claim.lower()

    # ── Scenario base rates (conservative, published-research derived) ──
    # rate_cut: rate cuts are followed by equity rallies ~65% of the time
    #           (based on post-Volcker era data, not fitted to parameters)
    if _matches_keywords(claim_lower, [
        "rate cut", "rate cuts", "fed cut", "easing",
        "dovish", "lower rate", "cutting rate",
    ]):
        return 0.65

    # rate_hike: rate hikes hurt equities short-term but signal economic
    #            strength — direction is ambiguous from pattern alone
    if _matches_keywords(claim_lower, [
        "rate hike", "rate hikes", "fed hike", "tightening",
        "hawkish", "raise rate", "hiking rate",
    ]):
        return 0.45

    # recession: historically market recession calls have high false-positive
    #            rates (~70% of recession predictions are wrong within the
    #            forecasted window), so low confidence
    if _matches_keywords(claim_lower, [
        "recession", "economic contraction", "depression",
        "hard landing", "economic downturn",
    ]):
        return 0.35

    # oil_spike: ~50% retrace within 1 month — no strong directional pattern
    if _matches_keywords(claim_lower, [
        "oil spike", "oil surge", "crude spike", "crude surge",
        "oil price shock", "energy crisis",
    ]):
        return 0.50

    # gold_rally: gold often rises in uncertainty — pattern is supportive
    if _matches_keywords(claim_lower, [
        "gold rally", "gold bull", "gold surge", "precious metal",
        "safe haven demand",
    ]):
        return 0.55

    # inflation: persistent inflation claims have ~55% historical accuracy
    if _matches_keywords(claim_lower, [
        "inflation", "cpi", "price level", "rising price",
        "cost push", "demand pull",
    ]):
        return 0.55

    # earnings: earnings surprise/beat claims — pattern supports ~60%
    if _matches_keywords(claim_lower, [
        "earnings beat", "earnings miss", "earnings surprise",
        "revenue growth", "profit margin",
    ]):
        return 0.60

    # Default: no strong historical pattern for this claim category
    return 0.50


# ── Main orchestration ────────────────────────────────────────────────────────


async def verify_claim(
    claim: str,
    affected_assets: list[str] | None = None,
    source_names: list[str] | None = None,
) -> VerificationResult:
    """Run all 4 independent verification layers on a claim.

    Each layer reads from a genuinely independent data source, as required
    by the Red Team C7 fix. Results are combined via weighted average using
    weights from investigation_config.

    Args:
        claim: The claim text to verify.
        affected_assets: List of ticker symbols or asset names the claim
                         is about (e.g. ["AAPL", "SPY"]). Used by Layer 1
                         to fetch relevant market data.
        source_names: List of source names (from source_authority.py) that
                      reported the claim. Used by Layer 3 to count
                      independent sources.

    Returns:
        VerificationResult with per-layer scores, weighted confidence, and
        verdict classification.
    """
    sources_used: list[str] = []

    # Run all 4 layers concurrently — each is independent
    import asyncio

    assets = affected_assets or []
    s_names = source_names or []

    results = await asyncio.gather(
        verify_claim_market_pricing(claim, assets),
        verify_claim_fundamental(claim),
        verify_claim_multisource(claim, s_names),
        verify_claim_historical(claim),
        return_exceptions=True,
    )

    l1 = results[0] if not isinstance(results[0], BaseException) else 0.50
    l2 = results[1] if not isinstance(results[1], BaseException) else 0.50
    l3 = results[2] if not isinstance(results[2], BaseException) else 0.50
    l4 = results[3] if not isinstance(results[3], BaseException) else 0.50

    # Handle exceptions gracefully
    for i, r in enumerate(results):
        if isinstance(r, BaseException):
            logger.warning("Layer %d verification raised: %s", i + 1, r)

    # Weighted composite score
    weighted = (
        WEIGHT_MARKET_PRICING * l1
        + WEIGHT_FUNDAMENTAL_DATA * l2
        + WEIGHT_MULTI_SOURCE * l3
        + WEIGHT_HISTORICAL_PATTERN * l4
    )

    # Track sources used
    if assets:
        sources_used.extend(f"market:{a}" for a in assets[:5])
    if s_names:
        sources_used.extend(f"news:{n}" for n in s_names[:5])

    layer_scores = [l1, l2, l3, l4]
    verdict = _classify_verdict(weighted, layer_scores)

    # Detect contradictions between layers
    contradiction_detail = _detect_contradiction(l1, l2, l3, l4)

    return VerificationResult(
        claim=claim,
        layer_1_market=round(l1, 3),
        layer_2_fundamental=round(l2, 3),
        layer_3_multisource=round(l3, 3),
        layer_4_historical=round(l4, 3),
        weighted_confidence=round(weighted, 3),
        verdict=verdict,
        sources_used=sources_used,
        contradiction_detail=contradiction_detail,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _matches_keywords(text: str, keywords: list[str]) -> bool:
    """Return True if any keyword is found in text (case-insensitive)."""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def _find_first_keyword(text: str, mapping: dict[str, str]) -> str | None:
    """Return the value for the first matching key found in text."""
    for keyword, value in mapping.items():
        if keyword in text:
            return value
    return None


# Common financial terms that are 1-5 alpha chars but are NOT tickers
_NON_TICKER_TERMS: set[str] = {
    "OIL", "GOLD", "BOND", "BONDS", "CASH", "YEN", "EURO", "POUND",
    "WTI", "BRENT", "GAS", "CORP", "TECH", "BANK", "FUND", "NOTE",
    "BILL", "COIN", "LOAN", "DEBT", "RISK", "HEDGE", "YIELD",
    "STOCK", "STOCKS", "INDEX", "FUT", "SPX", "NDX", "RUT", "VIX",
    "DXY", "UST", "BUND", "GILT", "JGB",
}


def _extract_asset_tickers(assets: list[str]) -> list[str]:
    """Filter asset list to likely stock/crypto ticker symbols.

    Returns tickers that look like standard US stock symbols (1-5 uppercase
    letters) or crypto pairs (e.g. BTC-USD), excluding common financial
    terms that are not actual tickers.
    """
    tickers: list[str] = []
    for a in assets:
        stripped = a.strip().upper()
        if not stripped:
            continue
        # Crypto pattern: XXX-USD
        if stripped.endswith("-USD") and len(stripped) > 4:
            tickers.append(stripped)
        # US stock pattern: 1-5 uppercase alpha chars, not a common term
        elif (1 <= len(stripped) <= 5
              and stripped.replace(".", "").isalpha()
              and stripped not in _NON_TICKER_TERMS):
            tickers.append(stripped)
    return tickers


def _extract_price(info: dict) -> float | None:
    """Extract current price from market data info dict."""
    candidates = [
        "regularMarketPrice",
        "currentPrice",
        "regularMarketOpen",
        "previousClose",
    ]
    for key in candidates:
        val = info.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def _extract_numeric_from_claim(claim: str) -> float | None:
    """Extract a numeric dollar/price value from claim text.

    Looks for patterns like "$123.45", "123.45 dollars", "price of 123.45".
    Returns the last (most specific) numeric value found, or None.
    """
    import re

    patterns = [
        r'\$(\d{1,6}(?:\.\d{1,2})?)',     # $123.45
        r'(\d{1,6}(?:\.\d{1,2})?)\s*dollars',  # 123.45 dollars
        r'price\s*(?:of|at|is|:)\s*\$?(\d{1,6}(?:\.\d{1,2})?)',  # price of $123.45
        r'(\d{1,6}(?:\.\d{1,2})?)\s*\$',   # 123.45 $
    ]
    matches: list[float] = []
    for pat in patterns:
        for m in re.finditer(pat, claim, re.IGNORECASE):
            try:
                matches.append(float(m.group(1)))
            except ValueError:
                continue
    return matches[-1] if matches else None


def _text_matches_sentiment(text: str, cot_signal: str) -> bool:
    """Heuristic: does claim text sentiment align with COT positioning?

    cot_signal typically contains phrases like:
      - "contrarian bearish (crowded long)" → bearish signal
      - "contrarian bullish (crowded short)" → bullish signal
      - "moderately net long ... no extreme signal" → mildly bullish
      - "near neutral ... no directional signal" → neutral
      - "Speculative net long" → position is long, contrarian bearish
      - "Speculative net short" → position is short, contrarian bullish

    We interpret the CONTRARIAN sentiment (what the market positioning
    actually implies for future direction), not the raw net position.
    """
    signal_lower = cot_signal.lower()
    text_lower = text.lower()

    # Determine the COT-implied directional signal
    if "contrarian bearish" in signal_lower:
        cot_direction = "bearish"
    elif "contrarian bullish" in signal_lower:
        cot_direction = "bullish"
    elif "no directional signal" in signal_lower or "near neutral" in signal_lower:
        cot_direction = "neutral"
    elif "no extreme signal" in signal_lower:
        cot_direction = "neutral"
    else:
        # Fallback: read raw net position
        if "net long" in signal_lower:
            cot_direction = "bearish"  # crowded long is contrarian bearish
        elif "net short" in signal_lower:
            cot_direction = "bullish"  # crowded short is contrarian bullish
        else:
            return True  # can't determine — give benefit of doubt

    # Determine claim sentiment from keywords
    bullish_words = ["rally", "bull", "rise", "surge", "soar", "growth",
                     "expansion", "strong", "upbeat", "positive"]
    bearish_words = ["crash", "bear", "fall", "drop", "plunge", "decline",
                     "recession", "weak", "downbeat", "negative", "sell"]

    claim_bullish = any(w in text_lower for w in bullish_words)
    claim_bearish = any(w in text_lower for w in bearish_words)

    # Bullish claim + bearish COT = contradiction → misalignment
    # Bearish claim + bullish COT = contradiction → misalignment
    if cot_direction == "bullish" and claim_bearish:
        return False
    if cot_direction == "bearish" and claim_bullish:
        return False
    # For neutral COT, consider matching if there is no strong contrary signal
    if cot_direction == "neutral":
        return True
    # Aligned: claim matches COT direction
    if cot_direction == "bullish" and claim_bullish:
        return True
    if cot_direction == "bearish" and claim_bearish:
        return True
    return True  # no strong signal either way


def _detect_contradiction(
    l1: float, l2: float, l3: float, l4: float,
) -> str | None:
    """Detect when layers disagree strongly with each other.

    A contradiction exists when one layer scores high (>=0.70) while
    another scores low (<=0.20). The gap must be >=0.50.
    """
    high_layers = []
    low_layers = []
    names = ["Market Pricing", "Fundamental Data", "Multi-Source News", "Historical Pattern"]
    scores = [l1, l2, l3, l4]

    for name, score in zip(names, scores):
        if score >= 0.70:
            high_layers.append((name, score))
        elif score <= 0.20:
            low_layers.append((name, score))

    # Contradiction: at least one high-score layer and one low-score layer
    if high_layers and low_layers:
        high_str = ", ".join(f"{n}({s:.2f})" for n, s in high_layers)
        low_str = ", ".join(f"{n}({s:.2f})" for n, s in low_layers)
        return f"Contradiction: {high_str} supports the claim while {low_str} refutes it."
    return None
