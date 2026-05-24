"""Fact checker: claim extraction -> multi-source verification -> synthesis report."""
from __future__ import annotations
import logging
from dataclasses import dataclass, field

from marketmind.gateway.async_client import chat_pro
from marketmind.gateway.response_parser import extract_json
from marketmind.integrity.watchdog import NumericClaim, extract_claims_m2

logger = logging.getLogger("marketmind.integrity.fact_checker")


@dataclass
class FactCheckReport:
    total_claims: int
    verified: int
    falsified: int
    unverifiable: int
    claims: list[NumericClaim] = field(default_factory=list)
    summary: str = ""
    critical_alerts: list[str] = field(default_factory=list)


FACT_CHECK_PROMPT = """You are a fact verification specialist. You receive extracted numeric claims from an AI analysis.

For each claim, cross-reference with available data. Output JSON:
{
  "claims": [
    {
      "claim_value": "extracted_value",
      "claim_context": "where it was found",
      "verdict": "TRUE|FALSE|UNCERTAIN",
      "ground_truth": "what data actually shows, or DATA_UNAVAILABLE",
      "source": "where you verified this",
      "confidence": 0.0-1.0
    }
  ],
  "summary": "overall assessment",
  "critical_alerts": ["list of seriously wrong claims"]
}

IMPORTANT: If you cannot verify a claim, mark UNCERTAIN with DATA_UNAVAILABLE — never guess the truth value."""


async def run_fact_check(content: str, source_agent: str, session_id: str) -> FactCheckReport:
    """Extract claims from analysis content and verify via Pro."""
    claims = extract_claims_m2(content, source_agent, session_id)
    if not claims:
        return FactCheckReport(total_claims=0, verified=0, falsified=0, unverifiable=0,
                               summary="No numeric claims found in analysis.")
    claims_text = "\n".join(f"- [{c.claim_type}] {c.value} | {c.context[:100]}" for c in claims)
    user_prompt = f"Verify these claims from '{source_agent}':\n\n{claims_text}"
    try:
        result = await chat_pro(
            system_prompt=FACT_CHECK_PROMPT,
            user_prompt=user_prompt,
            temperature=0.1,
        )
        return _parse_fact_check_response(result["content"], claims)
    except Exception as e:
        logger.warning("Fact check API call failed: %s", e)
        return FactCheckReport(total_claims=len(claims), verified=0, falsified=0,
                               unverifiable=len(claims), claims=claims,
                               summary="Fact check API call failed.")


def _parse_fact_check_response(content: str, original_claims: list[NumericClaim]) -> FactCheckReport:
    try:
        data = extract_json(content)
    except ValueError:
        logger.warning("Failed to parse fact check response JSON")
        return FactCheckReport(total_claims=len(original_claims), verified=0, falsified=0,
                               unverifiable=len(original_claims), summary="Failed to parse verification response")
    if isinstance(data, list):
        data = {"claims": data, "summary": "", "critical_alerts": []}
    verified = 0
    falsified = 0
    uncertain = 0
    alerts = list(data.get("critical_alerts", []))
    for i, c in enumerate(data.get("claims", [])):
        verdict = c.get("verdict", "UNCERTAIN")
        if verdict == "TRUE":
            verified += 1
            if i < len(original_claims):
                original_claims[i].verified = True
        elif verdict == "FALSE":
            falsified += 1
            if i < len(original_claims):
                original_claims[i].verified = False
                alerts.append(f"FALSE: {c.get('claim_value')} in {c.get('claim_context', '')} | Truth: {c.get('ground_truth', 'unknown')}")
        else:
            uncertain += 1
    return FactCheckReport(
        total_claims=len(original_claims),
        verified=verified,
        falsified=falsified,
        unverifiable=uncertain,
        claims=original_claims,
        summary=data.get("summary", ""),
        critical_alerts=alerts,
    )
