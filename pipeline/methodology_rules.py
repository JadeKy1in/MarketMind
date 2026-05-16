"""SHARP: Self-Healing Adaptive Rule Pipeline — Main AI methodology governance.

P3-2a: Rule decomposition from DECISION_SYSTEM_PROMPT + AttributionAgent.
P3-2b: RuleValidator (walk-forward gate) + RuleEvolver + dynamic assembly.

Key principle: AttributionAgent generates HYPOTHESES only. The walk-forward
backtest gate is the actual judge. LLM is NOT the decision-maker on rule validity.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("marketmind.pipeline.methodology_rules")


# ── Data classes ───────────────────────────────────────────────────────────

@dataclass
class MainAIRule:
    """A single decomposable rule from the decision system prompt."""
    rule_id: str
    content: str                     # The rule text
    category: str                    # "position_sizing" | "risk_management" | "quality" | "output_format"
    status: str = "active"           # "active" | "retired" | "under_review"
    source: str = "decomposition"    # "decomposition" | "evolution" | "manual"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    retired_at: str | None = None
    retire_reason: str | None = None
    generation: int = 0              # Incremented on each evolution
    parent_rule_id: str | None = None  # For evolved rules, the original


@dataclass
class RuleImpactHypothesis:
    """AttributionAgent output — a HYPOTHESIS, not a verdict.

    The walk-forward backtest gate determines whether this hypothesis
    translates into an actual rule retirement.
    """
    rule_id: str
    suspected_impact: str            # "positive" | "negative" | "neutral"
    confidence: float                # 0.0–1.0, Flash LLM self-reported confidence
    evidence_summary: str            # Brief rationale from Flash
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class RuleDecompositionResult:
    """Output of decomposing the DECISION_SYSTEM_PROMPT into auditable rules."""
    rules: list[MainAIRule]
    total_extracted: int
    decomposition_date: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── Rule ID generation ─────────────────────────────────────────────────────

def generate_rule_id(content: str, category: str, index: int) -> str:
    """Generate a stable rule ID from content, category, and index.

    Promoted from RuleDecomposer._generate_rule_id so RuleEvolver can call it
    without importing a private method.
    """
    raw = f"{category}:{content}:{index}".encode()
    return hashlib.sha256(raw).hexdigest()[:12]


# ── Rule decomposition ─────────────────────────────────────────────────────

class RuleDecomposer:
    """Decompose static DECISION_SYSTEM_PROMPT into individual auditable rules.

    Each rule gets a unique ID derived from content hash, a category, and
    can be independently audited, validated, and evolved by SHARP.
    """

    CATEGORY_KEYWORDS = {
        "position_sizing": [
            "position size", "heat limit", "allocation", "% of portfolio",
            "max position", "total equity", "capital allocation",
        ],
        "risk_management": [
            "stop loss", "stop-loss", "risk", "drawdown", "exposure",
            "hedge", "protection", "max hold days",
        ],
        "quality": [
            "verifiable", "fabricate", "source", "citation", "evidence",
            "data", "statistical", "rigorous", "validation",
        ],
        "output_format": [
            "JSON", "output", "format", "thesis", "card", "section",
            "structure", "sentence", "paragraph",
        ],
    }

    @classmethod
    def decompose(cls, system_prompt: str) -> RuleDecompositionResult:
        """Extract individual rules from the decision system prompt.

        Parses the prompt text, extracting sentences/paragraphs that express
        actionable constraints. Each extracted rule gets categorized and ID'd.
        """
        rules = []
        # Extract rules from the prompt by splitting on sentence boundaries
        # and filtering for actionable constraint patterns
        raw_rules = cls._extract_rule_candidates(system_prompt)

        for i, content in enumerate(raw_rules):
            category = cls._classify_rule(content)
            rule_id = cls._generate_rule_id(content, category, i)
            rules.append(MainAIRule(
                rule_id=rule_id,
                content=content.strip(),
                category=category,
                source="decomposition",
            ))

        return RuleDecompositionResult(
            rules=rules,
            total_extracted=len(rules),
        )

    @classmethod
    def _extract_rule_candidates(cls, text: str) -> list[str]:
        """Extract actionable constraint lines from prompt text."""
        lines = text.strip().split("\n")
        candidates = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            # Skip structural/format lines
            if stripped.startswith(("You are", "You receive", "Output JSON",
                                    "{", "}", "[", "]", '"', "IMPORTANT")):
                # For IMPORTANT lines, extract the actual rule
                if stripped.startswith("IMPORTANT"):
                    rule_text = stripped.replace("IMPORTANT:", "").strip()
                    if rule_text and len(rule_text) > 10:
                        candidates.append(rule_text)
                continue
            # Keep lines that express constraints
            if any(kw in stripped.lower() for kw in [
                "never", "must", "should", "always", "cannot",
                "position size", "stop-loss", "heat", "limit",
                "verifiable", "exceed", "fabricate",
            ]):
                # Further split on periods if line has multiple sentences
                for sentence in stripped.rstrip(".").split(". "):
                    s = sentence.strip().rstrip(".")
                    if s and len(s) > 10:
                        candidates.append(s + ".")

        if not candidates:
            # Fallback: return the whole prompt as one rule
            candidates = [text[:500]]

        return candidates

    @classmethod
    def _classify_rule(cls, content: str) -> str:
        """Classify a rule into a category based on keyword matching."""
        content_lower = content.lower()
        scores = {}
        for category, keywords in cls.CATEGORY_KEYWORDS.items():
            scores[category] = sum(1 for kw in keywords if kw in content_lower)
        if not scores or max(scores.values()) == 0:
            return "quality"
        return max(scores, key=scores.get)

    @staticmethod
    def _generate_rule_id(content: str, category: str, index: int) -> str:
        """Generate a stable rule ID from content hash.

        Delegates to module-level generate_rule_id for the hash, then wraps
        with the rule:category: prefix for backward compatibility.
        """
        hash_id = generate_rule_id(content, category, index)
        return f"rule:{category}:{hash_id}"


# ── Attribution agent ──────────────────────────────────────────────────────

class AttributionAgent:
    """Flash-powered hypothesis generator for rule impact analysis.

    CRITICAL: This agent generates HYPOTHESES only. It does NOT make
    final keep/retire decisions. The walk-forward backtest gate (RuleValidator
    in P3-2b) is the actual verdict mechanism.

    Design invariant (from Red Team review): LLM is NOT the judge.
    """

    ATTRIBUTION_PROMPT_TEMPLATE = """[SHARP ATTRIBUTION PROTOCOL]
You are analyzing whether specific decision rules contributed to a trading outcome.

Outcome: {outcome_summary}
Decision context: {context_summary}

Rules in effect for this decision:
{rules_list}

For each rule above, hypothesize whether it had positive, negative, or neutral impact.
Output your analysis as JSON with this structure:
{{
  "hypotheses": [
    {{
      "rule_id": "<rule id>",
      "suspected_impact": "positive|negative|neutral",
      "confidence": 0.0,
      "evidence_summary": "Brief (1-2 sentences) explaining your reasoning"
    }}
  ]
}}

IMPORTANT: You are generating HYPOTHESES, not verdicts. Your analysis will be
validated by a statistical backtest gate. Be conservative in confidence scores.
"""

    def __init__(self):
        self._hypothesis_cache: dict[str, list[RuleImpactHypothesis]] = {}

    def build_attribution_prompt(
        self, rules: list[MainAIRule], outcome_summary: str, context_summary: str
    ) -> str:
        """Build the prompt for Flash LLM attribution analysis."""
        rules_list = "\n".join(
            f"- [{r.rule_id}] ({r.category}) {r.content[:200]}"
            for r in rules
        )
        return self.ATTRIBUTION_PROMPT_TEMPLATE.format(
            outcome_summary=outcome_summary,
            context_summary=context_summary,
            rules_list=rules_list,
        )

    async def generate_hypotheses(
        self, rules: list[MainAIRule], outcome_summary: str, context_summary: str
    ) -> list[RuleImpactHypothesis]:
        """Generate impact hypotheses for each rule using Flash LLM.

        Returns cached results if the same rules+outcome combination was
        already analyzed.
        """
        cache_key = hashlib.sha256(
            f"{outcome_summary}:{context_summary}".encode()
        ).hexdigest()[:16]

        if cache_key in self._hypothesis_cache:
            return self._hypothesis_cache[cache_key]

        # Build prompt and call Flash
        prompt = self.build_attribution_prompt(rules, outcome_summary, context_summary)

        try:
            from marketmind.gateway.async_client import chat_flash
            result = await chat_flash(
                system_prompt="You are a statistical hypothesis generator. Output only valid JSON.",
                user_prompt=prompt,
                temperature=0.1,
                max_tokens=2048,
            )
            hypotheses = self._parse_attribution_response(result.get("content", "{}"))
        except Exception as e:
            logger.warning("AttributionAgent Flash call failed: %s — returning empty hypotheses", e)
            hypotheses = []

        self._hypothesis_cache[cache_key] = hypotheses
        return hypotheses

    @staticmethod
    def _parse_attribution_response(response_text: str) -> list[RuleImpactHypothesis]:
        """Parse Flash LLM JSON response into RuleImpactHypothesis objects."""
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from the response
            import re
            match = re.search(r'\{[\s\S]*\}', response_text)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    return []
            else:
                return []

        hypotheses = []
        for h in data.get("hypotheses", []):
            hypotheses.append(RuleImpactHypothesis(
                rule_id=h.get("rule_id", "unknown"),
                suspected_impact=h.get("suspected_impact", "neutral"),
                confidence=min(max(float(h.get("confidence", 0.5)), 0.0), 1.0),
                evidence_summary=h.get("evidence_summary", ""),
            ))

        return hypotheses

    def clear_cache(self) -> None:
        """Clear the hypothesis cache."""
        self._hypothesis_cache.clear()


# ── Rule registry ──────────────────────────────────────────────────────────

class RuleRegistry:
    """In-memory registry of active Main AI rules with audit trail support.

    Stores rules, tracks their status changes, and provides query methods
    for dynamic prompt assembly (P3-2b).
    """

    def __init__(self):
        self._rules: dict[str, MainAIRule] = {}
        self._audit_log: list[dict] = []

    def register(self, rule: MainAIRule) -> None:
        self._rules[rule.rule_id] = rule

    def get(self, rule_id: str) -> MainAIRule | None:
        return self._rules.get(rule_id)

    def get_active(self, category: str | None = None) -> list[MainAIRule]:
        """Get all active rules, optionally filtered by category."""
        # Snapshot values to prevent RuntimeError from concurrent mutation
        return [
            r for r in list(self._rules.values())
            if r.status == "active"
            and (category is None or r.category == category)
        ]

    def retire(self, rule_id: str, reason: str) -> bool:
        """Retire a rule with audit trail."""
        rule = self._rules.get(rule_id)
        if rule is None:
            return False
        rule.status = "retired"
        rule.retired_at = datetime.now(timezone.utc).isoformat()
        rule.retire_reason = reason
        self._log_audit(rule_id, "retired", {"reason": reason})
        return True

    def set_under_review(self, rule_id: str) -> bool:
        rule = self._rules.get(rule_id)
        if rule is None:
            return False
        rule.status = "under_review"
        self._log_audit(rule_id, "under_review", {})
        return True

    def _log_audit(self, rule_id: str, action: str, details: dict) -> None:
        self._audit_log.append({
            "rule_id": rule_id,
            "action": action,
            "details": details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get_audit_trail(self, rule_id: str | None = None,
                        limit: int = 50) -> list[dict]:
        """Get audit log, optionally filtered by rule_id."""
        entries = self._audit_log
        if rule_id:
            entries = [e for e in entries if e["rule_id"] == rule_id]
        return entries[-limit:]

    def to_dict(self) -> dict:
        """Serialize all rules for storage."""
        return {
            rid: {
                "rule_id": r.rule_id,
                "content": r.content,
                "category": r.category,
                "status": r.status,
                "source": r.source,
                "created_at": r.created_at,
                "retired_at": r.retired_at,
                "retire_reason": r.retire_reason,
                "generation": r.generation,
                "parent_rule_id": r.parent_rule_id,
            }
            for rid, r in self._rules.items()
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RuleRegistry":
        """Restore registry from serialized data."""
        registry = cls()
        for rid, rdata in data.items():
            rule = MainAIRule(
                rule_id=rdata["rule_id"],
                content=rdata["content"],
                category=rdata["category"],
                status=rdata.get("status", "active"),
                source=rdata.get("source", "decomposition"),
                created_at=rdata.get("created_at", ""),
                retired_at=rdata.get("retired_at"),
                retire_reason=rdata.get("retire_reason"),
                generation=rdata.get("generation", 0),
                parent_rule_id=rdata.get("parent_rule_id"),
            )
            registry._rules[rid] = rule
        return registry


# ── Dynamic Prompt Assembly (P3-2b) ──────────────────────────────────────

def assemble_dynamic_prompt(registry: RuleRegistry,
                            base_instructions: str = "",
                            max_chars: int = 8000) -> str:
    """Build a decision system prompt from active rules in the registry.

    Replaces the static DECISION_SYSTEM_PROMPT with a dynamically assembled
    prompt that only includes active (non-retired) rules. This enables
    SHARP to evolve the main AI's instructions without manual editing.

    Args:
        registry: The RuleRegistry containing decomposed and evolved rules.
        base_instructions: Static preamble text (role description, input format).
        max_chars: Maximum prompt length before truncation warning is appended.

    Returns:
        Complete system prompt assembled from active rules.
    """
    if not base_instructions:
        base_instructions = (
            "You are a decision synthesis engine. "
            "Your job is to produce the final decision cards that a human investor will review.\n\n"
            "You receive:\n"
            "- Layer 1 narrative analysis\n"
            "- Layer 2 fundamental analysis with ticker candidates\n"
            "- Layer 3 technical review (green/yellow/red lights)\n"
            "- Red Team challenges\n"
            "- Signal resonance verdict\n\n"
            "Output JSON with decision_cards, no_trade_card, and summary fields.\n\n"
            "CRITICAL RULES (dynamically assembled by SHARP):\n"
        )

    categories = ["position_sizing", "risk_management", "quality", "output_format"]
    parts = [base_instructions]
    total_len = len(base_instructions)
    truncated = False

    for category in categories:
        active_rules = registry.get_active(category=category)
        if not active_rules:
            continue
        category_label = category.replace("_", " ").title()
        header = f"\n## {category_label}"
        parts.append(header)
        total_len += len(header)
        for rule in active_rules:
            rule_line = f"- [{rule.rule_id}] {rule.content}"
            if total_len + len(rule_line) > max_chars:
                truncated = True
                break
            parts.append(rule_line)
            total_len += len(rule_line)
        if truncated:
            break

    footer = (
        "\n\nIMPORTANT: The no-trade card must be equally rigorous as the decision cards. "
        "All prices must be verifiable. Never fabricate."
    )
    if truncated:
        footer += (
            f"\n[SHARP WARNING: Prompt truncated at {max_chars} chars. "
            "Some rules were omitted. Review rule registry for bloat.]"
        )
        logger.warning(
            "Dynamic prompt truncated at %d chars — %d rules omitted. "
            "Consider retiring stale rules.",
            max_chars,
            sum(len(registry.get_active(cat)) for cat in categories) - sum(1 for _ in parts)
        )
    parts.append(footer)
    return "\n".join(parts)


def get_default_rules() -> RuleRegistry:
    """Initialize registry with rules decomposed from DECISION_SYSTEM_PROMPT.

    This is called on first use — subsequent runs use the evolved registry
    persisted to disk.
    """
    from marketmind.pipeline.decision import DECISION_SYSTEM_PROMPT
    result = RuleDecomposer.decompose(DECISION_SYSTEM_PROMPT)
    registry = RuleRegistry()
    for rule in result.rules:
        registry.register(rule)
    return registry
