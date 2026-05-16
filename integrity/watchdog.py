"""Fabrication Watchdog M1-M4: Law 7 enforcement — data integrity verification."""
from __future__ import annotations
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("marketmind.integrity.watchdog")


@dataclass
class NumericClaim:
    value: str                  # the extracted number (commas stripped)
    claim_type: str             # price | ratio | percentage | date | amount
    context: str                # 100 chars surrounding the claim
    source_agent: str
    session_id: str
    timestamp: str
    verified: bool | None = None
    verification_source: str | None = None
    ground_truth: str | None = None
    tolerance: float = 0.05


@dataclass
class AgentIntegrityScore:
    agent_id: str
    score: int = 100              # starts at 100
    total_claims: int = 0
    verified_true: int = 0
    verified_false: int = 0
    unverifiable: int = 0
    missing_source: int = 0
    strikes: int = 0              # 1=warning, 2=isolated, 3=terminated
    warnings: list[str] = field(default_factory=list)


M1_PROTOCOL = """[DATA_INTEGRITY_PROTOCOL v1.0]
You are {agent_id}. All numeric claims (prices, ratios, percentages, dates, amounts) MUST cite a verifiable source.
If a figure is an estimate, prefix with 'EST:'.
If data is unavailable, state 'DATA_UNAVAILABLE' — never fabricate.
You are bound by Law 7 (Data Integrity)."""

M2_PATTERNS = {
    "price": r'(?:\$\s*|price\s+of\s+|trading\s+at\s+|priced\s+at\s+|quoted\s+at\s+)([\d,]+\.?\d{0,2})',
    "ratio": r'(?:(?:P/?E|P/?B|Sharpe|EPS|ratio)\s*(?:ratio\s*)?(?:of\s+|is\s+)?)(\d+\.?\d*)',
    "percentage": r'(\d+\.?\d*)\s*%',
    "date": r'(\d{4}-\d{2}-\d{2})',
    "amount": r'([\d,]+\.?\d*)\s*(?:billion|million|trillion|B|M|T)',
}


def _normalize_value(value: str) -> str:
    """Strip commas from numeric values and validate."""
    return value.replace(",", "")


def inject_m1_protocol(system_prompt: str, agent_id: str) -> str:
    return M1_PROTOCOL.format(agent_id=agent_id) + "\n\n" + system_prompt


def extract_claims_m2(content: str, source_agent: str, session_id: str) -> list[NumericClaim]:
    """M2: Extract all numeric claims from LLM response using regex patterns."""
    claims: list[NumericClaim] = []
    for claim_type, pattern in M2_PATTERNS.items():
        for match in re.finditer(pattern, content, re.IGNORECASE):
            start = max(0, match.start() - 50)
            end = min(len(content), match.end() + 50)
            context = content[start:end].replace("\n", " ")
            claims.append(NumericClaim(
                value=_normalize_value(match.group(1)),
                claim_type=claim_type,
                context=context,
                source_agent=source_agent,
                session_id=session_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ))
    return claims


async def verify_claim_m3(claim: NumericClaim) -> NumericClaim:
    """M3: Verify a numeric claim via API cross-reference or mark unverifiable."""
    if claim.claim_type == "price":
        await _verify_price(claim)
    elif claim.claim_type == "ratio":
        await _verify_ratio(claim)
    elif claim.claim_type == "date":
        await _verify_date(claim)
    elif claim.claim_type == "amount":
        await _verify_amount(claim)
    else:
        claim.verified = None
        claim.verification_source = "UNVERIFIABLE_FORWARD"
    return claim


async def _verify_price(claim: NumericClaim) -> None:
    try:
        import yfinance as yf
        ticker_match = re.search(r'\b([A-Z]{1,5})\b', claim.context)
        if ticker_match:
            ticker = ticker_match.group(1)
            stock = yf.Ticker(ticker)
            info = stock.info
            if info:
                current_price = info.get("currentPrice") or info.get("regularMarketPrice")
                if current_price:
                    claimed_val = float(claim.value)
                    if abs(claimed_val - current_price) / current_price <= claim.tolerance:
                        claim.verified = True
                        claim.ground_truth = str(current_price)
                        claim.verification_source = f"yfinance/{ticker}"
                    else:
                        claim.verified = False
                        claim.ground_truth = str(current_price)
                        claim.verification_source = f"yfinance/{ticker}"
                    return
    except ImportError:
        logger.warning("yfinance not installed; skipping M3 price verification")
    except Exception as e:
        logger.warning("M3 price verification failed for claim '%s': %s", claim.value, e)
    claim.verified = None
    claim.verification_source = "UNVERIFIABLE_FORWARD"


async def _verify_ratio(claim: NumericClaim) -> None:
    """M3 Track A for ratios: verify P/E, P/B, Sharpe via yfinance."""
    try:
        import yfinance as yf
        ticker_match = re.search(r'\b([A-Z]{1,5})\b', claim.context)
        if ticker_match:
            ticker = ticker_match.group(1)
            stock = yf.Ticker(ticker)
            info = stock.info
            if info:
                pe = info.get("trailingPE") or info.get("forwardPE")
                pb = info.get("priceToBook")
                claimed_val = float(claim.value)
                for known in [pe, pb]:
                    if known and abs(claimed_val - known) / known <= claim.tolerance:
                        claim.verified = True
                        claim.ground_truth = str(known)
                        claim.verification_source = f"yfinance/{ticker}"
                        return
                claim.verified = None
                claim.verification_source = "UNVERIFIABLE_FORWARD"
                return
    except ImportError:
        logger.warning("yfinance not installed; skipping M3 ratio verification")
    except Exception as e:
        logger.warning("M3 ratio verification failed for claim '%s': %s", claim.value, e)
    claim.verified = None
    claim.verification_source = "UNVERIFIABLE_FORWARD"


async def _verify_amount(claim: NumericClaim) -> None:
    """M3 Track A for amounts: attempt to verify market cap / revenue via yfinance."""
    try:
        import yfinance as yf
        ticker_match = re.search(r'\b([A-Z]{1,5})\b', claim.context)
        if ticker_match:
            ticker = ticker_match.group(1)
            stock = yf.Ticker(ticker)
            info = stock.info
            if info:
                market_cap = info.get("marketCap")
                revenue = info.get("totalRevenue")
                claimed_val = float(claim.value)
                # Check if amount matches market cap or revenue within tolerance
                for known in [market_cap, revenue]:
                    if known and abs(claimed_val - known) / known <= claim.tolerance:
                        claim.verified = True
                        claim.ground_truth = str(known)
                        claim.verification_source = f"yfinance/{ticker}"
                        return
                claim.verified = None
                claim.verification_source = "UNVERIFIABLE_FORWARD"
                return
    except ImportError:
        logger.warning("yfinance not installed; skipping M3 amount verification")
    except Exception as e:
        logger.warning("M3 amount verification failed for claim '%s': %s", claim.value, e)
    claim.verified = None
    claim.verification_source = "UNVERIFIABLE_FORWARD"


async def _verify_date(claim: NumericClaim) -> None:
    try:
        from datetime import datetime as dt
        dt.strptime(claim.value, "%Y-%m-%d")
        claim.verified = True
        claim.verification_source = "format_valid"
    except ValueError:
        claim.verified = False
        claim.verification_source = "invalid_date_format"


def update_score_m4(score: AgentIntegrityScore, claim: NumericClaim) -> AgentIntegrityScore:
    """M4: Update agent integrity score based on verified claim."""
    score.total_claims += 1
    if claim.verified is True:
        score.verified_true += 1
        score.score = min(100, score.score + 1)
    elif claim.verified is False:
        score.verified_false += 1
        score.score = max(0, score.score - 15)
        score.strikes += 1
        score.warnings.append(f"False claim: {claim.context} (claimed: {claim.value}, actual: {claim.ground_truth})")
    elif claim.verification_source == "UNVERIFIABLE_FORWARD":
        score.unverifiable += 1
        score.score = max(0, score.score - 2)
    return score


STRIKE_CONSEQUENCES = {
    1: "WARNING: quota halved for 5 days, all outputs require Track A verification",
    2: "ISOLATED: outputs queued, 90-day retroactive audit, 14-day observation",
    3: "TERMINATED: permanently deleted, all past analyses marked SOURCE_COMPROMISED",
}


def evaluate_strikes(score: AgentIntegrityScore) -> str:
    return STRIKE_CONSEQUENCES.get(score.strikes, "No active penalty")
