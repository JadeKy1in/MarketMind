"""
output_formatter.py — Phase 7.6 / 7.7 Report Generator (Layer 4)

Transforms a DecisionReport into a structured Markdown trading decision report.
Enforces strict ASCII-only output; no emoji or non-printable characters.
"""

from __future__ import annotations

from typing import Any

from src.decision_aggregator import DecisionReport, ResonanceMatrix
from src.paradigm_anchors import AnchorState, ThreeAnchors


class ReportGenerator:
    """Generates a structured Markdown report from a DecisionReport object.

    The report follows a strict seven-section structure:
      1. EXECUTION CONCLUSION
      2. POSITION SIZING
      3. FOUR-DIMENSIONAL RESONANCE SCORING TRACE
      4. MACRO ANCHOR STATUS
      5. RED-TEAM AUDIT RESULT
      6. SAFETY VALVES TRIGGERED
      7. DISCLAIMER

    Output is guaranteed ASCII-only (no emoji, no non-ASCII symbols).
    """

    _DIVIDER: str = "---"

    def generate(self, report: DecisionReport) -> str:
        """Produce the complete Markdown report string."""
        parts: list[str] = []
        parts.append(self._header(report))
        parts.append(self._section_execution_conclusion(report))
        parts.append(self._section_position_sizing(report))
        parts.append(self._section_resonance_trace(report))
        parts.append(self._section_macro_anchors(report))
        parts.append(self._section_red_team_audit(report))
        parts.append(self._section_safety_valves(report))
        parts.append(self._section_disclaimer(report))
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _header(self, report: DecisionReport) -> str:
        return (
            "# EXECUTION REPORT\n\n"
            f"**Report ID:** `{report.report_id}`\n\n"
            f"**Generated At:** {report.generated_at}\n\n"
            f"**Target Ticker:** {report.target_ticker}\n\n"
            f"{self._DIVIDER}"
        )

    def _section_execution_conclusion(self, report: DecisionReport) -> str:
        conclusion = self._derive_conclusion(report.decision_track.value)
        integrity = "PASS" if report.logic_chain_integrity else "FAIL"

        lines: list[str] = [
            "## 1. EXECUTION CONCLUSION\n",
            f"**Decision Track:** `{report.decision_track.value}`",
            f"**Conclusion:** {conclusion}",
            f"**Logic Chain Integrity:** {integrity}",
            f"**Mosaic Narrative ID:** `{report.mosaic_narrative_id}`",
            f"**Consensus Fragility:** {report.consensus_fragility:.2f}%",
            "",
            f"**Final Score:** {report.final_score:.2f}",
            f"**Audit Deduction:** -{report.audit_deduction:.2f}",
            f"**Paradigm Multiplier:** {report.paradigm_multiplier:.2f}",
        ]
        return "\n".join(lines)

    def _section_position_sizing(self, report: DecisionReport) -> str:
        ps = report.position_sizing
        if ps is None:
            return "## 2. POSITION SIZING\n\nNo position sizing data available."

        lines: list[str] = [
            "## 2. POSITION SIZING\n",
            f"**Direction:** {ps.direction}",
        ]

        if ps.suggested_shares > 0:
            lines.append(
                f"**Suggested Shares:** {ps.suggested_shares:,}"
            )
            lines.append(f"**Max Shares:** {ps.max_shares:,}")
            lines.append(
                f"**Percent of Buying Power:** {ps.percent_of_buying_power:.2f}%"
            )
            lines.append(
                f"**Risk Capital at Stake:** ${ps.risk_capital_at_stake:,.2f}"
            )

        if ps.cooling_period_hours > 0:
            lines.append(
                f"**Cooling Period:** {ps.cooling_period_hours} hours"
            )

        return "\n".join(lines)

    def _section_resonance_trace(self, report: DecisionReport) -> str:
        lines: list[str] = [
            "## 3. FOUR-DIMENSIONAL RESONANCE SCORING TRACE\n"
        ]

        # 3.1 Raw Dimension Scores
        lines.append("### 3.1 Raw Dimension Scores\n")
        if report.raw_scores:
            for dim, score in sorted(report.raw_scores.items()):
                lines.append(f"- **{dim}:** {score:.2f}")
        else:
            lines.append("No raw dimension scores recorded.")

        lines.append("")

        # 3.2 Score Synthesis
        lines.append(
            "### 3.2 Score Synthesis\n"
        )
        lines.append(
            f"- **Final Score:** {report.final_score:.2f}"
        )
        lines.append(
            f"- **Audit Deduction:** -{report.audit_deduction:.2f}"
        )
        lines.append(
            f"- **Paradigm Multiplier:** {report.paradigm_multiplier:.2f}"
        )

        # 3.3 Cross-Dimension Verification (only if resonance exists)
        if report.resonance is not None:
            lines.append("")
            lines.append(
                "### 3.3 Cross-Dimension Verification\n"
            )
            r = report.resonance
            lines.append(
                f"- **Resonance Score:** {r.resonance_score:.1f}%"
            )
            lines.append(
                f"- **Dimensions Resonating:** {r.dimensions_resonating} / 4"
            )
            lines.append(
                f"- **Resonance Threshold Met:** "
                f"{'YES' if r.resonance_threshold_met else 'NO'}"
            )

            if r.resonance_pairs:
                lines.append("\n**Aligned Pairs:**")
                for pair in r.resonance_pairs:
                    lines.append(f"  - `{pair}`")
            if r.divergence_pairs:
                lines.append("\n**Divergent Pairs:**")
                for pair in r.divergence_pairs:
                    lines.append(f"  - `{pair}`")

        return "\n".join(lines)

    def _section_macro_anchors(self, report: DecisionReport) -> str:
        anchors = report.anchors
        if anchors is None:
            return (
                "## 4. MACRO ANCHOR STATUS\n\n"
                "No macro anchor data available."
            )

        lines: list[str] = [
            "## 4. MACRO ANCHOR STATUS\n"
        ]
        lines.append(
            self._anchor_subsection(
                "4.1", "Fiscal Credibility",
                anchors.fiscal_credibility, anchors.fiscal_evidence,
            )
        )
        lines.append("")
        lines.append(
            self._anchor_subsection(
                "4.2", "Geopolitical GII",
                anchors.geopolitical_gii, anchors.gii_evidence,
            )
        )
        lines.append("")
        lines.append(
            self._anchor_subsection(
                "4.3", "Reflexivity RAC",
                anchors.reflexivity_rac, anchors.rac_evidence,
            )
        )
        return "\n".join(lines)

    def _section_red_team_audit(self, report: DecisionReport) -> str:
        audit_status = "YES" if report.audit_passed else "NO"
        return (
            "## 5. RED-TEAM AUDIT RESULT\n\n"
            f"**Audit Passed:** {audit_status}\n\n"
            f"**Audit Deduction Applied:** {report.audit_deduction:.2f}\n\n"
            f"**Paradigm Multiplier After Audit:** "
            f"{report.paradigm_multiplier:.2f}"
        )

    def _section_safety_valves(self, report: DecisionReport) -> str:
        valves = report.safety_valves_triggered
        if not valves:
            return (
                "## 6. SAFETY VALVES TRIGGERED\n\n"
                "No safety valves triggered."
            )

        lines: list[str] = [
            "## 6. SAFETY VALVES TRIGGERED\n"
        ]
        for i, valve in enumerate(valves, start=1):
            lines.append(f"- **Valve {i}:** {valve}")
        return "\n".join(lines)

    def _section_disclaimer(self, report: DecisionReport) -> str:
        return (
            "## 7. DISCLAIMER\n\n"
            f"{report.execution_disclaimer}"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_conclusion(track: str) -> str:
        mapping: dict[str, str] = {
            "FULL_BUY": "BUY",
            "SCALED_BUY": "BUY",
            "FULL_SELL": "SELL",
            "SCALED_SELL": "SELL",
            "FORCE_CLEAROUT": "CLEAROUT",
            "OBSERVE_WAIT": "HOLD",
        }
        return mapping.get(track, "HOLD")

    @staticmethod
    def _anchor_subsection(
        number: str, title: str, state: AnchorState, evidence: str,
    ) -> str:
        lines: list[str] = [
            f"### {number} {title}",
            f"**State:** {state.value}",
            f"**Evidence:** {evidence}",
        ]
        return "\n".join(lines)