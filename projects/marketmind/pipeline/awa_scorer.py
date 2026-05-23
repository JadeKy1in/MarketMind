"""AWA Scorer — Ability x Willingness x Acknowledgment framework.

Pure Python, zero LLM. Scores a figure's market-moving potential based on
three dimensions per the Swiss Finance Institute signal theory framework.

Design: .claude/plans/market-figure-intelligence-module.md §3
  Final_Score = (Ability + 0.01) * (Willingness + 0.01) * (Acknowledgment + 0.01)
  Thresholds: >= 0.6 CRITICAL, 0.3-0.6 HIGH, < 0.3 LOW
"""

from __future__ import annotations

# ── Authority weighting constants (ability dimension) ──────────────────────
_ABILITY_INFO_ADVANTAGE_WEIGHT = 0.40
_ABILITY_HISTORICAL_ACCURACY_WEIGHT = 0.35
_ABILITY_INSTITUTIONAL_STATUS_WEIGHT = 0.25
_DEFAULT_HISTORICAL_ACCURACY = 0.50
_DEFAULT_UNKNOWN_ABILITY = 0.30
_DEFAULT_UNKNOWN_INSTITUTIONAL = 0.25

# ── Acknowledgment content-type weights ────────────────────────────────────
_ACKNOWLEDGMENT_IMPACT_WEIGHT = 0.40
_ACKNOWLEDGMENT_AGENCY_WEIGHT = 0.30
_ACKNOWLEDGMENT_URGENCY_WEIGHT = 0.30

# ── Willingness modifiers ──────────────────────────────────────────────────
AUTHORITY_DECAY_MULTIPLIER = 0.90
_DEFAULT_UNKNOWN_SIGNAL_COST = 0.30


class AWAScorer:
    """Compute AWA score for a market figure's statement/action.

    Final_Score = (Ability + 0.01) * (Willingness + 0.01) * (Acknowledgment + 0.01)

    Laplace smoothing (+0.01) prevents any single dimension from zeroing
    the entire product.

    Thresholds: >= 0.6 CRITICAL, 0.3-0.6 HIGH, < 0.3 LOW
    """

    # ── Default Ability scores by role (pre-calibrated, not ML-optimized) ──
    # These represent the figure's information advantage —
    # how close they sit to the decision chain.
    DEFAULT_ABILITY: dict[str, float] = {
        "fed_chair": 0.95,
        "fed_voter": 0.85,
        "fed_nonvoter": 0.60,
        "ecb_president": 0.90,
        "boj_governor": 0.85,
        "treasury_secretary": 0.80,
        "president": 0.70,
        "ceo_large_cap": 0.65,
        "ceo_mid_cap": 0.40,
        "activist_investor": 0.75,
        "fund_manager": 0.50,
        "celebrity": 0.20,
        "unknown": 0.30,
    }

    # Institutional status scores by role — normalized [0, 1].
    # Represents AUM / policy authority / regulatory power.
    _INSTITUTIONAL_STATUS: dict[str, float] = {
        "fed_chair": 1.00,
        "fed_voter": 0.85,
        "fed_nonvoter": 0.50,
        "ecb_president": 0.95,
        "boj_governor": 0.90,
        "treasury_secretary": 0.85,
        "president": 0.80,
        "ceo_large_cap": 0.60,
        "ceo_mid_cap": 0.35,
        "activist_investor": 0.65,
        "fund_manager": 0.50,
        "celebrity": 0.15,
        "unknown": 0.25,
    }

    # Signal cost hierarchy → base willingness (Kartik, Ottaviani &
    # Squintani 2007 — costly communication model).
    # L4 (highest): Form 4 insider buy with SEC liability → 0.95
    # L0 (lowest): Social media post → 0.20
    _SIGNAL_COST: dict[str, float] = {
        "form4_buy": 0.95,
        "form4_sell": 0.85,
        "13f_filing": 0.75,
        "filing": 0.65,
        "official_speech": 0.60,
        "speech": 0.60,
        "congress_testimony": 0.65,
        "media_interview": 0.40,
        "interview": 0.40,
        "trade": 0.70,
        "social_post": 0.20,
    }

    # Name → role lookup for well-known market figures.
    # Used when the person object lacks an explicit 'role' attribute.
    _NAME_ROLE_MAP: dict[str, str] = {
        "jerome powell": "fed_chair",
        "christine lagarde": "ecb_president",
        "kazuo ueda": "boj_governor",
        "donald trump": "president",
        "nancy pelosi": "president",
        "janet yellen": "treasury_secretary",
        "warren buffett": "fund_manager",
        "elon musk": "ceo_large_cap",
        "jensen huang": "ceo_large_cap",
        "keith gill": "celebrity",
        "roaring kitty": "celebrity",
        "carl icahn": "activist_investor",
        "bill ackman": "activist_investor",
        "michael burry": "fund_manager",
        "ray dalio": "fund_manager",
    }

    # ── Acknowledgment keyword sets ─────────────────────────────────────

    _IMPACT_WORDS: set[str] = {
        "surge", "plunge", "rally", "selloff", "sell-off", "spike",
        "crash", "soar", "tumble", "volatile", "breakout", "plummet",
        "skyrocket", "drop", "jump", "slide", "rebound", "collapse",
        "wipeout", "meltdown", "boom", "bust", "panic", "frenzy",
    }

    _AGENCY_MARKERS: set[str] = {
        "reuters", "bloomberg", "wsj", "financial times", "cnbc",
        "exclusive", "report", "confirmed", "according to", "sources",
        "official", "statement", "press release",
    }

    _URGENCY_MARKERS: set[str] = {
        "breaking", "urgent", "alert", "just in", "developing",
        "immediate", "emergency", "flash", "live",
    }

    # ── Public API ──────────────────────────────────────────────────────

    def score(
        self,
        person,  # dict | KeyPerson | any object carrying .name / ['name']
        event_type: str,
        text: str,
        historical_accuracy: float | None = None,
    ) -> dict:
        """Compute AWA score for one figure event.

        Args:
            person: Dict with 'name' (and optionally 'role') or an object
                    exposing a .name / .signal_direction attribute.
            event_type: One of the _SIGNAL_COST keys (e.g. 'official_speech',
                        'social_post', 'form4_buy').
            text: The statement / post / headline body.
            historical_accuracy: Past direction-match rate [0, 1].
                                 Defaults to 0.50 when unavailable.

        Returns:
            dict with keys:
                ability, willingness, acknowledgment,
                final_score, tier
        """
        ability = self._compute_ability(person, historical_accuracy)
        willingness = self._compute_willingness(person, event_type)
        acknowledgment = self._compute_acknowledgment(text)

        final_score = (
            (ability + 0.01)
            * (willingness + 0.01)
            * (acknowledgment + 0.01)
        )

        return {
            "ability": round(ability, 4),
            "willingness": round(willingness, 4),
            "acknowledgment": round(acknowledgment, 4),
            "final_score": round(final_score, 4),
            "tier": self.classify_tier(final_score),
        }

    # ── Dimension calculators ───────────────────────────────────────────

    def _compute_ability(
        self,
        person,
        historical_accuracy: float | None = None,
    ) -> float:
        """Ability = 0.40*info_advantage + 0.35*historical_accuracy + 0.25*institutional_status

        Args:
            person: Dict or object with name/role attributes.
            historical_accuracy: Optional float [0, 1]; defaults to 0.50.

        Returns:
            Float in [0, 1].
        """
        role = self._infer_role(person)
        info_advantage = self.DEFAULT_ABILITY.get(role, _DEFAULT_UNKNOWN_ABILITY)
        hist_acc = (
            historical_accuracy
            if historical_accuracy is not None
            else _DEFAULT_HISTORICAL_ACCURACY
        )
        institutional = self._INSTITUTIONAL_STATUS.get(role, _DEFAULT_UNKNOWN_INSTITUTIONAL)

        return (_ABILITY_INFO_ADVANTAGE_WEIGHT * info_advantage
                + _ABILITY_HISTORICAL_ACCURACY_WEIGHT * hist_acc
                + _ABILITY_INSTITUTIONAL_STATUS_WEIGHT * institutional)

    def _compute_willingness(self, person, event_type: str) -> float:
        """Willingness based on signal cost hierarchy.

        L4 (highest): Form 4 insider buy with SEC liability → 0.95
        L3: 13F filing → 0.75
        L2: Official speech (FOMC, Congress) → 0.60
        L1: Media interview → 0.40
        L0 (lowest): Social media post → 0.20

        Contrarian figures receive a 10 % discount — they benefit from
        engagement regardless of accuracy.
        """
        base = self._SIGNAL_COST.get(event_type, _DEFAULT_UNKNOWN_SIGNAL_COST)

        signal_dir = self._get_attr(person, "signal_direction", "")
        if signal_dir == "contrarian":
            base *= AUTHORITY_DECAY_MULTIPLIER

        return max(0.0, min(1.0, base))

    def _compute_acknowledgment(self, text: str) -> float:
        """Market acknowledgment via keyword intensity.

        Three weighted sub-scores, each normalised to [0, 1]:
          0.40 × price / volume impact words
          0.30 × news agency / authoritative source markers
          0.30 × urgency / immediacy markers

        A casual tweet scores ~0.05–0.15; a breaking-news headline
        scores ~0.30–0.50; a full-crisis alert scores ~0.70–1.00.
        """
        if not text:
            return 0.0
        text_lower = text.lower()

        # Impact words — cap at 3 hits for a full 1.0
        impact_count = sum(1 for w in self._IMPACT_WORDS if w in text_lower)
        impact_score = min(impact_count / 3.0, 1.0)

        # Agency markers — cap at 2 hits for a full 1.0
        agency_count = sum(1 for w in self._AGENCY_MARKERS if w in text_lower)
        agency_score = min(agency_count / 2.0, 1.0)

        # Urgency markers — cap at 2 hits for a full 1.0
        urgency_count = sum(1 for w in self._URGENCY_MARKERS if w in text_lower)
        urgency_score = min(urgency_count / 2.0, 1.0)

        return (_ACKNOWLEDGMENT_IMPACT_WEIGHT * impact_score
                + _ACKNOWLEDGMENT_AGENCY_WEIGHT * agency_score
                + _ACKNOWLEDGMENT_URGENCY_WEIGHT * urgency_score)

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def classify_tier(score: float) -> str:
        """Classify a final AWA score into its signal tier."""
        if score >= 0.6:
            return "CRITICAL"
        if score >= 0.3:
            return "HIGH"
        return "LOW"

    def _infer_role(self, person) -> str:
        """Infer the role string from a person dict/object.

        Priority:
          1. Explicit 'role' key / attribute.
          2. Name-based lookup against _NAME_ROLE_MAP.
          3. Fallback to 'unknown'.
        """
        role = self._get_attr(person, "role", None)
        if role:
            return role

        name = self._get_attr(person, "name", "")
        if isinstance(name, str):
            key = name.lower().strip()
            if key in self._NAME_ROLE_MAP:
                return self._NAME_ROLE_MAP[key]

        return "unknown"

    @staticmethod
    def _get_attr(obj, key: str, default=None):
        """Safe attribute / key access for dict-like and object-like persons."""
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)
