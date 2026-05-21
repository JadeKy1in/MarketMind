"""SHARP Rule Evolution — P3-2b walk-forward validation + atomic edits.

RuleValidator: WFA gate that is the ACTUAL verdict on rule validity.
RuleEvolver: Atomic edits (tune/add/remove) — never multi-rule rewrites.
assemble_dynamic_prompt: Build decision prompt from active rules only.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from marketmind.pipeline.methodology_rules import MainAIRule, RuleRegistry

logger = logging.getLogger("marketmind.pipeline.methodology_evolution")


class RuleValidator:
    """Walk-forward validation gate for SHARP rules.

    Uses the same pattern as WalkForwardValidator for shadows (P2-2):
    OOS performance determines keep/retire. Backtest is the ACTUAL verdict.
    """

    _MIN_CHECKS = 5

    def __init__(self, train_days: int = 60, test_days: int = 15):
        self.train_days = train_days
        self.test_days = test_days

    def validate(self, rule: MainAIRule,
                 audit_history: list[dict]) -> tuple[bool, str]:
        """Returns (should_retire: bool, reason: str)."""
        if len(audit_history) < self._MIN_CHECKS:
            return False, f"Insufficient audits: {len(audit_history)} < {self._MIN_CHECKS}"

        if len(audit_history) <= self.train_days:
            is_window = audit_history
            oos_window = []
        else:
            is_window = audit_history[:self.train_days]
            oos_window = audit_history[self.train_days:self.train_days + self.test_days]

        def _accuracy(entries):
            if not entries:
                return None
            return sum(1 for e in entries if e.get("correct", False)) / len(entries)

        is_acc = _accuracy(is_window)
        oos_acc = _accuracy(oos_window) if oos_window else None

        if oos_acc is None:
            return False, "No OOS data available — defer"

        if oos_acc < 0.50:
            return True, f"OOS accuracy {oos_acc:.2%} < 0.50 — rule does not generalize"

        if is_acc and is_acc > 0 and oos_acc / is_acc < 0.6:
            return True, (
                f"WFE degradation: OOS/IS = {oos_acc:.2%}/{is_acc:.2%} = "
                f"{oos_acc/is_acc:.2%} < 0.60"
            )

        return False, f"OOS accuracy {oos_acc:.2%} acceptable"


class RuleEvolver:
    """Evolution engine for SHARP rules.

    Three atomic edit types (never multi-rule rewrites):
    1. Tune threshold
    2. Add condition
    3. Remove rule
    """

    def __init__(self, registry: RuleRegistry, validator: RuleValidator | None = None):
        self.registry = registry
        self.validator = validator or RuleValidator()

    def evolve(self, audits: dict[str, list[dict]]) -> list[str]:
        """Run one evolution cycle. Returns list of change descriptions."""
        changes: list[str] = []
        for rule in self.registry.get_active():
            rule_audits = audits.get(rule.rule_id, [])
            if not rule_audits:
                continue
            should_retire, reason = self.validator.validate(rule, rule_audits)
            if should_retire:
                self.registry.retire(rule.rule_id, reason)
                changes.append(f"RETIRED {rule.rule_id}: {reason}")
                continue
            correct = sum(1 for a in rule_audits if a.get("correct", False))
            rule.validation_count += len(rule_audits)
            rule.success_count += correct
            rule.last_modified = datetime.now(timezone.utc).isoformat()
            rule._update_decay()
        return changes

    def tune_threshold(self, rule: MainAIRule, param_name: str,
                       new_value: float, old_value: float) -> str:
        """Atomic edit: replace a numeric threshold in a rule."""
        old_text = str(old_value)
        new_text = str(new_value)
        if old_text not in rule.rule_text:
            return f"Param '{param_name}' ({old_text}) not found in rule {rule.rule_id}"
        rule.rule_text = rule.rule_text.replace(old_text, new_text, 1)
        rule.version += 1
        rule.last_modified = datetime.now(timezone.utc).isoformat()
        return f"TUNED {rule.rule_id}: {param_name} {old_value} → {new_value}"

    def add_condition(self, rule: MainAIRule, condition: str) -> str:
        """Atomic edit: append a sub-condition to an existing rule."""
        rule.rule_text = rule.rule_text.rstrip() + f"\n  - {condition}"
        rule.version += 1
        rule.last_modified = datetime.now(timezone.utc).isoformat()
        return f"EXTENDED {rule.rule_id}: added condition '{condition[:60]}...'"

    def remove_rule(self, rule_id: str) -> str:
        """Explicitly retire a rule identified by WFA as harmful."""
        reason = "Evolver: removed by WFA validation gate"
        self.registry.retire(rule_id, reason)
        return f"REMOVED {rule_id}: {reason}"


def assemble_dynamic_prompt(registry: RuleRegistry,
                            base_instructions: str = "") -> str:
    """Build decision prompt from active rules in the registry.

    Categories in priority order: risk, analysis, timing, process.
    Retired rules are excluded.
    """
    active = registry.get_active()
    if not active:
        return base_instructions or "No active rules available."

    order = {"risk": 0, "analysis": 1, "timing": 2, "process": 3}
    sorted_rules = sorted(active, key=lambda r: (order.get(r.category, 9), r.rule_id))

    lines = [base_instructions] if base_instructions else []
    current_cat = None
    for rule in sorted_rules:
        if rule.category != current_cat:
            current_cat = rule.category
            lines.append(f"\n## {current_cat.upper()} RULES")
        decay_note = f" [decay={rule.decay_factor:.1f}]" if rule.decay_factor < 1.0 else ""
        lines.append(f"- [{rule.rule_id}]{decay_note} {rule.rule_text}")

    return "\n".join(lines)
