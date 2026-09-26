"""Methodology Evolver -- White-Box Methodology Self-Evolution for Shadow Ecosystem.

Tracks which analysis methods work and which don't. When a method consistently
fails, it decays and suggests alternatives. All changes are logged with
explainable audit trails -- you can trace WHY any strategy shift occurred.

Key principles:
  - Methods are tracked by ID with success/failure counters
  - Methods decay over time if not reinforced
  - Method changes are logged with rationale
  - Methodology reports are human-readable and auditable

Ported from robinhood methodology_evolver.py, adapted for MarketMind shadow domains.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("marketmind.shadows.methodology_evolver")

_METHOD_DIR = Path(__file__).resolve().parent.parent / "data" / "methodology"
_METHOD_DIR.mkdir(parents=True, exist_ok=True)
_METHOD_FILE = _METHOD_DIR / "method_tracker.json"
_AUDIT_FILE = _METHOD_DIR / "evolution_audit.jsonl"
_AUDIT_MAX_LINES = 10_000  # Rotate when exceeded, keeping most recent half


def _rotate_audit_if_needed() -> None:
    """Truncate audit file to most recent half when it exceeds max lines."""
    if not _AUDIT_FILE.exists():
        return
    try:
        with open(_AUDIT_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > _AUDIT_MAX_LINES:
            keep = _AUDIT_MAX_LINES // 2
            with open(_AUDIT_FILE, "w", encoding="utf-8") as f:
                f.writelines(lines[-keep:])
            logger.info("Audit file rotated: %d → %d lines", len(lines), keep)
    except Exception:
        pass  # Rotation is best-effort, don't block on failure


@dataclass
class MethodRecord:
    """Track record for a single analysis method."""
    method_id: str
    description: str
    total_predictions: int = 0
    correct_predictions: int = 0
    last_used: str = ""
    last_correct: str = ""
    decay_factor: float = 1.0    # 1.0 = full strength, decays toward 0
    active: bool = True
    category: str = "general"


@dataclass
class MethodologyReport:
    """Human-readable methodology health report."""
    date: str
    total_methods: int
    active_methods: int
    retired_methods: int
    best_performing: list[str]
    worst_performing: list[str]
    decayed_methods: list[str]
    recommended_changes: list[str]
    audit_entries: int


# Pre-registered methods for the MarketMind shadow ecosystem
DEFAULT_METHODS: list[MethodRecord] = [
    # Expert domains
    MethodRecord("expert-gold", "Gold/precious metals expert analysis", category="expert"),
    MethodRecord("expert-crypto", "Cryptocurrency market expert analysis", category="expert"),
    MethodRecord("expert-tech", "Technology sector expert analysis", category="expert"),
    MethodRecord("expert-energy", "Energy/commodities expert analysis", category="expert"),
    MethodRecord("expert-healthcare", "Healthcare/biotech expert analysis", category="expert"),
    MethodRecord("expert-realestate", "Real estate/REITs expert analysis", category="expert"),
    # Daredevil strategies
    MethodRecord("daredevil-scalper", "Intraday scalping with tight stops", category="daredevil"),
    MethodRecord("daredevil-trend-rider", "Momentum trend following with trailing stops", category="daredevil"),
    MethodRecord("daredevil-news-hound", "News-driven rapid entry/exit", category="daredevil"),
    MethodRecord("daredevil-fade-master", "Counter-trend fade at extremes", category="daredevil"),
    MethodRecord("daredevil-rotation", "Sector rotation timing", category="daredevil"),
    # Cross-cutting
    MethodRecord("catfish-contrarian", "Contrarian signal detection against herd", category="cross"),
    MethodRecord("fundamental-analysis", "Traditional fundamental valuation", category="cross"),
    MethodRecord("technical-analysis", "Price/volume technical analysis", category="cross"),
    MethodRecord("narrative-analysis", "Narrative velocity and sentiment tracking", category="cross"),
]


def _auto_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_tracker() -> dict[str, MethodRecord]:
    """Load the method tracker from disk, initializing defaults if needed."""
    if _METHOD_FILE.exists():
        try:
            data = json.loads(_METHOD_FILE.read_text())
            return {k: MethodRecord(**v) for k, v in data.items()}
        except (json.JSONDecodeError, TypeError):
            logger.warning("Corrupted method tracker, reinitializing from defaults")

    # Initialize with defaults
    tracker = {m.method_id: m for m in DEFAULT_METHODS}
    save_tracker(tracker)
    return tracker


def save_tracker(tracker: dict[str, MethodRecord]) -> None:
    """Persist method tracker to disk."""
    data = {
        k: {
            "method_id": v.method_id,
            "description": v.description,
            "total_predictions": v.total_predictions,
            "correct_predictions": v.correct_predictions,
            "last_used": v.last_used,
            "last_correct": v.last_correct,
            "decay_factor": v.decay_factor,
            "active": v.active,
            "category": v.category,
        }
        for k, v in tracker.items()
    }
    _METHOD_FILE.write_text(json.dumps(data, indent=2))


def log_method_outcome(
    method_id: str,
    prediction_id: str,
    correct: bool,
    context: str = "",
) -> None:
    """Log a single method outcome and write an audit entry.

    Args:
        method_id: Method identifier (e.g., "expert-gold").
        prediction_id: Unique prediction ID for traceability.
        correct: Whether the prediction was correct.
        context: Optional context string for audit trail.
    """
    tracker = load_tracker()

    if method_id not in tracker:
        # Auto-register unknown method
        tracker[method_id] = MethodRecord(
            method_id=method_id,
            description=f"Auto-registered: {method_id}",
            category="auto",
        )

    method = tracker[method_id]
    method.total_predictions += 1
    if correct:
        method.correct_predictions += 1
        method.last_correct = _auto_iso()
        method.decay_factor = min(1.0, method.decay_factor + 0.05)
    else:
        method.decay_factor = max(0.1, method.decay_factor - 0.08)

    method.last_used = _auto_iso()

    # Retire if accuracy drops below 30% with >= 10 predictions
    if method.total_predictions >= 10:
        accuracy = method.correct_predictions / method.total_predictions
        if accuracy < 0.30:
            method.active = False

    save_tracker(tracker)

    # Write audit entry
    entry = {
        "timestamp": _auto_iso(),
        "method_id": method_id,
        "prediction_id": prediction_id,
        "correct": correct,
        "decay_factor": round(method.decay_factor, 2),
        "active": method.active,
        "context": context,
    }
    with open(_AUDIT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def evolve_methodology() -> MethodologyReport:
    """Generate a methodology evolution report with actionable recommendations.

    This is the white-box explainability layer: it shows EXACTLY which methods
    are performing, which are decaying, and WHY changes are recommended.
    """
    tracker = load_tracker()
    now = _auto_iso()

    methods = list(tracker.values())
    active = [m for m in methods if m.active]
    retired = [m for m in methods if not m.active]

    # Rank by accuracy
    ranked = sorted(
        active,
        key=lambda m: m.correct_predictions / max(m.total_predictions, 1),
        reverse=True,
    )

    best = [
        f"{m.method_id} ({m.correct_predictions}/{m.total_predictions})"
        for m in ranked[:3] if m.total_predictions > 0
    ]

    worst = [
        f"{m.method_id} ({m.correct_predictions}/{m.total_predictions})"
        for m in ranked[-3:] if m.total_predictions > 0
    ]

    # Decayed methods (low decay factor but still active)
    decayed = [
        f"{m.method_id} (decay={m.decay_factor:.2f})"
        for m in active if m.decay_factor < 0.5
    ]

    # Recommendations
    recommendations: list[str] = []
    for m in active:
        if m.total_predictions >= 5:
            acc = m.correct_predictions / m.total_predictions
            if acc < 0.40:
                recommendations.append(
                    f"RETIRE {m.method_id}: accuracy {acc:.0%} over {m.total_predictions} predictions. "
                    f"Consider: replacing with alternative method or recalibrating inputs."
                )
            elif m.decay_factor < 0.3:
                recommendations.append(
                    f"BOOST {m.method_id}: decay at {m.decay_factor:.2f}. "
                    f"Recent predictions trending wrong. Review last 5 outcomes."
                )

    # Count audit entries
    audit_count = 0
    if _AUDIT_FILE.exists():
        audit_count = len(_AUDIT_FILE.read_text(encoding="utf-8").splitlines())

    return MethodologyReport(
        date=now,
        total_methods=len(methods),
        active_methods=len(active),
        retired_methods=len(retired),
        best_performing=best,
        worst_performing=worst,
        decayed_methods=decayed,
        recommended_changes=recommendations,
        audit_entries=audit_count,
    )


def format_evolution_report(report: MethodologyReport) -> str:
    """Format the methodology report as a readable Markdown section."""
    lines = [
        "## Methodology Evolution Report",
        f"**Date:** {report.date} | **Active Methods:** {report.active_methods}/{report.total_methods} "
        f"| **Audit Trail:** {report.audit_entries} entries",
        "",
    ]

    if report.best_performing:
        lines.append("### Best Performing")
        for m in report.best_performing:
            lines.append(f"- {m}")
        lines.append("")

    if report.worst_performing:
        lines.append("### Needs Attention")
        for m in report.worst_performing:
            lines.append(f"- {m}")
        lines.append("")

    if report.decayed_methods:
        lines.append("### Decayed Methods (low reinforcement)")
        for m in report.decayed_methods:
            lines.append(f"- {m}")
        lines.append("")

    if report.recommended_changes:
        lines.append("### Recommended Changes")
        for r in report.recommended_changes:
            lines.append(f"- {r}")
        lines.append("")

    if report.retired_methods > 0:
        lines.append(f"### Retired Methods: {report.retired_methods}")
        lines.append("Methods automatically retired when accuracy < 30% after 10+ predictions.")
        lines.append("")

    return "\n".join(lines)


# Method breeding extracted to shadows/method_breeding.py


class MethodologyEvolver:
    """High-level API for methodology tracking in the shadow ecosystem.

    Wraps the module-level functions with a class interface that can be
    injected into the crystallization engine and other components.
    """

    def __init__(self) -> None:
        """Initialize methodology evolver. Ensures tracker file exists."""
        load_tracker()  # Ensures defaults are written if no file exists

    def record_prediction(
        self, method_id: str, correct: bool, prediction_id: str = "", context: str = ""
    ) -> None:
        """Record a prediction outcome for a methodology.

        Args:
            method_id: The method identifier (e.g., "expert-gold").
            correct: Whether the prediction was correct.
            prediction_id: Optional unique prediction ID for traceability.
            context: Optional context string for audit trail.
        """
        pid = prediction_id or f"pred_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        log_method_outcome(method_id, pid, correct, context)

    def apply_decay(self, gamma: float = 0.95) -> list[str]:
        """Apply gamma decay to all active methods' decay factors.

        Args:
            gamma: Decay multiplier per cycle (0.0-1.0).

        Returns:
            List of method_ids that were retired due to decay.
        """
        tracker = load_tracker()
        retired_ids: list[str] = []
        for m in tracker.values():
            if not m.active:
                continue
            m.decay_factor = max(0.05, m.decay_factor * gamma)
            if m.total_predictions >= 10:
                accuracy = m.correct_predictions / max(m.total_predictions, 1)
                if accuracy < 0.30:
                    m.active = False
                    retired_ids.append(m.method_id)
        save_tracker(tracker)
        return retired_ids

    def retire_method(self, method_id: str) -> None:
        """Manually retire a method.

        Args:
            method_id: The method identifier to retire.
        """
        tracker = load_tracker()
        if method_id in tracker:
            tracker[method_id].active = False
            save_tracker(tracker)
            # Write audit entry
            entry = {
                "timestamp": _auto_iso(),
                "event": "method_retired",
                "method_id": method_id,
                "reason": "manual_retirement",
            }
            with open(_AUDIT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def generate_report(self) -> MethodologyReport:
        """Generate a full methodology health report."""
        return evolve_methodology()

    def record_methodology_change(
        self, method_id: str, change_description: str, rationale: str
    ) -> None:
        """Record a deliberate methodology change with rationale.

        Args:
            method_id: The method identifier being changed.
            change_description: What changed.
            rationale: Why the change was made.
        """
        entry = {
            "timestamp": _auto_iso(),
            "event": "methodology_change",
            "method_id": method_id,
            "change": change_description,
            "rationale": rationale,
        }
        with open(_AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info(
            "Methodology change recorded: %s — %s", method_id, change_description[:80]
        )

    def get_audit_trail(
        self, method_id: str | None = None, limit: int = 50
    ) -> list[dict]:
        """Get the methodology audit trail, optionally filtered by method_id."""
        if not _AUDIT_FILE.exists():
            return []
        entries = []
        with open(_AUDIT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if method_id is None or entry.get("method_id") == method_id:
                        entries.append(entry)
                except json.JSONDecodeError:
                    continue
        entries.reverse()
        return entries[:limit]


