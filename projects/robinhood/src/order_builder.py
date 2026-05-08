"""
order_builder.py — Phase 6 Unified Order Router & Assembler.

After the Qualifier produces a DecisionTrack + action_subtrack, the
OrderBuilder routes execution to the correct downstream protocol:

  OBSERVE_WAIT  ─► ObserveWaitProtocol  ─► ObserveAnalysis
  ACTION_SELL   ─► SellProtocol          ─► SellAnalysis
  ACTION_BUY    ─► BuyProtocol           ─► OrderSuggestion

The builder then assembles a unified ExecutionOutput dict that the
OutputFormatter can render into the final Markdown report.

Physical isolation:
  - Produces ONLY analytical/theoretical order structures.
  - No brokerage API connection. No live execution.

Usage::

    builder = OrderBuilder()
    output = builder.execute(qualifier_input, qualifier_output, asset_basket)
    report_dict = output.to_dict()          # → dict[str, Any] for formatter
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.buy_protocol import BuyProtocol, OrderSuggestion
from src.observe_wait import ObserveAnalysis, ObserveWaitProtocol
from src.qualitative_judgment import (
    ActionSubtrack,
    DecisionTrack,
    QualifierInput,
    QualifierOutput,
)
from src.scout_types import AssetBasket
from src.sell_protocol import SellAnalysis, SellProtocol


# =========================================================================
# Unified execution output
# =========================================================================


@dataclass
class ExecutionOutput:
    """Unified output of the OrderBuilder after routing the Qualifier result.

    Fields:
        order_id:            Unique order identifier (from qualifier, or auto-generated).
        created_at:          ISO 8601 timestamp.
        decision_track:      One of "OBSERVE_WAIT" | "ACTION_AND_ADJUST".
        action_subtrack:     One of "BUY" | "SELL" | "WAIT" | None.
        narrative_ref:       Macro narrative that triggered the decision.

        observe_analysis:    Populated iff decision_track == OBSERVE_WAIT.
        sell_analysis:       Populated iff action_subtrack == SELL.
        buy_order_suggestion: Populated iff action_subtrack == BUY.

        error:               If routing or protocol execution failed.

    Physical isolation warning is embedded regardless of route.
    """

    order_id: str
    created_at: str
    decision_track: str
    action_subtrack: Optional[str] = None
    narrative_ref: str = ""

    # Track A
    observe_analysis: Optional[ObserveAnalysis] = None

    # Track B — SELL
    sell_analysis: Optional[SellAnalysis] = None

    # Track B — BUY
    buy_order_suggestion: Optional[OrderSuggestion] = None

    # Error state
    error: Optional[str] = None

    # Physical isolation disclaimer (always present)
    execution_disclaimer: str = (
        "THEORETICAL ONLY — NO BROKERAGE API CONNECTED. "
        "All prices, limits, and orders are purely analytical. "
        "No live execution has been performed."
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to plain dict for the OutputFormatter.

        All three analysis slots are always present in the dict (as None if empty)
        to ensure consumers can safely access them without checking key existence.
        """
        base: Dict[str, Any] = {
            "order_id": self.order_id,
            "created_at": self.created_at,
            "decision_track": self.decision_track,
            "action_subtrack": self.action_subtrack,
            "narrative_ref": self.narrative_ref,
            "execution_disclaimer": self.execution_disclaimer,
            "error": self.error,
            # Track A
            "observe_analysis": asdict(self.observe_analysis) if self.observe_analysis is not None else None,
            # Track B — SELL
            "sell_analysis": asdict(self.sell_analysis) if self.sell_analysis is not None else None,
            # Track B — BUY
            "buy_order_suggestion": asdict(self.buy_order_suggestion) if self.buy_order_suggestion is not None else None,
        }

        return base

    @classmethod
    def error_output(
        cls,
        error_message: str,
        decision_track: str = "UNKNOWN",
    ) -> "ExecutionOutput":
        """Factory for error-state outputs."""
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            order_id=f"err_{now[:16].replace(':', '').replace('T', '_')}",
            created_at=now,
            decision_track=decision_track,
            error=error_message,
        )


# =========================================================================
# OrderBuilder — the unified router
# =========================================================================


class OrderBuilder:
    """Routes a Qualifier judgment to the correct downstream protocol.

    Flow::

        QualifierOutput
            │
            ├─ OBSERVE_WAIT  ──► ObserveWaitProtocol.analyze()
            ├─ ACTION + SELL  ──► SellProtocol.analyze()
            └─ ACTION + BUY   ──► BuyProtocol.analyze()

    The result is packaged into a single ``ExecutionOutput`` for downstream
    consumption by the OutputFormatter.
    """

    def __init__(self) -> None:
        self._observe_protocol = ObserveWaitProtocol()
        self._sell_protocol = SellProtocol()
        self._buy_protocol = BuyProtocol()
        self._last_output: Optional[ExecutionOutput] = None

    @property
    def last_output(self) -> Optional[ExecutionOutput]:
        """Most recent ``ExecutionOutput``, if any."""
        return self._last_output

    @property
    def now(self) -> str:
        """Current UTC ISO 8601 timestamp."""
        return datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def execute(
        self,
        qualifier_input: QualifierInput,
        qualifier_output: QualifierOutput,
        asset_basket: Optional[AssetBasket] = None,
        buying_power: float = 100_000.0,
    ) -> ExecutionOutput:
        """Route and execute based on the Qualifier's judgment.

        Args:
            qualifier_input: The original input fed to the Qualifier.
            qualifier_output: The Qualifier's judgment.
            asset_basket: Optional Phase 5 AssetBasket for ticker suggestions.
            buying_power: Available capital (defaults to 100k demo value).

        Returns:
            A fully populated ``ExecutionOutput``.
        """
        if qualifier_output.decision_track == DecisionTrack.OBSERVE_AND_WAIT:
            return self._route_observe(qualifier_input, qualifier_output)
        elif qualifier_output.decision_track == DecisionTrack.ACTION_AND_ADJUST:
            subtrack = qualifier_output.action_subtrack
            if subtrack == ActionSubtrack.SELL:
                return self._route_sell(qualifier_input, qualifier_output)
            elif subtrack == ActionSubtrack.BUY:
                return self._route_buy(
                    qualifier_input, qualifier_output, asset_basket, buying_power,
                )
            else:
                return ExecutionOutput.error_output(
                    error_message=(
                        f"Unknown action_subtrack '{subtrack}' "
                        f"for ACTION_AND_ADJUST track."
                    ),
                    decision_track="ACTION_AND_ADJUST",
                )
        else:
            raw_track = (
                qualifier_output.decision_track.value
                if isinstance(qualifier_output.decision_track, DecisionTrack)
                else str(qualifier_output.decision_track)
            )
            return ExecutionOutput.error_output(
                error_message=(
                    f"Unknown decision_track "
                    f"'{raw_track}'."
                ),
                decision_track="UNKNOWN",
            )

    # ------------------------------------------------------------------
    # Internal routing methods
    # ------------------------------------------------------------------

    def _resolve_narrative(
        self,
        qualifier_input: QualifierInput,
    ) -> str:
        """Extract a narrative ref from qualifier input macro tags."""
        if qualifier_input.macro_tags:
            return qualifier_input.macro_tags[0].narrative
        return ""

    def _route_observe(
        self,
        qualifier_input: QualifierInput,
        qualifier_output: QualifierOutput,
    ) -> ExecutionOutput:
        """Route to ObserveWait protocol."""
        analysis = self._observe_protocol.analyze(
            qualifier_input, qualifier_output,
        )

        output = ExecutionOutput(
            order_id=f"obs_{qualifier_output.judgment_id[3:]}",
            created_at=self.now,
            decision_track="OBSERVE_WAIT",
            action_subtrack="WAIT",
            narrative_ref=self._resolve_narrative(qualifier_input),
            observe_analysis=analysis,
        )
        self._last_output = output
        return output

    def _route_sell(
        self,
        qualifier_input: QualifierInput,
        qualifier_output: QualifierOutput,
    ) -> ExecutionOutput:
        """Route to Sell protocol."""
        analysis = self._sell_protocol.analyze(
            qualifier_input, qualifier_output,
        )

        output = ExecutionOutput(
            order_id=f"sl_{qualifier_output.judgment_id[3:]}",
            created_at=self.now,
            decision_track="ACTION_AND_ADJUST",
            action_subtrack="SELL",
            narrative_ref=self._resolve_narrative(qualifier_input),
            sell_analysis=analysis,
        )
        self._last_output = output
        return output

    def _route_buy(
        self,
        qualifier_input: QualifierInput,
        qualifier_output: QualifierOutput,
        asset_basket: Optional[AssetBasket],
        buying_power: float,
    ) -> ExecutionOutput:
        """Route to Buy protocol."""
        order = self._buy_protocol.analyze(
            qualifier_input, qualifier_output, asset_basket, buying_power,
        )

        output = ExecutionOutput(
            order_id=order.order_id,
            created_at=self.now,
            decision_track="ACTION_AND_ADJUST",
            action_subtrack="BUY",
            narrative_ref=self._resolve_narrative(qualifier_input),
            buy_order_suggestion=order,
        )
        self._last_output = output
        return output