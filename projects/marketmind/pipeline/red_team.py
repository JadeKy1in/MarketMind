"""Red Team: Adversarial challenge engine — structurally independent from main analysis."""
from __future__ import annotations
import json
import logging

logger = logging.getLogger("marketmind.pipeline.red_team")
from dataclasses import dataclass, field

from marketmind.gateway.async_client import chat_pro
from marketmind.gateway.response_parser import strip_markdown_fences
from marketmind.shadows.shadow_agent import defang_text


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
{defang_text(l1_raw) if l1_raw else 'No L1 analysis available'}

## Layer 2 Fundamental Analysis
{defang_text(l2_raw) if l2_raw else 'No L2 analysis available'}

## Tickers Under Consideration
{', '.join(tickers) if tickers else 'None'}

Find every legitimate objection. At least 1 critical-level challenge is expected, but declare 'no valid objection' if analysis is genuinely solid."""
    try:
        result = await chat_pro(
            system_prompt=RED_TEAM_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.5,  # slightly higher for adversarial creativity
            max_tokens=16384,
        )
        return _parse_red_team_response(result["content"])
    except Exception as e:
        logger.warning("Red Team analysis failed: %s", e)
        return RedTeamReport(overall_assessment="Red Team analysis failed")


def _parse_red_team_response(content: str) -> RedTeamReport:
    import re
    content = strip_markdown_fences(content)

    def _try_parse(text: str) -> dict | None:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            block = text[start:end + 1]
            try:
                return json.loads(block)
            except json.JSONDecodeError:
                pass
            repaired = re.sub(r",\s*([}\]])", r"\1", block)
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass
        return None

    data = _try_parse(content)
    if data is None:
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


# ── H8: Red Team Background Observer (Phase C PMV) ──────────────────────────

@dataclass
class BiasObservation:
    """A single bias observation logged during a session."""
    observation_type: str  # confirmation_bias|recency_bias|causal_error|...
    target_context: str    # L1_narrative|user_interaction|decision_finalization
    description: str
    severity: str = "minor"
    evidence: str = ""


class RedTeamObserver:
    """Background observer that logs interaction patterns and generates daily bias scorecards.

    H8 Phase C PMV: captures user+AI interaction patterns during L1 dialogue
    and logs them to red_team_observations table. A daily scorecard is
    generated after the session completes.
    """

    def __init__(self, state_db=None):
        self.state_db = state_db
        self.session_observations: list[BiasObservation] = []

    def observe(self, observation_type: str, target_context: str,
                description: str, severity: str = "minor", evidence: str = "") -> None:
        """Record an observation during the session (in-memory)."""
        self.session_observations.append(BiasObservation(
            observation_type=observation_type,
            target_context=target_context,
            description=description,
            severity=severity,
            evidence=evidence,
        ))

    def check_interaction_patterns(self, user_ideas: list[str],
                                   ai_responses: list[str],
                                   final_direction: str) -> list[BiasObservation]:
        """Analyze L1 interaction for systematic bias patterns (no LLM call needed)."""
        findings: list[BiasObservation] = []

        # 1. Confirmation-seeking: user proposes direction, AI agrees without sufficient challenge
        if user_ideas and ai_responses:
            # Count agreement signals in AI responses when user proposed ideas
            agree_markers = ["同意", "支持", "合理", "有道理", "agree", "correct", "valid", "right"]
            agree_count = sum(
                1 for resp in ai_responses
                if any(m in resp.lower() for m in agree_markers)
            )
            agree_ratio = agree_count / max(len(ai_responses), 1)
            if agree_ratio > 0.8 and len(user_ideas) >= 2:
                findings.append(BiasObservation(
                    observation_type="confirmation_bias",
                    target_context="user_interaction",
                    description=f"High agreement ratio ({agree_ratio:.0%}) — AI may be sycophantic",
                    severity="major" if agree_ratio > 0.9 else "minor",
                ))

        # 2. Recency bias: last question dominates final direction
        if len(user_ideas) >= 3 and final_direction:
            findings.append(BiasObservation(
                observation_type="recency_bias",
                target_context="L1_narrative",
                description=f"Multiple ({len(user_ideas)}) discussion topics — verify recency didn't dominate",
                severity="minor",
            ))

        # 3. Missing counterfactual: if user never asked "what if"
        counterfactual_phrases = ["如果", "万一", "反过来", "what if", "相反", "要是"]
        has_counterfactual = any(
            any(p in idea for p in counterfactual_phrases)
            for idea in user_ideas
        )
        if not has_counterfactual and len(user_ideas) >= 2:
            findings.append(BiasObservation(
                observation_type="missing_counterfactual",
                target_context="user_interaction",
                description="No counterfactual exploration during multi-turn discussion",
                severity="minor",
            ))

        return findings

    async def generate_daily_scorecard(self, session_date: str) -> str:
        """Generate a daily bias scorecard from all session observations."""
        if not self.session_observations:
            return "No bias observations recorded today."

        critical = sum(1 for o in self.session_observations if o.severity == "critical")
        major = sum(1 for o in self.session_observations if o.severity == "major")
        minor = sum(1 for o in self.session_observations if o.severity == "minor")

        lines = [
            "## Red Team Daily Bias Scorecard",
            f"Date: {session_date}",
            f"Total observations: {len(self.session_observations)}",
            f"  Critical: {critical}",
            f"  Major: {major}",
            f"  Minor: {minor}",
            "",
            "### Observations:",
        ]
        for obs in self.session_observations:
            lines.append(f"- [{obs.severity.upper()}] [{obs.target_context}] {obs.observation_type}: {obs.description}")

        scorecard = "\n".join(lines)

        # Persist to DB if available
        if self.state_db:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            conn = self.state_db._connect()
            try:
                for obs in self.session_observations:
                    conn.execute(
                        """INSERT INTO red_team_observations
                           (session_date, observation_type, target_context, description, severity, evidence, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (session_date, obs.observation_type, obs.target_context,
                         obs.description, obs.severity, obs.evidence, now)
                    )
                conn.commit()
            finally:
                conn.close()

        return scorecard
