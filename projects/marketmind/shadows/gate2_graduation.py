"""Gate 2 graduation — exam registry, ELITE fallback, interactive discussion.

Phase L Phase 4 — Plan §4. Custom exam registry + ELITE fallback for Gate 2.
States: pending_design → exam_scheduled → in_progress → passed|failed.
Failed → retry_pending (30d). Timeout 14d → deferred.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from marketmind.shadows.shadow_state import ShadowStateDB

logger = logging.getLogger("marketmind.shadows.gate2_graduation")

EXAM_STATES = [
    "pending_design", "exam_scheduled", "in_progress",
    "passed", "failed", "retry_pending", "deferred",
]
EXAM_RETRY_COOLDOWN_DAYS = 30
EXAM_NOTIFICATION_TIMEOUT_DAYS = 14
_REGISTRY_PATH = "data/shadows/exam_registry.json"

@dataclass
class ExamState:
    """Per-shadow exam state, persisted to exam_registry.json."""
    shadow_id: str
    state: str = "pending_design"
    first_notified_at: str | None = None
    failed_at: str | None = None
    deferred_at: str | None = None
    exam_config: dict | None = None
    result_history: list[dict] = field(default_factory=list)

@dataclass
class ExamResult:
    """Single exam execution result — user assigns final pass/fail."""
    shadow_id: str
    exam_type: str
    passed: bool
    score: float
    details: dict = field(default_factory=dict)
    executed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

# ── Registry persistence ───────────────────────────────────────────────────

def _load_registry() -> dict[str, ExamState]:
    path = Path(_REGISTRY_PATH)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load exam registry")
        return {}
    return {
        sid: ExamState(shadow_id=sid, **{k: v for k, v in data.items() if k != "shadow_id"})
        for sid, data in raw.items()
    }

def _save_registry(registry: dict[str, ExamState]) -> None:
    path = Path(_REGISTRY_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = {sid: {k: v for k, v in asdict(es).items() if k != "shadow_id"} for sid, es in registry.items()}
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")

def _days_since(date_str: str | None) -> int:
    if not date_str:
        return 0
    return max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(date_str)).days)

def _get_exam_state(shadow_id: str) -> ExamState:
    registry = _load_registry()
    if shadow_id not in registry:
        registry[shadow_id] = ExamState(shadow_id=shadow_id)
        _save_registry(registry)
    return registry[shadow_id]

def _set_exam_state(shadow_id: str, state: str) -> None:
    if state not in EXAM_STATES:
        raise ValueError(f"Invalid exam state '{state}'")
    registry = _load_registry()
    entry = registry.get(shadow_id, ExamState(shadow_id=shadow_id))
    old = entry.state
    entry.state = state
    registry[shadow_id] = entry
    _save_registry(registry)
    logger.info("Exam state '%s': %s → %s", shadow_id, old, state)


# ── Public API ─────────────────────────────────────────────────────────────

def check_exam_notification(shadow_id: str) -> bool:
    """Notify for pending_design/retry_pending. Auto-timeout >14d→deferred.

    Deferred→retry_pending after 30d. Failed→retry_pending after 30d. Tier check upstream."""

    es = _get_exam_state(shadow_id)
    now = datetime.now(timezone.utc).isoformat()

    if es.state == "failed" and _days_since(es.failed_at) >= EXAM_RETRY_COOLDOWN_DAYS:
        _set_exam_state(shadow_id, "retry_pending")
        es = _get_exam_state(shadow_id)
    if es.state == "deferred" and _days_since(es.deferred_at) >= 30:
        _set_exam_state(shadow_id, "retry_pending")
        es = _get_exam_state(shadow_id)

    if es.state not in ("pending_design", "retry_pending"):
        return False

    registry = _load_registry()
    if es.first_notified_at is None:
        es.first_notified_at = now
        registry[shadow_id] = es
        _save_registry(registry)

    if _days_since(es.first_notified_at) > EXAM_NOTIFICATION_TIMEOUT_DAYS:
        es.state = "deferred"
        es.deferred_at = now
        registry[shadow_id] = es
        _save_registry(registry)
        logger.info("Exam notification for '%s' auto-deferred (>14d)", shadow_id)
        return False
    return True


def reset_exam_on_demotion(shadow_id: str, old_tier: str, new_tier: str) -> None:
    """Reset exam state on ELITE→non-ELITE demotion.

    Graduated (passed) → retry_pending (retake same exam).
    Net-new ELITE → pending_design (fresh exam design).
    """
    if old_tier != "elite" or new_tier == "elite":
        return
    es = _get_exam_state(shadow_id)
    new_state = "retry_pending" if es.state == "passed" else "pending_design"
    _set_exam_state(shadow_id, new_state)
    logger.info("Exam reset on demotion '%s' %s→%s: %s", shadow_id, old_tier, new_tier, new_state)


async def get_graduated_shadows(state_db: ShadowStateDB, session_id: str) -> list[dict]:
    """Return graduated shadows (exam_state=passed + currently ELITE) for Gate 2."""
    registry = _load_registry()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result: list[dict] = []
    for shadow_id, es in registry.items():
        if es.state != "passed":
            continue
        config = state_db.get_shadow(shadow_id)
        if config is None:
            continue
        latest = state_db.get_latest_snapshot(shadow_id)
        if latest is None or (latest.achievement_tier or "").lower() != "elite":
            continue
        analysis_done = latest.date == today and (latest.insights_generated or 0) > 0
        result.append({
            "shadow_id": shadow_id, "display_name": config.display_name,
            "shadow_type": config.shadow_type, "tier": latest.achievement_tier,
            "domain": getattr(config, "domain", "macro"),
            "analysis_done": analysis_done,
            "status": "ready" if analysis_done else "analyzing",
            "exam_config": es.exam_config,
        })
    return result


async def get_elite_fallback(state_db: ShadowStateDB) -> list[dict]:
    """ELITE fallback: when zero shadows graduated, return ELITE static analysis."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    elites: list[dict] = []
    for config in state_db.get_active_shadows():
        latest = state_db.get_latest_snapshot(config.shadow_id)
        if latest is None or (latest.achievement_tier or "").lower() != "elite":
            continue
        elites.append({
            "shadow_id": config.shadow_id, "display_name": config.display_name,
            "shadow_type": config.shadow_type, "tier": latest.achievement_tier,
            "domain": getattr(config, "domain", "macro"),
            "win_rate": round((latest.win_rate_pct or 0) / 100.0, 4),
            "cumulative_return": round((latest.cumulative_return_pct or 0) / 100.0, 4),
            "composite_score": latest.composite_score,
            "analysis_date": latest.date,
            "analysis_done": latest.date == today and (latest.insights_generated or 0) > 0,
        })
    return elites


async def run_exam(shadow_id: str, exam_config: dict) -> list[ExamResult]:
    """Execute exam for one shadow based on configured exam type.

    Exam types: historical_backtest, stress_test, cross_domain_challenge,
    data_blind_test (auto); thesis_defense (semi-auto).
    System executes, collects data, presents to user for final judgment.
    """
    exam_type = exam_config.get("type", "historical_backtest")
    params = exam_config.get("params", {})
    _set_exam_state(shadow_id, "in_progress")
    logger.info("Exam '%s' started for '%s'", exam_type, shadow_id)
    try:
        results = await _run_exam_type(shadow_id, exam_type, params)
        registry = _load_registry()
        if shadow_id in registry and results:
            registry[shadow_id].result_history.append(asdict(results[0]))
            _save_registry(registry)
        logger.info("Exam '%s' completed for '%s'", exam_type, shadow_id)
        return results
    except Exception:
        logger.exception("Exam '%s' failed for '%s'", exam_type, shadow_id)
        _set_exam_state(shadow_id, "pending_design")
        raise


# ── Exam runners (stubs, wired in Phase 4 integration) ────────────────────
async def _run_exam_type(shadow_id: str, exam_type: str, params: dict) -> list[ExamResult]:
    em = lambda **kw: ExamResult(shadow_id=shadow_id, exam_type=exam_type, passed=False, score=0.0, details=kw)
    if exam_type == "historical_backtest":
        return [em(ticker=params.get("ticker", "SPY"),
                   start_date=params.get("start_date", "2020-01-01"),
                   end_date=params.get("end_date", "2020-12-31"),
                   note="Backtest data collected. Awaiting user judgment.")]
    elif exam_type == "stress_test":
        scenarios = params.get("scenarios", ["gfc_2008", "covid_2020", "rate_hike_2022"])
        return [em(scenarios=scenarios,
                   note=f"Stress test ({len(scenarios)} scenarios) completed. Awaiting user judgment.")]
    elif exam_type == "cross_domain_challenge":
        target = params.get("target_domain", "crypto")
        return [em(target_domain=target,
                   note=f"Cross-domain challenge ({target}) completed. Awaiting user judgment.")]
    elif exam_type == "data_blind_test":
        event = params.get("event_date", "2024-08-05")
        return [em(event_date=event,
                   note=f"Blind test on event {event} completed. Awaiting user judgment.")]
    elif exam_type == "thesis_defense":
        topics = params.get("topics", ["methodology_rationale", "risk_management", "edge_sustainability"])
        return [em(topics=topics, mode="semi_auto",
                   note="Questions prepared. User conducts interactive defense.",
                   suggested_questions=[
                       "Explain the core logic of your investment methodology.",
                       "Under what market conditions does your strategy underperform?",
                       "Describe your risk management framework and position sizing rules.",
                       "What is your edge? How do you verify it persists?",
                       "If you could change one thing about your approach, what would it be?",
                   ])]
    else:
        raise ValueError(f"Unknown exam type: {exam_type}")
