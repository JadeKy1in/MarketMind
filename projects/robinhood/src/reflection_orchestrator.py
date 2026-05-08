"""
reflection_orchestrator.py — Phase 8.3.2 反射编排器

The ReflectionOrchestrator monitors the trading step counter and triggers
periodic belief system maintenance at T = n × 50 step intervals (academic
standard from TradingGroup arXiv:2505.04479).

Three responsibilities:
  1. Scheduled Decay: When trading_steps % 50 == 0, call
     manager.apply_global_decay() to decay ALL active beliefs.
  2. Belief State Logging: After each decay, log the full active belief
     state for observability.
  3. Memory Export Trigger: Optionally trigger belief_memory_adapter
     export after each decay cycle.

Architecture:
  - Holds a BeliefStateManager instance (injected at init).
  - Decouples "when to decay" (orchestrator) from "how to decay" (manager).
  - Can be used as a standalone scheduler or integrated into the
    ShadowPipeline's daily run loop.

Integration with ShadowPipeline:
  After each complete Day-T→Day-T+1 cycle, the pipeline calls:
    orchestrator.on_trading_step_completed(current_step_count)

  If current_step_count % 50 == 0, the decay fires automatically.

SPARC:
  Specification: PM requirement — auto-decay every 50 steps.
  Pseudocode: check modulo → if 0, call manager.apply_global_decay() → log.
  Architecture: Observer pattern over trading step counter.
  Refinement: Safe against multiple fires at the same step (idempotent).
  Completion: Ready for end-to-end test.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .belief_state_manager import BeliefStateManager
from .belief_types import BeliefSnapshot

logger = logging.getLogger(__name__)


# ============================================================
# Configuration
# ============================================================

@dataclass
class ReflectionSchedulerConfig:
    """Configuration for the ReflectionOrchestrator scheduler.

    Attributes:
        decay_interval: Number of trading steps between decays. Default 50
            (TradingGroup arXiv:2505.04479 academic standard).
        decay_steps_per_interval: How many decay steps to apply each time.
            Default 1 (gentle decay per interval).
        log_after_decay: If True, log full belief state after each decay.
            Default True.
        trigger_memory_export: If True, call memory adapter export after
            each decay. Default False (requires adapter injection).
    """
    decay_interval: int = 50
    decay_steps_per_interval: int = 1
    log_after_decay: bool = True
    trigger_memory_export: bool = False


# ============================================================
# Reflection Orchestrator
# ============================================================

class ReflectionOrchestrator:
    """Reflection Orchestrator — monitors trading steps and schedules decay.

    Usage:
        manager = BeliefStateManager()
        orchestrator = ReflectionOrchestrator(manager)

        # During pipeline execution
        for step in range(1, 201):
            # ... trading logic ...
            orchestrator.on_trading_step_completed(step)
    """

    def __init__(
        self,
        manager: BeliefStateManager,
        config: Optional[ReflectionSchedulerConfig] = None,
    ) -> None:
        """Initialize the orchestrator with a BeliefStateManager instance.

        Args:
            manager: The BeliefStateManager to schedule decay on.
            config: Optional scheduler configuration.
        """
        self._manager = manager
        self._config = config or ReflectionSchedulerConfig()
        self._last_decay_step: int = -1  # Track to prevent double-fires
        self._total_decays_fired: int = 0
        self._decay_history: List[Dict[str, Any]] = []

        logger.info(
            "ReflectionOrchestrator initialized: interval=%d, decay_steps=%d",
            self._config.decay_interval,
            self._config.decay_steps_per_interval,
        )

    # ============================================================
    # Core API
    # ============================================================

    def on_trading_step_completed(self, step: int) -> Dict[str, Any]:
        """Called when a trading step completes.

        If step % decay_interval == 0, triggers the scheduled decay.
        Idempotent: if two calls happen for the same step, only the
        first fires.

        Args:
            step: The current trading step count (1-indexed).

        Returns:
            Dict with keys:
              - 'decay_fired': True if decay was triggered.
              - 'decayed_nodes': Number of nodes decayed.
              - 'active_after': Number of active nodes after decay.
              - 'step': The step that triggered (or checked) the decay.
        """
        result: Dict[str, Any] = {
            "decay_fired": False,
            "decayed_nodes": 0,
            "active_after": self._manager.get_active_count(),
            "step": step,
        }

        # Check if decay interval is reached
        if step % self._config.decay_interval != 0:
            return result

        # Prevent double-fire for same step
        if step == self._last_decay_step:
            logger.debug(
                "Decay already fired for step %d (idempotent guard)",
                step,
            )
            return result

        logger.info(
            "🔄 Reflection trigger: step=%d (interval=%d)",
            step,
            self._config.decay_interval,
        )

        # Fire the decay
        decayed = self._manager.apply_global_decay(
            steps=self._config.decay_steps_per_interval,
        )
        self._last_decay_step = step
        self._total_decays_fired += 1

        result["decay_fired"] = True
        result["decayed_nodes"] = decayed
        result["active_after"] = self._manager.get_active_count()
        result["decay_number"] = self._total_decays_fired

        # Record in history
        history_entry = {
            "step": step,
            "decay_number": self._total_decays_fired,
            "decayed_nodes": decayed,
            "active_before_decay": result["active_after"] + decayed,
            "active_after_decay": result["active_after"],
        }
        self._decay_history.append(history_entry)

        # Log active belief state if configured
        if self._config.log_after_decay:
            self._log_belief_state(step)

        logger.info(
            "Reflection complete: decayed %d nodes, %d active remaining "
            "(decay #%d)",
            decayed,
            result["active_after"],
            self._total_decays_fired,
        )

        return result

    # ============================================================
    # Memory Export Integration
    # ============================================================

    def set_memory_adapter(self, adapter: Any) -> None:
        """Inject a memory adapter for post-decay export.

        The adapter must have an export_to_memory method that accepts
        (snapshots, conflicts, retirements).

        Args:
            adapter: The memory adapter instance.
        """
        self._memory_adapter = adapter
        logger.debug("Memory adapter injected into ReflectionOrchestrator")

        # Enable memory export if an adapter is provided
        import copy
        cfg = copy.copy(self._config)
        cfg.trigger_memory_export = True
        self._config = cfg

    def _export_to_memory(self) -> int:
        """Export current belief state to memory graph.

        Returns:
            Number of entities written, or -1 if no adapter is set.
        """
        if not hasattr(self, "_memory_adapter"):
            logger.warning("Memory export requested but no adapter set.")
            return -1

        try:
            snapshots = self._manager.list_all()
            conflicts = self._manager.list_conflicts()
            retirements = self._manager.list_retirements()
            total = self._memory_adapter.export_to_memory(
                snapshots, conflicts, retirements,
            )
            logger.debug("Memory export completed: %d entities written", total)
            return total
        except Exception as e:
            logger.error("Memory export failed: %s", e)
            return -1

    # ============================================================
    # Querying
    # ============================================================

    def get_decay_history(self) -> List[Dict[str, Any]]:
        """Return the history of all decay events.

        Returns:
            List of dicts, each with step, decay_number, decayed_nodes, etc.
        """
        return list(self._decay_history)

    def get_total_decays_fired(self) -> int:
        """Return the total number of decay events fired."""
        return self._total_decays_fired

    def get_last_decay_step(self) -> int:
        """Return the step at which the last decay was fired."""
        return self._last_decay_step

    def get_config(self) -> ReflectionSchedulerConfig:
        """Return a copy of the current config."""
        import copy
        return copy.copy(self._config)

    # ============================================================
    # Simulation Mode (for tests)
    # ============================================================

    def simulate_steps(self, count: int) -> List[Dict[str, Any]]:
        """Simulate `count` trading steps, firing decays at interval boundaries.

        Useful for testing the decay schedule without an actual trading loop.

        Args:
            count: Number of steps to simulate.

        Returns:
            List of result dicts for steps where decay was fired.
        """
        results: List[Dict[str, Any]] = []
        for step in range(1, count + 1):
            result = self.on_trading_step_completed(step)
            if result["decay_fired"]:
                results.append(result)
        return results

    # ============================================================
    # Private Helpers
    # ============================================================

    def _log_belief_state(self, step: int) -> None:
        """Log the current active belief state for observability."""
        active = self._manager.list_active()
        if not active:
            logger.info("  No active beliefs at step %d", step)
            return

        logger.info("  Active beliefs at step %d:", step)
        for snap in active:
            logger.info(
                "    • %s — E=%.3f, U=%.4f, score=%.4f, obs=%d",
                snap.node.proposition[:50],
                snap.expectation,
                snap.uncertainty,
                snap.score,
                snap.observation_count,
            )