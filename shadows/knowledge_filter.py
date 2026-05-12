"""Knowledge Filter — Learngenes selective inheritance for challenger shadows.

Manages knowledge inheritance when a challenger replaces a target shadow.
Ensures only verified, cross-checked knowledge transfers while isolating
false positives for independent 30-day re-verification.

Filter rules:
- PASS: verification_count >= 2 (cross-verified insights)
- PASS: verification_count >= 1 (verified methodology components)
- DROP: verification_count == 0 (unverified heuristics and rules)
- ISOLATE: known false positives (marked for independent 30-day re-verification)

ACE Risk score: 0-1 based on cascade depth and unverified ratio.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("marketmind.shadows.knowledge_filter")


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class KnowledgeItem:
    """A single piece of inheritable knowledge from a shadow.

    Represents insights, methodology components, heuristics, or rules
    that can be passed to challenger shadows during elimination/replacement.
    """
    item_id: str
    source_shadow_id: str
    category: str           # "insight" | "methodology_component" | "heuristic" | "rule"
    content: str
    verification_count: int = 0
    false_positive_count: int = 0

    VALID_CATEGORIES = {"insight", "methodology_component", "heuristic", "rule"}

    def __post_init__(self):
        if self.category not in self.VALID_CATEGORIES:
            raise ValueError(
                f"category must be one of {self.VALID_CATEGORIES}, got '{self.category}'"
            )
        if self.verification_count < 0:
            raise ValueError(f"verification_count must be >= 0, got {self.verification_count}")
        if self.false_positive_count < 0:
            raise ValueError(f"false_positive_count must be >= 0, got {self.false_positive_count}")


# ── Filter ──────────────────────────────────────────────────────────────────

class KnowledgeFilter:
    """Selectively filters knowledge items for challenger inheritance.

    Manages the Learngenes — determines which knowledge from a failing shadow
    should transfer to a challenger and which should be dropped or isolated.

    Filter rules by category:
    - insight: PASS if verification_count >= 2
    - methodology_component: PASS if verification_count >= 1
    - heuristic: PASS if verification_count >= 2; DROP if verification_count == 0
    - rule: PASS if verification_count >= 1; DROP if verification_count == 0

    Override: Any item with false_positive_count > 0 is ISOLATED (not passed,
    queued for 30-day independent re-verification).

    ACE (Adversarial Cascade Effect) risk measures the danger of propagating
    unverified or weakly-verified knowledge through multiple generations.
    High ACE risk -> knowledge inheritance chain should be broken.
    """

    # Thresholds
    INSIGHT_MIN_VERIFICATION = 2
    METHODOLOGY_MIN_VERIFICATION = 1
    HEURISTIC_MIN_VERIFICATION = 2
    RULE_MIN_VERIFICATION = 1

    # ACE risk weights
    ACE_UNVERIFIED_WEIGHT = 0.50      # Weight for unverified ratio
    ACE_FALSE_POSITIVE_WEIGHT = 0.30  # Weight for known false positive ratio
    ACE_CASCADE_INTERACTION = 0.20    # Cascade depth interaction with unverified/fp ratio

    def __init__(self):
        self._isolated_items: list[KnowledgeItem] = []

    # ── Filtering ────────────────────────────────────────────────────────

    def filter_inheritance(
        self, source_shadow_id: str, knowledge_items: list[KnowledgeItem]
    ) -> list[KnowledgeItem]:
        """Filter knowledge items for inheritance to a challenger.

        Applies category-specific verification thresholds and false-positive
        isolation. Returns only items that should be inherited.

        Args:
            source_shadow_id: The shadow being replaced (origin of knowledge).
            knowledge_items: All knowledge items from the source.

        Returns:
            List of KnowledgeItem that passed filtering (should be inherited).
        """
        self._isolated_items = []
        passed: list[KnowledgeItem] = []

        for item in knowledge_items:
            # ISOLATE: known false positives always isolated
            if item.false_positive_count > 0:
                self._isolated_items.append(item)
                logger.debug(
                    "ISOLATE: item '%s' (category=%s, false_positives=%d) — queued for 30-day re-verification",
                    item.item_id, item.category, item.false_positive_count
                )
                continue

            # Category-specific verification thresholds
            if item.category == "insight":
                if item.verification_count >= self.INSIGHT_MIN_VERIFICATION:
                    passed.append(item)
                else:
                    logger.debug(
                        "DROP: insight '%s' — verification_count=%d < %d",
                        item.item_id, item.verification_count, self.INSIGHT_MIN_VERIFICATION
                    )

            elif item.category == "methodology_component":
                if item.verification_count >= self.METHODOLOGY_MIN_VERIFICATION:
                    passed.append(item)
                else:
                    logger.debug(
                        "DROP: methodology '%s' — verification_count=%d < %d",
                        item.item_id, item.verification_count, self.METHODOLOGY_MIN_VERIFICATION
                    )

            elif item.category == "heuristic":
                if item.verification_count >= self.HEURISTIC_MIN_VERIFICATION:
                    passed.append(item)
                else:
                    logger.debug(
                        "DROP: heuristic '%s' — verification_count=%d < %d",
                        item.item_id, item.verification_count, self.HEURISTIC_MIN_VERIFICATION
                    )

            elif item.category == "rule":
                if item.verification_count >= self.RULE_MIN_VERIFICATION:
                    passed.append(item)
                else:
                    logger.debug(
                        "DROP: rule '%s' — verification_count=%d < %d",
                        item.item_id, item.verification_count, self.RULE_MIN_VERIFICATION
                    )

        logger.info(
            "Knowledge filter: source=%s total=%d passed=%d isolated=%d dropped=%d",
            source_shadow_id, len(knowledge_items), len(passed),
            len(self._isolated_items),
            len(knowledge_items) - len(passed) - len(self._isolated_items)
        )

        return passed

    def get_isolated_items(self) -> list[KnowledgeItem]:
        """Get the list of items isolated (false positives) from the last filter_inheritance call."""
        return list(self._isolated_items)

    # ── ACE Risk ─────────────────────────────────────────────────────────

    def detect_ace_risk(self, items: list[KnowledgeItem]) -> float:
        """Compute ACE (Adversarial Cascade Effect) risk score.

        Measures the risk of propagating unreliable knowledge through
        multiple shadow generations. Score in [0, 1] where higher = more risk.

        - Returns 0.0 if ALL items are verified and have no false positives.
        - Otherwise: unverified ratio (0.5 weight) + false positive ratio (0.3 weight)
          + cascade depth interaction with unverified/fp items (0.2 weight).

        Cascade depth only amplifies risk when unverified or false positive
        items are present — verified-only chains have zero ACE risk.

        Args:
            items: Knowledge items being considered for inheritance.

        Returns:
            ACE risk score between 0.0 and 1.0.
        """
        if not items:
            return 0.0

        n = len(items)

        # Count categories
        unverified_count = sum(1 for item in items if item.verification_count == 0)
        fp_count = sum(1 for item in items if item.false_positive_count > 0)

        unverified_ratio = unverified_count / n
        fp_ratio = fp_count / n

        # If everything is verified and no false positives, ACE risk is zero
        if unverified_ratio == 0.0 and fp_ratio == 0.0:
            return 0.0

        # Source diversity / cascade depth
        source_ids = set(item.source_shadow_id for item in items)
        cascade_depth = min(len(source_ids) / max(n, 1), 1.0)

        # ACE risk: cascade depth only amplifies when unverified/fp items exist
        ace_score = (
            self.ACE_UNVERIFIED_WEIGHT * unverified_ratio +
            self.ACE_FALSE_POSITIVE_WEIGHT * fp_ratio +
            self.ACE_CASCADE_INTERACTION * cascade_depth * max(unverified_ratio, fp_ratio)
        )

        return min(ace_score, 1.0)

    # ── Filter rule descriptions ─────────────────────────────────────────

    def get_filter_rules_description(self) -> dict:
        """Return human-readable description of current filter rules."""
        return {
            "insight": f"PASS if verification_count >= {self.INSIGHT_MIN_VERIFICATION}",
            "methodology_component": f"PASS if verification_count >= {self.METHODOLOGY_MIN_VERIFICATION}",
            "heuristic": f"PASS if verification_count >= {self.HEURISTIC_MIN_VERIFICATION}, DROP if 0",
            "rule": f"PASS if verification_count >= {self.RULE_MIN_VERIFICATION}, DROP if 0",
            "false_positive_override": "ISOLATE regardless of verification (30-day re-verification)",
            "ace_weights": {
                "unverified_ratio": self.ACE_UNVERIFIED_WEIGHT,
                "false_positive_ratio": self.ACE_FALSE_POSITIVE_WEIGHT,
                "cascade_interaction": self.ACE_CASCADE_INTERACTION,
            },
        }
