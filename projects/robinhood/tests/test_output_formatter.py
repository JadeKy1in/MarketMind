"""
test_output_formatter.py -- Phase 7.6 / 7.7 test suite for ReportGenerator (Layer 4)

Test coverage:
  - All seven required report sections present
  - Conditional rendering (null fields, empty lists)
  - ASCII-only enforcement (no emoji, no decorative characters)
  - Edge cases: missing position sizing, empty resonance, empty safety valves
  - Integration: build a full DecisionReport and verify the complete output
"""

from __future__ import annotations

import re
import uuid

import pytest

from src.paradigm_anchors import AnchorState, ThreeAnchors
from src.decision_aggregator import (
    DecisionReport,
    DecisionTrack,
    PositionSizing,
    ResonanceMatrix,
)
from src.output_formatter import ReportGenerator


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def generator() -> ReportGenerator:
    """A fresh ReportGenerator for each test."""
    return ReportGenerator()


@pytest.fixture
def sample_anchors() -> ThreeAnchors:
    """Standard all-GREEN macro anchors."""
    return ThreeAnchors(
        fiscal_credibility=AnchorState.GREEN,
        geopolitical_gii=AnchorState.GREEN,
        reflexivity_rac=AnchorState.GREEN,
        fiscal_evidence="No fiscal credibility concerns detected.",
        gii_evidence="No geopolitical instability detected.",
        rac_evidence="No reflexivity anomalies detected.",
    )


@pytest.fixture
def yellow_anchors() -> ThreeAnchors:
    """One YELLOW anchor to test conditional rendering."""
    return ThreeAnchors(
        fiscal_credibility=AnchorState.GREEN,
        geopolitical_gii=AnchorState.YELLOW,
        reflexivity_rac=AnchorState.GREEN,
        fiscal_evidence="No fiscal credibility concerns detected.",
        gii_evidence="YELLOW triggered by keywords: tariff, trade friction",
        rac_evidence="No reflexivity anomalies detected.",
    )


@pytest.fixture
def full_resonance() -> ResonanceMatrix:
    """All dimensions aligned -- high resonance score."""
    return ResonanceMatrix(
        dimensions_resonating=5,
        resonance_pairs=[
            "fundamental<->technical",
            "fundamental<->event_driven",
            "fundamental<->sentiment",
            "technical<->event_driven",
            "technical<->sentiment",
        ],
        divergence_pairs=[],
        resonance_threshold_met=True,
        resonance_score=83.3,
    )


@pytest.fixture
def partial_resonance() -> ResonanceMatrix:
    """Some aligned, some diverged -- moderate resonance."""
    return ResonanceMatrix(
        dimensions_resonating=2,
        resonance_pairs=[
            "fundamental<->technical",
        ],
        divergence_pairs=[
            "event_driven<->sentiment",
        ],
        resonance_threshold_met=False,
        resonance_score=50.0,
    )


@pytest.fixture
def full_buy_report(
    sample_anchors: ThreeAnchors,
    full_resonance: ResonanceMatrix,
) -> DecisionReport:
    """A fully populated FULL_BUY report with all fields set."""
    return DecisionReport(
        report_id=str(uuid.uuid4()),
        generated_at="2026-05-06T12:00:00Z",
        target_ticker="IAU",
        raw_scores={
            "fundamental": 92.0,
            "technical": 88.0,
            "event_driven": 95.0,
            "sentiment": 85.0,
        },
        audit_deduction=0.0,
        paradigm_multiplier=1.0,
        final_score=91.50,
        decision_track=DecisionTrack.FULL_BUY,
        position_sizing=PositionSizing(
            direction="BUY",
            suggested_shares=1000,
            max_shares=1200,
            percent_of_buying_power=38.00,
            risk_capital_at_stake=95_000.00,
            cooling_period_hours=0,
        ),
        resonance=full_resonance,
        logic_chain_integrity=True,
        audit_passed=True,
        mosaic_narrative_id="mosaic-bull-001",
        consensus_fragility=15.0,
        anchors=sample_anchors,
        safety_valves_triggered=[],
        execution_disclaimer=(
            "THEORETICAL DECISION ONLY. NO BROKERAGE API CONNECTED. "
            "EXECUTION MUST BE PERFORMED MANUALLY BY ACCOUNT HOLDER."
        ),
    )


@pytest.fixture
def scaled_sell_report(
    yellow_anchors: ThreeAnchors,
    partial_resonance: ResonanceMatrix,
) -> DecisionReport:
    """A SCALED_SELL report with audit deduction, yellow anchor, safety valves."""
    return DecisionReport(
        report_id=str(uuid.uuid4()),
        generated_at="2026-05-06T14:30:00Z",
        target_ticker="TLT",
        raw_scores={
            "fundamental": 35.0,
            "technical": 42.0,
            "event_driven": 28.0,
            "sentiment": 45.0,
        },
        audit_deduction=15.00,
        paradigm_multiplier=0.85,
        final_score=28.65,
        decision_track=DecisionTrack.SCALED_SELL,
        position_sizing=PositionSizing(
            direction="SELL",
            suggested_shares=200,
            max_shares=400,
            percent_of_buying_power=12.00,
            risk_capital_at_stake=18_000.00,
            cooling_period_hours=0,
        ),
        resonance=partial_resonance,
        logic_chain_integrity=False,
        audit_passed=False,
        mosaic_narrative_id="mosaic-bear-002",
        consensus_fragility=72.0,
        anchors=yellow_anchors,
        safety_valves_triggered=[
            "Valve-1: buying_power_cap_40pct",
            "Valve-5: yellow_anchor_85pct_cap",
        ],
        execution_disclaimer=(
            "THEORETICAL DECISION ONLY. NO BROKERAGE API CONNECTED. "
            "EXECUTION MUST BE PERFORMED MANUALLY BY ACCOUNT HOLDER."
        ),
    )


@pytest.fixture
def no_positioning_report(
    sample_anchors: ThreeAnchors,
) -> DecisionReport:
    """A report with position_sizing = None to test null handling."""
    return DecisionReport(
        report_id=str(uuid.uuid4()),
        generated_at="2026-05-06T08:00:00Z",
        target_ticker="GLD",
        raw_scores={},
        audit_deduction=0.0,
        paradigm_multiplier=1.0,
        final_score=0.0,
        decision_track=DecisionTrack.OBSERVE_WAIT,
        position_sizing=None,
        resonance=None,
        logic_chain_integrity=False,
        audit_passed=False,
        mosaic_narrative_id="mosaic-empty-003",
        consensus_fragility=50.0,
        anchors=None,
        safety_valves_triggered=[],
        execution_disclaimer=(
            "THEORETICAL DECISION ONLY. NO BROKERAGE API CONNECTED. "
            "EXECUTION MUST BE PERFORMED MANUALLY BY ACCOUNT HOLDER."
        ),
    )


@pytest.fixture
def clearout_report(sample_anchors: ThreeAnchors) -> DecisionReport:
    """A FORCE_CLEAROUT report with cooling period."""
    return DecisionReport(
        report_id=str(uuid.uuid4()),
        generated_at="2026-05-06T18:00:00Z",
        target_ticker="SPY",
        raw_scores={
            "fundamental": 15.0,
            "technical": 20.0,
            "event_driven": 10.0,
            "sentiment": 25.0,
        },
        audit_deduction=30.00,
        paradigm_multiplier=0.0,
        final_score=0.0,
        decision_track=DecisionTrack.FORCE_CLEAROUT,
        position_sizing=PositionSizing(
            direction="CLEAROUT",
            suggested_shares=0,
            max_shares=0,
            percent_of_buying_power=0.0,
            risk_capital_at_stake=0.0,
            cooling_period_hours=38,
        ),
        resonance=ResonanceMatrix(
            dimensions_resonating=0,
            resonance_pairs=[],
            divergence_pairs=["fundamental<->technical",
                              "event_driven<->sentiment"],
            resonance_threshold_met=False,
            resonance_score=0.0,
        ),
        logic_chain_integrity=False,
        audit_passed=False,
        mosaic_narrative_id="mosaic-clear-004",
        consensus_fragility=90.0,
        anchors=sample_anchors,
        safety_valves_triggered=["Valve-4: force_clearout_cooling_38h"],
        execution_disclaimer=(
            "THEORETICAL DECISION ONLY. NO BROKERAGE API CONNECTED. "
            "EXECUTION MUST BE PERFORMED MANUALLY BY ACCOUNT HOLDER."
        ),
    )


# ======================================================================
# Tests: Report structure
# ======================================================================


class TestReportGenerator:
    """Core report generation tests."""

    def test_generate_returns_string(self, generator: ReportGenerator,
                                      full_buy_report: DecisionReport) -> None:
        """generate() returns a non-empty string."""
        md = generator.generate(full_buy_report)
        assert isinstance(md, str)
        assert len(md) > 200

    def test_contains_header(self, generator: ReportGenerator,
                              full_buy_report: DecisionReport) -> None:
        """Report contains EXECUTION REPORT header with ID, timestamp, ticker."""
        md = generator.generate(full_buy_report)
        assert "# EXECUTION REPORT" in md
        assert full_buy_report.report_id in md
        assert "2026-05-06T12:00:00Z" in md
        assert "IAU" in md

    def test_contains_execution_conclusion_section(
        self, generator: ReportGenerator, full_buy_report: DecisionReport
    ) -> None:
        """Section 1: EXECUTION CONCLUSION present with decision track."""
        md = generator.generate(full_buy_report)
        assert "## 1. EXECUTION CONCLUSION" in md
        assert "full_buy" in md
        assert "Final Score" in md

    def test_contains_position_sizing_section(
        self, generator: ReportGenerator, full_buy_report: DecisionReport
    ) -> None:
        """Section 2: POSITION SIZING with share details."""
        md = generator.generate(full_buy_report)
        assert "## 2. POSITION SIZING" in md
        assert "**Direction:** BUY" in md
        assert "**Suggested Shares:** 1,000" in md

    def test_contains_resonance_trace_section(
        self, generator: ReportGenerator, full_buy_report: DecisionReport
    ) -> None:
        """Section 3: FOUR-DIMENSIONAL RESONANCE SCORING TRACE."""
        md = generator.generate(full_buy_report)
        assert "## 3. FOUR-DIMENSIONAL RESONANCE SCORING TRACE" in md
        assert "**fundamental:** 92.00" in md
        assert "83.3%" in md

    def test_contains_macro_anchor_section(
        self, generator: ReportGenerator, full_buy_report: DecisionReport
    ) -> None:
        """Section 4: MACRO ANCHOR STATUS with all three anchors."""
        md = generator.generate(full_buy_report)
        assert "## 4. MACRO ANCHOR STATUS" in md
        assert "### 4.1 Fiscal Credibility" in md
        assert "### 4.2 Geopolitical GII" in md
        assert "### 4.3 Reflexivity RAC" in md

    def test_contains_red_team_audit_section(
        self, generator: ReportGenerator, full_buy_report: DecisionReport
    ) -> None:
        """Section 5: RED-TEAM AUDIT RESULT."""
        md = generator.generate(full_buy_report)
        assert "## 5. RED-TEAM AUDIT RESULT" in md
        assert "**Audit Passed:** YES" in md

    def test_contains_safety_valves_section(
        self, generator: ReportGenerator, full_buy_report: DecisionReport
    ) -> None:
        """Section 6: SAFETY VALVES TRIGGERED."""
        md = generator.generate(full_buy_report)
        assert "## 6. SAFETY VALVES TRIGGERED" in md

    def test_contains_disclaimer_section(
        self, generator: ReportGenerator, full_buy_report: DecisionReport
    ) -> None:
        """Section 7: DISCLAIMER with the execution disclaimer text."""
        md = generator.generate(full_buy_report)
        assert "## 7. DISCLAIMER" in md
        assert "THEORETICAL DECISION ONLY" in md

    def test_report_starts_with_header(self, generator: ReportGenerator,
                                        full_buy_report: DecisionReport) -> None:
        """Report begins with the EXECUTION REPORT heading."""
        md = generator.generate(full_buy_report)
        assert md.startswith("# EXECUTION REPORT")

    def test_sections_in_order(self, generator: ReportGenerator,
                                full_buy_report: DecisionReport) -> None:
        """All seven sections appear in correct numeric order."""
        md = generator.generate(full_buy_report)
        sections = [
            "1. EXECUTION CONCLUSION",
            "2. POSITION SIZING",
            "3. FOUR-DIMENSIONAL RESONANCE SCORING TRACE",
            "4. MACRO ANCHOR STATUS",
            "5. RED-TEAM AUDIT RESULT",
            "6. SAFETY VALVES TRIGGERED",
            "7. DISCLAIMER",
        ]
        positions = [md.index(s) for s in sections]
        assert positions == sorted(positions), (
            f"Section order is wrong: {positions}"
        )


# ======================================================================
# Tests: Conditional rendering (null / empty edge cases)
# ======================================================================


class TestReportGeneratorEdgeCases:
    """Edge case and null-handling tests."""

    def test_no_position_sizing_handled(
        self, generator: ReportGenerator, no_positioning_report: DecisionReport
    ) -> None:
        """When position_sizing is None, display fallback text."""
        md = generator.generate(no_positioning_report)
        assert "No position sizing data available." in md

    def test_no_anchors_handled(
        self, generator: ReportGenerator, no_positioning_report: DecisionReport
    ) -> None:
        """When anchors is None, display fallback text."""
        md = generator.generate(no_positioning_report)
        assert "No macro anchor data available." in md

    def test_no_resonance_handled(
        self, generator: ReportGenerator, no_positioning_report: DecisionReport
    ) -> None:
        """When resonance is None, skip cross-verification sub-section."""
        md = generator.generate(no_positioning_report)
        assert "### 3.1 Raw Dimension Scores" in md
        assert "### 3.2 Score Synthesis" in md
        # No subsection 3.3 since resonance is None
        assert "### 3.3" not in md

    def test_no_raw_scores_handled(
        self, generator: ReportGenerator, no_positioning_report: DecisionReport
    ) -> None:
        """When raw_scores is empty, display fallback."""
        md = generator.generate(no_positioning_report)
        assert "No raw dimension scores recorded." in md

    def test_empty_safety_valves(
        self, generator: ReportGenerator, full_buy_report: DecisionReport
    ) -> None:
        """When no safety valves triggered, display the fallback message."""
        md = generator.generate(full_buy_report)
        assert "No safety valves triggered." in md

    def test_multiple_safety_valves(
        self, generator: ReportGenerator, scaled_sell_report: DecisionReport
    ) -> None:
        """When safety valves are triggered, each is listed."""
        md = generator.generate(scaled_sell_report)
        assert "**Valve 1:** Valve-1: buying_power_cap_40pct" in md
        assert "**Valve 2:** Valve-5: yellow_anchor_85pct_cap" in md

    def test_observe_wait_track(
        self, generator: ReportGenerator, no_positioning_report: DecisionReport
    ) -> None:
        """OBSERVE_WAIT track shows HOLD conclusion."""
        md = generator.generate(no_positioning_report)
        assert "observe_wait" in md
        assert "HOLD" in md

    def test_sell_track(
        self, generator: ReportGenerator, scaled_sell_report: DecisionReport
    ) -> None:
        """SCALED_SELL track shows SELL conclusion."""
        md = generator.generate(scaled_sell_report)
        assert "scaled_sell" in md
        assert "SELL" in md

    def test_yellow_anchor_rendering(
        self, generator: ReportGenerator, scaled_sell_report: DecisionReport
    ) -> None:
        """YELLOW anchor state shown correctly with evidence."""
        md = generator.generate(scaled_sell_report)
        assert "YELLOW" in md
        assert "Geopolitical GII" in md
        assert "tariff" in md


# ======================================================================
# Tests: ASCII-only enforcement
# ======================================================================


class TestAsciiOnly:
    """Verifies no non-ASCII characters leak into generated reports."""

    _NON_ASCII_RE = re.compile(r"[^\x20-\x7E\n\t]")

    def test_full_buy_ascii_only(
        self, generator: ReportGenerator, full_buy_report: DecisionReport
    ) -> None:
        """Full BUY report contains only ASCII printable characters."""
        md = generator.generate(full_buy_report)
        non_ascii = self._NON_ASCII_RE.findall(md)
        assert len(non_ascii) == 0, (
            f"Found {len(non_ascii)} non-ASCII characters: {non_ascii[:10]}"
        )

    def test_scaled_sell_ascii_only(
        self, generator: ReportGenerator, scaled_sell_report: DecisionReport
    ) -> None:
        """SCALED_SELL report contains only ASCII printable characters."""
        md = generator.generate(scaled_sell_report)
        non_ascii = self._NON_ASCII_RE.findall(md)
        assert len(non_ascii) == 0, (
            f"Found {len(non_ascii)} non-ASCII characters: {non_ascii[:10]}"
        )

    def test_no_positioning_report_ascii_only(
        self, generator: ReportGenerator, no_positioning_report: DecisionReport
    ) -> None:
        """Null-filled report still enforces ASCII-only."""
        md = generator.generate(no_positioning_report)
        non_ascii = self._NON_ASCII_RE.findall(md)
        assert len(non_ascii) == 0, (
            f"Found {len(non_ascii)} non-ASCII characters: {non_ascii[:10]}"
        )

    def test_no_emoji_in_report(
        self, generator: ReportGenerator, full_buy_report: DecisionReport
    ) -> None:
        """Zero emoji characters present in the output."""
        md = generator.generate(full_buy_report)
        # Emoji range detection via high surrogate pairs
        emoji_pattern = re.compile(
            "[\U0001F600-\U0001F64F"  # emoticons
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F680-\U0001F6FF"  # transport & map
            "\U0001F1E0-\U0001F1FF"  # flags
            "\U00002702-\U000027B0"  # dingbats
            "\U000024C2-\U0001F251"  # enclosed
            "]+",
            flags=re.UNICODE,
        )
        emojis = emoji_pattern.findall(md)
        assert len(emojis) == 0, f"Found emoji characters: {emojis[:5]}"


# ======================================================================
# Tests: Content accuracy
# ======================================================================


class TestContentAccuracy:
    """Verifies specific field values render correctly in the output."""

    def test_score_values_appear(
        self, generator: ReportGenerator, full_buy_report: DecisionReport
    ) -> None:
        """Raw scores, final score, and deduction are all present."""
        md = generator.generate(full_buy_report)
        assert "91.50" in md
        assert "0.00" in md
        assert "1.00" in md

    def test_audit_deduction_appears(
        self, generator: ReportGenerator, scaled_sell_report: DecisionReport
    ) -> None:
        """Audit deduction renders correctly."""
        md = generator.generate(scaled_sell_report)
        assert "15.00" in md
        assert "**Audit Passed:** NO" in md

    def test_fragility_value(
        self, generator: ReportGenerator, scaled_sell_report: DecisionReport
    ) -> None:
        """Consensus fragility renders."""
        md = generator.generate(scaled_sell_report)
        assert "72.00" in md

    def test_logic_chain_integrity(
        self, generator: ReportGenerator, full_buy_report: DecisionReport
    ) -> None:
        """Logic chain integrity PASS/FAIL rendering."""
        md = generator.generate(full_buy_report)
        assert "PASS" in md

    def test_logic_chain_integrity_fail(
        self, generator: ReportGenerator, scaled_sell_report: DecisionReport
    ) -> None:
        """Logic chain integrity FAIL rendering."""
        md = generator.generate(scaled_sell_report)
        assert "FAIL" in md

    def test_cooling_period(
        self, generator: ReportGenerator, clearout_report: DecisionReport
    ) -> None:
        """Cooling period hours render correctly."""
        md = generator.generate(clearout_report)
        assert "38 hours" in md
        assert "CLEAROUT" in md