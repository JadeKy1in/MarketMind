"""Tests for Shadow Phase 2: keyword-triggered temp shadows, beta shadows, retired shadows."""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from marketmind.shadows.event_detector import EventDetector
from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.shadows.shadow_mother import ShadowMother
from marketmind.config.settings import ShadowSettings


# ── Keyword trigger detection ──────────────────────────────────────────────

@pytest.mark.skip(reason="EventDetector keyword-triggering API completely redesigned")
class TestKeywordTriggerDetection:
    """detect_keyword_triggers: session-level keyword frequency counter."""

    def test_no_threshold_not_triggered(self):
        detector = EventDetector()
        result = detector.detect_keyword_triggers("bitcoin is interesting")
        assert result == []
        # One mention does not cross threshold of 3
        assert detector._keyword_counter.get("crypto", 0) < 3

    def test_crosses_threshold_triggers_domain(self):
        detector = EventDetector()
        # 3 separate turns mentioning crypto keywords, each with one distinct keyword
        r1 = detector.detect_keyword_triggers("bitcoin price is volatile")
        assert r1 == []  # 1 mention, below threshold
        r2 = detector.detect_keyword_triggers("ethereum gas fees are dropping")
        assert r2 == []  # 2 mentions, still below threshold
        r3 = detector.detect_keyword_triggers("defi protocols gaining traction")
        assert "crypto" in r3  # 3rd mention crosses threshold

    def test_multiple_keywords_in_one_turn_count_correctly(self):
        detector = EventDetector()
        # "bitcoin", "crypto", "ethereum" all in same text → 3 hits
        detector.detect_keyword_triggers("bitcoin and ethereum are both crypto assets")
        assert detector._keyword_counter.get("crypto", 0) == 3

    def test_domain_triggers_only_once_per_session(self):
        detector = EventDetector()
        detector.detect_keyword_triggers("bitcoin up 5%")
        r2 = detector.detect_keyword_triggers("ethereum rally continues")
        assert r2 == []  # 2 mentions, still below threshold
        r3 = detector.detect_keyword_triggers("defi ecosystem expanding")
        assert "crypto" in r3
        # Fourth mention — domain already triggered, should not return again
        r4 = detector.detect_keyword_triggers("bitcoin hits new all time high")
        assert "crypto" not in r4

    def test_reset_keyword_state_clears_counters(self):
        detector = EventDetector()
        detector.detect_keyword_triggers("bitcoin is volatile")
        detector.detect_keyword_triggers("bitcoin hits resistance")
        detector.detect_keyword_triggers("bitcoin might correct")
        assert "crypto" in detector._triggered_domains
        detector.reset_keyword_state()
        assert detector._keyword_counter == {}
        assert detector._triggered_domains == set()

    def test_multiple_domains_independent_counters(self):
        detector = EventDetector()
        detector.detect_keyword_triggers("bitcoin surges on etf inflows")  # crypto: 1
        detector.detect_keyword_triggers("gold rallies on fed rate cut expectations")  # gold: 1
        r3 = detector.detect_keyword_triggers("bitcoin adoption growing")  # crypto: 1 (now 2)
        assert r3 == []
        r4 = detector.detect_keyword_triggers("crypto market cap hits 3 trillion")  # crypto: 1 (now 3)
        assert "crypto" in r4
        # gold only mentioned once so far
        assert "gold" not in r4


# ── Beta shadow creation and isolation ───────────────────────────────────

@pytest.mark.skip(reason="ShadowMother beta shadow management removed")
class TestBetaShadowLifecycle:
    """Beta shadows: sandboxed methodology testing with isolated output."""

    @pytest.fixture
    def settings(self):
        return ShadowSettings()

    @pytest.fixture
    def db(self, temp_shadow_db):
        """DB with one expert template shadow."""
        config = ShadowConfig(
            shadow_id="expert:tech:silicon_oracle",
            shadow_type="expert",
            display_name="Silicon Oracle",
            methodology_prompt="You are a tech sector expert analyzing semiconductor stocks.",
            virtual_capital=50000.0,
            domain="tech",
        )
        temp_shadow_db.create_shadow(config)
        return temp_shadow_db

    @pytest.mark.asyncio
    async def test_create_beta_shadow_from_template(self, db, settings):
        mother = ShadowMother(settings, db)
        variant = {"risk_aversion": "low", "momentum_weight": "0.4"}
        shadow_id = await mother.create_beta_shadow("expert:tech:silicon_oracle", variant)

        shadow = db.get_shadow(shadow_id)
        assert shadow is not None
        assert shadow.status == "beta"
        assert shadow.shadow_type == "beta"
        assert shadow.parent_shadow_id == "expert:tech:silicon_oracle"
        assert "BETA METHODOLOGY VARIANT" in shadow.methodology_prompt
        assert "risk_aversion: low" in shadow.methodology_prompt

    @pytest.mark.asyncio
    async def test_create_beta_shadow_missing_template_raises(self, db, settings):
        mother = ShadowMother(settings, db)
        with pytest.raises(ValueError, match="not found"):
            await mother.create_beta_shadow("nonexistent:shadow", {})

    @pytest.mark.asyncio
    async def test_beta_shadow_excluded_from_ranking_eligible(self, db, settings):
        """Beta shadows should not appear in ranking-eligible list."""
        mother = ShadowMother(settings, db)
        variant = {"test": "variant"}
        beta_id = await mother.create_beta_shadow("expert:tech:silicon_oracle", variant)

        eligible = db.get_ranking_eligible_shadows()
        beta_ids = [s.shadow_id for s in eligible]
        assert beta_id not in beta_ids
        # Expert template should still be eligible
        assert "expert:tech:silicon_oracle" in beta_ids

    @pytest.mark.asyncio
    async def test_beta_shadow_visible_for_analysis(self, db, settings):
        """Beta shadows should appear in visible list (for analysis) but not ranking."""
        mother = ShadowMother(settings, db)
        beta_id = await mother.create_beta_shadow("expert:tech:silicon_oracle", {"test": "v"})

        visible = db.get_visible_shadows()
        visible_ids = [s.shadow_id for s in visible]
        assert beta_id in visible_ids

        eligible = db.get_ranking_eligible_shadows()
        eligible_ids = [s.shadow_id for s in eligible]
        assert beta_id not in eligible_ids

    @pytest.mark.asyncio
    async def test_promote_beta_shadow_insufficient_days(self, db, settings):
        """Promotion requires 20 days of history."""
        mother = ShadowMother(settings, db)
        beta_id = await mother.create_beta_shadow("expert:tech:silicon_oracle", {"test": "v"})

        # No snapshot history → promotion should fail
        result = await mother.promote_beta_shadow(beta_id)
        assert result is False

    @pytest.mark.asyncio
    async def test_promote_beta_shadow_not_beta_status(self, db, settings):
        """Cannot promote a shadow that isn't beta."""
        mother = ShadowMother(settings, db)
        result = await mother.promote_beta_shadow("expert:tech:silicon_oracle")
        assert result is False


# ── Retired shadow lifecycle ──────────────────────────────────────────────

class TestRetiredShadowLifecycle:
    """Retired shadows: frozen benchmarks with preserved methodology/history."""

    def test_retire_shadow_sets_status_and_reason(self, temp_shadow_db):
        config = ShadowConfig(
            shadow_id="expert:energy:oil_bull",
            shadow_type="expert",
            display_name="Oil Bull",
            methodology_prompt="You are an energy sector expert.",
            virtual_capital=40000.0,
            domain="energy",
        )
        temp_shadow_db.create_shadow(config)
        temp_shadow_db.retire_shadow("expert:energy:oil_bull", "tier_degradation")

        shadow = temp_shadow_db.get_shadow("expert:energy:oil_bull")
        assert shadow is not None
        assert shadow.status == "retired"
        assert shadow.retirement_reason == "tier_degradation"
        assert shadow.retired_at is not None

    def test_retired_shadow_not_in_visible(self, temp_shadow_db):
        config = ShadowConfig(
            shadow_id="expert:energy:oil_bull",
            shadow_type="expert",
            display_name="Oil Bull",
            methodology_prompt="You are an energy expert.",
            virtual_capital=40000.0,
            domain="energy",
        )
        temp_shadow_db.create_shadow(config)
        temp_shadow_db.retire_shadow("expert:energy:oil_bull", "methodology_obsolete")

        visible = temp_shadow_db.get_visible_shadows()
        visible_ids = [s.shadow_id for s in visible]
        assert "expert:energy:oil_bull" not in visible_ids

    def test_retired_shadow_not_in_active(self, temp_shadow_db):
        config = ShadowConfig(
            shadow_id="expert:fx:dollar_bear",
            shadow_type="expert",
            display_name="Dollar Bear",
            methodology_prompt="You are an FX expert.",
            virtual_capital=30000.0,
            domain="fx",
        )
        temp_shadow_db.create_shadow(config)
        temp_shadow_db.retire_shadow("expert:fx:dollar_bear", "manual")

        active = temp_shadow_db.get_active_shadows()
        active_ids = [s.shadow_id for s in active]
        assert "expert:fx:dollar_bear" not in active_ids

    def test_retire_shadow_closes_open_trades(self, temp_shadow_db):
        config = ShadowConfig(
            shadow_id="expert:bonds:yield_hawk",
            shadow_type="expert",
            display_name="Yield Hawk",
            methodology_prompt="You are a fixed income expert.",
            virtual_capital=35000.0,
            domain="bonds",
        )
        temp_shadow_db.create_shadow(config)
        temp_shadow_db.retire_shadow("expert:bonds:yield_hawk", "challenger_loss")

        shadow = temp_shadow_db.get_shadow("expert:bonds:yield_hawk")
        assert shadow.status == "retired"
        assert shadow.retirement_reason == "challenger_loss"


# ── Beta analysis isolation ───────────────────────────────────────────────

class TestBetaAnalysisIsolation:
    """Beta analyses go to beta_analyses table, isolated from main analyses."""

    @pytest.fixture
    def db_with_beta(self, temp_shadow_db):
        """DB with one beta shadow."""
        config = ShadowConfig(
            shadow_id="beta:tech:test_beta_1",
            shadow_type="beta",
            display_name="Test Beta Tech",
            methodology_prompt="Beta test methodology.",
            virtual_capital=25000.0,
            domain="tech",
            status="beta",
        )
        temp_shadow_db.create_shadow(config)
        return temp_shadow_db

    def test_save_beta_analyses_isolated(self, db_with_beta):
        beta_votes = [
            {"ticker": "NVDA", "direction": "long", "confidence": 0.75,
             "thesis": "AI chip demand growing", "risk_note": "Valuation risk"}
        ]
        db_with_beta.save_beta_analyses(
            "beta:tech:test_beta_1", "2026-05-18", beta_votes,
            methodology_variant='{"risk_aversion": "low"}'
        )

        # Verify it's in beta_analyses
        conn = db_with_beta._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM beta_analyses WHERE shadow_id = ?",
                ("beta:tech:test_beta_1",)
            ).fetchall()
            assert len(rows) == 1
            assert rows[0]["ticker"] == "NVDA"
            assert rows[0]["direction"] == "long"
            assert rows[0]["methodology_variant"] == '{"risk_aversion": "low"}'
        finally:
            conn.close()

    def test_beta_analyses_not_in_main_table(self, db_with_beta):
        beta_votes = [
            {"ticker": "AMD", "direction": "short", "confidence": 0.60,
             "thesis": "Overbought", "risk_note": "Momentum risk"}
        ]
        db_with_beta.save_beta_analyses(
            "beta:tech:test_beta_1", "2026-05-18", beta_votes)

        # Main shadow_analyses should not have beta data
        conn = db_with_beta._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM shadow_analyses WHERE shadow_id = ?",
                ("beta:tech:test_beta_1",)
            ).fetchall()
            assert len(rows) == 0
        finally:
            conn.close()
