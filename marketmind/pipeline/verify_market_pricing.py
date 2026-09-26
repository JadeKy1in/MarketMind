"""Layer 1 Market Pricing verification — COT positioning, stock prices, market data.

Extracted from pipeline/verification_chain.py for modular compliance (grandfather reduction).
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("marketmind.pipeline.verify_market_pricing")

# ── Keyword-to-cot mapping ──────────────────────────────────────────────

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

# Common financial terms that are 1-5 alpha chars but are NOT tickers
_NON_TICKER_TERMS: set[str] = {
    "OIL", "GOLD", "BOND", "BONDS", "CASH", "YEN", "EURO", "POUND",
    "WTI", "BRENT", "GAS", "CORP", "TECH", "BANK", "FUND", "NOTE",
    "BILL", "COIN", "LOAN", "DEBT", "RISK", "HEDGE", "YIELD",
    "STOCK", "STOCKS", "INDEX", "FUT", "SPX", "NDX", "RUT", "VIX",
    "DXY", "UST", "BUND", "GILT", "JGB",
}


def extract_asset_tickers(assets: list[str]) -> list[str]:
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


def extract_price(info: dict) -> float | None:
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


def extract_numeric_from_claim(claim: str) -> float | None:
    """Extract a numeric dollar/price value from claim text.

    Looks for patterns like "$123.45", "123.45 dollars", "price of 123.45".
    Returns the last (most specific) numeric value found, or None.
    """
    patterns = [
        r'\$(\d{1,6}(?:\.\d{1,2})?)',
        r'(\d{1,6}(?:\.\d{1,2})?)\s*dollars',
        r'price\s*(?:of|at|is|:)\s*\$?(\d{1,6}(?:\.\d{1,2})?)',
        r'(\d{1,6}(?:\.\d{1,2})?)\s*\$',
    ]
    matches: list[float] = []
    for pat in patterns:
        for m in re.finditer(pat, claim, re.IGNORECASE):
            try:
                matches.append(float(m.group(1)))
            except ValueError:
                continue
    return matches[-1] if matches else None


def text_matches_sentiment(text: str, cot_signal: str) -> bool:
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
            cot_direction = "bearish"
        elif "net short" in signal_lower:
            cot_direction = "bullish"
        else:
            return True

    # Determine claim sentiment from keywords
    bullish_words = ["rally", "bull", "rise", "surge", "soar", "growth",
                     "expansion", "strong", "upbeat", "positive"]
    bearish_words = ["crash", "bear", "fall", "drop", "plunge", "decline",
                     "recession", "weak", "downbeat", "negative", "sell"]

    claim_bullish = any(w in text_lower for w in bullish_words)
    claim_bearish = any(w in text_lower for w in bearish_words)

    if cot_direction == "bullish" and claim_bearish:
        return False
    if cot_direction == "bearish" and claim_bullish:
        return False
    if cot_direction == "neutral":
        return True
    if cot_direction == "bullish" and claim_bullish:
        return True
    if cot_direction == "bearish" and claim_bearish:
        return True
    return True


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
         futures as a macro sentiment proxy.
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
    ticker_from_assets = extract_asset_tickers(assets)
    if ticker_from_assets:
        try:
            from marketmind.gateway.market_data import get_market_data
            for ticker in ticker_from_assets[:3]:
                result = await get_market_data(ticker, "fundamentals")
                if result and "info" in result:
                    price = extract_price(result["info"])
                    if price is not None:
                        sources_used.append(f"market_data:{ticker}")
                        claim_price_match = extract_numeric_from_claim(claim)
                        if claim_price_match is not None:
                            diff_pct = abs(price - claim_price_match) / max(price, 0.01)
                            if diff_pct < 0.02:
                                confidence = 0.90
                            elif diff_pct < 0.05:
                                confidence = 0.75
                            elif diff_pct < 0.10:
                                confidence = 0.55
                            else:
                                confidence = 0.25
                        else:
                            confidence = 0.50
                        break
        except Exception as e:
            logger.warning("Layer 1 market data fetch failed for %s: %s",
                           ticker_from_assets, e)

    # Strategy 2: Rate/monetary claims → COT positioning on ES as macro proxy
    _rate_keywords = {"rate", "rates", "fed", "fomc", "monetary", "interest"}
    if confidence == 0.50 and any(kw in claim_lower for kw in _rate_keywords):
        try:
            from marketmind.gateway.macro_data import get_cot_data
            cot = await get_cot_data("ES")
            if cot and "signal" in cot and "error" not in cot:
                sources_used.append("macro_data:cot_ES")
                signal = cot["signal"]
                if text_matches_sentiment(claim_lower, signal):
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
                        if text_matches_sentiment(claim_lower, signal):
                            confidence = 0.70
                        else:
                            confidence = 0.40
                    break
                except Exception as e:
                    logger.warning("Layer 1 COT fetch for %s failed: %s",
                                   cot_asset, e)
                    break

    return confidence
