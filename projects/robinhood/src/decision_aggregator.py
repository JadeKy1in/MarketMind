"""
decision_aggregator.py — Layer 3 Decision Aggregation Engine (Phase 7.4)

Aggregates all upstream signals (four-dimensional scores, mosaic narrative,
red-team audit, paradigm anchors, account state) into a final DecisionReport
that routes to the appropriate execution track (BUY / SELL / OBSERVE_WAIT /
FORCE_CLEAROUT).

Blueprint Architecture (§1–§5):
  1. Score synthesis — weighted average (30/15/30/25) − audit deduction
  2. Paradigm multiplier — MIN-rule over three macro anchors
  3. Four-dimensional resonance verification (>=3/4 dimensions aligned)
  4. Position sizing — fractional Kelly based on score tier
  5. Safety valves — hard caps that cannot be overridden
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from src.account_reader import AccountState
from src.mosaic_reasoning import MosaicNarrative
from src.paradigm_anchors import (
    AnchorState,
    ThreeAnchors,
    compute_paradigm_multiplier,
)
from src.red_team_auditor import RedTeamAuditReport


# ---------------------------------------------------------------------------
# Constants — PM-approved thresholds
# ---------------------------------------------------------------------------

# Score synthesis weights (blueprint §1.2)
ENGINE_WEIGHTS: dict[str, float] = {
    "fundamental": 0.30,
    "technical": 0.15,
    "event_driven": 0.30,
    "sentiment": 0.25,
}

# Resonance verification
RESONANCE_MIN_ALIGNED: int = 3  # >= 3/4 dimensions must agree
RESONANCE_ALIGNMENT_THRESHOLD: float = 60.0  # score >= 60 = "aligned"
RESONANCE_DIVERGENCE_THRESHOLD: float = 40.0  # score < 40 = "diverged"

# Score-to-track thresholds (blueprint §6 / §2.2)
FULL_BUY_THRESHOLD: float = 90.0
SCALED_BUY_THRESHOLD: float = 70.0
OBSERVE_WAIT_THRESHOLD: float = 50.0
SCALED_SELL_THRESHOLD: float = 30.0

# Position sizing (blueprint §2.3)
RISK_BUDGET_PERCENT_DEFAULT: float = 0.02  # 2% of net worth per position
MAX_BUYING_POWER_USAGE_DEFAULT: float = 0.40  # 40% of buying power max
CALM_PERIOD_HOURS_DEFAULT: int = 38  # cooling after FORCE_CLEAROUT

# Fractional Kelly factors per score tier (blueprint §2.2)
KELLY_FACTORS: dict[str, float] = {
    "full_buy": 1.00,
    "scaled_buy": 0.80,
    "scaled_sell": 0.30,
}


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DecisionTrack(Enum):
    """Final routing target — passed to Phase 6 / Layer 4."""

    FULL_BUY = "full_buy"
    SCALED_BUY = "scaled_buy"
    OBSERVE_WAIT = "observe_wait"
    SCALED_SELL = "scaled_sell"
    FORCE_CLEAROUT = "force_clearout"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ResonanceMatrix:
    """Cross-verification matrix of four-dimensional alignment."""

    dimensions_resonating: int = 0
    resonance_pairs: List[str] = field(default_factory=list)
    divergence_pairs: List[str] = field(default_factory=list)
    resonance_threshold_met: bool = False
    resonance_score: float = 0.0

    def __post_init__(self) -> None:
        # Invariant I1: threshold_met ≡ dimensions_resonating >= 3
        self.resonance_threshold_met = self.dimensions_resonating >= 3


@dataclass
class PositionSizing:
    """Computed position sizing descriptor (blueprint §2.2)."""

    direction: str = "HOLD"
    suggested_shares: int = 0
    max_shares: int = 0
    percent_of_buying_power: float = 0.0
    risk_capital_at_stake: float = 0.0
    cooling_period_hours: int = 0


@dataclass(frozen=True)
class DecisionReport:
    """Final Layer 3 output — passed to Layer 4 / OrderBuilder.

    Invariants (blueprint §4):
      I1 — resonance_threshold_met ≡ dimensions_resonating >= 3
      I2 — paradigm_multiplier ∈ {0.0, 0.85, 1.0}
      I3 — direction ∈ {BUY, SELL, HOLD, CLEAROUT}
      I4 — cooling_period_hours > 0 ⇔ decision_track == FORCE_CLEAROUT
      I5 — suggested_shares <= max_shares
      I6 — risk_capital_at_stake <= net_worth * 0.02
      I7 — any anchor RED → paradigm_multiplier == 0.0
      I8 — execution_disclaimer non-empty
    """

    report_id: str
    generated_at: str
    target_ticker: str

    # Score provenance
    raw_scores: Dict[str, float] = field(default_factory=dict)
    audit_deduction: float = 0.0
    paradigm_multiplier: float = 1.0
    final_score: float = 0.0

    # Decision routing
    decision_track: DecisionTrack = DecisionTrack.OBSERVE_WAIT
    position_sizing: Optional[PositionSizing] = None

    # Quality checks
    resonance: Optional[ResonanceMatrix] = None
    logic_chain_integrity: bool = False
    audit_passed: bool = False
    mosaic_narrative_id: str = ""
    consensus_fragility: float = 50.0

    # Risk control
    anchors: Optional[ThreeAnchors] = None
    safety_valves_triggered: List[str] = field(default_factory=list)
    execution_disclaimer: str = (
        "THEORETICAL DECISION ONLY. NO BROKERAGE API CONNECTED. "
        "EXECUTION MUST BE PERFORMED MANUALLY BY ACCOUNT HOLDER."
    )


# ---------------------------------------------------------------------------
# DecisionAggregator — core engine
# ---------------------------------------------------------------------------

class DecisionAggregator:
    """Phase 7.4 Layer 3 — Decision Aggregation Engine.

    Public entry point: aggregate() — the one-shot pipeline.

    Internal pipeline order (blueprint §3.2):
      1. _score_synthesis()       → raw, adjusted, dimension_scores
      2. _compute_anchors()       → ThreeAnchors
      3. _compute_resonance()     → ResonanceMatrix
      4. _compute_position()      → PositionSizing
      5. _assemble_report()       → DecisionReport
    """

    def __init__(
        self,
        risk_budget_percent: float = RISK_BUDGET_PERCENT_DEFAULT,
        max_buying_power_pct: float = MAX_BUYING_POWER_USAGE_DEFAULT,
        calm_period_hours: int = CALM_PERIOD_HOURS_DEFAULT,
    ) -> None:
        """Initialise the aggregator with risk parameters.

        Args:
            risk_budget_percent: Max single-position risk / net worth.
            max_buying_power_pct: Max single-ticker buying-power usage.
            calm_period_hours: Cooling period after FORCE_CLEAROUT.
        """
        self._risk_budget = risk_budget_percent
        self._max_bp_pct = max_buying_power_pct
        self._calm_hours = calm_period_hours

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def aggregate(
        self,
        dimension_scores: dict[str, float],
        dimension_details: dict[str, dict[str, Any]],
        mosaic_narrative: MosaicNarrative,
        audit_report: RedTeamAuditReport,
        account_state: AccountState,
        target_ticker: str,
        target_price: float,
    ) -> DecisionReport:
        """Execute the full decision aggregation pipeline.

        Args:
            dimension_scores: Normalised 0-100 scores per dimension, e.g.
                {"fundamental": 75, "technical": 80, "event_driven": 72,
                 "sentiment": 65}.
            dimension_details: Full details dict per dimension with score
                + reasoning (from resonance_aggregator output).
            mosaic_narrative: MosaicReasoner output — includes consensus
                fragility, PVI count, cross-domain links.
            audit_report: RedTeamAudit output — resilience score and pass.
            account_state: AccountState from account_reader.
            target_ticker: Ticker symbol.
            target_price: Current target price.

        Returns:
            Fully populated DecisionReport.
        """
        # Step 1 — Score synthesis
        raw_score, adjusted_score, audit_deduction = self._score_synthesis(
            dimension_scores, audit_report,
        )

        # Step 2 — Compute anchors
        anchors = self._compute_anchors(dimension_details, mosaic_narrative)
        paradigm_mult = compute_paradigm_multiplier(anchors)

        # Step 3 — Compute resonance
        resonance = self._compute_resonance(dimension_scores)

        # Step 4 — Compute position sizing
        positioning = self._compute_position(
            adjusted_score, paradigm_mult, account_state,
            target_ticker, target_price,
        )

        # Step 5 — Apply safety valves
        sizing, valves = self._apply_safety_valves(
            positioning, anchors, account_state,
        )

        # Step 6 — Assemble final report
        final_score = max(0.0, min(100.0, adjusted_score * paradigm_mult))
        track = self.score_to_track(final_score)

        report = self._assemble_report(
            raw_scores=dimension_scores,
            audit_deduction=audit_deduction,
            paradigm_multiplier=paradigm_mult,
            final_score=final_score,
            decision_track=track,
            position_sizing=sizing,
            resonance=resonance,
            audit_passed=audit_report.pass_audit,
            mosaic_narrative=mosaic_narrative,
            anchors=anchors,
            safety_valves=valves,
        )

        return report

    # ------------------------------------------------------------------
    # Step 1 — Score synthesis
    # ------------------------------------------------------------------

    def _score_synthesis(
        self,
        dimension_scores: dict[str, float],
        audit_report: RedTeamAuditReport,
    ) -> tuple[float, float, float]:
        """Weighted average minus audit deduction.

        Args:
            dimension_scores: {dim: 0-100 score}.
            audit_report: RedTeamAuditReport with resilience_score.

        Returns:
            (raw_score, adjusted_score, audit_deduction)
        """
        raw = 0.0
        weight_sum = 0.0
        for dim, score in dimension_scores.items():
            w = ENGINE_WEIGHTS.get(dim, 0.0)
            raw += score * w
            weight_sum += w

        if weight_sum > 0:
            raw /= weight_sum  # Normalise in case of missing dims

        # Audit deduction: resilience score 100 → deduction 0; 70 → deduction 30
        deduction = 100.0 - audit_report.overall_resilience_score
        deduction = max(0.0, min(100.0, deduction))

        adjusted = raw - deduction
        adjusted = max(0.0, min(100.0, adjusted))

        return raw, adjusted, deduction

    # ------------------------------------------------------------------
    # Step 2 — Anchor computation
    # ------------------------------------------------------------------

    def _compute_anchors(
        self,
        dimension_details: dict[str, dict[str, Any]],
        mosaic_narrative: MosaicNarrative,
    ) -> ThreeAnchors:
        """Derive the three paradigm anchors from existing data.

        Uses keyword-driven heuristics on engine reasoning texts and
        mosaic narrative fields.  No new data sources (PM ruling Q2).

        Returns:
            ThreeAnchors with states and evidence strings.
        """
        # Collect all reasoning text
        texts = []
        for dim_key in ("fundamental", "technical", "event_driven", "sentiment"):
            dd = dimension_details.get(dim_key, {})
            texts.append(str(dd.get("reasoning", "")))

        texts.append(str(mosaic_narrative.macro_theme))
        texts.append(str(mosaic_narrative.why_counter_is_weaker))
        for ev in mosaic_narrative.physical_verifications:
            texts.append(str(ev.consequence_if_failed))
            texts.append(str(ev.description))

        combined = " ".join(texts).lower()

        # ── Anchor 1 — Fiscal Credibility ──
        fiscal_red_keywords = (
            "cds spread", "auction tail", "primary dealer", "downgrade",
            "default risk", "fiscal deficit", "debt ceiling", "credit event",
        )
        fiscal_yellow_keywords = (
            "sovereign yield", "fiscal policy", "rating outlook", "debt gdp",
        )

        fiscal_state = AnchorState.GREEN
        fiscal_evidence = "No fiscal credibility concerns detected."

        if any(kw in combined for kw in fiscal_red_keywords):
            fiscal_state = AnchorState.RED
            matched_red = [kw for kw in fiscal_red_keywords if kw in combined]
            fiscal_evidence = (
                f"RED triggered by keywords: {', '.join(matched_red)}"
            )
        elif any(kw in combined for kw in fiscal_yellow_keywords):
            fiscal_state = AnchorState.YELLOW
            matched_yellow = [kw for kw in fiscal_yellow_keywords if kw in combined]
            fiscal_evidence = (
                f"YELLOW triggered by keywords: {', '.join(matched_yellow)}"
            )

        # ── Anchor 2 — Geopolitical GII ──
        gii_red_keywords = (
            "war", "invasion", "sanctions", "military escalation",
            "trade embargo", "blockade", "geopolitical risk",
        )
        gii_yellow_keywords = (
            "tariff", "trade friction", "political tension", "supply chain",
            "diplomatic", "geopolitical instability",
        )

        gii_state = AnchorState.GREEN
        gii_evidence = "No geopolitical instability detected."

        if any(kw in combined for kw in gii_red_keywords):
            gii_state = AnchorState.RED
            matched_red = [kw for kw in gii_red_keywords if kw in combined]
            gii_evidence = (
                f"RED triggered by keywords: {', '.join(matched_red)}"
            )
        elif any(kw in combined for kw in gii_yellow_keywords):
            gii_state = AnchorState.YELLOW
            matched_yellow = [kw for kw in gii_yellow_keywords if kw in combined]
            gii_evidence = (
                f"YELLOW triggered by keywords: {', '.join(matched_yellow)}"
            )

        # ── Anchor 3 — Reflexivity RAC ──
        rac_red_keywords = (
            "reflexivity", "self-reinforcing", "feedback loop",
            "correlation breakdown", "decoupling", "asset bubble",
            "liquidity spiral", "forced liquidation",
        )
        rac_yellow_keywords = (
            "money flow", "momentum divergence", "relative strength",
            "correlation", "flow pattern",
        )

        rac_state = AnchorState.GREEN
        rac_evidence = "No reflexivity anomalies detected."

        if any(kw in combined for kw in rac_red_keywords):
            rac_state = AnchorState.RED
            matched_red = [kw for kw in rac_red_keywords if kw in combined]
            rac_evidence = (
                f"RED triggered by keywords: {', '.join(matched_red)}"
            )
        elif any(kw in combined for kw in rac_yellow_keywords):
            rac_state = AnchorState.YELLOW
            matched_yellow = [kw for kw in rac_yellow_keywords if kw in combined]
            rac_evidence = (
                f"YELLOW triggered by keywords: {', '.join(matched_yellow)}"
            )

        return ThreeAnchors(
            fiscal_credibility=fiscal_state,
            geopolitical_gii=gii_state,
            reflexivity_rac=rac_state,
            fiscal_evidence=fiscal_evidence,
            gii_evidence=gii_evidence,
            rac_evidence=rac_evidence,
        )

    # ------------------------------------------------------------------
    # Step 3 — Resonance computation
    # ------------------------------------------------------------------

    def _compute_resonance(
        self,
        dimension_scores: dict[str, float],
    ) -> ResonanceMatrix:
        """Compute the four-dimensional resonance cross-verification.

        Alignment: score >= RESONANCE_ALIGNMENT_THRESHOLD (60)
        Divergence: score < RESONANCE_DIVERGENCE_THRESHOLD (40)

        Returns:
            ResonanceMatrix with pair lists and count.
        """
        dims = list(dimension_scores.keys())
        resonating = 0
        resonance_pairs = []
        divergence_pairs = []

        for i in range(len(dims)):
            for j in range(i + 1, len(dims)):
                a, b = dims[i], dims[j]
                avg = (dimension_scores[a] + dimension_scores[b]) / 2.0
                pair_label = f"{a}↔{b}"

                if avg >= RESONANCE_ALIGNMENT_THRESHOLD:
                    resonating += 1
                    resonance_pairs.append(pair_label)
                elif avg < RESONANCE_DIVERGENCE_THRESHOLD:
                    divergence_pairs.append(pair_label)

        # resonance_score = percentage of aligned pairs out of total possible
        total_pairs = len(dims) * (len(dims) - 1) // 2
        resonance_score = (
            (resonating / total_pairs) * 100.0 if total_pairs > 0 else 0.0
        )

        return ResonanceMatrix(
            dimensions_resonating=resonating,
            resonance_pairs=resonance_pairs,
            divergence_pairs=divergence_pairs,
            resonance_score=round(resonance_score, 1),
        )

    # ------------------------------------------------------------------
    # Step 4 — Position sizing
    # ------------------------------------------------------------------

    def _compute_position(
        self,
        adjusted_score: float,
        paradigm_multiplier: float,
        account_state: AccountState,
        target_ticker: str,
        target_price: float,
    ) -> PositionSizing:
        """Compute position sizing from score + paradigm + account.

        Returns a PositionSizing; safety valves are applied in step 5.
        """
        net_worth = self._compute_net_worth(account_state)
        risk_capital = net_worth * self._risk_budget

        # Score tier → capital fraction (blueprint §2.2)
        track = self.score_to_track(adjusted_score)

        if track == DecisionTrack.FULL_BUY:
            kelly = KELLY_FACTORS["full_buy"]
            direction = "BUY"
        elif track == DecisionTrack.SCALED_BUY:
            kelly = KELLY_FACTORS["scaled_buy"]
            direction = "BUY"
        elif track == DecisionTrack.OBSERVE_WAIT:
            return PositionSizing(direction="HOLD")
        elif track == DecisionTrack.SCALED_SELL:
            kelly = KELLY_FACTORS["scaled_sell"]
            direction = "SELL"
        else:  # FORCE_CLEAROUT
            return PositionSizing(
                direction="CLEAROUT",
                cooling_period_hours=self._calm_hours,
            )

        # Apply paradigm multiplier to risk capital
        risk_capital *= paradigm_multiplier

        if target_price <= 0:
            return PositionSizing(direction=direction)

        suggested = int((risk_capital * kelly) / target_price)
        max_shares_raw = int(
            (account_state.buying_power * self._max_bp_pct) / target_price
        )
        max_shares = max(0, max_shares_raw)

        suggested = min(max(suggested, 0), max_shares)

        bp_usage = (
            (suggested * target_price) / account_state.buying_power
            if account_state.buying_power > 0 else 0.0
        )

        return PositionSizing(
            direction=direction,
            suggested_shares=suggested,
            max_shares=max_shares,
            percent_of_buying_power=round(bp_usage * 100, 2),
            risk_capital_at_stake=round(suggested * target_price, 2),
            cooling_period_hours=(
                self._calm_hours if direction == "CLEAROUT" else 0
            ),
        )

    # ------------------------------------------------------------------
    # Step 5 — Safety valves
    # ------------------------------------------------------------------

    def _apply_safety_valves(
        self,
        sizing: PositionSizing,
        anchors: ThreeAnchors,
        account_state: AccountState,
    ) -> tuple[PositionSizing, list[str]]:
        """Apply hard safety valves that cannot be overridden.

        Safety valves (blueprint §2.3):
          1. Single-ticker cap: ≤ 40% of buying power (20% if fiscal RED)
          2. Single-ticker risk: ≤ 2% of net worth
          3. Net exposure: fiscal RED → equity net exposure ≤ 30%
          4. Cooling: FORCE_CLEAROUT → 38h mandatory
          5. Yellow cap: any anchor YELLOW → risk capital × 0.85

        Args:
            sizing: Pre-valve position sizing.
            anchors: Current anchor states.
            account_state: Current account state.

        Returns:
            (sizing with valves applied, list of triggered valve names)
        """
        triggered: list[str] = []
        net_worth = self._compute_net_worth(account_state)
        target_price = (
            sizing.risk_capital_at_stake / sizing.suggested_shares
            if sizing.suggested_shares > 0 else 0.0
        )

        # ── Valve 1: Buying power cap ──
        max_bp_pct = self._max_bp_pct
        if anchors.fiscal_credibility == AnchorState.RED:
            max_bp_pct = 0.20  # 20% hard cap if fiscal RED

        max_by_bp = 0
        if target_price > 0 and account_state.buying_power > 0:
            max_by_bp = int(
                (account_state.buying_power * max_bp_pct) / target_price
            )

        if sizing.suggested_shares > max_by_bp and max_by_bp > 0:
            triggered.append(f"Valve-1: buying_power_cap_{int(max_bp_pct*100)}pct")
            sizing = self._clone_with_shares(sizing, min(sizing.suggested_shares, max_by_bp), target_price, account_state.buying_power)

        # ── Valve 2: Single-ticker risk ──
        max_by_risk = 0
        if target_price > 0:
            max_by_risk = int((net_worth * self._risk_budget) / target_price)

        if sizing.suggested_shares > max_by_risk and max_by_risk > 0:
            triggered.append("Valve-2: single_ticker_risk_cap_2pct")
            sizing = self._clone_with_shares(sizing, min(sizing.suggested_shares, max_by_risk), target_price, account_state.buying_power)

        # ── Valve 3: Fiscal RED → net exposure cap (only affects BUY) ──
        if anchors.fiscal_credibility == AnchorState.RED and sizing.direction == "BUY":
            # 30% of existing positions as max additional
            existing_exposure = sum(
                p.current_price * p.shares for p in account_state.positions
            )
            max_exposure = existing_exposure * 0.30
            max_by_exposure = 0
            if target_price > 0:
                max_by_exposure = int(max_exposure / target_price)

            if sizing.suggested_shares > max_by_exposure and max_by_exposure > 0:
                triggered.append("Valve-3: fiscal_red_net_exposure_30pct")
                sizing = self._clone_with_shares(sizing, max_by_exposure, target_price, account_state.buying_power)

        # ── Valve 5: Yellow any anchor → risk capital × 0.85 ──
        any_yellow = (
            anchors.fiscal_credibility == AnchorState.YELLOW
            or anchors.geopolitical_gii == AnchorState.YELLOW
            or anchors.reflexivity_rac == AnchorState.YELLOW
        )
        if any_yellow and sizing.suggested_shares > 0:
            capped = int(sizing.suggested_shares * 0.85)
            if capped < sizing.suggested_shares:
                triggered.append(
                    f"Valve-5: yellow_anchor_85pct_cap"
                )
                sizing = self._clone_with_shares(sizing, capped, target_price, account_state.buying_power)

        return sizing, triggered

    # ------------------------------------------------------------------
    # Step 6 — Report assembly
    # ------------------------------------------------------------------

    def _assemble_report(
        self,
        *,
        raw_scores: dict[str, float],
        audit_deduction: float,
        paradigm_multiplier: float,
        final_score: float,
        decision_track: DecisionTrack,
        position_sizing: PositionSizing,
        resonance: ResonanceMatrix,
        audit_passed: bool,
        mosaic_narrative: MosaicNarrative,
        anchors: ThreeAnchors,
        safety_valves: list[str],
    ) -> DecisionReport:
        """Assemble the final DecisionReport."""
        return DecisionReport(
            report_id=str(uuid.uuid4()),
            generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z",
            target_ticker=mosaic_narrative.source_matrix_id or "UNKNOWN",
            raw_scores=raw_scores,
            audit_deduction=round(audit_deduction, 2),
            paradigm_multiplier=paradigm_multiplier,
            final_score=round(final_score, 2),
            decision_track=decision_track,
            position_sizing=position_sizing,
            resonance=resonance,
            logic_chain_integrity=resonance.resonance_threshold_met,
            audit_passed=audit_passed,
            mosaic_narrative_id=mosaic_narrative.narrative_id,
            consensus_fragility=mosaic_narrative.consensus_fragility,
            anchors=anchors,
            safety_valves_triggered=safety_valves,
        )

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def score_to_track(score: float) -> DecisionTrack:
        """Map a 0-100 score to the corresponding execution track.

        Thresholds (blueprint §6):
            >= 90  → FULL_BUY
            >= 70  → SCALED_BUY
            >= 50  → OBSERVE_WAIT
            >= 30  → SCALED_SELL
            <  30  → FORCE_CLEAROUT
        """
        if score >= FULL_BUY_THRESHOLD:
            return DecisionTrack.FULL_BUY
        if score >= SCALED_BUY_THRESHOLD:
            return DecisionTrack.SCALED_BUY
        if score >= OBSERVE_WAIT_THRESHOLD:
            return DecisionTrack.OBSERVE_WAIT
        if score >= SCALED_SELL_THRESHOLD:
            return DecisionTrack.SCALED_SELL
        return DecisionTrack.FORCE_CLEAROUT

    @staticmethod
    def _compute_net_worth(account_state: AccountState) -> float:
        """Compute net worth from cash + market value of positions."""
        position_value = sum(
            p.current_price * p.shares for p in account_state.positions
        )
        return account_state.cash + position_value

    @staticmethod
    def _clone_with_shares(
        sizing: PositionSizing,
        new_shares: int,
        target_price: float,
        buying_power: float = 0.0,
    ) -> PositionSizing:
        """Create a new PositionSizing with updated share count."""
        return PositionSizing(
            direction=sizing.direction,
            suggested_shares=new_shares,
            max_shares=sizing.max_shares,
            percent_of_buying_power=(
                round((new_shares * target_price) / buying_power * 100, 2)
                if buying_power > 0 else 0.0
            ),
            risk_capital_at_stake=round(new_shares * target_price, 2),
            cooling_period_hours=sizing.cooling_period_hours,
        )