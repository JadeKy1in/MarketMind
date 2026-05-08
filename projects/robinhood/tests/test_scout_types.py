"""
test_scout_types.py - Unit tests for scout_types.py (Phase 5 data structures)

Tests all data types defined in src/scout_types.py for correct instantiation,
field defaults, edge cases, and validation rules.

Test taxonomy:
  - TC-TYPES-001..003: AssetMappingField   (dimension flag enum)
  - TC-TYPES-004..008: AssetBasket          (3-dimensional allocation)
  - TC-TYPES-009..013: MacroTag             (macro narrative tagging)
  - TC-TYPES-014..018: SourceRecord         (source governance ledger)
  - TC-TYPES-019..023: AuditorCheckpoint    (causal invalidation state)
  - TC-TYPES-024..028: ContinuationState    (multi-turn API merge)
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List

import pytest

from src.scout_types import (
    AssetBasket,
    AssetMappingField,
    AuditorCheckpoint,
    ContinuationState,
    InvalidationTrigger,
    MacroTag,
    NarrativeTag,
    SourceRecord,
    source_weight,
)


# =========================================================================
# TC-TYPES-001..003: AssetMappingField (enum)
# =========================================================================


class TestAssetMappingField:
    """Validate the three asset dimension flags and their string values."""

    def test_high_liquidity_field(self) -> None:
        """TC-TYPES-001: HIGH_LIQUIDITY has correct value."""
        assert AssetMappingField.HIGH_LIQUIDITY.value == "high_liquidity"

    def test_low_expense_field(self) -> None:
        """TC-TYPES-002: LOW_EXPENSE_RATIO has correct value."""
        assert AssetMappingField.LOW_EXPENSE_RATIO.value == "low_expense_ratio"

    def test_high_beta_field(self) -> None:
        """TC-TYPES-003: HIGH_BETA has correct value."""
        assert AssetMappingField.HIGH_BETA.value == "high_beta"


# =========================================================================
# TC-TYPES-004..008: AssetBasket
# =========================================================================


class TestAssetBasket:
    """Validate AssetBasket creation, defaults, and edge cases."""

    def test_full_basket(self) -> None:
        """TC-TYPES-004: Create a basket with all three dimensions populated."""
        basket = AssetBasket(
            high_liquidity=["GLD", "SPY"],
            low_expense_ratio=["IAU", "VOO"],
            high_beta=["GDX", "BTC"],
        )
        assert basket.high_liquidity == ["GLD", "SPY"]
        assert basket.low_expense_ratio == ["IAU", "VOO"]
        assert basket.high_beta == ["GDX", "BTC"]
        assert basket.dimension_count() == 3

    def test_partial_basket(self) -> None:
        """TC-TYPES-005: Basket with only one dimension populated is valid."""
        basket = AssetBasket(
            high_liquidity=["GLD"],
        )
        assert basket.high_liquidity == ["GLD"]
        assert basket.low_expense_ratio == []
        assert basket.high_beta == []
        assert basket.dimension_count() == 1

    def test_empty_basket(self) -> None:
        """TC-TYPES-006: Empty basket is valid (e.g. 'wait' signal)."""
        basket = AssetBasket()
        assert basket.high_liquidity == []
        assert basket.low_expense_ratio == []
        assert basket.high_beta == []
        assert basket.dimension_count() == 0
        assert basket.all_tickers() == []

    def test_all_tickers_dedup(self) -> None:
        """TC-TYPES-007: all_tickers() returns deduplicated union."""
        basket = AssetBasket(
            high_liquidity=["GLD", "SPY"],
            low_expense_ratio=["IAU", "GLD"],  # GLD duplicated
            high_beta=["GDX"],
        )
        tickers = basket.all_tickers()
        assert sorted(tickers) == sorted(["GLD", "SPY", "IAU", "GDX"])
        assert len(tickers) == 4  # no duplicates

    def test_basket_iteration(self) -> None:
        """TC-TYPES-008: Basket can be iterated by dimension key."""
        basket = AssetBasket(
            high_liquidity=["GLD"],
            high_beta=["BTC"],
        )
        # Verify we can extract tickers per dimension
        assert basket.get("high_liquidity") == ["GLD"]
        assert basket.get("low_expense_ratio") == []
        assert basket.get("high_beta") == ["BTC"]


# =========================================================================
# TC-TYPES-009..013: MacroTag / NarrativeTag
# =========================================================================


class TestMacroTag:
    """Validate macro narrative tagging data structure."""

    def test_minimal_macro_tag(self) -> None:
        """TC-TYPES-009: MacroTag with minimum required fields."""
        tag = MacroTag(
            narrative="Fed signals rate cut",
            category="monetary_policy",
            confidence=0.85,
        )
        assert tag.narrative == "Fed signals rate cut"
        assert tag.category == "monetary_policy"
        assert tag.confidence == 0.85
        assert tag.related_assets == []
        assert tag.source_ids == []

    def test_full_macro_tag(self) -> None:
        """TC-TYPES-010: MacroTag with all fields populated."""
        tag = MacroTag(
            narrative="Geopolitical conflict escalation",
            category="geopolitical",
            confidence=0.92,
            related_assets=["GLD", "IAU", "GDX"],
            source_ids=["src_eia_001", "src_reuters_002"],
        )
        assert tag.narrative == "Geopolitical conflict escalation"
        assert tag.category == "geopolitical"
        assert sorted(tag.related_assets) == sorted(["GLD", "IAU", "GDX"])
        assert len(tag.source_ids) == 2

    def test_low_confidence_tag(self) -> None:
        """TC-TYPES-011: Very low confidence tags are still valid."""
        tag = MacroTag(
            narrative="Rumored OPEC production cut",
            category="commodity",
            confidence=0.15,
        )
        assert tag.confidence == 0.15

    def test_narrative_tag_minimal(self) -> None:
        """TC-TYPES-012: NarrativeTag with minimum fields (alias type)."""
        tag = NarrativeTag(
            narrative="Inflationary pressure easing",
            category="inflation",
            confidence=0.78,
        )
        assert tag.narrative == "Inflationary pressure easing"
        assert tag.category == "inflation"
        assert tag.subcategory is None

    def test_narrative_tag_full(self) -> None:
        """TC-TYPES-013: NarrativeTag with subcategory."""
        tag = NarrativeTag(
            narrative="China stimulus package",
            category="geopolitical",
            confidence=0.81,
            subcategory="asia_pacific",
        )
        assert tag.subcategory == "asia_pacific"


# =========================================================================
# TC-TYPES-014..018: SourceRecord
# =========================================================================


class TestSourceRecord:
    """Validate source governance record."""

    def test_minimal_source_record(self) -> None:
        """TC-TYPES-014: SourceRecord with minimum required fields."""
        rec = SourceRecord(
            source_id="src_fred_001",
            source_name="FRED",
            url="https://fred.stlouisfed.org/series/GDP",
        )
        assert rec.source_id == "src_fred_001"
        assert rec.publish_time is not None
        assert rec.content_hash is None
        assert rec.verified_by == []

    def test_full_source_record(self) -> None:
        """TC-TYPES-015: SourceRecord with all fields."""
        now = datetime.now(timezone.utc)
        rec = SourceRecord(
            source_id="src_eia_001",
            source_name="EIA",
            url="https://www.eia.gov/petroleum/crudeoil/",
            publish_time=now,
            content_hash="abc123def456",
            summary="EIA crude oil inventory report",
            verified_by=["fred", "reuters"],
        )
        assert rec.source_id == "src_eia_001"
        assert rec.verified_by == ["fred", "reuters"]

    def test_source_weight(self) -> None:
        """TC-TYPES-016: source_weight returns expected values for known sources."""
        assert source_weight("fred") > 0.0
        assert source_weight("eia") > 0.0
        assert source_weight("reuters") > 0.0
        assert source_weight("twitter") < source_weight("fred")

    def test_source_weight_unknown(self) -> None:
        """TC-TYPES-017: Unknown source gets lowest weight."""
        assert source_weight("unknown_source_xyz") == 0.05

    def test_source_weight_case_insensitive(self) -> None:
        """TC-TYPES-018: source_weight is case-insensitive."""
        assert source_weight("FRED") == source_weight("fred")
        assert source_weight("EIA") == source_weight("eia")
        assert source_weight("Reuters") == source_weight("reuters")


# =========================================================================
# TC-TYPES-019..023: AuditorCheckpoint / InvalidationTrigger
# =========================================================================


class TestAuditorCheckpoint:
    """Validate invalidation trigger and checkpoint data structures."""

    def test_minimal_invalidation_trigger(self) -> None:
        """TC-TYPES-019: InvalidationTrigger with minimum fields."""
        trigger = InvalidationTrigger(
            condition="NFP > 250k",
            type="macro",
        )
        assert trigger.condition == "NFP > 250k"
        assert trigger.type == "macro"
        assert trigger.time_horizon == timedelta(hours=48)
        assert trigger.is_triggered is False

    def test_full_invalidation_trigger(self) -> None:
        """TC-TYPES-020: InvalidationTrigger with all fields."""
        trigger = InvalidationTrigger(
            condition="IAU < $40",
            type="technical",
            asset="IAU",
            time_horizon=timedelta(days=5),
        )
        assert trigger.asset == "IAU"
        assert trigger.time_horizon == timedelta(days=5)

    def test_minimal_auditor_checkpoint(self) -> None:
        """TC-TYPES-021: AuditorCheckpoint with minimum fields."""
        checkpoint = AuditorCheckpoint(
            checkpoint_id="chk_20260505_gold_001",
            narrative="Long gold thesis",
            recommendation="buy",
        )
        assert checkpoint.checkpoint_id == "chk_20260505_gold_001"
        assert checkpoint.invalidation_triggers == []
        assert checkpoint.status == "active"
        assert checkpoint.score is None

    def test_full_auditor_checkpoint(self) -> None:
        """TC-TYPES-022: AuditorCheckpoint with triggers and score."""
        checkpoint = AuditorCheckpoint(
            checkpoint_id="chk_20260505_gold_002",
            narrative="Long gold thesis based on rate cut expectations",
            recommendation="buy",
            invalidation_triggers=[
                InvalidationTrigger(
                    condition="NFP > 250k",
                    type="macro",
                    time_horizon=timedelta(days=7),
                ),
                InvalidationTrigger(
                    condition="IAU < $40",
                    type="technical",
                    asset="IAU",
                    time_horizon=timedelta(days=5),
                ),
            ],
            score=0.85,
        )
        assert len(checkpoint.invalidation_triggers) == 2
        assert checkpoint.score == 0.85
        assert checkpoint.status == "active"

    def test_checkpoint_invalidate(self) -> None:
        """TC-TYPES-023: mark_invalidated changes status and adds reason."""
        checkpoint = AuditorCheckpoint(
            checkpoint_id="chk_20260505_gold_003",
            narrative="Test invalidation",
            recommendation="buy",
        )
        assert checkpoint.status == "active"
        checkpoint.mark_invalidated(reason="NFP came in at 300k")
        assert checkpoint.status == "invalidated"
        assert checkpoint.invalidation_reason == "NFP came in at 300k"


# =========================================================================
# TC-TYPES-024..028: ContinuationState
# =========================================================================


class TestContinuationState:
    """Validate multi-turn API continuation protocol data structure."""

    def test_initial_continuation_state(self) -> None:
        """TC-TYPES-024: ContinuationState starts empty."""
        state = ContinuationState(session_id="cont_20260505_001")
        assert state.session_id == "cont_20260505_001"
        assert state.fragments == []
        assert state.turn_count == 0
        assert state.is_complete is False
        assert state.merged_json is None

    def test_add_fragment(self) -> None:
        """TC-TYPES-025: Adding fragments increments turn count."""
        state = ContinuationState(session_id="cont_20260505_002")
        fragment = {"analysis": "test", "confidence": 0.8}
        state.add_fragment(turn=1, fragment=fragment)
        assert len(state.fragments) == 1
        assert state.turn_count == 1
        assert state.fragments[0]["turn"] == 1
        assert state.fragments[0]["data"] == fragment

    def test_merge_strict(self) -> None:
        """TC-TYPES-026: merge_strict combines fragments by deep merge."""
        state = ContinuationState(session_id="cont_20260505_003")
        state.add_fragment(1, {"analysis": "part1", "assets": ["GLD"]})
        state.add_fragment(2, {"analysis": "part2", "assets": ["IAU"]})

        merged = state.merge_strict()
        assert merged["analysis"] == "part1 part2"
        assert "GLD" in merged["assets"]
        assert "IAU" in merged["assets"]

    def test_merge_strict_no_duplicates(self) -> None:
        """TC-TYPES-027: merge_strict deduplicates list fields."""
        state = ContinuationState(session_id="cont_20260505_004")
        state.add_fragment(1, {"assets": ["GLD", "IAU"]})
        state.add_fragment(2, {"assets": ["IAU", "GDX"]})

        merged = state.merge_strict()
        assert len(merged["assets"]) == 3  # GLD, IAU, GDX (no dup)
        assert sorted(merged["assets"]) == sorted(["GLD", "IAU", "GDX"])

    def test_simple_add_fragment(self) -> None:
        """TC-TYPES-028: Adding turn 0 fragment initializes merge correctly."""
        state = ContinuationState(session_id="cont_20260505_005")
        state.add_fragment(0, {"summary": "initial analysis"})
        assert state.turn_count == 1
        assert state.fragments[0]["turn"] == 0


# =========================================================================
# TC-TYPES-029..043: Phase 6 — Risk Engine & Dual-Track Decision Types
# =========================================================================


class TestSellTriggerSource:
    """Validate SellTriggerSource enum values (Phase 6 — Sell/Liquidate Protocol)."""

    def test_macro_invalidation(self) -> None:
        """TC-TYPES-029: MACRO_INVALIDATION has correct value."""
        from src.scout_types import SellTriggerSource
        assert SellTriggerSource.MACRO_INVALIDATION.value == "macro_invalidation"

    def test_technical_breakdown(self) -> None:
        """TC-TYPES-030: TECHNICAL_BREAKDOWN has correct value."""
        from src.scout_types import SellTriggerSource
        assert SellTriggerSource.TECHNICAL_BREAKDOWN.value == "technical_breakdown"

    def test_portfolio_rebalancing(self) -> None:
        """TC-TYPES-031: PORTFOLIO_REBALANCING has correct value."""
        from src.scout_types import SellTriggerSource
        assert SellTriggerSource.PORTFOLIO_REBALANCING.value == "portfolio_rebalancing"


class TestRiskProfileLabel:
    """Validate RiskProfileLabel enum values (Phase 6 — Risk-Reward Profiling)."""

    def test_asymmetric(self) -> None:
        """TC-TYPES-032: ASYMMETRIC has correct value."""
        from src.scout_types import RiskProfileLabel
        assert RiskProfileLabel.ASYMMETRIC.value == "asymmetric"

    def test_speculative(self) -> None:
        """TC-TYPES-033: SPECULATIVE has correct value."""
        from src.scout_types import RiskProfileLabel
        assert RiskProfileLabel.SPECULATIVE.value == "speculative"

    def test_trend_following(self) -> None:
        """TC-TYPES-034: TREND_FOLLOWING has correct value."""
        from src.scout_types import RiskProfileLabel
        assert RiskProfileLabel.TREND_FOLLOWING.value == "trend_following"


class TestRiskProfile:
    """Validate RiskProfile dataclass (Phase 6 — Layer 1 Risk-Reward Profiling)."""

    def test_full_risk_profile(self) -> None:
        """TC-TYPES-035: RiskProfile with all fields populated."""
        from src.scout_types import RiskProfile, RiskProfileLabel
        profile = RiskProfile(
            profile_id="rp_gold_001",
            narrative_ref="Fed rate cut expectations",
            label=RiskProfileLabel.ASYMMETRIC,
            risk_reward_ratio=3.5,
            expected_upside_pct=25.0,
            expected_downside_pct=7.0,
            safety_margin_pct=18.0,
            confidence_rating="HIGH",
            rationale="Gold deeply undervalued on rate cut repricing",
            triggering_conditions=["Fed dovish pivot", "USD weakness"],
            risk_warnings=["Sharp reversal if NFP beats expectations"],
            time_horizon="3-6 months",
        )
        assert profile.profile_id == "rp_gold_001"
        assert profile.label == RiskProfileLabel.ASYMMETRIC
        assert profile.safety_margin_pct == 18.0
        assert len(profile.triggering_conditions) == 2

    def test_speculative_profile(self) -> None:
        """TC-TYPES-036: Speculative risk profile."""
        from src.scout_types import RiskProfile, RiskProfileLabel
        profile = RiskProfile(
            profile_id="rp_btc_001",
            narrative_ref="BTC halving breakout",
            label=RiskProfileLabel.SPECULATIVE,
            risk_reward_ratio=2.0,
            expected_upside_pct=40.0,
            expected_downside_pct=20.0,
            safety_margin_pct=5.0,
            confidence_rating="MEDIUM",
            rationale="High volatility event-driven trade",
            triggering_conditions=["Halving event", "Increased institutional flow"],
            risk_warnings=["Extreme volatility", "Possible 30% drawdown"],
            time_horizon="1-3 months",
        )
        assert profile.label == RiskProfileLabel.SPECULATIVE
        assert profile.confidence_rating == "MEDIUM"

    def test_trend_following_profile(self) -> None:
        """TC-TYPES-037: Trend-following risk profile."""
        from src.scout_types import RiskProfile, RiskProfileLabel
        profile = RiskProfile(
            profile_id="rp_spy_001",
            narrative_ref="Structural bull trend on rate cuts",
            label=RiskProfileLabel.TREND_FOLLOWING,
            risk_reward_ratio=2.2,
            expected_upside_pct=12.0,
            expected_downside_pct=5.5,
            safety_margin_pct=6.5,
            confidence_rating="HIGH",
            rationale="Established trend with strong macro backing",
            triggering_conditions=["Yield curve steepening", "ISM > 50"],
            risk_warnings=["Late cycle risk", "Valuation compression"],
            time_horizon="6-12 months",
        )
        assert profile.label == RiskProfileLabel.TREND_FOLLOWING
        assert profile.expected_upside_pct == 12.0


class TestAssetPenetrationItem:
    """Validate AssetPenetrationItem dataclass (Phase 6 — Layer 2)."""

    def test_full_penetration_item(self) -> None:
        """TC-TYPES-038: AssetPenetrationItem with all fields."""
        from src.scout_types import AssetPenetrationItem
        item = AssetPenetrationItem(
            ticker="GLD",
            direction="BUY",
            layer="core",
            layer_rationale="Direct gold price exposure via ETF",
            suggested_weight_pct=40.0,
            current_price=205.50,
            limit_price=203.00,
            stop_loss=195.00,
            take_profit=225.00,
            expected_return_pct=9.8,
            beta=0.35,
            correlation_warning="Moderate correlation with USD",
            risk_note="Gold may lag if real yields rise",
        )
        assert item.ticker == "GLD"
        assert item.layer == "core"
        assert item.suggested_weight_pct == 40.0
        assert item.stop_loss == 195.00
        assert item.beta == 0.35

    def test_minimal_penetration_item(self) -> None:
        """TC-TYPES-039: AssetPenetrationItem with only required fields."""
        from src.scout_types import AssetPenetrationItem
        item = AssetPenetrationItem(
            ticker="GDX",
            direction="BUY",
            layer="upstream_leverage",
            layer_rationale="Gold miners operational leverage",
            suggested_weight_pct=25.0,
        )
        assert item.ticker == "GDX"
        assert item.current_price is None
        assert item.stop_loss is None


class TestOrderSuggestion:
    """Validate OrderSuggestion dataclass (Phase 6 — Final Output)."""

    def test_full_buy_order(self) -> None:
        """TC-TYPES-040: Full buy OrderSuggestion with RiskProfile + penetration."""
        from src.scout_types import (
            OrderSuggestion, RiskProfile, RiskProfileLabel,
            AssetPenetrationItem,
        )
        risk = RiskProfile(
            profile_id="rp_gold_001",
            narrative_ref="Fed rate cut expectations",
            label=RiskProfileLabel.ASYMMETRIC,
            risk_reward_ratio=3.5,
            expected_upside_pct=25.0,
            expected_downside_pct=7.0,
            safety_margin_pct=18.0,
            confidence_rating="HIGH",
            rationale="Deep value on rate cut repricing",
            triggering_conditions=["Fed dovish pivot"],
            risk_warnings=["NFP surprise risk"],
            time_horizon="3-6 months",
        )
        items = [
            AssetPenetrationItem(
                ticker="GLD", direction="BUY", layer="core",
                layer_rationale="Direct ETF", suggested_weight_pct=40.0,
                limit_price=203.00,
            ),
            AssetPenetrationItem(
                ticker="GDX", direction="BUY", layer="upstream_leverage",
                layer_rationale="Miner leverage", suggested_weight_pct=20.0,
            ),
        ]
        order = OrderSuggestion(
            order_id="ord_gold_20260505_001",
            created_at="2026-05-05T17:00:00Z",
            decision_track="ACTION_AND_ADJUST",
            action_type="BUY",
            risk_profile=risk,
            penetration_items=items,
            total_notional_commitment=100000.0,
            cash_reserve_after=50000.0,
            cash_reserve_pct=33.3,
            account_state_ref="acct_20260505_001",
            causal_audit_refs=["chk_gold_001", "chk_gold_002"],
        )
        assert order.order_id == "ord_gold_20260505_001"
        assert order.action_type == "BUY"
        assert len(order.penetration_items) == 2
        assert order.execution_disclaimer == (
            "THEORETICAL OUTPUT ONLY - NO BROKERAGE API CONNECTED"
        )

    def test_execution_disclaimer_default(self) -> None:
        """TC-TYPES-041: OrderSuggestion has built-in execution disclaimer."""
        from src.scout_types import (
            OrderSuggestion, RiskProfile, RiskProfileLabel,
        )
        risk = RiskProfile(
            profile_id="rp_minimal", narrative_ref="test",
            label=RiskProfileLabel.TREND_FOLLOWING,
            risk_reward_ratio=1.0, expected_upside_pct=5.0,
            expected_downside_pct=5.0, safety_margin_pct=0.0,
            confidence_rating="LOW", rationale="test",
            triggering_conditions=[], risk_warnings=[], time_horizon="1m",
        )
        order = OrderSuggestion(
            order_id="ord_test_001", created_at="now",
            decision_track="ACTION_AND_ADJUST", action_type="BUY",
            risk_profile=risk, penetration_items=[],
            total_notional_commitment=0.0, cash_reserve_after=0.0,
            cash_reserve_pct=0.0, account_state_ref="test",
            causal_audit_refs=[],
        )
        assert "THEORETICAL" in order.execution_disclaimer
        assert "NO BROKERAGE" in order.execution_disclaimer


class TestMarketEvolutionReport:
    """Validate MarketEvolutionReport dataclass (Phase 6 — Observe & Wait)."""

    def test_full_observe_report(self) -> None:
        """TC-TYPES-042: Full observe report with watch points and dark currents."""
        from src.scout_types import (
            MarketEvolutionReport, NarrativeThread, WatchPoint,
        )
        currents = [
            NarrativeThread(
                narrative="Stealth dollar weakening",
                evidence_chain=["DXY falling for 3 consecutive weeks",
                                "EM currency basket strengthening"],
                confidence=0.72,
            ),
        ]
        points = [
            WatchPoint(
                direction="cpi_trend",
                description="US CPI MoM",
                current_value=0.2,
                activation_threshold=0.28,
                activation_operator="gt",
                activated_action="Activate long TLT",
                data_source="BLS",
            ),
            WatchPoint(
                direction="fed_speak",
                description="Powell speech tone",
                current_value=0.5,
                activation_threshold=0.75,
                activation_operator="cross_above",
                activated_action="Increase gold allocation",
                data_source="Fed calendar",
            ),
        ]
        report = MarketEvolutionReport(
            report_id="mer_20260505_001",
            created_at="2026-05-05T17:00:00Z",
            decision_track="OBSERVE_AND_WAIT",
            trigger_scenario="CONTRADICTION",
            reason_for_observe="DXY weak but NFP strong - contradicting signals",
            dark_currents=currents,
            watch_points=points,
            review_timeline="2026-05-08 after CPI release",
        )
        assert report.report_id == "mer_20260505_001"
        assert report.trigger_scenario == "CONTRADICTION"
        assert len(report.dark_currents) == 1
        assert len(report.watch_points) == 2

    def test_qualitative_judgment(self) -> None:
        """TC-TYPES-043: QualitativeJudgment routes to OBSERVE track correctly."""
        from src.scout_types import QualitativeJudgment
        j = QualitativeJudgment(
            judgment_id="qj_20260505_001",
            timestamp="2026-05-05T17:00:00Z",
            signal_coherence_score=35.0,
            reward_risk_ratio=0.8,
            market_regime="choppy",
            decision_track="OBSERVE_AND_WAIT",
            track_confidence=0.85,
            decision_rationale="Low signal coherence with poor reward/risk",
            observe_scenario="CONTRADICTION",
        )
        assert j.judgment_id == "qj_20260505_001"
        assert j.decision_track == "OBSERVE_AND_WAIT"
        assert j.suggested_subtrack is None
        assert j.observe_scenario == "CONTRADICTION"
        assert j.signal_coherence_score == 35.0


class TestLiquidationReport:
    """Validate LiquidationReport dataclass (Phase 6 — Sell/Liquidate Protocol)."""

    def test_full_liquidation(self) -> None:
        """TC-TYPES-044: Full sell report with macro + technical triggers."""
        from src.scout_types import LiquidationReport, SellTriggerSource
        report = LiquidationReport(
            action="SELL",
            position_to_close="IAU",
            current_shares=500,
            suggested_liquidation_ratio=1.0,
            trigger_source=SellTriggerSource.MACRO_INVALIDATION,
            macro_trigger="NFP: 320K vs consensus 180K",
            technical_trigger="IAU closing below 60MA @ $38.20",
            evidence_chain=[
                "Strong labor market reduces gold hedge demand",
                "Real yields rising on hawkish repricing",
            ],
            protective_stop=None,
            reason_narrative="Complete liquidation: macro invalidation of gold thesis",
            causal_audit_ref="chk_gold_003",
        )
        assert report.action == "SELL"
        assert report.position_to_close == "IAU"
        assert report.suggested_liquidation_ratio == 1.0
        assert report.macro_trigger == "NFP: 320K vs consensus 180K"
        assert report.evidence_chain is not None
        assert len(report.evidence_chain) == 2

    def test_partial_liquidation(self) -> None:
        """TC-TYPES-045: Partial sell with protective stop."""
        from src.scout_types import LiquidationReport, SellTriggerSource
        report = LiquidationReport(
            position_to_close="GLD",
            current_shares=200,
            suggested_liquidation_ratio=0.5,
            trigger_source=SellTriggerSource.TECHNICAL_BREAKDOWN,
            technical_trigger="Failed to hold $200 support level",
            protective_stop=198.00,
            reason_narrative="Partial reduction on technical weakness",
            causal_audit_ref="chk_gld_002",
        )
        assert report.suggested_liquidation_ratio == 0.5
        assert report.trigger_source == SellTriggerSource.TECHNICAL_BREAKDOWN
        assert report.protective_stop == 198.00
        assert report.macro_trigger is None
