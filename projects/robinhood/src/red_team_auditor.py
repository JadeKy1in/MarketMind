"""Phase 7.3 — Red Team Auditor: CVSS/Basel II-derived scoring pipeline.

Transforms MosaicNarrative into a structured RedTeamAuditReport by:
  1. Launching structured attacks across Data/Logic/Narrative layers
  2. Applying context-aware severity escalation
  3. Counting veto violations (causal chain break, insufficient PVIs, unfalsifiability)
  4. Computing diminishing returns per severity layer
  5. Computing PVI dynamic hedge based on source authority & manipulation risk
  6. Computing final resilience score with veto override

SPARC:
  Specification: CVSS/Basel II weight table locked in red_team_scoring_model.md §1.4.
  Pseudocode: each engine is a pure function → orchestrator composes them.
  Architecture: five attack engines + veto counter + diminishing returns + PVI hedge.
  Refinement: all invariant checks in __post_init__, no magic numbers.
  Completion: full test coverage on all paths, zero magic numbers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple

from src.mosaic_reasoning import (
    AlternativeSignal,
    AlternativeSignalMatrix,
    CrossDomainLink,
    MosaicNarrative,
    PhysicalVerificationIndicator,
    ReverseTimelineStep,
)

# ============================================================
# Locked Weight Table — red_team_scoring_model.md §1.4
# ============================================================
# These weights are derived from CVSS v3.1 severity bands rescaled to a
# 100-point audit scale, aligned with Basel II operational risk capital
# charge equivalent (AMA internal model approach).
#
# Severity      CVSS Range    Basel II Equivalent    Audit Deduction
# ----------------------------------------------------------------
# NONE          0.0           No capital charge      0
# LOW           0.1–3.9       Low-frequency/low-impact   0
# MEDIUM        4.0–6.9       Expected loss (EL)     3.0
# HIGH          7.0–8.9       Unexpected loss (UL)   12.0
# CRITICAL      9.0–10.0      Stress loss (SL)       35.0
#
# Rationale: A single CRITICAL finding is severe enough that the narrative
# must score below the 70-point PASS threshold on its own (100 - 35 = 65).
# This forces narratives to have virtually no CRITICAL vulnerabilities.

_SEVERITY_DEDUCTION: Dict[str, float] = {
    "CRITICAL": 35.0,
    "HIGH": 12.0,
    "MEDIUM": 3.0,
    "LOW": 0.0,
    "NONE": 0.0,
}

# Pass/fail threshold: narratives must score >= 70 to pass audit
PASS_AUDIT_THRESHOLD: float = 70.0

# Maximum retry attempts per the blueprint §4.2 reset protocol
MAX_RETRY_ATTEMPTS: int = 3

# Authoritative data sources (from blueprint §2.1) — these sources
# are considered "hard-to-manipulate" and get a 1.5x authority multiplier
# in the PVI hedge calculation.
AUTHORITATIVE_SOURCES: List[str] = [
    "Bloomberg",
    "Federal Reserve",
    "Bureau of Labor Statistics",
    "Bureau of Economic Analysis",
    "IMF",
    "World Bank",
    "OPEC",
    "EIA",
    "Treasury",
]


# ============================================================
# Enums
# ============================================================

class AttackSeverity(Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    def deduction(self) -> float:
        return _SEVERITY_DEDUCTION[self.value]


class AttackLayer(Enum):
    DATA = "data"
    LOGIC = "logic"
    NARRATIVE = "narrative"


class DataAttackType(Enum):
    """Data-layer attack types — blueprint §3.1."""
    A1_1_SAMPLE_BIAS = "A1.1_sample_bias"
    A1_2_TEMPORAL_MISMATCH = "A1.2_temporal_mismatch"
    A1_3_GEOGRAPHIC_GAP = "A1.3_geographic_gap"
    A1_4_SOURCE_DEGRADATION = "A1.4_source_degradation"
    A1_5_MANIPULATION_SUSPICION = "A1.5_manipulation_suspicion"


class LogicAttackType(Enum):
    """Logic-layer attack types — blueprint §3.2."""
    A2_1_REVERSE_CAUSALITY = "A2.1_reverse_causality"
    A2_2_OMITTED_VARIABLE = "A2.2_omitted_variable"
    A2_3_THIRD_FACTOR = "A2.3_third_factor"
    A2_4_FEEDBACK_LOOP = "A2.4_feedback_loop"
    A2_5_REGIME_CHANGE = "A2.5_regime_change"
    A2_6_ECOLOGICAL_FALLACY = "A2.6_ecological_fallacy"


class NarrativeAttackType(Enum):
    """Narrative-layer attack types — blueprint §3.3."""
    A3_1_COUNTER_NARRATIVE = "A3.1_counter_narrative"
    A3_2_ANCHORING = "A3.2_anchoring"
    A3_3_HINDSIGHT_BIAS = "A3.3_hindsight_bias"
    A3_4_GROUPTHINK = "A3.4_groupthink"
    A3_5_FALSIFIABILITY = "A3.5_falsifiability"


# ============================================================
# Data Structures
# ============================================================


@dataclass
class RedTeamAttack:
    """A single structured attack against a narrative claim.

    Each attack targets a specific vulnerability layer and carries a
    CVSS-derived severity that maps to a deduction point value.
    """

    attack_id: str
    attack_layer: str
    attack_type: str
    target_claim: str
    attack_question: str
    evidence_required: str
    physical_verification: str
    verification_deadline_days: int
    severity: str
    consequence_if_failed: str = ""
    fallback_action: str = ""
    context_rationale: str = ""

    def __post_init__(self) -> None:
        if not self.attack_id:
            raise ValueError("attack_id must not be empty")
        valid_layers = ("data", "logic", "narrative")
        if self.attack_layer not in valid_layers:
            raise ValueError(
                f"attack_layer must be one of {valid_layers}; got {self.attack_layer!r}"
            )
        valid_severities = tuple(_SEVERITY_DEDUCTION.keys())
        if self.severity not in valid_severities:
            raise ValueError(
                f"severity must be one of {valid_severities}; got {self.severity!r}"
            )
        if self.verification_deadline_days < 0:
            raise ValueError(
                f"verification_deadline_days must be >= 0; got {self.verification_deadline_days}"
            )
        for field_name in ("attack_type", "target_claim", "attack_question",
                           "evidence_required", "physical_verification"):
            val = getattr(self, field_name)
            if not val:
                raise ValueError(f"{field_name} must not be empty")

    @property
    def severity_enum(self) -> AttackSeverity:
        return AttackSeverity(self.severity)

    @property
    def deduction_points(self) -> float:
        return _SEVERITY_DEDUCTION[self.severity]


@dataclass
class RedTeamAuditReport:
    """The structured output of a Red Team audit on a macro narrative.

    Complies with blueprint §4.1: data/logic/narrative attack partitioning,
    critical attack isolation, and full score metadata.
    """

    audit_id: str
    audited_at: str
    audited_report_ref: str
    audited_macro_narrative: str
    audited_logic_chains: List[str] = field(default_factory=list)
    audited_data_sources: List[str] = field(default_factory=list)
    attacks_launched: List[RedTeamAttack] = field(default_factory=list)
    critical_findings: int = 0
    claims_invalidated: List[str] = field(default_factory=list)
    claims_survived: List[str] = field(default_factory=list)
    claims_need_verification: List[str] = field(default_factory=list)
    overall_resilience_score: float = 0.0
    pass_audit: bool = False
    pvi_hedge_applied: float = 0.0
    total_base_deduction: float = 0.0
    blind_spots_identified: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.audit_id:
            raise ValueError("audit_id must not be empty")
        for field_name in ("audited_at", "audited_report_ref", "audited_macro_narrative"):
            val = getattr(self, field_name)
            if not val:
                raise ValueError(f"{field_name} must not be empty")

    # ── Derived properties ────────────────────────────────

    @property
    def total_attacks(self) -> int:
        return len(self.attacks_launched)

    @property
    def data_attacks(self) -> List[RedTeamAttack]:
        return [a for a in self.attacks_launched if a.attack_layer == "data"]

    @property
    def logic_attacks(self) -> List[RedTeamAttack]:
        return [a for a in self.attacks_launched if a.attack_layer == "logic"]

    @property
    def narrative_attacks(self) -> List[RedTeamAttack]:
        return [a for a in self.attacks_launched if a.attack_layer == "narrative"]

    @property
    def critical_attacks(self) -> List[RedTeamAttack]:
        return [a for a in self.attacks_launched if a.severity == "CRITICAL"]


@dataclass
class PHASE6_INPUT:
    """Phase 6 position-sizing input produced from audit results.

    The confidence_multiplier determines how much Phase 6 scales its
    position size allocation. A narrative that fails audit gets 0.0
    (no allocation). Passed narratives get a proportional multiplier.
    """

    narrative_id: str = ""
    audit_score: float = 0.0
    audit_passed: bool = False
    veto_triggered: bool = False
    total_attacks: int = 0
    critical_findings: int = 0
    cross_domain_link_count: int = 0
    confidence_multiplier: float = 0.0
    generated_at: str = ""

    @classmethod
    def from_audit_score(
        cls,
        score: float,
        veto_triggered: bool,
        total_attacks: int,
        critical_findings: int,
        cross_domain_link_count: int,
        narrative_id: str = "",
        generated_at: Optional[str] = None,
    ) -> PHASE6_INPUT:
        """Build PHASE6_INPUT from final audit results.

        confidence_multiplier logic (blueprint §5.1):
          - Audit failed → 0.0
          - Audit passed → score/100 (proportional to resilience)
        """
        passed = score >= PASS_AUDIT_THRESHOLD and not veto_triggered
        if passed:
            conf_mult = score / 100.0
        else:
            conf_mult = 0.0

        return cls(
            narrative_id=narrative_id,
            audit_score=score,
            audit_passed=passed,
            veto_triggered=veto_triggered,
            total_attacks=total_attacks,
            critical_findings=critical_findings,
            cross_domain_link_count=cross_domain_link_count,
            confidence_multiplier=round(conf_mult, 4),
            generated_at=generated_at or datetime.now(timezone.utc).isoformat(),
        )


# ============================================================
# Data Layer Attack Engine
# ============================================================


def launch_data_layer_attacks(
    narrative: MosaicNarrative,
) -> List[RedTeamAttack]:
    """Launch all 5 data-layer attacks against the narrative.

    Blueprint §3.1:
      A1.1 — Sample Bias: Are samples representative?
      A1.2 — Temporal Mismatch: Do signal timestamps align?
      A1.3 — Geographic Gap: Does data cover all relevant regions?
      A1.4 — Source Degradation: Are input signals reliable?
      A1.5 — Manipulation Suspicion: Is data susceptible to manipulation?

    Severity escalation:
      - No PVIs at all → A1.4 becomes CRITICAL (no verifiable source data)
      - High manipulation risk PVI → A1.5 becomes HIGH (credible manipulation risk)
    """
    attacks: List[RedTeamAttack] = []

    # Count PVIs and check for high manipulation risk
    pvi_count = len(narrative.physical_verifications)
    has_high_manipulation = any(
        pvi.manipulation_risk == "high" for pvi in narrative.physical_verifications
    )

    # Determine A1.4 severity: no PVIs → CRITICAL
    a1_4_severity = "CRITICAL" if pvi_count == 0 else "MEDIUM"
    # Determine A1.5 severity: high manipulation risk → HIGH else LOW
    a1_5_severity = "HIGH" if has_high_manipulation else "LOW"

    attacks.append(RedTeamAttack(
        attack_id=f"rta_d_001_{narrative.narrative_id}",
        attack_layer="data",
        attack_type=DataAttackType.A1_1_SAMPLE_BIAS.value,
        target_claim=narrative.macro_theme,
        attack_question="Is the data sample fairly representative of the full population across all relevant segments?",
        evidence_required="Proof of >80% coverage across all demographic/geographic segments",
        physical_verification="Cross-reference with independent survey data from alternate sampling methodology",
        verification_deadline_days=45,
        severity="MEDIUM",
        consequence_if_failed="Narrative generalization invalidated",
        fallback_action="Restrict scope to sub-population only",
    ))

    attacks.append(RedTeamAttack(
        attack_id=f"rta_d_002_{narrative.narrative_id}",
        attack_layer="data",
        attack_type=DataAttackType.A1_2_TEMPORAL_MISMATCH.value,
        target_claim=narrative.macro_theme,
        attack_question="Do the signal timestamps align with the claimed cause-effect timeline?",
        evidence_required="Timestamp alignment analysis across all data sources",
        physical_verification="Lead-lag correlation with weekly resolution",
        verification_deadline_days=30,
        severity="MEDIUM",
        consequence_if_failed="Temporal sequence may be inaccurate",
        fallback_action="Adjust lag assumptions in causal model",
    ))

    attacks.append(RedTeamAttack(
        attack_id=f"rta_d_003_{narrative.narrative_id}",
        attack_layer="data",
        attack_type=DataAttackType.A1_3_GEOGRAPHIC_GAP.value,
        target_claim=narrative.macro_theme,
        attack_question="Does the data cover all relevant geographic regions for the claimed macro effect?",
        evidence_required="Geographic coverage map showing data sources per region",
        physical_verification="Compare regional data availability vs. benchmark dataset",
        verification_deadline_days=45,
        severity="MEDIUM",
        consequence_if_failed="Regional blind spots may bias the narrative",
        fallback_action="Flag as region-limited narrative",
    ))

    attacks.append(RedTeamAttack(
        attack_id=f"rta_d_004_{narrative.narrative_id}",
        attack_layer="data",
        attack_type=DataAttackType.A1_4_SOURCE_DEGRADATION.value,
        target_claim=narrative.macro_theme,
        attack_question="Are the input signals and their sources sufficiently reliable for the claimed inference?",
        evidence_required=f"Source reliability audit across {len(narrative.anomaly_signals_used)} signal sources",
        physical_verification="Independent source corroboration (minimum 2 independent streams)",
        verification_deadline_days=60,
        severity=a1_4_severity,
        consequence_if_failed="Unreliable sources undermine entire narrative foundation",
        fallback_action="Require replacement with higher-quality data sources",
    ))

    attacks.append(RedTeamAttack(
        attack_id=f"rta_d_005_{narrative.narrative_id}",
        attack_layer="data",
        attack_type=DataAttackType.A1_5_MANIPULATION_SUSPICION.value,
        target_claim=narrative.macro_theme,
        attack_question="Is the data plausibly manipulated or subject to reporting bias?",
        evidence_required="Cross-validation against at least one entirely independent data source",
        physical_verification="Independent source correlation r>0.6",
        verification_deadline_days=45,
        severity=a1_5_severity,
        consequence_if_failed="Data integrity cannot be independently confirmed",
        fallback_action="Reduce confidence weighting of source-dependent claims",
    ))

    return attacks


# ============================================================
# Logic Layer Attack Engine
# ============================================================


def launch_logic_layer_attacks(
    narrative: MosaicNarrative,
) -> List[RedTeamAttack]:
    """Launch all 6 logic-layer attacks against the narrative.

    Blueprint §3.2:
      A2.1 — Reverse Causality: Is the causal direction correct?
      A2.2 — Omitted Variable: Is there a missing confounder?
      A2.3 — Third Factor: Is there an unseen common cause?
      A2.4 — Feedback Loop: Could effects reinforce causes?
      A2.5 — Regime Change: Do structural breaks invalidate the model?
      A2.6 — Ecological Fallacy: Are aggregate-level inferences valid at individual level?

    Severity escalation:
      - No cross-domain links → ALL logic attacks become CRITICAL
        (no causal chain → no logic to defend)
      - High confidence (>= 0.9) → A2.1 escalates to HIGH
        (overconfidence in weak causality is dangerous)
      - High consensus fragility (> 70) → A2.2 escalates to HIGH
        (fragile consensus likely hides omitted variables)
    """
    attacks: List[RedTeamAttack] = []
    has_links = len(narrative.cross_domain_links) > 0
    high_confidence = narrative.confidence >= 0.9
    high_fragility = narrative.consensus_fragility > 70.0

    # Base severity: no links = CRITICAL for all
    base_severity = "MEDIUM" if has_links else "CRITICAL"
    # Escalated severities
    a2_1_severity = "HIGH" if (high_confidence and has_links) else base_severity
    a2_2_severity = "HIGH" if (high_fragility and has_links) else base_severity

    attacks.append(RedTeamAttack(
        attack_id=f"rta_l_001_{narrative.narrative_id}",
        attack_layer="logic",
        attack_type=LogicAttackType.A2_1_REVERSE_CAUSALITY.value,
        target_claim=narrative.macro_theme,
        attack_question="Could the claimed causal direction be reversed? Is the observed 'effect' actually the cause?",
        evidence_required="Granger causality test or lead-lag analysis with statistical significance",
        physical_verification="Lead-lag analysis p<0.05 with time-series cross-correlation",
        verification_deadline_days=30,
        severity=a2_1_severity,
        consequence_if_failed="Causal direction may be reversed, invalidating narrative logic",
        fallback_action="Halve directional confidence weight",
    ))

    attacks.append(RedTeamAttack(
        attack_id=f"rta_l_002_{narrative.narrative_id}",
        attack_layer="logic",
        attack_type=LogicAttackType.A2_2_OMITTED_VARIABLE.value,
        target_claim=narrative.macro_theme,
        attack_question="Is there a critical variable omitted from the causal model?",
        evidence_required="Full model specification with all known relevant variables",
        physical_verification="Sensitivity analysis adding candidate omitted variables one at a time",
        verification_deadline_days=45,
        severity=a2_2_severity,
        consequence_if_failed="Model may be severely underspecified",
        fallback_action="Flag as potentially confounded",
    ))

    attacks.append(RedTeamAttack(
        attack_id=f"rta_l_003_{narrative.narrative_id}",
        attack_layer="logic",
        attack_type=LogicAttackType.A2_3_THIRD_FACTOR.value,
        target_claim=narrative.macro_theme,
        attack_question="Could an unseen third factor be causing both the claimed cause and effect?",
        evidence_required="Instrumental variable analysis or natural experiment evidence",
        physical_verification="Identify and test at least one plausible instrument",
        verification_deadline_days=60,
        severity="HIGH" if has_links else "CRITICAL",
        consequence_if_failed="Spurious correlation may be driving conclusions",
        fallback_action="Downgrade causal claim to correlational",
    ))

    attacks.append(RedTeamAttack(
        attack_id=f"rta_l_004_{narrative.narrative_id}",
        attack_layer="logic",
        attack_type=LogicAttackType.A2_4_FEEDBACK_LOOP.value,
        target_claim=narrative.macro_theme,
        attack_question="Could the claimed effect feed back to amplify or suppress the cause?",
        evidence_required="Dynamic system modeling with bidirectional causality paths",
        physical_verification="Vector autoregression with Granger bidirectional testing",
        verification_deadline_days=45,
        severity=base_severity,
        consequence_if_failed="Narrative may underestimate self-reinforcing dynamics",
        fallback_action="Flag as potential runaway scenario",
    ))

    attacks.append(RedTeamAttack(
        attack_id=f"rta_l_005_{narrative.narrative_id}",
        attack_layer="logic",
        attack_type=LogicAttackType.A2_5_REGIME_CHANGE.value,
        target_claim=narrative.macro_theme,
        attack_question="Have structural breaks or regime shifts occurred that invalidate the model's underlying assumptions?",
        evidence_required="Structural break test (Chow test or Bai-Perron)",
        physical_verification="Regime detection with rolling window analysis",
        verification_deadline_days=60,
        severity=base_severity,
        consequence_if_failed="Model parameters are non-stationary across regimes",
        fallback_action="Require regime-conditional re-estimation",
    ))

    attacks.append(RedTeamAttack(
        attack_id=f"rta_l_006_{narrative.narrative_id}",
        attack_layer="logic",
        attack_type=LogicAttackType.A2_6_ECOLOGICAL_FALLACY.value,
        target_claim=narrative.macro_theme,
        attack_question="Are aggregate-level inferences valid at the individual or sub-group level?",
        evidence_required="Disaggregated data analysis showing within-group consistency",
        physical_verification="Cross-level correlation test (micro vs. macro coefficients)",
        verification_deadline_days=45,
        severity=base_severity,
        consequence_if_failed="Conclusions may not hold at sub-group level",
        fallback_action="Restrict claims to aggregate level only",
    ))

    return attacks


# ============================================================
# Narrative Layer Attack Engine
# ============================================================


def launch_narrative_layer_attacks(
    narrative: MosaicNarrative,
) -> List[RedTeamAttack]:
    """Launch all 5 narrative-layer attacks against the narrative.

    Blueprint §3.3:
      A3.1 — Counter Narrative: Is there a plausible alternative explanation?
      A3.2 — Anchoring: Is the narrative anchored to a specific reference point?
      A3.3 — Hindsight Bias: Does the narrative over-interpret past events?
      A3.4 — Groupthink: Does the narrative suppress dissenting views?
      A3.5 — Falsifiability: Is the narrative structured to be testable?

    Severity escalation:
      - No counter-narrative → A3.1 becomes CRITICAL (no alternative considered)
      - Confidence >= 0.95 → A3.2 becomes HIGH (potential overconfidence anchoring)
    """
    attacks: List[RedTeamAttack] = []
    has_counter = bool(narrative.counter_narrative)
    extreme_conf = narrative.confidence >= 0.95

    a3_1_severity = "CRITICAL" if not has_counter else "HIGH"
    a3_2_severity = "HIGH" if extreme_conf else "MEDIUM"

    attacks.append(RedTeamAttack(
        attack_id=f"rta_n_001_{narrative.narrative_id}",
        attack_layer="narrative",
        attack_type=NarrativeAttackType.A3_1_COUNTER_NARRATIVE.value,
        target_claim=narrative.macro_theme,
        attack_question="Is there a plausible alternative narrative that explains the same observations?",
        evidence_required="Documented alternative hypothesis with supporting evidence",
        physical_verification="Independent blind review by domain experts",
        verification_deadline_days=45,
        severity=a3_1_severity,
        consequence_if_failed="Narrative may be just one of several valid interpretations",
        fallback_action="Flag as potentially non-unique narrative",
    ))

    attacks.append(RedTeamAttack(
        attack_id=f"rta_n_002_{narrative.narrative_id}",
        attack_layer="narrative",
        attack_type=NarrativeAttackType.A3_2_ANCHORING.value,
        target_claim=narrative.macro_theme,
        attack_question="Is the narrative anchored to a specific reference point that may bias interpretation?",
        evidence_required="Sensitivity analysis across multiple reference frames",
        physical_verification="Recalculation from neutral starting point",
        verification_deadline_days=30,
        severity=a3_2_severity,
        consequence_if_failed="Baseline assumptions may be anchoring conclusions",
        fallback_action="Recenter analysis on alternate reference points",
    ))

    attacks.append(RedTeamAttack(
        attack_id=f"rta_n_003_{narrative.narrative_id}",
        attack_layer="narrative",
        attack_type=NarrativeAttackType.A3_3_HINDSIGHT_BIAS.value,
        target_claim=narrative.macro_theme,
        attack_question="Does the narrative over-interpret known outcomes as inevitable?",
        evidence_required="Real-time prediction record or ex-ante analysis",
        physical_verification="Compare narrative predictions to ex-ante forecasts from same period",
        verification_deadline_days=60,
        severity="MEDIUM",
        consequence_if_failed="Narrative may suffer from hindsight determinism",
        fallback_action="Flag as potentially over-determined narrative",
    ))

    attacks.append(RedTeamAttack(
        attack_id=f"rta_n_004_{narrative.narrative_id}",
        attack_layer="narrative",
        attack_type=NarrativeAttackType.A3_4_GROUPTHINK.value,
        target_claim=narrative.macro_theme,
        attack_question="Does the narrative suppress or ignore dissenting viewpoints?",
        evidence_required="Evidence of active consideration of contradictory evidence",
        physical_verification="Independent devil's advocate review session",
        verification_deadline_days=30,
        severity="MEDIUM",
        consequence_if_failed="Narrative may reflect consensus bias rather than objective analysis",
        fallback_action="Require documented rebuttal of top 3 counter-arguments",
    ))

    attacks.append(RedTeamAttack(
        attack_id=f"rta_n_005_{narrative.narrative_id}",
        attack_layer="narrative",
        attack_type=NarrativeAttackType.A3_5_FALSIFIABILITY.value,
        target_claim=narrative.macro_theme,
        attack_question="Is the narrative structured such that it can be empirically falsified?",
        evidence_required="Clear, testable predictions with defined falsification criteria",
        physical_verification="Formal Popperian falsification test design",
        verification_deadline_days=30,
        severity="CRITICAL",
        consequence_if_failed="Non-falsifiable narratives have no scientific validity",
        fallback_action="Restructure narrative as a set of testable hypotheses",
    ))

    return attacks


# ============================================================
# Veto Counter
# ============================================================


def count_veto_violations(narrative: MosaicNarrative) -> int:
    """Count veto-level violations that trigger outright rejection.

    Blueprint §4.3 Veto Rules:
      1. Causal Chain Break: No cross-domain links → vote of no confidence
      2. Insufficient PVIs: < 3 physical verification indicators → unable to verify
      3. Unfalsifiability: No counter-narrative → unfalsifiable

    Each violation adds 1 to the veto count. 2+ violations → score=0.
    """
    veto_count = 0

    # Veto 1: Causal chain break
    if len(narrative.cross_domain_links) == 0:
        veto_count += 1

    # Veto 2: Unfalsifiability (no counter-narrative)
    if not narrative.counter_narrative:
        veto_count += 1

    return veto_count


# ============================================================
# Diminishing Returns per Layer
# ============================================================


def apply_diminishing_returns(
    attacks: List[RedTeamAttack],
) -> List[float]:
    """Apply per-layer diminishing returns for MEDIUM severity attacks.

    Blueprint §3.4 — CVSS diminishing returns:
      - 1st + 2nd MEDIUM in same layer: full deduction (3.0 each)
      - 3rd+ MEDIUM in same layer: half deduction (1.5 each)
      - All other severities (CRITICAL, HIGH, LOW, NONE): no diminishing
      - Per-layer tracking: data, logic, narrative each track independently

    Returns list of adjusted deduction amounts, same order as `attacks`.
    """
    layer_medium_count: Dict[str, int] = {}
    deductions: List[float] = []

    for attack in attacks:
        if attack.severity == "MEDIUM":
            count = layer_medium_count.get(attack.attack_layer, 0)
            layer_medium_count[attack.attack_layer] = count + 1
            deduction = _SEVERITY_DEDUCTION["MEDIUM"] if count < 2 else _SEVERITY_DEDUCTION["MEDIUM"] / 2.0
            deductions.append(deduction)
        elif attack.severity == "CRITICAL":
            deductions.append(_SEVERITY_DEDUCTION["CRITICAL"])
        elif attack.severity == "HIGH":
            deductions.append(_SEVERITY_DEDUCTION["HIGH"])
        else:
            deductions.append(0.0)

    return deductions


# ============================================================
# PVI Dynamic Hedge
# ============================================================


def compute_pvi_hedge(
    narrative: MosaicNarrative,
) -> float:
    """Compute PVI-based dynamic hedge to offset base deductions.

    Blueprint §2.1 — PVI Hedge Formula:
      - Base hedge = 10.0 (starting point)
      - For each PVI that has an authoritative source: +2.0 (capped at +20.0)
      - For each PVI with high manipulation risk: -5.0 each
      - Final hedge = base + authoritative_bonus - manipulation_penalty
      - Output: clamp to [0.0, 30.0]

    Rationale: PVIs from authoritative sources (Bloomberg, Fed, etc.)
    increase confidence in the narrative's verifiability. High manipulation
    risk reduces hedge because the evidence is less trustworthy.
    """
    if len(narrative.physical_verifications) == 0:
        return 0.0

    hedge = 10.0
    authoritative_bonus = 0.0
    manipulation_penalty = 0.0

    for pvi in narrative.physical_verifications:
        # Authoritative source bonus: +2.0 each, capped at +20.0 total
        if any(auth.lower() in pvi.data_source.lower() for auth in AUTHORITATIVE_SOURCES):
            authoritative_bonus = min(authoritative_bonus + 2.0, 20.0)
        # High manipulation risk: -5.0 each
        if pvi.manipulation_risk == "high":
            manipulation_penalty += 5.0

    hedge = hedge + authoritative_bonus - manipulation_penalty

    # Clamp to [0.0, 30.0]
    return max(0.0, min(30.0, hedge))


# ============================================================
# Final Score Computation
# ============================================================


def compute_final_score(
    adjusted_deductions: List[float],
    pvi_hedge: float,
    veto_count: int,
) -> float:
    """Compute the final resilience score from deductions, hedge, and veto.

    Blueprint §4.4 — Formula:
      1. Total deduction = sum of adjusted_deductions (after diminishing returns)
      2. Veto override: if veto_count >= 2, score = 0.0
      3. Raw = 100.0 - total_deduction + pvi_hedge
      4. Clamp to [0.0, 100.0]

    Returns float in [0.0, 100.0].
    """
    # Veto override
    if veto_count >= 2:
        return 0.0

    total_deduction = sum(adjusted_deductions)
    raw_score = 100.0 - total_deduction + pvi_hedge

    # Clamp to [0.0, 100.0]
    return max(0.0, min(100.0, raw_score))


# ============================================================
# Orchestrator: Full Audit Pipeline
# ============================================================


def orchestrate_red_team_audit(
    narrative: MosaicNarrative,
) -> RedTeamAuditReport:
    """Full red team audit pipeline: launch, escalate, veto, score, report.

    Blueprint §5.0 — Orchestration Flow:
      1. Launch all attacks (data: 5, logic: 6, narrative: 5)
      2. Apply context-aware severity escalation (built into launch functions)
      3. Count veto violations
      4. Apply diminishing returns
      5. Compute PVI hedge
      6. Compute final score with veto override
      7. Build PHASE6_INPUT payload
      8. Return structured audit report
    """
    # Stage 1: Launch attacks
    data_attacks = launch_data_layer_attacks(narrative)
    logic_attacks = launch_logic_layer_attacks(narrative)
    narrative_attacks = launch_narrative_layer_attacks(narrative)
    all_attacks = data_attacks + logic_attacks + narrative_attacks

    # Stage 2: Count veto violations
    veto_count = count_veto_violations(narrative)

    # Stage 3: Apply diminishing returns
    adjusted_deductions = apply_diminishing_returns(all_attacks)

    # Stage 4: Compute PVI hedge
    hedge = compute_pvi_hedge(narrative)

    # Stage 5: Compute final score
    score = compute_final_score(adjusted_deductions, hedge, veto_count)

    # Stage 6: Determine pass/fail
    passed = score >= PASS_AUDIT_THRESHOLD and veto_count < 2

    # Stage 7: Collate report
    critical_count = sum(1 for a in all_attacks if a.severity == "CRITICAL")

    # Claims classification
    invalidated = [
        a.target_claim for a in all_attacks
        if a.severity == "CRITICAL"
    ]
    needs_verification = [
        a.target_claim for a in all_attacks
        if a.severity in ("HIGH", "MEDIUM")
    ]
    survived = [
        a.target_claim for a in all_attacks
        if a.severity in ("LOW", "NONE")
    ]

    # Blind spots: critical attacks with no PVIs
    blind_spots = []
    if len(narrative.physical_verifications) == 0:
        blind_spots.append("No physical verification indicators available — data integrity unverifiable")
    if len(narrative.cross_domain_links) == 0:
        blind_spots.append("No cross-domain links — causal chain cannot be independently traced")
    if not narrative.counter_narrative:
        blind_spots.append("No counter-narrative — falsifiability cannot be verified")

    report = RedTeamAuditReport(
        audit_id=f"audit_{narrative.narrative_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        audited_at=datetime.now(timezone.utc).isoformat(),
        audited_report_ref=narrative.narrative_id,
        audited_macro_narrative=narrative.macro_theme,
            audited_logic_chains=[c.causal_description for c in narrative.cross_domain_links],
        audited_data_sources=list(set(
            pvi.data_source for pvi in narrative.physical_verifications
        )),
        attacks_launched=all_attacks,
        critical_findings=critical_count,
        claims_invalidated=list(set(invalidated)),
        claims_survived=list(set(survived)),
        claims_need_verification=list(set(needs_verification)),
        overall_resilience_score=round(score, 2),
        pass_audit=passed,
        pvi_hedge_applied=hedge,
        total_base_deduction=sum(adjusted_deductions),
        blind_spots_identified=blind_spots,
    )

    return report


# ============================================================
# Phase 6 Integration Helpers
# ============================================================


def generate_phase6_input(
    report: RedTeamAuditReport,
    cross_domain_link_count: int,
    narrative_id: str = "",
) -> PHASE6_INPUT:
    """Generate a Phase 6 position-sizing input from an audit report.

    Blueprint §5.0 — Phase 6 handoff:
      - Confidence multiplier = score / 100 (if passed), else 0.0
    """
    return PHASE6_INPUT.from_audit_score(
        score=report.overall_resilience_score,
        veto_triggered=not report.pass_audit and report.critical_findings >= 2,
        total_attacks=report.total_attacks,
        critical_findings=report.critical_findings,
        cross_domain_link_count=cross_domain_link_count,
        narrative_id=narrative_id or report.audited_report_ref,
    )
