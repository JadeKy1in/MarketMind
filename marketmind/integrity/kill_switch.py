"""Perpetual no-trade detection + kill switch (FIA 2024 three-tier alerting).

Addresses the "no-trade paradox": a system that never trades has Sharpe=0.0
(code default), NOT <0, so the existing CEO-report kill conditions never fire.
This module catches the "paralyzed system" state that the old conditions miss.

RTS 6 (EU): Independent monitoring — runs even when pipeline crashes. State
file is separate from pipeline state so it survives pipeline failures.
"""
from __future__ import annotations
import json, logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

logger = logging.getLogger("marketmind.integrity.kill_switch")

# integrity/kill_switch.py → parent.parent = marketmind/ (package root)
_STATE_FILE = Path(__file__).resolve().parent.parent / ".claude" / "state" / "kill_switch_state.json"

# FIA 2024 three-tier thresholds
T1_NO_TRADE_KILL = 60        # paralyzed: no-trade + L3-red both at 60d → SUSPENDED
T1_L3_RED_KILL = 60
T1_NO_NON_MOCK_KILL = 90     # likely miscalibrated → SUSPENDED
T2_NO_TRADE_WARN = 30
T2_L3_RED_WARN = 14
T2_ELITE_EMPTY_WARN = 14
T3_NO_TRADE_INFO = 7

class KillSwitchState(Enum):
    ACTIVE = "ACTIVE"
    WARNING = "WARNING"
    SUSPENDED = "SUSPENDED"

# Fields persisted to JSON (used by _save/load to avoid repetition)
_PERSIST_KEYS = [
    "consecutive_no_trade_days", "total_runs", "total_trades",
    "last_trade_date", "consecutive_l3_red_days", "elite_shadow_count_history",
    "consecutive_elite_empty_days", "consecutive_no_non_mock_days",
    "state", "override_reason",
]

@dataclass
class KillSwitchMonitor:
    """Tracks no-trade streaks; enforces three-tier kill switch.

    Call ``check_after_run(metrics)`` at end of each pipeline run.  If the
    pipeline crashed, pass ``pipeline_crashed=True`` so the crash records as
    a no-trade data point.  State auto-persists to
    ``.claude/state/kill_switch_state.json``.
    """
    consecutive_no_trade_days: int = 0
    total_runs: int = 0
    total_trades: int = 0
    last_trade_date: str | None = None
    consecutive_l3_red_days: int = 0
    elite_shadow_count_history: list[int] = field(default_factory=list)
    state: KillSwitchState = KillSwitchState.ACTIVE
    override_reason: str | None = None
    consecutive_elite_empty_days: int = 0
    consecutive_no_non_mock_days: int = 0
    _dirty: bool = field(default=False, repr=False, compare=False)

    # ── Public API ──────────────────────────────────────────────────────

    def check_after_run(self, metrics: dict, *, pipeline_crashed: bool = False) -> KillSwitchState:
        """Evaluate kill switch after a pipeline run.

        metrics keys: had_trade (bool), had_non_mock_trade (bool),
        l3_green_light_rate (float 0..1), elite_shadow_count (int),
        date (str ISO).  Returns current KillSwitchState.
        """
        if self.state == KillSwitchState.SUSPENDED:
            logger.info("SUSPENDED — skipping evaluation (override_reason=%s)", self.override_reason)
            return self.state
        self.total_runs += 1

        # Safe extraction — defaults to all-false when pipeline crashed
        if pipeline_crashed:
            had_trade = had_non_mock_trade = False
            l3_green_light_rate = 0.0
            elite_count = 0
            run_date = metrics.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        else:
            had_trade = bool(metrics.get("had_trade", False))
            had_non_mock_trade = bool(metrics.get("had_non_mock_trade", False))
            l3_green_light_rate = float(metrics.get("l3_green_light_rate", 0.0))
            elite_count = int(metrics.get("elite_shadow_count", 0))
            run_date = str(metrics.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d")))

        # Update streaks
        if had_trade:
            self.total_trades += 1; self.last_trade_date = run_date; self.consecutive_no_trade_days = 0
        else:
            self.consecutive_no_trade_days += 1
        if had_non_mock_trade:
            self.consecutive_no_non_mock_days = 0
        else:
            self.consecutive_no_non_mock_days += 1
        if l3_green_light_rate <= 0.0:
            self.consecutive_l3_red_days += 1
        else:
            self.consecutive_l3_red_days = 0
        self.elite_shadow_count_history.append(elite_count)
        if elite_count <= 0:
            self.consecutive_elite_empty_days += 1
        else:
            self.consecutive_elite_empty_days = 0

        new_state = self._evaluate()
        if new_state != self.state:
            logger.warning(
                "Kill switch: %s → %s (no_trade=%dd l3_red=%dd no_non_mock=%dd elite_empty=%dd runs=%d trades=%d)",
                self.state.value, new_state.value, self.consecutive_no_trade_days,
                self.consecutive_l3_red_days, self.consecutive_no_non_mock_days,
                self.consecutive_elite_empty_days, self.total_runs, self.total_trades,
            )
            self.state = new_state; self._dirty = True
        self._save()
        return self.state

    def manual_override(self, reason: str) -> KillSwitchState:
        """Resume from SUSPENDED. Resets all counters. Reason is audited."""
        logger.warning("Kill switch MANUAL OVERRIDE: %s (was %s)", reason, self.state.value)
        self.state = KillSwitchState.ACTIVE
        self.override_reason = reason
        self.consecutive_no_trade_days = self.consecutive_l3_red_days = 0
        self.consecutive_no_non_mock_days = self.consecutive_elite_empty_days = 0
        self._dirty = True
        self._save()
        return self.state

    # ── Tier evaluation ─────────────────────────────────────────────────

    def _evaluate(self) -> KillSwitchState:
        """Check T3→T1→T2 (T1 checked first, takes priority over T2)."""
        # T3: INFO — log only
        if self.consecutive_no_trade_days >= T3_NO_TRADE_INFO:
            logger.info("T3 INFO: %dd no-trade (thresh=%d) runs=%d trades=%d",
                        self.consecutive_no_trade_days, T3_NO_TRADE_INFO,
                        self.total_runs, self.total_trades)

        # T1: FATAL → SUSPENDED (Condition A: paralyzed; B: miscalibrated)
        t1_reasons: list[str] = []
        if self.consecutive_no_trade_days >= T1_NO_TRADE_KILL and self.consecutive_l3_red_days >= T1_L3_RED_KILL:
            t1_reasons.append(f"PARALYZED: no-trade={self.consecutive_no_trade_days}d + L3-red={self.consecutive_l3_red_days}d")
        if self.consecutive_no_non_mock_days >= T1_NO_NON_MOCK_KILL:
            t1_reasons.append(f"MISCALIBRATED: no non-mock trade {self.consecutive_no_non_mock_days}d")
        if t1_reasons:
            logger.critical("T1 FATAL — SUSPENDED: %s", "; ".join(t1_reasons))
            return KillSwitchState.SUSPENDED

        # T2: WARNING
        t2_reasons: list[str] = []
        if self.consecutive_no_trade_days >= T2_NO_TRADE_WARN:
            t2_reasons.append(f"no-trade={self.consecutive_no_trade_days}d")
        if self.consecutive_l3_red_days >= T2_L3_RED_WARN:
            t2_reasons.append(f"L3-red={self.consecutive_l3_red_days}d")
        if self.consecutive_elite_empty_days >= T2_ELITE_EMPTY_WARN:
            t2_reasons.append(f"ELITE-empty={self.consecutive_elite_empty_days}d")
        if t2_reasons:
            logger.warning("T2 WARNING: %s", "; ".join(t2_reasons))
            return KillSwitchState.WARNING

        # Auto-recover WARNING→ACTIVE when all T2 conditions clear
        if self.state == KillSwitchState.WARNING:
            return KillSwitchState.ACTIVE
        return self.state

    # ── Persistence ──────────────────────────────────────────────────────

    def _save(self) -> None:
        data = {k: (self.state.value if k == "state" else getattr(self, k)) for k in _PERSIST_KEYS}
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        try:
            _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._dirty = False
        except OSError as e:
            logger.error("Failed to persist kill switch state: %s", e)

    @classmethod
    def load(cls) -> KillSwitchMonitor:
        if not _STATE_FILE.exists():
            logger.info("No existing kill switch state — starting fresh")
            return cls()
        try:
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            state_raw = data.get("state", "ACTIVE")
            try:
                state = KillSwitchState(state_raw)
            except ValueError:
                logger.warning("Unknown state '%s' in file — defaulting ACTIVE", state_raw)
                state = KillSwitchState.ACTIVE
            monitor = cls(
                consecutive_no_trade_days=int(data.get("consecutive_no_trade_days", 0)),
                total_runs=int(data.get("total_runs", 0)),
                total_trades=int(data.get("total_trades", 0)),
                last_trade_date=data.get("last_trade_date"),
                consecutive_l3_red_days=int(data.get("consecutive_l3_red_days", 0)),
                elite_shadow_count_history=data.get("elite_shadow_count_history", []),
                consecutive_elite_empty_days=int(data.get("consecutive_elite_empty_days", 0)),
                consecutive_no_non_mock_days=int(data.get("consecutive_no_non_mock_days", 0)),
                state=state,
                override_reason=data.get("override_reason"),
            )
            logger.info("Loaded kill switch: %s runs=%d trades=%d no_trade=%dd",
                        state.value, monitor.total_runs, monitor.total_trades,
                        monitor.consecutive_no_trade_days)
            return monitor
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error("Corrupted state file %s — starting fresh: %s", _STATE_FILE, e)
            return cls()


def get_monitor() -> KillSwitchMonitor:
    """Convenience: load persisted state (not a singleton — state is in JSON)."""
    return KillSwitchMonitor.load()
