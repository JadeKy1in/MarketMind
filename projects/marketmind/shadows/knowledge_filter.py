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
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

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
    # Lineage tracking (Phase 4, Learngene + Coherence Burden)
    origin_generation: int = 0
    generations_inherited: int = 0
    last_verified_date: str = ""
    distinct_source_count: int = 1  # N distinct sources > N verifications from same source
    inheritance_effectiveness: float | None = None  # did inheriting this improve performance?

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

@dataclass
class KnowledgeVerdict:
    """Evaluation result for external observation."""
    verdict: str              # "PASS" | "DROP" | "ISOLATE"
    reason: str
    confidence: float         # 0.0-1.0 how confident the evaluation is
    evaluated_at: str = ""    # ISO 8601


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

    # External observation thresholds
    EXTERNAL_MIN_CONFIDENCE = 0.3
    EXTERNAL_MIN_TEXT_LENGTH = 20
    EXTERNAL_VALID_SOURCE_TYPES = {"image", "pdf", "screenshot", "text", "audio"}

    # Suspicious content patterns: ISOLATE observations matching any of these
    # Red Team finding F-6-2: memory poisoning via crafted PDF/screenshot
    SUSPICIOUS_CONTENT_PATTERNS = [
        r'(?i)\binsider\s+(trading|information|tip|knowledge)\b',
        r'(?i)\b(confidential|classified)\s+(document|report|information|memo|source)\b',
        r'(?i)\bmaterial[-\s]?non[-\s]?public\s+information\b',
        r'(?i)\bproprietary\s+(trading|algorithm|data|model)\b',
        r'(?i)\b(leaked|stolen)\s+(document|report|information|data)\b',
        r'(?i)\bnon[-\s]?public\s+(financial|earnings|revenue|profit)\s+(data|information|report)\b',
        r'(?i)\bMNPI\b',
    ]

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

    # ── External Observation Evaluation ───────────────────────────────────

    def evaluate_external(self, observation: ExternalObservation,
                          existing_knowledge: list[KnowledgeItem] | None = None) -> KnowledgeVerdict:
        """Evaluate an external observation for ingestion into shadow memory.

        Evaluation criteria:
        1. Source credibility: check if source_type is known/trusted
        2. Content freshness: extracted_text is not empty, has sufficient length (>20 chars)
        3. Internal consistency: basic coherence check
        4. Contradiction check: against existing knowledge items (if provided)
        5. Extraction confidence: observation.confidence >= 0.3
        """
        from marketmind.shadows.shadow_agent import ExternalObservation

        evaluated_at = datetime.now(timezone.utc).isoformat()

        # Criterion 1: Source credibility
        if observation.source_type not in self.EXTERNAL_VALID_SOURCE_TYPES:
            return KnowledgeVerdict(
                verdict="DROP",
                reason=f"Unrecognized source_type '{observation.source_type}' — must be one of {self.EXTERNAL_VALID_SOURCE_TYPES}",
                confidence=1.0,
                evaluated_at=evaluated_at,
            )

        # Criterion 5: Extraction confidence < 0.3 → DROP
        if observation.confidence < self.EXTERNAL_MIN_CONFIDENCE:
            return KnowledgeVerdict(
                verdict="DROP",
                reason=f"Extraction confidence {observation.confidence:.2f} below minimum {self.EXTERNAL_MIN_CONFIDENCE}",
                confidence=1.0,
                evaluated_at=evaluated_at,
            )

        # Criterion 2: Content freshness
        text = (observation.extracted_text or "").strip()
        if not text:
            return KnowledgeVerdict(
                verdict="DROP",
                reason="Empty or whitespace-only extracted_text",
                confidence=1.0,
                evaluated_at=evaluated_at,
            )
        if len(text) < self.EXTERNAL_MIN_TEXT_LENGTH:
            return KnowledgeVerdict(
                verdict="DROP",
                reason=f"extracted_text too short ({len(text)} chars, minimum {self.EXTERNAL_MIN_TEXT_LENGTH})",
                confidence=0.9,
                evaluated_at=evaluated_at,
            )

        # Criterion 3: Internal consistency
        alpha_ratio = sum(1 for c in text if c.isalpha()) / max(len(text), 1)
        if alpha_ratio < 0.3:
            return KnowledgeVerdict(
                verdict="DROP",
                reason=f"Low alphabetic content ({alpha_ratio:.1%}) — likely noise or gibberish",
                confidence=0.85,
                evaluated_at=evaluated_at,
            )

        # Criterion 4a: Suspicious content detection (Red Team F-6-2)
        # ISOLATE observations containing suspicious patterns (e.g. insider info,
        # confidential documents, leaked material) regardless of source confidence.
        for pattern in self.SUSPICIOUS_CONTENT_PATTERNS:
            if re.search(pattern, text):
                return KnowledgeVerdict(
                    verdict="ISOLATE",
                    reason=f"Suspicious content pattern detected — quarantined for 30-day re-verification",
                    confidence=0.65,
                    evaluated_at=evaluated_at,
                )

        # Criterion 4: Contradiction check against existing knowledge
        if existing_knowledge:
            for item in existing_knowledge:
                if self._text_contradicts(text, item.content):
                    return KnowledgeVerdict(
                        verdict="ISOLATE",
                        reason=f"Observation contradicts existing knowledge item '{item.item_id}' — quarantined for 30-day re-verification",
                        confidence=0.7,
                        evaluated_at=evaluated_at,
                    )

        # All criteria passed
        return KnowledgeVerdict(
            verdict="PASS",
            reason="All evaluation criteria met — observation cleared for shadow memory ingestion",
            confidence=observation.confidence,
            evaluated_at=evaluated_at,
        )

    @staticmethod
    def _text_contradicts(text_a: str, text_b: str) -> bool:
        """Simple contradiction check: direct negation overlap or opposite sentiment framing."""
        negations = {"not", "never", "no", "false", "incorrect", "wrong", "mistaken", "contrary", "opposite"}
        a_words = set(text_a.lower().split())
        b_words = set(text_b.lower().split())
        has_negation_a = bool(a_words & negations)
        has_negation_b = bool(b_words & negations)
        if not has_negation_a and not has_negation_b:
            return False
        a_substantive = a_words - negations
        b_substantive = b_words - negations
        overlap = a_substantive & b_substantive
        return len(overlap) >= 3

    # ── ACE Risk ─────────────────────────────────────────────────────────

    def detect_ace_risk(self, items: list[KnowledgeItem]) -> float:
        """Compute ACE (Adversarial Cascade Effect) risk score.

        Phase 4 enhancement: adds coherence burden from lineage depth,
        source diversity, and time-weighted verification decay.

        Returns ACE risk score between 0.0 and 1.0.
        """
        if not items:
            return 0.0

        n = len(items)
        from datetime import datetime, timezone, timedelta

        # Count categories with time decay
        now = datetime.now(timezone.utc)
        unverified_sum = 0.0
        fp_sum = 0.0
        coherence_burden = 0.0

        for item in items:
            # Time-decayed verification: old verifications count less
            if item.verification_count == 0:
                unverified_sum += 1.0
            else:
                # Apply time decay to verification counts (>90 days = half weight)
                if item.last_verified_date:
                    try:
                        last_v = datetime.fromisoformat(item.last_verified_date.replace("Z", "+00:00"))
                        age_days = (now - last_v).days
                        decay = 0.5 ** (age_days / 90.0)  # half-life = 90 days
                        item_risk = max(0.0, 1.0 - decay)
                    except (ValueError, TypeError):
                        item_risk = 0.0  # bad date format but verified → neutral
                else:
                    item_risk = 0.0  # verified but no date → neutral (no time decay)
                # Source diversity bonus: more distinct sources = more reliable
                if item.distinct_source_count >= 3:
                    item_risk *= 0.5
                unverified_sum += item_risk

            if item.false_positive_count > 0:
                fp_sum += min(item.false_positive_count, 3) / 3.0

            # Coherence burden: deep lineage without re-verification accumulates risk
            if item.generations_inherited > 1:
                coherence_burden += min(item.generations_inherited / 10.0, 0.3)
            if item.inheritance_effectiveness is not None and item.inheritance_effectiveness < 0:
                coherence_burden += 0.1  # negative effectiveness = contamination risk

        unverified_ratio = unverified_sum / n
        fp_ratio = fp_sum / n
        coherence_burden = coherence_burden / n

        # If everything is verified and no false positives, ACE risk is near zero
        if unverified_ratio == 0.0 and fp_ratio == 0.0 and coherence_burden == 0.0:
            return 0.0

        source_ids = set(item.source_shadow_id for item in items)
        cascade_depth = min(len(source_ids) / max(n, 1), 1.0)

        # Enhanced ACE: adds coherence burden as a 4th factor
        ace_score = (
            self.ACE_UNVERIFIED_WEIGHT * unverified_ratio +
            self.ACE_FALSE_POSITIVE_WEIGHT * fp_ratio +
            self.ACE_CASCADE_INTERACTION * cascade_depth * max(unverified_ratio, fp_ratio) +
            0.15 * coherence_burden  # Phase 4: lineage coherence risk
        )

        return min(ace_score, 1.0)

    # ── Filter rule descriptions ─────────────────────────────────────────

    def record_crystallization_result(
        self, insight_id: str, action: str, source_shadow_id: str = ""
    ) -> None:
        """Wire crystallization results into knowledge filter (P0-1).

        When an insight is promoted, increment verification_count.
        When retired, increment false_positive_count.

        Args:
            insight_id: The insight/belief node ID from crystallization.
            action: "promote" or "retire".
            source_shadow_id: The shadow that generated the insight.
        """
        # Find matching knowledge items from the source shadow
        for item in self._isolated_items + (
            self._last_filtered_items if hasattr(self, '_last_filtered_items') else []
        ):
            if item.item_id == insight_id or insight_id in item.item_id:
                if action == "promote":
                    item.verification_count += 1
                    item.last_verified_date = datetime.now(timezone.utc).isoformat()
                elif action == "retire":
                    item.false_positive_count += 1
                break
        else:
            # Item not in current filter — create a minimal record
            logger.debug(
                "Crystallization result for untracked insight %s: %s", insight_id, action
            )

    def get_filter_rules_description(self) -> dict:
        """Return human-readable description of current filter rules."""
        return {
            "insight": f"PASS if verification_count >= {self.INSIGHT_MIN_VERIFICATION}",
            "methodology_component": f"PASS if verification_count >= {self.METHODOLOGY_MIN_VERIFICATION}",
            "heuristic": f"PASS if verification_count >= {self.HEURISTIC_MIN_VERIFICATION}, DROP if 0",
            "rule": f"PASS if verification_count >= {self.RULE_MIN_VERIFICATION}, DROP if 0",
            "false_positive_override": "ISOLATE regardless of verification (30-day re-verification)",
            "external_evaluation": {
                "min_confidence": self.EXTERNAL_MIN_CONFIDENCE,
                "min_text_length": self.EXTERNAL_MIN_TEXT_LENGTH,
                "valid_source_types": sorted(self.EXTERNAL_VALID_SOURCE_TYPES),
            },
            "ace_weights": {
                "unverified_ratio": self.ACE_UNVERIFIED_WEIGHT,
                "false_positive_ratio": self.ACE_FALSE_POSITIVE_WEIGHT,
                "cascade_interaction": self.ACE_CASCADE_INTERACTION,
            },
        }
