"""Fragility scanner — compares live market data against fragility thresholds.

Zero LLM calls. Pure computation. UTC timestamps throughout.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from marketmind.config import fragility_thresholds as ft_config


@dataclass
class FragilityAlert:
    threshold: ft_config.FragilityThreshold
    current_value: float | None
    distance_pct: float | None     # how far from threshold (negative = crossed)
    crossed: bool
    severity: str                   # "CRITICAL" | "WARNING" | "MONITOR" | "CLEAR"


@dataclass
class FragilityReport:
    alerts: list[FragilityAlert]
    crossed: list[FragilityAlert]
    warnings: list[FragilityAlert]
    # 0 (stable) to 1 (extreme fragility); None = not evaluated (scan failed, or fewer
    # than half of the scored thresholds had data) so readers cannot mistake it for
    # "no fragility".
    overall_fragility_score: float | None
    staleness_warnings: list[str]
    summary: str
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # metric -> reason it could not be evaluated (no source / fetch failed)
    unavailable: dict[str, str] = field(default_factory=dict)
    # Coverage of the score: scored (crossable, active) thresholds evaluated / total.
    coverage_evaluated: int = 0
    coverage_total: int = 0


# The score needs at least this share of the scored thresholds to have data.
MIN_SCORE_COVERAGE = 0.5


def _compute_distance(current: float, threshold: float, direction: str) -> float:
    """Compute signed distance percentage from threshold.

    Positive = safe side of threshold (not crossed).
    Negative = threshold is crossed.

    For "below" thresholds: current < threshold → crossed (negative distance).
    For "above" thresholds: current > threshold → crossed (negative distance).
    """
    if threshold == 0:
        return 0.0
    raw = (current - threshold) / abs(threshold) * 100
    if direction == "above":
        raw = -raw
    return raw


def _classify_alert(
    distance_pct: float,
) -> tuple[str, bool]:
    """Classify severity from distance percentage."""
    if distance_pct < 0:
        return "CRITICAL", True
    elif distance_pct < 5:
        return "WARNING", False
    elif distance_pct < 15:
        return "MONITOR", False
    else:
        return "CLEAR", False


def _compute_fragility_score(alerts: list[FragilityAlert]) -> float:
    """Weighted fragility score: 0 (stable) to 1 (extreme fragility)."""
    if not alerts:
        return 0.0
    weights = {"CRITICAL": 1.0, "WARNING": 0.5, "MONITOR": 0.15, "CLEAR": 0.0}
    total = sum(weights[a.severity] for a in alerts)
    return round(total / len(alerts), 4)


async def scan_fragility(
    market_data: dict[str, float],
    unavailable: dict[str, str] | None = None,
) -> FragilityReport:
    """Scan all active thresholds against current market data.

    Args:
        market_data: Dict mapping metric names to current values.
                     e.g. {"bank_reserves": 2.9, "us10y_yield": 4.35, ...}
        unavailable: Optional metric -> reason for inputs that could not be fetched.

    Returns:
        FragilityReport with alerts, crossed list, score, and summary.
        Metrics with no value are listed in `unavailable`, never treated as safe.
    """
    staleness_warnings = ft_config.validate_thresholds()
    missing: dict[str, str] = dict(unavailable or {})

    alerts: list[FragilityAlert] = []
    for t in ft_config.THRESHOLD_LIBRARY:
        if not t.is_active:
            continue

        current_value = market_data.get(t.metric)
        if current_value is None:
            missing.setdefault(t.metric, "no data supplied")
            continue
        try:
            finite = math.isfinite(current_value)
        except TypeError:
            finite = False
        if not finite:
            # NaN compares False against every line, which used to read as CLEAR.
            missing[t.metric] = f"non-finite value ({current_value!r})"
            continue

        if not t.crossable:
            # MONITOR-only threshold: show the value, never cross, keep out of the score.
            alerts.append(FragilityAlert(threshold=t, current_value=current_value,
                                         distance_pct=None, crossed=False, severity="MONITOR"))
            continue

        # distance_pct is always measured against threshold_value (the crossing line),
        # so "negative = crossed = CRITICAL" holds for every threshold.
        distance_pct = _compute_distance(current_value, t.threshold_value, t.direction)
        severity, crossed = _classify_alert(distance_pct)
        if not crossed and t.warning_value is not None:
            # Two-tier threshold: the WARNING/MONITOR/CLEAR bands are measured against the
            # earlier warning line, and passing it is capped at WARNING (not crossed).
            w_severity, w_passed = _classify_alert(
                _compute_distance(current_value, t.warning_value, t.direction))
            severity = "WARNING" if w_passed else w_severity

        alerts.append(FragilityAlert(
            threshold=t,
            current_value=current_value,
            distance_pct=round(distance_pct, 2),
            crossed=crossed,
            severity=severity,
        ))

    crossed = [a for a in alerts if a.crossed]
    warnings_list = [a for a in alerts if a.severity == "WARNING"]

    scored = [a for a in alerts if a.threshold.crossable]
    coverage_total = sum(1 for t in ft_config.THRESHOLD_LIBRARY if t.is_active and t.crossable)
    coverage_evaluated = len(scored)
    enough = bool(scored) and coverage_evaluated >= MIN_SCORE_COVERAGE * coverage_total
    score = _compute_fragility_score(scored) if enough else None

    crossed_count = len(crossed)
    warning_count = len(warnings_list)
    monitor_only = sum(1 for a in alerts if not a.threshold.crossable)
    monitor_count = sum(1 for a in alerts if a.severity == "MONITOR")
    clear_count = sum(1 for a in alerts if a.severity == "CLEAR")
    coverage = f"coverage {coverage_evaluated}/{coverage_total} scored thresholds"
    counts = (f"{crossed_count} CRITICAL, {warning_count} WARNING, {monitor_count} MONITOR"
              f" ({monitor_only} monitor-only), {clear_count} CLEAR")

    if not alerts:
        summary = f"Fragility not evaluated: no threshold had data ({coverage})"
    elif score is None:
        summary = (f"Fragility score not evaluated: insufficient coverage ({coverage}, "
                   f"need at least half); {counts}")
    else:
        summary = f"Fragility score {score:.2f} ({coverage}): {counts}"
    if missing:
        summary += f" ({len(missing)} thresholds not evaluated: {', '.join(sorted(missing))})"

    return FragilityReport(
        alerts=alerts,
        crossed=crossed,
        warnings=warnings_list,
        overall_fragility_score=score,
        staleness_warnings=staleness_warnings,
        summary=summary,
        unavailable=missing,
        coverage_evaluated=coverage_evaluated,
        coverage_total=coverage_total,
    )


__all__ = ["FragilityAlert", "FragilityReport", "scan_fragility"]
