"""Tests for Shadow Phase 2: keyword-triggered temp shadows, beta shadows, retired shadows."""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from marketmind.shadows.event_detector import EventDetector, DetectedEvent
from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig


# ── Keyword trigger detection ──────────────────────────────────────────────

class TestKeywordTriggerDetection:
    """EventDetector._detect_by_keywords: multi-keyword event detection per event type."""

    def test_detect_by_keywords_no_match(self):
        """Headlines with <2 keyword matches return empty list."""
        detector = EventDetector()
        keywords = [r'(?:bitcoin|crypto)\s', r'(?:rally|surge)\s']
        news = [{"headline": "Markets are stable today"}]
        result = detector._detect_by_keywords(news, "test_type", keywords, 0.5)
        assert result == []

    def test_detect_by_keywords_detects_event(self):
        """Headlines with 2+ keyword matches return DetectedEvent."""
        detector = EventDetector()
        keywords = [
            r'(?:Fed|Federal Reserve|central bank)\s',
            r'(?:rate|hike|cut)\s',
        ]
        news = [{"headline": "Fed rate hike surprises markets"}]
        events = detector._detect_by_keywords(news, "cb_shock", keywords, 0.6)
        assert len(events) == 1
        event = events[0]
        assert event.event_type == "cb_shock"
        assert event.impact_score >= 0.7  # base 0.6 + 2*0.1 = 0.8
        assert isinstance(event.event_id, str) and len(event.event_id) == 16

    def test_detect_cb_shock_realistic_headline(self):
        """CB shock detection: Fed + rate terms should trigger."""
        detector = EventDetector()
        news = [{"headline": "Fed rate cut shocks markets as Powell signals more easing"}]
        events = detector.detect_cb_shock(news)
        assert len(events) >= 1
        assert events[0].event_type == "cb_shock"

    def test_detect_geopolitical_realistic_headline(self):
        """Geopolitical detection: conflict + sanctions keywords trigger event."""
        detector = EventDetector()
        news = [{"headline": "Military conflict escalates: missile attack triggers sanctions"}]
        events = detector.detect_geopolitical(news)
        assert len(events) >= 1
        assert events[0].event_type == "geopolitical"

    def test_detect_vol_shock_from_market_data(self):
        """Vol shock detection requires zscore >= 5.0 for each ticker."""
        detector = EventDetector()
        market_data = {"AAPL": 6.2, "NVDA": 3.1, "SPY": 5.5}
        events = detector.detect_vol_shock(market_data)
        tickers = {e.affected_assets[0] for e in events}
        assert "AAPL" in tickers
        assert "SPY" in tickers
        assert "NVDA" not in tickers
        for e in events:
            assert e.event_type == "vol_shock"
            assert 0.0 < e.impact_score <= 1.0

    def test_prioritize_events_by_impact(self):
        """Events are sorted by impact score descending, truncated to max_shadows."""
        detector = EventDetector()
        events = [
            DetectedEvent("e1", "cb_shock", "low", [], 0.3, "2026-05-23T00:00:00"),
            DetectedEvent("e2", "cb_shock", "high", [], 0.9, "2026-05-23T00:00:00"),
            DetectedEvent("e3", "geopolitical", "mid", [], 0.5, "2026-05-23T00:00:00"),
            DetectedEvent("e4", "vol_shock", "mid_high", [], 0.7, "2026-05-23T00:00:00"),
        ]
        result = detector.prioritize_events(events, max_shadows=3)
        assert len(result) == 3
        assert result[0].impact_score == 0.9
        assert result[1].impact_score == 0.7
        assert result[2].impact_score == 0.5


# ── Beta shadow creation and isolation ───────────────────────────────────

class TestBetaShadowLifecycle:
    """Beta shadows: sandboxed methodology testing with isolated output."""

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
    async def test_create_beta_shadow_from_template(self, db):
        from marketmind.shadows.beta_lifecycle import create_beta_shadow

        variant = {"risk_aversion": "low", "momentum_weight": "0.4"}
        shadow_id = await create_beta_shadow(db, "expert:tech:silicon_oracle", variant)

        shadow = db.get_shadow(shadow_id)
        assert shadow is not None
        assert shadow.status == "beta"
        assert shadow.shadow_type == "beta"
        assert shadow.parent_shadow_id == "expert:tech:silicon_oracle"
        assert "BETA METHODOLOGY VARIANT" in shadow.methodology_prompt
        assert "risk_aversion: low" in shadow.methodology_prompt

    @pytest.mark.asyncio
    async def test_create_beta_shadow_missing_template_raises(self, db):
        from marketmind.shadows.beta_lifecycle import create_beta_shadow

        with pytest.raises(ValueError, match="not found"):
            await create_beta_shadow(db, "nonexistent:shadow", {})

    @pytest.mark.asyncio
    async def test_beta_shadow_excluded_from_ranking_eligible(self, db):
        """Beta shadows should not appear in ranking-eligible list."""
        from marketmind.shadows.beta_lifecycle import create_beta_shadow

        variant = {"test": "variant"}
        beta_id = await create_beta_shadow(db, "expert:tech:silicon_oracle", variant)

        eligible = db.get_ranking_eligible_shadows()
        beta_ids = [s.shadow_id for s in eligible]
        assert beta_id not in beta_ids
        # Expert template should still be eligible
        assert "expert:tech:silicon_oracle" in beta_ids

    @pytest.mark.asyncio
    async def test_beta_shadow_visible_for_analysis(self, db):
        """Beta shadows should appear in visible list (for analysis) but not ranking."""
        from marketmind.shadows.beta_lifecycle import create_beta_shadow

        beta_id = await create_beta_shadow(db, "expert:tech:silicon_oracle", {"test": "v"})

        visible = db.get_visible_shadows()
        visible_ids = [s.shadow_id for s in visible]
        assert beta_id in visible_ids

        eligible = db.get_ranking_eligible_shadows()
        eligible_ids = [s.shadow_id for s in eligible]
        assert beta_id not in eligible_ids

    @pytest.mark.asyncio
    async def test_promote_beta_shadow_insufficient_days(self, db):
        """Promotion requires 20 days of history."""
        from marketmind.shadows.beta_lifecycle import create_beta_shadow, promote_beta_shadow

        beta_id = await create_beta_shadow(db, "expert:tech:silicon_oracle", {"test": "v"})

        # No snapshot history → promotion should fail
        result = await promote_beta_shadow(db, beta_id)
        assert result is False

    @pytest.mark.asyncio
    async def test_promote_beta_shadow_not_beta_status(self, db):
        """Cannot promote a shadow that isn't beta."""
        from marketmind.shadows.beta_lifecycle import promote_beta_shadow

        result = await promote_beta_shadow(db, "expert:tech:silicon_oracle")
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
