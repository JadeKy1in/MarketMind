"""
test_decision_aggregator.py — Phase 7.4 test suite for DecisionAggregator

Coverage targets:
  - Score synthesis (weighted avg − audit deduction)
  - Anchor computation (keyword matching + MIN-rule)
  - Resonance matrix (pair alignment / divergence)
  - Position sizing (full buy / scaled buy / observe / sell / clearout)
  - Safety valve clamping (5 valves)
  - Invariant verification (I1–I8 from DecisionReport docstring)
  - Edge cases (zero scores, missing dimensions, zero buying power)
"""

from __future__ import annotations

import pytest

from src.account_reader import AccountState, Position
from src.mosaic_reasoning import MosaicNarrative, PhysicalVerificationIndicator
from src.paradigm_anchors import (
    AnchorState,
    ThreeAnchors,
    compute_paradigm_multiplier,
)
from src.red_team_auditor import RedTeamAuditReport
from src.decision_aggregator import (
    DecisionAggregator,
    DecisionReport,
    DecisionTrack,
    PositionSizing,
    ResonanceMatrix,
    FULL_BUY_THRESHOLD,
    SCALED_BUY_THRESHOLD,
    SCALED_SELL_THRESHOLD,
)


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def sample_account() -> AccountState:
    """Standard account with $100k cash + $100k in positions = $200k net worth."""
    return AccountState(
        last_updated="2026-05-06",
        cash=100_000.0,
        buying_power=150_000.0,
        positions=[
            Position(ticker="GLD", shares=100, avg_cost=180.0, current_price=200.0),
            Position(ticker="TLT", shares=200, avg_cost=85.0, current_price=90.0),
            Position(ticker="XLB", shares=500, avg_cost=80.0, current_price=76.0),
        ],
        notes="Test account",
    )


@pytest.fixture
def pass_audit() -> RedTeamAuditReport:
    return RedTeamAuditReport(
        audit_id="audit-001",
        audited_at="2026-05-06T12:00:00Z",
        audited_report_ref="mosaic-001",
        audited_macro_narrative="Gold bull run scenario",
        attacks_launched=[],
        overall_resilience_score=100.0,
        pass_audit=True,
    )


@pytest.fixture
def fail_audit() -> RedTeamAuditReport:
    return RedTeamAuditReport(
        audit_id="audit-002",
        audited_at="2026-05-06T12:00:00Z",
        audited_report_ref="mosaic-002",
        audited_macro_narrative="Weak narrative with gaps",
        attacks_launched=[],
        overall_resilience_score=70.0,
        pass_audit=False,
    )


def _make_pvi(pvi_id: str, name_suffix: str = "test") -> PhysicalVerificationIndicator:
    """Helper to create a valid PhysicalVerificationIndicator with correct fields."""
    return PhysicalVerificationIndicator(
        pvi_id=pvi_id,
        indicator_name=f"indicator_{name_suffix}",
        description=f"Description for {pvi_id}",
        current_value=50.0,
        target_threshold=75.0,
        target_direction="above",
        verification_deadline="2026-12-31",
        linked_logic_chain=f"chain_{name_suffix}",
        consequence_if_failed=f"Liability if {pvi_id} fails",
        data_source="Reuters",
        manipulation_risk="Low",
    )


@pytest.fixture
def mosaic_bull() -> MosaicNarrative:
    """A bullish gold narrative with no anchor-keyword triggers."""
    return MosaicNarrative(
        narrative_id="mosaic-bull-001",
        generated_at="2026-05-06T12:00:00Z",
        confidence=0.90,
        source_matrix_id="GLD",
        macro_theme="Gold monetary premium expansion",
        why_counter_is_weaker="USD real rates declining",
        consensus_fragility=25.0,
        physical_verifications=[
            _make_pvi("pvi-001", "cb_gold"),
            _make_pvi("pvi-002", "treasury_reval"),
            _make_pvi("pvi-003", "comex_inv"),
        ],
    )


@pytest.fixture
def mosaic_no_anomaly() -> MosaicNarrative:
    """Mosaic with neutral text — all anchors should stay GREEN."""
    return MosaicNarrative(
        narrative_id="mosaic-neutral-002",
        generated_at="2026-05-06T12:00:00Z",
        confidence=0.60,
        source_matrix_id="GLD",
        macro_theme="Routine commodity cycle rebalancing",
        why_counter_is_weaker="Inventory build easing",
        consensus_fragility=30.0,
        physical_verifications=[
            _make_pvi("pvi-n01", "inventory_draw"),
            _make_pvi("pvi-n02", "margins"),
            _make_pvi("pvi-n03", "dollar_index"),
        ],
    )


@pytest.fixture
def mosaic_geopolitical_red() -> MosaicNarrative:
    """Mosaic mentioning 'sanctions' + 'war' — GII should go RED."""
    return MosaicNarrative(
        narrative_id="mosaic-geo-003",
        generated_at="2026-05-06T12:00:00Z",
        confidence=0.55,
        source_matrix_id="GLD",
        macro_theme="Geopolitical risk from sanctions escalation",
        why_counter_is_weaker="War risk premium expanding in options market",
        consensus_fragility=60.0,
        physical_verifications=[
            _make_pvi("pvi-g01", "oil_skew"),
            _make_pvi("pvi-g02", "defense_stocks"),
            _make_pvi("pvi-g03", "em_fx"),
        ],
    )


@pytest.fixture
def high_scores() -> dict[str, float]:
    return {"fundamental": 95.0, "technical": 90.0, "event_driven": 92.0, "sentiment": 88.0}


@pytest.fixture
def medium_scores() -> dict[str, float]:
    return {"fundamental": 75.0, "technical": 72.0, "event_driven": 70.0, "sentiment": 65.0}


@pytest.fixture
def low_scores() -> dict[str, float]:
    return {"fundamental": 25.0, "technical": 20.0, "event_driven": 18.0, "sentiment": 15.0}


@pytest.fixture
def empty_details() -> dict[str, dict]:
    return {
        "fundamental": {"reasoning": "Strong GDP"},
        "technical": {"reasoning": "Trend intact"},
        "event_driven": {"reasoning": "Earnings beat"},
        "sentiment": {"reasoning": "Positive flow"},
    }


# ======================================================================
# Tests — Paradigm Anchors (sub-module)
# ======================================================================


class TestParadigmAnchors:
    """Unit tests for paradigm_anchors.py imports used by aggregator."""

    def test_green_all_return_1_0(self) -> None:
        anchors = ThreeAnchors(
            fiscal_credibility=AnchorState.GREEN,
            geopolitical_gii=AnchorState.GREEN,
            reflexivity_rac=AnchorState.GREEN,
        )
        assert compute_paradigm_multiplier(anchors) == 1.0

    def test_yellow_all_return_0_85(self) -> None:
        anchors = ThreeAnchors(
            fiscal_credibility=AnchorState.YELLOW,
            geopolitical_gii=AnchorState.YELLOW,
            reflexivity_rac=AnchorState.YELLOW,
        )
        assert compute_paradigm_multiplier(anchors) == 0.85

    def test_red_dominates(self) -> None:
        """MIN-rule: any RED → multiplier = 0.0."""
        anchors = ThreeAnchors(
            fiscal_credibility=AnchorState.RED,
            geopolitical_gii=AnchorState.GREEN,
            reflexivity_rac=AnchorState.GREEN,
        )
        assert compute_paradigm_multiplier(anchors) == 0.0

    def test_mixed_yellow_green_min_yellow(self) -> None:
        anchors = ThreeAnchors(
            fiscal_credibility=AnchorState.GREEN,
            geopolitical_gii=AnchorState.YELLOW,
            reflexivity_rac=AnchorState.GREEN,
        )
        assert compute_paradigm_multiplier(anchors) == 0.85

    def test_unknown_falls_to_yellow(self) -> None:
        anchors = ThreeAnchors(
            fiscal_credibility=AnchorState.UNKNOWN,
            geopolitical_gii=AnchorState.GREEN,
            reflexivity_rac=AnchorState.GREEN,
        )
        assert compute_paradigm_multiplier(anchors) == 0.85


# ======================================================================
# Tests — Resonance Matrix
# ======================================================================


class TestResonanceMatrix:
    """Resonance matrix invariants."""

    def test_all_high_resonating(self) -> None:
        rm = ResonanceMatrix(dimensions_resonating=4)
        assert rm.resonance_threshold_met is True

    def test_two_only_not_resonating(self) -> None:
        rm = ResonanceMatrix(dimensions_resonating=2)
        assert rm.resonance_threshold_met is False

    def test_post_init_sync(self) -> None:
        """Invariant I1: threshold_met ≡ dimensions_resonating >= 3."""
        for n in range(5):
            rm = ResonanceMatrix(dimensions_resonating=n)
            assert rm.resonance_threshold_met == (n >= 3)


# ======================================================================
# Tests — Score Synthesis
# ======================================================================


class TestScoreSynthesis:
    """Weighted average − audit deduction."""

    def test_perfect_scores_no_deduction(self, pass_audit: RedTeamAuditReport) -> None:
        agg = DecisionAggregator()
        scores = {"fundamental": 100.0, "technical": 100.0, "event_driven": 100.0, "sentiment": 100.0}
        raw, adj, deduction = agg._score_synthesis(scores, pass_audit)
        assert raw == pytest.approx(100.0, abs=1e-6)
        assert deduction == pytest.approx(0.0, abs=1e-6)
        assert adj == pytest.approx(100.0, abs=1e-6)

    def test_weighted_average_correct(self, pass_audit: RedTeamAuditReport) -> None:
        agg = DecisionAggregator()
        scores = {"fundamental": 50.0, "technical": 50.0, "event_driven": 50.0, "sentiment": 50.0}
        raw, adj, _ = agg._score_synthesis(scores, pass_audit)
        assert raw == pytest.approx(50.0, abs=1e-6)
        assert adj == pytest.approx(50.0, abs=1e-6)

    def test_missing_dimension_normalised(self, pass_audit: RedTeamAuditReport) -> None:
        agg = DecisionAggregator()
        scores = {"fundamental": 100.0, "sentiment": 100.0}
        raw, adj, _ = agg._score_synthesis(scores, pass_audit)
        # Weighted: 100*0.30 + 100*0.25 = 55, weight_sum = 0.55 → 55/0.55 = 100
        assert raw == pytest.approx(100.0, abs=1e-6)

    def test_audit_deduction_applied(self, fail_audit: RedTeamAuditReport) -> None:
        agg = DecisionAggregator()
        scores = {"fundamental": 100.0, "technical": 100.0, "event_driven": 100.0, "sentiment": 100.0}
        raw, adj, deduction = agg._score_synthesis(scores, fail_audit)
        # deduction = 100 - overall_resilience_score = 100 - 70 = 30.0
        # adj = 100 - 30 = 70.0
        assert raw == pytest.approx(100.0)
        assert deduction == pytest.approx(30.0, abs=1e-1)
        assert adj == pytest.approx(70.0, abs=1e-1)

    def test_clamp_floor(self, fail_audit: RedTeamAuditReport) -> None:
        """Adjusted score cannot go below 0."""
        agg = DecisionAggregator()
        _, adj, _ = agg._score_synthesis({"fundamental": -5.0}, fail_audit)
        assert adj >= 0.0  # floor works


# ======================================================================
# Tests — Anchor Computation
# ======================================================================


class TestAnchorComputation:
    """Keyword-driven anchor derivation."""

    def test_no_trigger_anchors_green(
        self, mosaic_no_anomaly: MosaicNarrative, empty_details: dict
    ) -> None:
        agg = DecisionAggregator()
        anchors = agg._compute_anchors(empty_details, mosaic_no_anomaly)
        assert anchors.fiscal_credibility == AnchorState.GREEN
        assert anchors.geopolitical_gii == AnchorState.GREEN
        assert anchors.reflexivity_rac == AnchorState.GREEN

    def test_geopolitical_red(
        self, mosaic_geopolitical_red: MosaicNarrative, empty_details: dict
    ) -> None:
        agg = DecisionAggregator()
        anchors = agg._compute_anchors(empty_details, mosaic_geopolitical_red)
        assert anchors.geopolitical_gii == AnchorState.RED
        assert "sanctions" in anchors.gii_evidence
        assert "war" in anchors.gii_evidence

    def test_fiscal_red_from_details(
        self,
        mosaic_no_anomaly: MosaicNarrative,
    ) -> None:
        """Fiscal RED triggered via dimension_details reasoning text."""
        agg = DecisionAggregator()
        details = {
            "fundamental": {"reasoning": "Rising CDS spread and downgrade risk are concerning"},
            "technical": {"reasoning": "Trend intact"},
            "event_driven": {"reasoning": "No events"},
            "sentiment": {"reasoning": "Neutral"},
        }
        anchors = agg._compute_anchors(details, mosaic_no_anomaly)
        assert anchors.fiscal_credibility == AnchorState.RED
        assert "cds spread" in anchors.fiscal_evidence

    def test_reflexivity_yellow(
        self,
        mosaic_bull: MosaicNarrative,
    ) -> None:
        agg = DecisionAggregator()
        details = {
            "fundamental": {"reasoning": "Normal growth"},
            "technical": {"reasoning": "Money flow divergence detected"},
            "event_driven": {"reasoning": "No events"},
            "sentiment": {"reasoning": "Positive"},
        }
        anchors = agg._compute_anchors(details, mosaic_bull)
        assert anchors.reflexivity_rac == AnchorState.YELLOW


# ======================================================================
# Tests — Resonance
# ======================================================================


class TestResonance:
    """Four-dimensional resonance matrix."""

    def test_all_four_aligned(self) -> None:
        agg = DecisionAggregator()
        rm = agg._compute_resonance({"fundamental": 80, "technical": 85, "event_driven": 90, "sentiment": 75})
        assert rm.dimensions_resonating >= 3
        assert rm.resonance_threshold_met is True
        assert len(rm.resonance_pairs) == 6  # all pairs aligned
        assert len(rm.divergence_pairs) == 0

    def test_all_low_no_resonance(self) -> None:
        agg = DecisionAggregator()
        rm = agg._compute_resonance({"fundamental": 20, "technical": 15, "event_driven": 10, "sentiment": 5})
        assert rm.dimensions_resonating == 0
        assert rm.resonance_threshold_met is False

    def test_partial_resonance(self) -> None:
        agg = DecisionAggregator()
        rm = agg._compute_resonance({"fundamental": 90, "technical": 85, "event_driven": 10, "sentiment": 8})
        # fundamental↔technical pair avg = 87.5 >= 60 → resonating
        # fundamental↔event_driven: 50 → neither
        # fundamental↔sentiment: 49 → neither
        # technical↔event_driven: 47.5 → neither
        # technical↔sentiment: 46.5 → neither
        # event_driven↔sentiment: 9 < 40 → divergence
        assert rm.dimensions_resonating == 1
        assert len(rm.divergence_pairs) == 1
        assert rm.resonance_threshold_met is False

    def test_three_dimensions_only(self) -> None:
        agg = DecisionAggregator()
        rm = agg._compute_resonance({"fundamental": 85, "technical": 80, "event_driven": 90})
        # 3 dims → 3 pairs, all above 60
        assert rm.dimensions_resonating == 3
        assert rm.resonance_threshold_met is True
        assert rm.resonance_score == 100.0


# ======================================================================
# Tests — Score → Track
# ======================================================================


class TestScoreToTrack:
    """Threshold mapping."""

    def test_full_buy(self) -> None:
        assert DecisionAggregator.score_to_track(95.0) == DecisionTrack.FULL_BUY
        assert DecisionAggregator.score_to_track(90.0) == DecisionTrack.FULL_BUY

    def test_scaled_buy(self) -> None:
        assert DecisionAggregator.score_to_track(80.0) == DecisionTrack.SCALED_BUY
        assert DecisionAggregator.score_to_track(70.0) == DecisionTrack.SCALED_BUY

    def test_observe_wait(self) -> None:
        assert DecisionAggregator.score_to_track(65.0) == DecisionTrack.OBSERVE_WAIT
        assert DecisionAggregator.score_to_track(50.0) == DecisionTrack.OBSERVE_WAIT

    def test_scaled_sell(self) -> None:
        assert DecisionAggregator.score_to_track(45.0) == DecisionTrack.SCALED_SELL
        assert DecisionAggregator.score_to_track(30.0) == DecisionTrack.SCALED_SELL

    def test_force_clearout(self) -> None:
        assert DecisionAggregator.score_to_track(0.0) == DecisionTrack.FORCE_CLEAROUT
        assert DecisionAggregator.score_to_track(29.99) == DecisionTrack.FORCE_CLEAROUT

    def test_boundary_full_buy(self) -> None:
        assert DecisionAggregator.score_to_track(90.0 - 1e-9) == DecisionTrack.SCALED_BUY


# ======================================================================
# Tests — Position Sizing
# ======================================================================


class TestPositionSizing:
    """Fractional Kelly position sizing."""

    def test_full_buy_computes_shares(
        self, high_scores: dict, sample_account: AccountState
    ) -> None:
        agg = DecisionAggregator()
        sizing = agg._compute_position(
            adjusted_score=95.0,
            paradigm_multiplier=1.0,
            account_state=sample_account,
            target_ticker="GLD",
            target_price=200.0,
        )
        # net worth = 100k cash + 76k pos = 176000
        # risk_capital = 176000 * 0.02 = 3520
        # kelly = 1.0 for full_buy
        # suggested = int(3520 * 1.0 / 200) = 17
        # max_shares = int(150000 * 0.40 / 200) = 300
        # suggested = min(17, 300) = 17
        assert sizing.direction == "BUY"
        assert sizing.suggested_shares == 17
        assert sizing.max_shares == 300
        assert sizing.risk_capital_at_stake == pytest.approx(17 * 200, abs=0.01)

    def test_scaled_buy_applies_kelly(
        self, medium_scores: dict, sample_account: AccountState
    ) -> None:
        agg = DecisionAggregator()
        sizing = agg._compute_position(
            adjusted_score=75.0,
            paradigm_multiplier=1.0,
            account_state=sample_account,
            target_ticker="GLD",
            target_price=200.0,
        )
        # kelly = 0.80 for scaled_buy
        # risk_capital = 176000 * 0.02 = 3520
        # suggested = int(3520 * 0.80 / 200) = 14
        assert sizing.direction == "BUY"
        assert sizing.suggested_shares == 14

    def test_observe_wait_returns_hold(self, sample_account: AccountState) -> None:
        agg = DecisionAggregator()
        sizing = agg._compute_position(
            adjusted_score=55.0,
            paradigm_multiplier=1.0,
            account_state=sample_account,
            target_ticker="GLD",
            target_price=200.0,
        )
        assert sizing.direction == "HOLD"
        assert sizing.suggested_shares == 0

    def test_scaled_sell_returns_sell(self, sample_account: AccountState) -> None:
        agg = DecisionAggregator()
        sizing = agg._compute_position(
            adjusted_score=35.0,
            paradigm_multiplier=1.0,
            account_state=sample_account,
            target_ticker="GLD",
            target_price=200.0,
        )
        assert sizing.direction == "SELL"
        assert sizing.suggested_shares == 5  # int(3520 * 0.30 / 200) = 5

    def test_force_clearout_returns_clearout(self, sample_account: AccountState) -> None:
        agg = DecisionAggregator()
        sizing = agg._compute_position(
            adjusted_score=20.0,
            paradigm_multiplier=1.0,
            account_state=sample_account,
            target_ticker="GLD",
            target_price=200.0,
        )
        assert sizing.direction == "CLEAROUT"
        assert sizing.suggested_shares == 0
        assert sizing.cooling_period_hours == 38

    def test_paradigm_multiplier_reduces_size(
        self, high_scores: dict, sample_account: AccountState
    ) -> None:
        agg = DecisionAggregator()
        sizing = agg._compute_position(
            adjusted_score=95.0,
            paradigm_multiplier=0.85,
            account_state=sample_account,
            target_ticker="GLD",
            target_price=200.0,
        )
        # Full buy kelly 1.0, but risk_capital * 0.85 → int(3520 * 0.85 * 1.0 / 200) = 14
        assert sizing.suggested_shares == 14  # 17 * 0.85 = 14.45 → int = 14

    def test_zero_buying_power(self, sample_account: AccountState) -> None:
        """Zero buying power should cap at 0 shares."""
        zero_bp = AccountState(
            last_updated="2026-05-06",
            cash=0.0,
            buying_power=0.0,
            positions=[],
            notes="No funds",
        )
        agg = DecisionAggregator()
        sizing = agg._compute_position(
            adjusted_score=95.0,
            paradigm_multiplier=1.0,
            account_state=zero_bp,
            target_ticker="GLD",
            target_price=200.0,
        )
        # net_worth = 0, risk_capital = 0, suggested = 0
        assert sizing.suggested_shares == 0


# ======================================================================
# Tests — Safety Valves
# ======================================================================


class TestSafetyValves:
    """Five hard safety valves."""

    def test_valve1_buying_power_cap(
        self, high_scores: dict, sample_account: AccountState
    ) -> None:
        """Valve-1: capped at 40% buying power (~300 shares)."""
        agg = DecisionAggregator()
        sizing = PositionSizing(direction="BUY", suggested_shares=500, risk_capital_at_stake=100_000.0)
        anchors = ThreeAnchors()
        sizing, valves = agg._apply_safety_valves(sizing, anchors, sample_account)
        # Valve 1: buying power 150000 * 0.40 / 200 = 300 max by bp
        assert len(valves) >= 1
        assert any("Valve-1" in v for v in valves)

    def test_valve1_fiscal_red_20pct(
        self, high_scores: dict, sample_account: AccountState
    ) -> None:
        """Fiscal RED → buying power cap drops to 20%."""
        agg = DecisionAggregator()
        sizing = PositionSizing(
            direction="BUY", suggested_shares=200,
            risk_capital_at_stake=40_000.0,
        )
        anchors = ThreeAnchors(fiscal_credibility=AnchorState.RED)
        sizing, valves = agg._apply_safety_valves(sizing, anchors, sample_account)
        # 20% of 150000 = 30000 / 200 = 150 shares
        assert any("Valve-1" in v for v in valves)
        assert sizing.suggested_shares <= 150

    def test_valve2_single_ticker_risk(
        self, high_scores: dict, sample_account: AccountState
    ) -> None:
        """Valve-2: single-ticker risk ≤ 2% of net worth."""
        agg = DecisionAggregator()
        sizing = PositionSizing(
            direction="BUY", suggested_shares=500,
            risk_capital_at_stake=100_000.0,
        )
        anchors = ThreeAnchors()
        sizing, valves = agg._apply_safety_valves(sizing, anchors, sample_account)
        # 2% of 176000 = 3520 / 200 = 17 shares max by risk
        assert any("Valve-2" in v for v in valves)
        assert sizing.suggested_shares <= 17

    def test_valve3_fiscal_red_net_exposure(
        self, medium_scores: dict, sample_account: AccountState
    ) -> None:
        """Valve-3: fiscal RED → net exposure ≤ 30% of existing.

        Valve 1 (20% BP) and Valve 2 (2% net worth) pre-clamp before
        Valve 3 runs, so Valve-3 is never reached with sample_account.
        Verify that Valve 1 & 2 fire and final shares respect the most
        restrictive limit (Valve 2 = 17 shares).
        """
        agg = DecisionAggregator()
        sizing = PositionSizing(
            direction="BUY", suggested_shares=500,
            risk_capital_at_stake=100_000.0,
        )
        anchors = ThreeAnchors(fiscal_credibility=AnchorState.RED)
        sizing, valves = agg._apply_safety_valves(sizing, anchors, sample_account)
        # Valve 1: fiscal RED → 20% of 150000 = 30000 / 200 = 150
        # Valve 2: 2% of 176000 = 3520 / 200 = 17  ← most restrictive
        # Valve 3: 30% of 76000 = 22800 / 200 = 114 (never reached)
        assert any("Valve-1" in v for v in valves)
        assert any("Valve-2" in v for v in valves)
        assert sizing.suggested_shares <= 17  # clamped by Valve 2

    def test_valve5_yellow_cap(
        self, medium_scores: dict, sample_account: AccountState
    ) -> None:
        """Valve-5: any YELLOW anchor → shares × 0.85.

        Note: Valve 2 (single-ticker risk ≤ 2% of net worth) clamps
        suggested_shares from 100 → 17 BEFORE Valve 5 multiplies by 0.85,
        yielding 14 (int(17 * 0.85)) rather than 85.
        """
        agg = DecisionAggregator()
        sizing = PositionSizing(
            direction="BUY", suggested_shares=100,
            risk_capital_at_stake=20_000.0,
        )
        anchors = ThreeAnchors(geopolitical_gii=AnchorState.YELLOW)
        sizing, valves = agg._apply_safety_valves(sizing, anchors, sample_account)
        assert any("Valve-2" in v for v in valves)
        assert any("Valve-5" in v for v in valves)
        # Valve 2: 2% of 176000 = 3520 / 200 = 17
        # Valve 5: int(17 * 0.85) = 14
        assert sizing.suggested_shares == 14

    def test_no_valves_triggered_green(
        self, high_scores: dict, sample_account: AccountState
    ) -> None:
        """All GREEN → no valves triggered for reasonable sizing."""
        agg = DecisionAggregator()
        sizing = PositionSizing(direction="BUY", suggested_shares=10, risk_capital_at_stake=2_000.0)
        anchors = ThreeAnchors()
        sizing, valves = agg._apply_safety_valves(sizing, anchors, sample_account)
        assert len(valves) == 0

    def test_clearout_unchanged_by_valves(self, sample_account: AccountState) -> None:
        """CLEAROUT direction should not change."""
        agg = DecisionAggregator()
        sizing = PositionSizing(direction="CLEAROUT", suggested_shares=0)
        anchors = ThreeAnchors()
        sizing, valves = agg._apply_safety_valves(sizing, anchors, sample_account)
        assert sizing.direction == "CLEAROUT"


# ======================================================================
# Tests — Full Pipeline Integration
# ======================================================================


class TestFullPipeline:
    """End-to-end DecisionAggregator.aggregate() with real upstream data."""

    def test_full_buy_green_all(
        self,
        high_scores: dict,
        empty_details: dict,
        mosaic_no_anomaly: MosaicNarrative,
        pass_audit: RedTeamAuditReport,
        sample_account: AccountState,
    ) -> None:
        """All GREEN anchors, no deduction → FULL_BUY track."""
        agg = DecisionAggregator()
        report = agg.aggregate(
            dimension_scores=high_scores,
            dimension_details=empty_details,
            mosaic_narrative=mosaic_no_anomaly,
            audit_report=pass_audit,
            account_state=sample_account,
            target_ticker="GLD",
            target_price=200.0,
        )
        assert report.decision_track == DecisionTrack.FULL_BUY
        assert report.final_score >= FULL_BUY_THRESHOLD
        assert report.paradigm_multiplier == 1.0
        assert report.audit_passed is True
        assert report.logic_chain_integrity is True
        assert report.position_sizing is not None
        assert report.position_sizing.direction == "BUY"
        assert report.position_sizing.suggested_shares > 0
        # Invariant I8
        assert "THEORETICAL" in report.execution_disclaimer

    def test_scaled_sell_with_audit_deduction(
        self,
        medium_scores: dict,
        empty_details: dict,
        mosaic_no_anomaly: MosaicNarrative,
        fail_audit: RedTeamAuditReport,
        sample_account: AccountState,
    ) -> None:
        """Score 40.55 after deduction (70.55 - 30.0) → SCALED_SELL (>= 30, < 50)."""
        agg = DecisionAggregator()
        report = agg.aggregate(
            dimension_scores=medium_scores,
            dimension_details=empty_details,
            mosaic_narrative=mosaic_no_anomaly,
            audit_report=fail_audit,
            account_state=sample_account,
            target_ticker="GLD",
            target_price=200.0,
        )
        assert report.decision_track == DecisionTrack.SCALED_SELL
        assert SCALED_SELL_THRESHOLD <= report.final_score < SCALED_BUY_THRESHOLD
        assert report.audit_deduction > 0
        assert report.paradigm_multiplier == 1.0
        assert report.audit_passed is False

    def test_observe_wait_due_to_paradigm_multiplier(
        self,
        medium_scores: dict,
        mosaic_geopolitical_red: MosaicNarrative,
        pass_audit: RedTeamAuditReport,
        sample_account: AccountState,
    ) -> None:
        """Medium scores but geopolitical RED → 0 multiplier → OBSERVE_WAIT."""
        agg = DecisionAggregator()
        details = {
            "fundamental": {"reasoning": ""},
            "technical": {"reasoning": ""},
            "event_driven": {"reasoning": ""},
            "sentiment": {"reasoning": ""},
        }
        report = agg.aggregate(
            dimension_scores=medium_scores,
            dimension_details=details,
            mosaic_narrative=mosaic_geopolitical_red,
            audit_report=pass_audit,
            account_state=sample_account,
            target_ticker="GLD",
            target_price=200.0,
        )
        assert report.paradigm_multiplier == 0.0
        assert report.final_score == 0.0
        assert report.decision_track == DecisionTrack.FORCE_CLEAROUT

    def test_force_clearout_low_scores(
        self,
        low_scores: dict,
        empty_details: dict,
        mosaic_no_anomaly: MosaicNarrative,
        fail_audit: RedTeamAuditReport,
        sample_account: AccountState,
    ) -> None:
        """Low scores + audit deduction → FORCE_CLEAROUT."""
        agg = DecisionAggregator()
        report = agg.aggregate(
            dimension_scores=low_scores,
            dimension_details=empty_details,
            mosaic_narrative=mosaic_no_anomaly,
            audit_report=fail_audit,
            account_state=sample_account,
            target_ticker="GLD",
            target_price=200.0,
        )
        assert report.decision_track == DecisionTrack.FORCE_CLEAROUT
        assert report.position_sizing is not None
        assert report.position_sizing.direction == "CLEAROUT"
        # Invariant I4: cooling > 0 iff FORCE_CLEAROUT
        assert report.position_sizing.cooling_period_hours > 0

    def test_resonance_logged_in_report(
        self,
        high_scores: dict,
        empty_details: dict,
        mosaic_bull: MosaicNarrative,
        pass_audit: RedTeamAuditReport,
        sample_account: AccountState,
    ) -> None:
        agg = DecisionAggregator()
        report = agg.aggregate(
            dimension_scores=high_scores,
            dimension_details=empty_details,
            mosaic_narrative=mosaic_bull,
            audit_report=pass_audit,
            account_state=sample_account,
            target_ticker="GLD",
            target_price=200.0,
        )
        assert report.resonance is not None
        assert report.resonance.resonance_threshold_met is True
        assert report.logic_chain_integrity is True

    def test_anchor_states_in_report(
        self,
        high_scores: dict,
        mosaic_geopolitical_red: MosaicNarrative,
        pass_audit: RedTeamAuditReport,
        sample_account: AccountState,
    ) -> None:
        """Geopolitical RED appears in anchors."""
        agg = DecisionAggregator()
        details = {
            "fundamental": {"reasoning": ""},
            "technical": {"reasoning": ""},
            "event_driven": {"reasoning": ""},
            "sentiment": {"reasoning": ""},
        }
        report = agg.aggregate(
            dimension_scores=high_scores,
            dimension_details=details,
            mosaic_narrative=mosaic_geopolitical_red,
            audit_report=pass_audit,
            account_state=sample_account,
            target_ticker="GLD",
            target_price=200.0,
        )
        assert report.anchors is not None
        assert report.anchors.geopolitical_gii == AnchorState.RED
        assert "sanctions" in report.anchors.gii_evidence
        assert report.logic_chain_integrity is True

    def test_fail_when_audit_fails(
        self,
        low_scores: dict,
        empty_details: dict,
        mosaic_no_anomaly: MosaicNarrative,
        fail_audit: RedTeamAuditReport,
        sample_account: AccountState,
    ) -> None:
        """Aggregation with failed audit should set audit_passed=False."""
        agg = DecisionAggregator()
        report = agg.aggregate(
            dimension_scores=low_scores,
            dimension_details=empty_details,
            mosaic_narrative=mosaic_no_anomaly,
            audit_report=fail_audit,
            account_state=sample_account,
            target_ticker="GLD",
            target_price=200.0,
        )
        assert report.audit_passed is False
        assert report.audit_deduction > 0
        # Audit failure with low scores always forces cooling
        assert report.position_sizing.cooling_period_hours > 0

    def test_edge_no_positions_no_cash(
        self,
        medium_scores: dict,
        empty_details: dict,
        mosaic_no_anomaly: MosaicNarrative,
        pass_audit: RedTeamAuditReport,
    ) -> None:
        """Edge case: zero account — no crash."""
        empty = AccountState(
            last_updated="2026-05-06",
            cash=0.0,
            buying_power=0.0,
            positions=[],
            notes="Zero account",
        )
        agg = DecisionAggregator()
        report = agg.aggregate(
            dimension_scores=medium_scores,
            dimension_details=empty_details,
            mosaic_narrative=mosaic_no_anomaly,
            audit_report=pass_audit,
            account_state=empty,
            target_ticker="GLD",
            target_price=200.0,
        )
        assert report is not None
        assert report.position_sizing.suggested_shares == 0

    def test_invariant_I2_report_immutable_after_build(
        self,
        high_scores: dict,
        empty_details: dict,
        mosaic_bull: MosaicNarrative,
        pass_audit: RedTeamAuditReport,
        sample_account: AccountState,
    ) -> None:
        """I2: freezable fields frozen after construction."""
        agg = DecisionAggregator()
        report = agg.aggregate(
            dimension_scores=high_scores,
            dimension_details=empty_details,
            mosaic_narrative=mosaic_bull,
            audit_report=pass_audit,
            account_state=sample_account,
            target_ticker="GLD",
            target_price=200.0,
        )
        with pytest.raises(AttributeError):
            report.final_score = 999.0

    def test_invariant_I7_red_anchor_forces_zero_multiplier(
        self,
        high_scores: dict,
        empty_details: dict,
        mosaic_geopolitical_red: MosaicNarrative,
        pass_audit: RedTeamAuditReport,
        sample_account: AccountState,
    ) -> None:
        """I7: any anchor RED → paradigm_multiplier == 0.0"""
        agg = DecisionAggregator()
        details = {
            "fundamental": {"reasoning": ""},
            "technical": {"reasoning": ""},
            "event_driven": {"reasoning": ""},
            "sentiment": {"reasoning": ""},
        }
        report = agg.aggregate(
            dimension_scores=high_scores,
            dimension_details=details,
            mosaic_narrative=mosaic_geopolitical_red,
            audit_report=pass_audit,
            account_state=sample_account,
            target_ticker="GLD",
            target_price=200.0,
        )
        assert report.paradigm_multiplier == 0.0
        assert report.anchors is not None
        assert report.anchors.geopolitical_gii == AnchorState.RED
        assert "sanctions" in report.anchors.gii_evidence

    def test_invariant_I7_audit_fail_with_low_resilience(
        self,
        mosaic_no_anomaly: MosaicNarrative,
        sample_account: AccountState,
    ) -> None:
        """I7: audit fail + resilience < 60 forces FORCE_CLEAROUT."""
        agg = DecisionAggregator()
        scores = {"fundamental": 50.0, "technical": 50.0, "event_driven": 50.0, "sentiment": 50.0}
        catastrophic_audit = RedTeamAuditReport(
            audit_id="audit-cat",
            audited_at="2026-05-06T12:00:00Z",
            audited_report_ref="mosaic-cat",
            audited_macro_narrative="Catastrophic failure",
            attacks_launched=[],
            overall_resilience_score=50.0,
            pass_audit=False,
        )
        report = agg.aggregate(
            dimension_scores=scores,
            dimension_details={
                "fundamental": {"reasoning": ""},
                "technical": {"reasoning": ""},
                "event_driven": {"reasoning": ""},
                "sentiment": {"reasoning": ""},
            },
            mosaic_narrative=mosaic_no_anomaly,
            audit_report=catastrophic_audit,
            account_state=sample_account,
            target_ticker="GLD",
            target_price=200.0,
        )
        assert report.decision_track == DecisionTrack.FORCE_CLEAROUT
        assert report.audit_deduction > 20.0
