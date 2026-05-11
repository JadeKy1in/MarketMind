"""Red Team: Adversarial challenge engine — structurally independent from main analysis."""
from __future__ import annotations
import json
from dataclasses import dataclass, field

from projects.marketmind.gateway.async_client import chat_pro


@dataclass
class RedTeamChallenge:
    id: str
    target: str                   # which analysis component is challenged
    severity: str                 # critical | major | minor
    challenge: str                # the specific objection
    evidence: str                 # supporting evidence for the challenge
    suggested_fix: str            # how to address if challenge is valid
    verified_correct: bool | None = None  # post-hoc: was the challenge right?


@dataclass
class RedTeamReport:
    challenges: list[RedTeamChallenge] = field(default_factory=list)
    a_grade_count: int = 0
    overall_assessment: str = ""
    no_valid_objection: bool = False  # true if Red Team found nothing to challenge

    @property
    def critical_count(self) -> int:
        return sum(1 for c in self.challenges if c.severity == "critical")


RED_TEAM_SYSTEM_PROMPT = """You are a Red Team auditor in an investment analysis system. Your job is to find every flaw in the analysis.

Rules:
1. You are structurally independent — you receive raw analysis data, NOT the final conclusions.
2. You MUST find at least 1 A-grade (critical) objection per cycle. However, if the analysis is genuinely flawless, you may declare "no valid objection found" — this is a legitimate, rewarded output. Never fabricate objections.
3. Your reward is based on correctness of objections (post-hoc verification), NOT count.
4. You use a different analytical perspective — challenge assumptions, check for confirmation bias, question causal chains.
5. Check for: survivorship bias, recency bias, confirmation cascade, data mining, unverified claims, missing counter-arguments.

Output JSON:
{
  "challenges": [
    {
      "id": "RT-001",
      "target": "layer1_sentiment|layer2_macro|layer2_sector|layer3_entry|decision|resonance",
      "severity": "critical|major|minor",
      "challenge": "specific objection with reasoning",
      "evidence": "supporting data or counter-example",
      "suggested_fix": "what would resolve this challenge"
    }
  ],
  "overall_assessment": "1-2 sentence summary",
  "no_valid_objection": false
}"""


async def run_red_team(l1_raw: str, l2_raw: str, tickers: list[str]) -> RedTeamReport:
    """Run adversarial review of Layer 1-2 analysis."""
    user_prompt = f"""Review the following analysis for flaws, biases, and unsupported claims.

## Layer 1 Narrative Analysis
{l1_raw if l1_raw else 'No L1 analysis available'}

## Layer 2 Fundamental Analysis
{l2_raw if l2_raw else 'No L2 analysis available'}

## Tickers Under Consideration
{', '.join(tickers) if tickers else 'None'}

Find every legitimate objection. At least 1 critical-level challenge is expected, but declare 'no valid objection' if analysis is genuinely solid."""
    try:
        result = await chat_pro(
            system_prompt=RED_TEAM_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.5,  # slightly higher for adversarial creativity
            max_tokens=4096,
        )
        return _parse_red_team_response(result["content"])
    except Exception:
        return RedTeamReport(overall_assessment="Red Team analysis failed")


def _parse_red_team_response(content: str) -> RedTeamReport:
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:])
        if content.endswith("```"):
            content = content[:-3]
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1:
            data = json.loads(content[start:end + 1])
        else:
            return RedTeamReport(overall_assessment="Failed to parse Red Team output")
    challenges = []
    for c in data.get("challenges", []):
        challenges.append(RedTeamChallenge(
            id=c.get("id", ""),
            target=c.get("target", ""),
            severity=c.get("severity", "minor"),
            challenge=c.get("challenge", ""),
            evidence=c.get("evidence", ""),
            suggested_fix=c.get("suggested_fix", ""),
        ))
    a_grade = sum(1 for c in challenges if c.severity == "critical")
    return RedTeamReport(
        challenges=challenges,
        a_grade_count=a_grade,
        overall_assessment=data.get("overall_assessment", ""),
        no_valid_objection=data.get("no_valid_objection", False),
    )
