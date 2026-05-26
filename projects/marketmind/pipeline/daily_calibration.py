"""Daily calibration — closed-loop feedback from past predictions to future prompts.

After each pipeline run, saves the day's predictions. Before the next run,
loads recent predictions and compares with actual market outcomes (from the
shadow analysis repo's next-day return signs). Generates a calibration
context block that gets injected into L1 and Decision prompts.

This is the main pipeline equivalent of the shadow AEL weekly Flash review,
operating at daily frequency with lightweight market-grounding.
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


def _calibration_dir() -> Path:
    d = Path(__file__).resolve().parent.parent / ".claude" / "calibration"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_prediction(pred: DailyPrediction) -> None:
    try:
        fpath = _calibration_dir() / f"{pred.date}.json"
        data = {
            "date": pred.date, "l1_grade": pred.l1_grade,
            "l1_quadrant": pred.l1_quadrant, "l1_direction": pred.l1_direction,
            "ticker_candidates": pred.ticker_candidates,
            "decisions": pred.decisions,
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
        )
    except Exception:
        logger.debug("Failed to load calibration for %s", date, exc_info=True)
        return None


def get_calibration_context(shadow_db, days: int = 7) -> str:
    """Build calibration context for injection into L1/Decision prompts.

    Loads predictions from the past N days, checks each ticker direction
    against actual next-day returns from the shadow analysis repo, and
    generates a concise summary of prediction accuracy.
    """
    today = datetime.now(timezone.utc).date()
    predictions: list[DailyPrediction] = []
    for i in range(1, days + 1):
        d = (today - timedelta(days=i)).isoformat()
        pred = load_prediction(d)
        if pred:
            predictions.append(pred)

    if not predictions:
        return ""

    lines = [f"## Calibration Context (past {len(predictions)} days)"]
    lines.append("Yesterday's predictions vs actual market outcomes:\n")

    correct = 0
    total = 0
    grade_counts: dict[str, int] = {}
    quadrant_hits: dict[str, tuple[int, int]] = {}

    for pred in predictions:
        grade_counts[pred.l1_grade] = grade_counts.get(pred.l1_grade, 0) + 1
        for dec in pred.decisions:
            ticker = dec.get("ticker", "")
            direction = dec.get("direction", "")
            if not ticker or direction == "abstain":
                continue
            total += 1
            actual_sign = _get_next_day_sign(shadow_db, ticker, pred.date)
            expected = 1 if direction == "long" else -1
            if actual_sign is not None and actual_sign != 0:
                is_correct = (expected > 0 and actual_sign > 0) or (
                    expected < 0 and actual_sign < 0)
                if is_correct:
                    correct += 1
                q = pred.l1_quadrant
                c, t = quadrant_hits.get(q, (0, 0))
                quadrant_hits[q] = (c + (1 if is_correct else 0), t + 1)

    if total > 0:
        acc = correct / total * 100
        lines.append(f"- Direction accuracy: {correct}/{total} ({acc:.0f}%)")
        if acc < 40:
            lines.append("  ⚠ Direction calls unreliable. "
                         "Consider reducing confidence or narrowing selection.")
        elif acc > 65:
            lines.append("  ✓ Direction calls above chance. Maintain methodology.")

    if grade_counts:
        gs = ", ".join(f"{g}={c}" for g, c in sorted(grade_counts.items()))
        lines.append(f"- Grade distribution: {gs}")
        low_grades = grade_counts.get("E", 0) + grade_counts.get("D", 0)
        if low_grades > len(predictions) * 0.7:
            lines.append("  ⚠ Most events graded D/E. Grading may be too pessimistic.")

    if quadrant_hits:
        lines.append("- Quadrant accuracy:")
        for q, (c, t) in sorted(quadrant_hits.items()):
            lines.append(f"  {q}: {c}/{t} ({c/t*100:.0f}%)")

    lines.append("\nUse this calibration to adjust confidence and grade assessments.")
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
