"""Prediction calibration tracking — Brier scores, ECE, direction accuracy."""

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from collections import defaultdict


@dataclass
class CalibrationResult:
    tracker_id: str
    total_predictions: int
    verified_predictions: int
    brier_score: float              # 0 (perfect) to 1 (worst)
    direction_accuracy: float       # 0-1
    ece: float | None               # Expected Calibration Error (null if <10 verified)
    calibration_buckets: dict[str, dict]  # {"0.0-0.1": {"predicted": 5, "actual": 0.0}, ...}
    platt_a: float | None           # Platt scaling coefficient
    platt_b: float | None
    needs_more_data: bool           # True if <10 verified predictions


def compute_brier_score(predictions: list) -> float:
    """BS = mean((confidence_i - outcome_i)^2).

    outcome_i = 1 if VERIFIED_SUCCESS, 0 if VERIFIED_FAILURE.
    Skips PENDING predictions.
    """
    verified = [p for p in predictions if p.status in ("VERIFIED_SUCCESS", "VERIFIED_FAILURE")]
    if not verified:
        return float('nan')
    bs = sum((p.confidence - (1.0 if p.status == "VERIFIED_SUCCESS" else 0.0)) ** 2
             for p in verified) / len(verified)
    return round(bs, 6)


def compute_direction_accuracy(predictions: list) -> float:
    """What fraction of directional predictions were correct?"""
    verified = [p for p in predictions if p.status in ("VERIFIED_SUCCESS", "VERIFIED_FAILURE")]
    if not verified:
        return float('nan')
    correct = sum(1 for p in verified if p.status == "VERIFIED_SUCCESS")
    return round(correct / len(verified), 4)


def compute_ece(predictions: list, n_buckets: int = 10) -> float | None:
    """Expected Calibration Error.

    Partitions predictions into confidence buckets (0.0-0.1, 0.1-0.2, ...),
    computes |accuracy_in_bucket - avg_confidence_in_bucket| * bucket_weight.
    """
    verified = [p for p in predictions if p.status in ("VERIFIED_SUCCESS", "VERIFIED_FAILURE")]
    if len(verified) < 10:
        return None  # insufficient data

    buckets = defaultdict(list)
    for p in verified:
        bucket = min(int(p.confidence * n_buckets), n_buckets - 1)
        buckets[bucket].append(p)

    ece = 0.0
    for bucket, preds in buckets.items():
        if not preds:
            continue
        bucket_accuracy = sum(1.0 for p in preds if p.status == "VERIFIED_SUCCESS") / len(preds)
        bucket_confidence = sum(p.confidence for p in preds) / len(preds)
        bucket_weight = len(preds) / len(verified)
        ece += abs(bucket_accuracy - bucket_confidence) * bucket_weight

    return round(ece, 6)


def compute_calibration_buckets(predictions: list) -> dict:
    """Group predictions into confidence buckets with actual success rates.

    For detecting systematic over/under-confidence per bucket.
    """
    verified = [p for p in predictions if p.status in ("VERIFIED_SUCCESS", "VERIFIED_FAILURE")]
    buckets = defaultdict(lambda: {"predicted": 0, "actual_success": 0})
    for p in verified:
        bucket_key = f"{int(p.confidence * 10) / 10:.1f}-{int(p.confidence * 10) / 10 + 0.1:.1f}"
        buckets[bucket_key]["predicted"] += 1
        if p.status == "VERIFIED_SUCCESS":
            buckets[bucket_key]["actual_success"] += 1
    for k, v in buckets.items():
        v["actual_rate"] = round(v["actual_success"] / v["predicted"], 3) if v["predicted"] > 0 else 0.0
    return dict(buckets)


async def track_calibration(
    predictions: list,
    tracker_id: str,
    store,  # LearningStore — duck-typed: requires update_calibration(tracker_id, dict)
) -> CalibrationResult:
    """Compute all calibration metrics and update the store."""
    verified_count = sum(1 for p in predictions if p.status != "PENDING")
    bs = compute_brier_score(predictions)
    da = compute_direction_accuracy(predictions)
    ece = compute_ece(predictions)
    buckets = compute_calibration_buckets(predictions)

    result = CalibrationResult(
        tracker_id=tracker_id,
        total_predictions=len(predictions),
        verified_predictions=verified_count,
        brier_score=bs if not math.isnan(bs) else 0.5,
        direction_accuracy=da if not math.isnan(da) else 0.5,
        ece=ece,
        calibration_buckets=buckets,
        platt_a=None,  # set once N>=50
        platt_b=None,
        needs_more_data=verified_count < 10,
    )

    store.update_calibration(tracker_id, {
        "total_predictions": result.total_predictions,
        "brier_score_cumulative": result.brier_score,
        "direction_accuracy": result.direction_accuracy,
        "ece": result.ece,
        "platt_a": result.platt_a,
        "platt_b": result.platt_b,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    })

    return result
