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

SHADOW_DB_CACHE: dict[str, float] = {}


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
    """Enhanced calibration context with stage-level metrics and evolution awareness."""
    direction_accuracy: float | None = None
    direction_correct: int = 0
    direction_total: int = 0
    # Magnitude-weighted scoring (P3): rewards calls that are both correct AND large
    magnitude_score: float | None = None  # sum(expected_sign * actual_return) / n
    magnitude_mean_return: float | None = None  # avg |return| on correct calls
    grade_distribution: dict[str, int] = field(default_factory=dict)
    quadrant_accuracy: dict[str, tuple[int, int]] = field(default_factory=dict)
    # Flash quality
    flash_impact_vs_volatility_corr: float | None = None
    flash_high_impact_validation_rate: float | None = None
    # HVR ROI
    hvr_roi_ratio: float | None = None
    # L3 evolution awareness: recent rule changes from Layer 3
    recent_evolutions: list[dict] = field(default_factory=list)
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
    magnitude_sum = 0.0
    magnitude_sum_correct = 0.0
    magnitude_n_correct = 0
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
            actual_return = _get_next_day_return(shadow_db, ticker, pred.date)
            actual_sign = 1 if (actual_return or 0) > 0 else (-1 if (actual_return or 0) < 0 else 0)
            expected = 1 if direction == "long" else -1
            if actual_return is not None and actual_sign != 0:
                is_correct = (expected > 0 and actual_sign > 0) or (expected < 0 and actual_sign < 0)
                if is_correct:
                    correct += 1
                # P3: Magnitude-weighted score
                magnitude_sum += expected * actual_return
                if is_correct:
                    magnitude_sum_correct += abs(actual_return)
                    magnitude_n_correct += 1
                q = pred.l1_quadrant
                c, t = quadrant_hits.get(q, (0, 0))
                quadrant_hits[q] = (c + (1 if is_correct else 0), t + 1)

    ctx.direction_correct = correct
    ctx.direction_total = total
    ctx.direction_accuracy = correct / total if total > 0 else None
    ctx.magnitude_score = magnitude_sum / total if total > 0 else None
    ctx.magnitude_mean_return = magnitude_sum_correct / magnitude_n_correct if magnitude_n_correct > 0 else None
    ctx.grade_distribution = grade_counts

    if quadrant_hits:
        ctx.quadrant_accuracy = quadrant_hits

    if flash_total > 0:
        ctx.flash_high_impact_validation_rate = flash_validated / flash_total

    if hvr_articles_total > 0:
        ctx.hvr_roi_ratio = hvr_signals_total / hvr_articles_total

    # L3 evolution awareness: load recent rule changes
    ctx.recent_evolutions = _load_recent_evolutions(days=days)

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

    # P3: Magnitude-weighted warnings
    if ctx.direction_accuracy is not None and ctx.magnitude_score is not None:
        if ctx.direction_accuracy > 0.55 and (ctx.magnitude_score or 0) < 0:
            ctx.warning_flags.append(
                "Direction accuracy > 55% but magnitude score is negative — "
                "correct on small moves, wrong on large moves. Risk of adverse selection."
            )

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

    if ctx.magnitude_score is not None:
        lines.append(f"- Magnitude-weighted score: {ctx.magnitude_score:+.4f} "
                     f"(avg expected_return × actual_return)")
    if ctx.magnitude_mean_return is not None:
        lines.append(f"- Avg return on correct calls: {ctx.magnitude_mean_return:.4f}")

    if ctx.hvr_roi_ratio is not None:
        lines.append(f"- HVR investigation ROI: {ctx.hvr_roi_ratio:.0%} (signals found / articles investigated)")

    for flag in ctx.warning_flags:
        lines.append(f"  {'⚠' if '>' not in flag.split('—')[0] else '✓'} {flag}")

    if ctx.recent_evolutions:
        lines.append("")
        lines.append("## Recent Methodology Evolutions (from Layer 3)")
        lines.append("The following rules were recently changed. Factor these into today's analysis:")
        for ev in ctx.recent_evolutions[:5]:
            rid = ev.get("rule_id", "?")
            reason = ev.get("reason", "")[:150]
            lines.append(f"- [{rid}] {reason}")

    lines.append("Use this calibration to adjust confidence and methodology.")
    return "\n".join(lines)


def _evolution_log_path() -> Path:
    return Path(__file__).resolve().parent.parent / ".claude" / "metrics" / "evolutions.jsonl"


def _load_recent_evolutions(days: int = 7) -> list[dict]:
    """Load recent L3 rule evolutions for calibration context.

    These show L1/Decision prompts what rules have recently changed,
    closing the L3 → L1 feedback loop.
    """
    log_path = _evolution_log_path()
    if not log_path.exists():
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days))
    recent: list[dict] = []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entry_date = entry.get("date", "")
                    if entry_date >= cutoff.strftime("%Y-%m-%d"):
                        recent.append(entry)
                except json.JSONDecodeError:
                    continue
    except Exception:
        logger.debug("Failed to load evolution log", exc_info=True)
    return recent


def _get_next_day_sign(shadow_db, ticker: str, date: str) -> int | None:
    cache_key = f"sign:{ticker}:{date}"
    if cache_key in SHADOW_DB_CACHE:
        cached = SHADOW_DB_CACHE[cache_key]
        return cached if cached != 0 else None
    try:
        sign = shadow_db.get_next_day_return_sign(ticker, date)
        SHADOW_DB_CACHE[cache_key] = sign if sign is not None else 0
        return sign
    except Exception:
        SHADOW_DB_CACHE[cache_key] = 0
        return None


def _get_next_day_return(shadow_db, ticker: str, date: str) -> float | None:
    """Get next trading day's actual return for magnitude-weighted scoring.

    Uses a separate cache key prefix to avoid collision with _get_next_day_sign.
    """
    cache_key = f"ret:{ticker}:{date}"
    if cache_key in SHADOW_DB_CACHE:
        cached = SHADOW_DB_CACHE[cache_key]
        return cached if cached != 0.0 else None
    try:
        ret = shadow_db.get_next_day_return(ticker, date)
        SHADOW_DB_CACHE[cache_key] = ret if ret is not None else 0.0
        return ret
    except Exception:
        SHADOW_DB_CACHE[cache_key] = 0.0
        return None
