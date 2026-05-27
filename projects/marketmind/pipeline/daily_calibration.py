"""Daily calibration — closed-loop feedback + stage-level performance tracking.

Layer 1 of the main pipeline evolution system.

After each pipeline run, saves the day's predictions. Before the next run,
loads recent predictions and compares with actual market outcomes.

Enhanced (2026-05-27): Flash triage accuracy tracking + HVR investigation ROI
tracking, feeding into the weekly tactical audit (Layer 2).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("marketmind.pipeline.calibration")

SHADOW_DB_CACHE: dict[str, int] = {}


@dataclass
class DailyPrediction:
    date: str
    l1_grade: str
    l1_quadrant: str
    l1_direction: str
    ticker_candidates: list[str] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    # Enhanced fields
    flash_high_impact_count: int = 0
    flash_avg_impact: float = 0.0
    hvr_signals_found: int = 0
    hvr_articles_investigated: int = 0


def _calibration_dir() -> Path:
    d = Path(__file__).resolve().parent.parent / ".claude" / "calibration"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class CalibrationContext:
    """Enhanced calibration context with stage-level metrics."""
    direction_accuracy: float | None = None
    direction_correct: int = 0
    direction_total: int = 0
    grade_distribution: dict[str, int] = field(default_factory=dict)
    quadrant_accuracy: dict[str, tuple[int, int]] = field(default_factory=dict)
    # Flash quality
    flash_impact_vs_volatility_corr: float | None = None
    flash_high_impact_validation_rate: float | None = None
    # HVR ROI
    hvr_roi_ratio: float | None = None
    # Summary
    warning_flags: list[str] = field(default_factory=list)


def save_prediction(pred: DailyPrediction) -> None:
    try:
        fpath = _calibration_dir() / f"{pred.date}.json"
        data = {
            "date": pred.date, "l1_grade": pred.l1_grade,
            "l1_quadrant": pred.l1_quadrant, "l1_direction": pred.l1_direction,
            "ticker_candidates": pred.ticker_candidates,
            "decisions": pred.decisions,
            "flash_high_impact_count": pred.flash_high_impact_count,
            "flash_avg_impact": pred.flash_avg_impact,
            "hvr_signals_found": pred.hvr_signals_found,
            "hvr_articles_investigated": pred.hvr_articles_investigated,
        }
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.debug("Failed to save calibration for %s", pred.date, exc_info=True)


def load_prediction(date: str) -> DailyPrediction | None:
    try:
        fpath = _calibration_dir() / f"{date}.json"
        if not fpath.exists():
            return None
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return DailyPrediction(
            date=data["date"], l1_grade=data["l1_grade"],
            l1_quadrant=data["l1_quadrant"], l1_direction=data["l1_direction"],
            ticker_candidates=data.get("ticker_candidates", []),
            decisions=data.get("decisions", []),
            flash_high_impact_count=data.get("flash_high_impact_count", 0),
            flash_avg_impact=data.get("flash_avg_impact", 0.0),
            hvr_signals_found=data.get("hvr_signals_found", 0),
            hvr_articles_investigated=data.get("hvr_articles_investigated", 0),
        )
    except Exception:
        logger.debug("Failed to load calibration for %s", date, exc_info=True)
        return None


def get_calibration_context(shadow_db, days: int = 7) -> str:
    """Build enhanced calibration context for L1/Decision prompt injection."""
    ctx = compute_calibration_context(shadow_db, days)
    return _format_context(ctx)


def compute_calibration_context(shadow_db, days: int = 7) -> CalibrationContext:
    """Compute enhanced calibration metrics from past predictions.

    Tracks: direction accuracy, grade distribution, quadrant accuracy,
    Flash impact validation rate, HVR investigation ROI.
    """
    today = datetime.now(timezone.utc).date()
    predictions: list[DailyPrediction] = []
    for i in range(1, days + 1):
        d = (today - timedelta(days=i)).isoformat()
        pred = load_prediction(d)
        if pred:
            predictions.append(pred)

    ctx = CalibrationContext()

    if not predictions:
        return ctx

    correct = 0
    total = 0
    grade_counts: dict[str, int] = {}
    quadrant_hits: dict[str, tuple[int, int]] = {}
    flash_validated = 0
    flash_total = 0
    hvr_signals_total = 0
    hvr_articles_total = 0

    for pred in predictions:
        grade_counts[pred.l1_grade] = grade_counts.get(pred.l1_grade, 0) + 1

        # Flash impact validation: high-impact days should have decisive returns
        if pred.flash_high_impact_count > 0:
            flash_total += 1
            # Check if any decision on this day was correct
            day_correct = False
            for dec in pred.decisions:
                ticker = dec.get("ticker", "")
                direction = dec.get("direction", "")
                if not ticker or direction == "abstain":
                    continue
                actual_sign = _get_next_day_sign(shadow_db, ticker, pred.date)
                expected = 1 if direction == "long" else -1
                if actual_sign is not None and actual_sign != 0:
                    if (expected > 0 and actual_sign > 0) or (expected < 0 and actual_sign < 0):
                        day_correct = True
                        break
            if day_correct:
                flash_validated += 1

        # HVR ROI
        hvr_signals_total += pred.hvr_signals_found
        hvr_articles_total += pred.hvr_articles_investigated

        for dec in pred.decisions:
            ticker = dec.get("ticker", "")
            direction = dec.get("direction", "")
            if not ticker or direction == "abstain":
                continue
            total += 1
            actual_sign = _get_next_day_sign(shadow_db, ticker, pred.date)
            expected = 1 if direction == "long" else -1
            if actual_sign is not None and actual_sign != 0:
                is_correct = (expected > 0 and actual_sign > 0) or (expected < 0 and actual_sign < 0)
                if is_correct:
                    correct += 1
                q = pred.l1_quadrant
                c, t = quadrant_hits.get(q, (0, 0))
                quadrant_hits[q] = (c + (1 if is_correct else 0), t + 1)

    ctx.direction_correct = correct
    ctx.direction_total = total
    ctx.direction_accuracy = correct / total if total > 0 else None
    ctx.grade_distribution = grade_counts

    if quadrant_hits:
        ctx.quadrant_accuracy = quadrant_hits

    if flash_total > 0:
        ctx.flash_high_impact_validation_rate = flash_validated / flash_total

    if hvr_articles_total > 0:
        ctx.hvr_roi_ratio = hvr_signals_total / hvr_articles_total

    # Warning flags
    if ctx.direction_accuracy is not None and ctx.direction_accuracy < 0.40:
        ctx.warning_flags.append("Direction accuracy < 40% — consider narrowing selection or reducing confidence.")
    elif ctx.direction_accuracy is not None and ctx.direction_accuracy > 0.65:
        ctx.warning_flags.append("Direction accuracy > 65% — methodology is working, maintain discipline.")

    low_grades = grade_counts.get("E", 0) + grade_counts.get("D", 0)
    if low_grades > len(predictions) * 0.7:
        ctx.warning_flags.append("Most events graded D/E — grading may be too pessimistic.")

    if ctx.flash_high_impact_validation_rate is not None:
        if ctx.flash_high_impact_validation_rate < 0.30:
            ctx.warning_flags.append("Flash high-impact scores rarely validated — noise filter too loose.")
        elif ctx.flash_high_impact_validation_rate > 0.70:
            ctx.warning_flags.append("Flash high-impact scores well-validated — triage is effective.")

    if ctx.hvr_roi_ratio is not None:
        if ctx.hvr_roi_ratio < 0.10:
            ctx.warning_flags.append("HVR investigation ROI < 10% — HVR may be over-investigating without finding signals.")
        elif ctx.hvr_roi_ratio > 0.50:
            ctx.warning_flags.append("HVR investigation ROI > 50% — investigation is productive.")

    return ctx


def _format_context(ctx: CalibrationContext) -> str:
    """Format calibration context for prompt injection."""
    if not ctx.direction_total:
        return ""

    lines = [f"## Calibration Context (past predictions)"]
    lines.append("Yesterday's predictions vs actual market outcomes:")

    if ctx.direction_accuracy is not None:
        lines.append(f"- Direction accuracy: {ctx.direction_correct}/{ctx.direction_total} "
                     f"({ctx.direction_accuracy:.0%})")

    if ctx.grade_distribution:
        gs = ", ".join(f"{g}={c}" for g, c in sorted(ctx.grade_distribution.items()))
        lines.append(f"- Grade distribution: {gs}")

    if ctx.quadrant_accuracy:
        lines.append("- Quadrant accuracy:")
        for q, (c, t) in sorted(ctx.quadrant_accuracy.items()):
            lines.append(f"  {q}: {c}/{t} ({c/t:.0%})")

    if ctx.flash_high_impact_validation_rate is not None:
        lines.append(f"- Flash high-impact validation rate: {ctx.flash_high_impact_validation_rate:.0%}")

    if ctx.hvr_roi_ratio is not None:
        lines.append(f"- HVR investigation ROI: {ctx.hvr_roi_ratio:.0%} (signals found / articles investigated)")

    for flag in ctx.warning_flags:
        lines.append(f"  {'⚠' if '>' not in flag.split('—')[0] else '✓'} {flag}")

    lines.append("Use this calibration to adjust confidence and methodology.")
    return "\n".join(lines)


def _get_next_day_sign(shadow_db, ticker: str, date: str) -> int | None:
    cache_key = f"{ticker}:{date}"
    if cache_key in SHADOW_DB_CACHE:
        return SHADOW_DB_CACHE[cache_key]
    try:
        sign = shadow_db.get_next_day_return_sign(ticker, date)
        SHADOW_DB_CACHE[cache_key] = sign if sign is not None else 0
        return sign
    except Exception:
        SHADOW_DB_CACHE[cache_key] = 0
        return None
