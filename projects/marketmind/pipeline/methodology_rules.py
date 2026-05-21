"""SHARP: Self-Healing Adaptive Rule Pipeline — Main AI methodology governance.

P3-2a: Rule decomposition from DECISION_SYSTEM_PROMPT + AttributionAgent.
Decomposes the static DECISION_SYSTEM_PROMPT into individually auditable rules
with the same pattern shadows already use: ID -> decay -> validation -> audit.

Key principle: AttributionAgent generates HYPOTHESES only. The walk-forward
backtest gate is the actual judge. LLM is NOT the decision-maker on rule validity.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("marketmind.pipeline.methodology_rules")


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class MainAIRule:
    """A single decomposable rule from the decision system prompt.

    Each rule gets a stable ID derived from content hash, a category,
    and can be independently audited, validated, and retired by SHARP.
    """
    rule_id: str                          # e.g. "R001_risk"
    rule_text: str                        # The rule as it appears in the prompt
    category: str                         # "risk" | "timing" | "analysis" | "process"
    version: int = 1
    created_date: str = ""
    last_modified: str = ""
    status: str = "active"                # "active" | "retired" | "modified"
    decay_factor: float = 1.0             # 1.0 = full strength, decays toward 0
    validation_count: int = 0
    success_count: int = 0
    retired_date: str | None = None
    retirement_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.created_date:
            self.created_date = datetime.now(timezone.utc).isoformat()
        if not self.last_modified:
            self.last_modified = self.created_date

    def _update_decay(self) -> None:
        """Update decay factor based on validation count.

        High validation count with low success → decay toward 0.
        High success with many validations → maintain or restore.
        Formula: decay = min(1.0, success_rate * log10(validation_count + 1) / 2)
        """
        import math
        if self.validation_count == 0:
            return
        rate = self.success_count / max(self.validation_count, 1)
        log_factor = math.log10(self.validation_count + 1) / 2.0
        self.decay_factor = min(1.0, rate * log_factor)


@dataclass
class AttributionHypothesis:
    """Output of AttributionAgent — hypothesis only, NOT verdict.

    The walk-forward backtest gate determines whether this hypothesis
    translates into an actual rule retirement. LLM is NOT the judge.
    """
    rule_id: str
    suspected_impact: str                 # "positive" | "negative" | "neutral"
    confidence: float                     # 0.0-1.0
    evidence_summary: str                 # Brief description of evidence
    date: str = ""

    def __post_init__(self) -> None:
        if not self.date:
            self.date = datetime.now(timezone.utc).isoformat()


# ── Rule ID generation ────────────────────────────────────────────────────────

def _generate_rule_id(content: str, category: str, index: int) -> str:
    """Generate a stable, short rule ID from content hash + category + index."""
    short_cat = {"risk": "RSK", "timing": "TIM", "analysis": "ANL", "process": "PRC"}
    prefix = short_cat.get(category, "GEN")
    raw = f"{category}:{content}:{index}".encode("utf-8")
    hash_suffix = hashlib.sha256(raw).hexdigest()[:8].upper()
    return f"R{prefix}-{hash_suffix}"


# ── Rule Decomposer ──────────────────────────────────────────────────────────

class RuleDecomposer:
    """Decompose the static DECISION_SYSTEM_PROMPT into auditable rules.

    Parses the prompt text into individual, categorized, ID-bearing rules
    that can be independently tracked, validated, and evolved by SHARP.
    """

    CATEGORY_KEYWORDS: dict[str, list[str]] = {
        "risk": [
            "position size", "heat limit", "stop-loss", "stop loss",
            "total equity", "drawdown", "exposure", "max position",
            "capital allocation", "risk", "portfolio",
        ],
        "timing": [
            "max hold days", "hold period", "entry timing", "exit timing",
            "time window", "duration", "expiration",
        ],
        "analysis": [
            "verifiable", "fabricate", "source", "citation", "evidence",
            "data", "statistical", "validation", "price",
        ],
        "process": [
            "JSON", "output", "format", "thesis", "card", "section",
            "sentence", "paragraph", "structure", "no-trade",
        ],
    }

    @staticmethod
    def decompose(system_prompt: str) -> list[MainAIRule]:
        """Parse DECISION_SYSTEM_PROMPT into structured rules.

        Extracts numbered/bulleted rules, IMPORTANT annotations, and
        constraint-bearing sentences. Assigns IDs and categories.
        """
        candidates = RuleDecomposer._extract_rule_candidates(system_prompt)
        rules: list[MainAIRule] = []

        for i, content in enumerate(candidates):
            category = RuleDecomposer._classify_rule(content)
            rule_id = _generate_rule_id(content, category, i)
            now = datetime.now(timezone.utc).isoformat()
            rules.append(MainAIRule(
                rule_id=rule_id,
                rule_text=content.strip(),
                category=category,
                created_date=now,
                last_modified=now,
            ))

        return rules

    @staticmethod
    def assemble(rules: list[MainAIRule], base_instructions: str = "") -> str:
        """Reassemble active rules into a decision system prompt.

        Groups rules by category, adds headers, and produces a complete
        prompt suitable for use as the decision system prompt.

        Args:
            rules: The active (non-retired) rules to include.
            base_instructions: Optional static preamble (role, input description).
                               If empty, a sensible default is used.

        Returns:
            Complete system prompt assembled from active rules.
        """
        if not base_instructions:
            base_instructions = (
                "You are a decision synthesis engine. Your job is to produce "
                "the final decision cards that a human investor will review.\n\n"
                "You receive:\n"
                "- Layer 1 narrative analysis\n"
                "- Layer 2 fundamental analysis with ticker candidates\n"
                "- Layer 3 technical review (green/yellow/red lights)\n"
                "- Red Team challenges\n"
                "- Signal resonance verdict\n"
            )

        category_labels = {
            "risk": "Risk & Position Sizing",
            "timing": "Timing & Holding Period",
            "analysis": "Analysis Quality & Verifiability",
            "process": "Output Format & Process",
        }

        # Group rules by category preserving insertion order
        grouped: dict[str, list[MainAIRule]] = {}
        for rule in rules:
            if rule.status != "active":
                continue
            grouped.setdefault(rule.category, []).append(rule)

        parts: list[str] = [base_instructions]

        # Output format section (critical for JSON parsing)
        parts.append("\nOutput JSON:\n{")
        parts.append('  "decision_cards": [')
        parts.append('    {')
        parts.append('      "ticker": "TICKER",')
        parts.append('      "direction": "long|short",')
        parts.append('      "position_size_pct": 0.0,')
        parts.append('      "entry_low": 0.0,')
        parts.append('      "entry_high": 0.0,')
        parts.append('      "stop_loss": 0.0,')
        parts.append('      "target_price": 0.0,')
        parts.append('      "max_hold_days": 30,')
        parts.append('      "reward_risk_ratio": 0.0,')
        parts.append('      "thesis": "1-sentence thesis",')
        parts.append('      "risk_statement": "1-sentence risk",')
        parts.append('      "red_team_note": "key objection",')
        parts.append('      "cash_reframing": "if I had cash today..."')
        parts.append('    }')
        parts.append('  ],')
        parts.append('  "no_trade_card": {')
        parts.append('    "thesis": "why not trading is best",')
        parts.append('    "supporting_evidence": ["reason1", "reason2"],')
        parts.append('    "counterfactual": "what would make us trade",')
        parts.append('    "structural_advantages": ["edge1", "edge2"]')
        parts.append('  },')
        parts.append('  "summary": "1-paragraph overall assessment"')
        parts.append('}')

        # Per-category rules
        display_order = ["risk", "analysis", "timing", "process"]
        for category in display_order:
            cat_rules = grouped.get(category, [])
            if not cat_rules:
                continue
            label = category_labels.get(category, category.title())
            parts.append(f"\n## {label}")
            for rule in cat_rules:
                parts.append(f"- [{rule.rule_id}] {rule.rule_text}")

        return "\n".join(parts)

    @staticmethod
    def get_rules_by_category(
        rules: list[MainAIRule], category: str
    ) -> list[MainAIRule]:
        """Filter rules to a specific category."""
        return [r for r in rules if r.category == category]

    @staticmethod
    def _extract_rule_candidates(text: str) -> list[str]:
        """Extract actionable constraint lines from the prompt text.

        Handles: IMPORTANT annotations, must/never/should/cannot statements,
        and constraint-bearing sentences with rule-like keywords.
        """
        lines = text.strip().split("\n")
        candidates: list[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Skip JSON structure lines
            if stripped.rstrip(",") in ('{', '}', '[', ']') or stripped.startswith('"'):
                continue

            # Skip input description markers
            if stripped.startswith("- ") and not any(
                kw in stripped.lower()
                for kw in ["never", "must", "should", "cannot", "always", "limit",
                           "exceed", "verifiable", "fabricate", "position",
                           "stop-loss", "heat", "equity"]
            ):
                continue

            # Handle IMPORTANT: annotations — extract the rule after the colon
            if stripped.upper().startswith("IMPORTANT"):
                rule_text = re.sub(r'^IMPORTANT\s*:\s*', '', stripped, flags=re.IGNORECASE).strip()
                if rule_text and len(rule_text) > 10:
                    # Split compound IMPORTANT lines on sentence boundaries
                    for sentence in _split_sentences(rule_text):
                        if sentence and len(sentence) > 10:
                            candidates.append(sentence)
                continue

            # Skip structural/intro lines
            if stripped.startswith(("You are", "You receive", "Output JSON",
                                      "Your job", "Produce decision")):
                continue

            # Keep lines that express constraints via keyword or pattern
            constraint_keywords = [
                "never", "must", "should", "always", "cannot",
                "position size", "stop-loss", "stop loss", "heat", "limit",
                "verifiable", "exceed", "fabricate", "equally",
                "structural", "max hold", "no-trade",
            ]
            if any(kw in stripped.lower() for kw in constraint_keywords):
                for sentence in _split_sentences(stripped):
                    s = sentence.strip()
                    if s and len(s) > 10:
                        candidates.append(s)

        # Deduplicate while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for c in candidates:
            normalized = c.strip().lower()
            if normalized not in seen:
                seen.add(normalized)
                deduped.append(c)

        if not deduped:
            # Fallback: treat the whole prompt as a single rule
            deduped = [text[:500].strip()]

        return deduped

    @staticmethod
    def _classify_rule(content: str) -> str:
        """Classify a rule into a category based on keyword scoring."""
        content_lower = content.lower()
        scores: dict[str, int] = {}
        for category, keywords in RuleDecomposer.CATEGORY_KEYWORDS.items():
            scores[category] = sum(1 for kw in keywords if kw in content_lower)

        if not scores or max(scores.values()) == 0:
            return "process"  # Default category

        return max(scores, key=scores.get)


def _split_sentences(text: str) -> list[str]:
    """Split text on sentence boundaries (. ! ?) while preserving the delimiter."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    result: list[str] = []
    for s in sentences:
        s = s.strip().rstrip(".")
        if s:
            result.append(s + ".")
    return result


# ── Rule Registry ─────────────────────────────────────────────────────────────

class RuleRegistry:
    """In-memory registry of active Main AI rules with audit trail support.

    Stores rules, tracks status changes, and provides query methods
    for dynamic prompt assembly (used by P3-2b RuleValidator/RuleEvolver).
    """

    def __init__(self) -> None:
        self._rules: dict[str, MainAIRule] = {}
        self._audit_log: list[dict] = []

    def register(self, rule: MainAIRule) -> None:
        """Add or update a rule in the registry."""
        self._rules[rule.rule_id] = rule

    def get(self, rule_id: str) -> MainAIRule | None:
        """Retrieve a rule by ID."""
        return self._rules.get(rule_id)

    def get_active(self, category: str | None = None) -> list[MainAIRule]:
        """Get all active rules, optionally filtered by category."""
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
        rule.retired_date = datetime.now(timezone.utc).isoformat()
        rule.retirement_reason = reason
        self._log_audit(rule_id, "retired", {"reason": reason})
        return True

    def set_under_review(self, rule_id: str) -> bool:
        """Mark a rule as under review."""
        rule = self._rules.get(rule_id)
        if rule is None:
            return False
        rule.status = "under_review"
        self._log_audit(rule_id, "under_review", {})
        return True

    def mark_validated(self, rule_id: str, success: bool) -> bool:
        """Increment validation/success counters for a rule."""
        rule = self._rules.get(rule_id)
        if rule is None:
            return False
        rule.validation_count += 1
        if success:
            rule.success_count += 1
            rule.decay_factor = min(1.0, rule.decay_factor + 0.05)
        else:
            rule.decay_factor = max(0.0, rule.decay_factor - 0.15)
        rule.last_modified = datetime.now(timezone.utc).isoformat()
        return True

    def _log_audit(self, rule_id: str, action: str, details: dict) -> None:
        self._audit_log.append({
            "rule_id": rule_id,
            "action": action,
            "details": details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get_audit_trail(
        self, rule_id: str | None = None, limit: int = 50
    ) -> list[dict]:
        """Get audit log entries, optionally filtered by rule_id."""
        entries = self._audit_log
        if rule_id:
            entries = [e for e in entries if e["rule_id"] == rule_id]
        return entries[-limit:]

    def to_dict(self) -> dict:
        """Serialize all rules for persistence."""
        return {
            rid: {
                "rule_id": r.rule_id,
                "rule_text": r.rule_text,
                "category": r.category,
                "version": r.version,
                "created_date": r.created_date,
                "last_modified": r.last_modified,
                "status": r.status,
                "decay_factor": r.decay_factor,
                "validation_count": r.validation_count,
                "success_count": r.success_count,
                "retired_date": r.retired_date,
                "retirement_reason": r.retirement_reason,
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
                rule_text=rdata["rule_text"],
                category=rdata["category"],
                version=rdata.get("version", 1),
                created_date=rdata.get("created_date", ""),
                last_modified=rdata.get("last_modified", ""),
                status=rdata.get("status", "active"),
                decay_factor=rdata.get("decay_factor", 1.0),
                validation_count=rdata.get("validation_count", 0),
                success_count=rdata.get("success_count", 0),
                retired_date=rdata.get("retired_date"),
                retirement_reason=rdata.get("retirement_reason"),
            )
            registry._rules[rid] = rule
        return registry


# ── Convenience: decompose from the canonical DECISION_SYSTEM_PROMPT ──────────

def get_default_rules() -> RuleRegistry:
    """Initialize registry with rules decomposed from DECISION_SYSTEM_PROMPT.

    Called on first use — subsequent runs use the evolved registry
    persisted to disk.
    """
    from marketmind.pipeline.decision import DECISION_SYSTEM_PROMPT

    rules = RuleDecomposer.decompose(DECISION_SYSTEM_PROMPT)
    registry = RuleRegistry()
    for rule in rules:
        registry.register(rule)
    return registry
