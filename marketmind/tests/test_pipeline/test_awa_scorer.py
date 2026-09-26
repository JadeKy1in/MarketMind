"""Tests for AWA Scorer — Ability x Willingness x Acknowledgment framework."""
import pytest

from marketmind.pipeline.awa_scorer import AWAScorer


class TestAWAScorer:
    """Tests for the AWAScorer class."""

    @pytest.fixture
    def scorer(self) -> AWAScorer:
        return AWAScorer()

    # ── test_fed_chair_high_ability ─────────────────────────────────

    def test_fed_chair_high_ability(self, scorer: AWAScorer) -> None:
        """Fed Chair should score high on the ability dimension.

        Jerome Powell sits at the centre of the monetary policy decision
        chain. His info_advantage and institutional_status are maximal,
        so even with a default (0.50) historical accuracy the composite
        ability should comfortably exceed 0.70.
        """
        person = {"name": "Jerome Powell"}
        result = scorer.score(
            person=person,
            event_type="official_speech",
            text="The Federal Reserve remains data-dependent.",
        )

        assert result["ability"] > 0.70, (
            f"Expected ability > 0.70 for Fed Chair, got {result['ability']}"
        )
        # Sanity: ability cannot exceed 1.0
        assert result["ability"] <= 1.0

    # ── test_social_post_low_willingness ────────────────────────────

    def test_social_post_low_willingness(self, scorer: AWAScorer) -> None:
        """Social media posts should carry low willingness scores.

        Social posts are the cheapest signal type (L0 in the cost
        hierarchy). Even for a Fed Chair the willingness should stay
        below 0.40 because the cost of posting is negligible compared
        to an official speech or SEC filing.
        """
        person = {"name": "Jerome Powell"}
        result = scorer.score(
            person=person,
            event_type="social_post",
            text="Interesting data today.",
        )

        assert result["willingness"] < 0.30, (
            f"Expected willingness < 0.30 for social_post, "
            f"got {result['willingness']}"
        )

    # ── test_critical_tier_threshold ────────────────────────────────

    def test_critical_tier_threshold(self, scorer: AWAScorer) -> None:
        """Verify tier classification at each boundary.

        CRITICAL:  score >= 0.60
        HIGH:      0.30 <= score < 0.60
        LOW:       score < 0.30
        """
        assert scorer.classify_tier(0.60) == "CRITICAL"
        assert scorer.classify_tier(0.80) == "CRITICAL"
        assert scorer.classify_tier(0.30) == "HIGH"
        assert scorer.classify_tier(0.45) == "HIGH"
        assert scorer.classify_tier(0.59) == "HIGH"
        assert scorer.classify_tier(0.00) == "LOW"
        assert scorer.classify_tier(0.29) == "LOW"

    # ── test_full_score_with_high_acknowledgment ────────────────────

    def test_full_score_with_high_acknowledgment(
        self, scorer: AWAScorer
    ) -> None:
        """A breaking-news event from a high-ability figure should
        produce a CRITICAL or HIGH tier score.

        Uses all three dimensions near their maxima to verify the
        final_score is computed correctly and lands in a non-trivial tier.
        """
        person = {"name": "Jerome Powell", "role": "fed_chair"}
        result = scorer.score(
            person=person,
            event_type="official_speech",
            text=(
                "BREAKING: Reuters exclusive — Federal Reserve Chair "
                "signals emergency rate cut. Markets plunge on the alert, "
                "massive selloff across all sectors. Bloomberg confirmed."
            ),
            historical_accuracy=0.85,
        )

        # With high inputs on all three dimensions the score should
        # reach at least HIGH territory.
        assert result["tier"] in ("HIGH", "CRITICAL"), (
            f"Expected HIGH or CRITICAL, got {result['tier']} "
            f"(final_score={result['final_score']})"
        )
        assert result["final_score"] > 0.0
        assert result["ability"] > 0.0
        assert result["willingness"] > 0.0
        assert result["acknowledgment"] > 0.0
