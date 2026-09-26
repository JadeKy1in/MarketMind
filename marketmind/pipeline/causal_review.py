"""Causal post-mortem review — Phase C PMV (3-step simplified protocol)."""

from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from marketmind.gateway.async_client import chat_pro
from marketmind.gateway.response_parser import strip_markdown_fences

logger = logging.getLogger("marketmind.pipeline.causal_review")

@dataclass
class CausalReviewResult:
    """Output from causal post-mortem review."""
    step1_confounders: list[str] = field(default_factory=list)  # identified confounders/colliders
    step1_confidence: float = 0.0
    step2_info_gaps: list[str] = field(default_factory=list)    # missing information
    step2_completeness_score: float = 0.0  # 0.0-1.0
    step3_root_cause: str = ""             # causal_error | info_gap | analysis_error | black_swan
    step3_evidence: str = ""
    methodology_changes: list[str] = field(default_factory=list)
    raw_response: str = ""

CAUSAL_REVIEW_SYSTEM_PROMPT = """You are a causal reasoning auditor. Review the investment decision logic for causal errors and information gaps.

Step 1 — Confounder/Collider Check:
For each causal claim in the decision, ask:
- "Is there a hidden variable C that caused both A and B?" (confounder)
- "Did controlling for variable D artificially create this relationship?" (collider)
Output each identified issue with a confidence score.

Step 2 — Information Completeness:
Compare the information used in this decision against what should have been checked:
- What standard data sources were missing?
- Was partial information mistaken for complete information?
Score completeness 0.0-1.0.

Step 3 — Root Cause Classification:
Based on Steps 1-2 and the actual market outcome, classify the primary root cause as one of:
- "causal_error": Correlation mistaken for causation, confounder/collider bias
- "info_gap": Decision made with incomplete information
- "analysis_error": Information was sufficient but reasoning was flawed
- "black_swan": Unpredictable external event, no analysis could have caught this

Output JSON:
{
  "step1": {"confounders": ["..."], "confidence": 0.0},
  "step2": {"info_gaps": ["..."], "completeness_score": 0.0},
  "step3": {"root_cause": "causal_error|info_gap|analysis_error|black_swan", "evidence": "..."},
  "methodology_changes": ["concrete suggestion 1", "concrete suggestion 2"]
}
"""

async def run_causal_review(
    decision_thesis: str,
    decision_evidence: list[str],
    actual_outcome: str,
    info_sources_used: list[str],
) -> CausalReviewResult:
    """Run 3-step causal post-mortem on a past decision."""
    user_prompt = f"""Review this investment decision:

## Decision Thesis
{decision_thesis}

## Evidence Used
{chr(10).join(f'- {e}' for e in decision_evidence) if decision_evidence else 'None recorded'}

## Information Sources Consulted
{chr(10).join(f'- {s}' for s in info_sources_used) if info_sources_used else 'None recorded'}

## Actual Outcome
{actual_outcome}

Analyze for causal errors, information gaps, and classify the root cause."""

    try:
        result = await chat_pro(
            system_prompt=CAUSAL_REVIEW_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.2,
        )
        return _parse_causal_response(result.get("content", ""))
    except Exception as e:
        logger.warning("Causal review failed: %s", e)
        return CausalReviewResult(
            step3_root_cause="analysis_error",
            step3_evidence=f"Causal review execution failed: {e}"
        )

def _parse_causal_response(content: str) -> CausalReviewResult:
    content = strip_markdown_fences(content)
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1:
            data = json.loads(content[start:end + 1])
        else:
            return CausalReviewResult(step3_root_cause="analysis_error",
                                       step3_evidence="Failed to parse causal review output")

    s1 = data.get("step1", {})
    s2 = data.get("step2", {})
    s3 = data.get("step3", {})

    return CausalReviewResult(
        step1_confounders=s1.get("confounders", []),
        step1_confidence=float(s1.get("confidence", 0)),
        step2_info_gaps=s2.get("info_gaps", []),
        step2_completeness_score=float(s2.get("completeness_score", 0)),
        step3_root_cause=s3.get("root_cause", "causal_error"),
        step3_evidence=s3.get("evidence", ""),
        methodology_changes=data.get("methodology_changes", []),
        raw_response=content,
    )
