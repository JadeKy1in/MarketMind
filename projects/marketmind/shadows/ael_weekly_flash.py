"""AEL Layer 1: Weekly Flash tactical review — execution quality audit.

Runs every 7 days using Flash model. Focus: did shadow follow methodology?
Were votes placed correctly? Exit conditions honored?

Snorkel Rule: critique only when confidence >= 70%. Uses z-score of daily
returns vs historical baseline. Output: 1-2 bullet corrections per shadow,
max 5 active, promoted to monthly Pro if persisted 2+ consecutive weeks.
"""
from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("marketmind.shadows.ael_weekly_flash")

REVIEW_WINDOW_DAYS = 7
HISTORICAL_BASELINE_DAYS = 90
Z_DEVIATION = -1.5       # z-score below which we flag deviation
Z_CLEAN = -1.0           # z-score above which we skip entirely
COMPLIANCE_LOW = 0.70    # below this → likely methodology mistake
COMPLIANCE_HIGH = 0.90   # above this → regime noise (not the shadow's fault)
MIN_CONFIDENCE = 0.70    # minimum confidence to emit a critique


@dataclass
class WeeklyFlashReview:
    """Output from one weekly Flash tactical review."""
    shadow_id: str
    week_start: str
    week_end: str
    corrections: list[str] = field(default_factory=list)  # 1-2 bullets
    snorkel_z_score: float = 0.0
    methodology_compliance: float = 0.0
    confidence: float = 0.0
    skipped: bool = False    # True when snorkel rule suppresses critique


async def run_weekly_flash_review(
    shadow_id: str,
    state_db,
    *,
    week_start: str = "",
    week_end: str = "",
) -> WeeklyFlashReview | None:
    """Run 7-day tactical review for one shadow. Returns None if insufficient history."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week_end = week_end or today
    week_start = week_start or (
        datetime.now(timezone.utc) - timedelta(days=REVIEW_WINDOW_DAYS)
    ).strftime("%Y-%m-%d")

    # Fetch snapshots
    snapshots = state_db.get_snapshot_history(shadow_id, days=HISTORICAL_BASELINE_DAYS)
    if not snapshots:
        logger.debug("ael_weekly_flash: no snapshots for %s", shadow_id)
        return None
    recent = [s for s in snapshots if week_start <= s.date <= week_end]
    if len(recent) < 3:
        logger.debug("ael_weekly_flash: %s has only %d recent days", shadow_id, len(recent))
        return None

    # Compute z-score of recent daily returns vs historical baseline
    hist_rets = _returns(snapshots)
    recent_rets = _returns(recent)
    z = _z_score(recent_rets, hist_rets)

    # Snorkel: no deviation → skip immediately
    if z > Z_CLEAN:
        return _review(shadow_id, week_start, week_end, z_score=z, skipped=True)

    # Fetch trades within the 7-day review window only
    all_trades = state_db.get_trade_history(shadow_id, limit=REVIEW_WINDOW_DAYS * 3)
    trades = [t for t in (all_trades or [])
              if hasattr(t, 'date') and week_start <= t.date <= week_end]
    config = state_db.get_shadow(shadow_id)
    methodology = config.methodology_prompt if config else ""

    compliance, confidence = await _check_compliance(
        shadow_id, methodology, trades, recent, week_start, week_end
    )

    # Snorkel decision matrix
    if z < Z_DEVIATION:
        if compliance >= COMPLIANCE_HIGH:
            return _review(shadow_id, week_start, week_end, z_score=z,
                           compliance=compliance, skipped=True)
        if compliance < COMPLIANCE_LOW and confidence >= MIN_CONFIDENCE:
            corrections = await _generate_corrections(
                shadow_id, methodology, trades, recent, week_start, week_end, z, compliance
            )
            return _review(shadow_id, week_start, week_end, z_score=z,
                           compliance=compliance, confidence=confidence,
                           corrections=corrections)

    return _review(shadow_id, week_start, week_end, z_score=z,
                   compliance=compliance, skipped=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _review(shadow_id, ws, we, *, z_score=0.0, compliance=0.0, confidence=0.0,
            corrections=None, skipped=False):
    """Shorthand constructor for WeeklyFlashReview."""
    return WeeklyFlashReview(
        shadow_id=shadow_id, week_start=ws, week_end=we,
        corrections=corrections or [], snorkel_z_score=z_score,
        methodology_compliance=compliance, confidence=confidence, skipped=skipped,
    )


def _returns(snapshots: list) -> list[float]:
    return [s.daily_return_pct for s in snapshots if s.daily_return_pct is not None]


def _z_score(recent: list[float], historical: list[float]) -> float:
    if len(historical) < 5 or not recent:
        return 0.0
    hist_mean = statistics.mean(historical)
    hist_std = statistics.pstdev(historical)
    if hist_std == 0.0:
        return 0.0
    return (statistics.mean(recent) - hist_mean) / hist_std


def _trades_text(trades: list) -> str:
    if not trades:
        return "No trades."
    lines = []
    for t in trades[:20]:
        pnl = f"{t.pnl_pct:+.2f}%" if t.pnl_pct is not None else "OPEN"
        lines.append(f"  {t.ticker} {t.direction.upper()} entry={t.entry_price:.2f} "
                     f"exit={t.exit_price or 'N/A'} pnl={pnl} reason={t.exit_reason or 'N/A'}")
    return "\n".join(lines)


def _snapshots_text(snapshots: list) -> str:
    lines = []
    for s in sorted(snapshots, key=lambda x: x.date):
        ret = f"{s.daily_return_pct:+.2f}%" if s.daily_return_pct is not None else "N/A"
        wr = f"{s.win_rate_pct:.1f}%" if s.win_rate_pct is not None else "N/A"
        lines.append(f"  {s.date}: ret={ret} wr={wr} tier={s.achievement_tier or 'N/A'}")
    return "\n".join(lines)


async def _check_compliance(shadow_id, methodology, trades, snapshots, ws, we):
    """Flash: assess methodology compliance. Returns (compliance, confidence)."""
    from marketmind.gateway.async_client import chat_with_integrity

    sys = (
        "You are a methodology compliance auditor. Compare a shadow agent's "
        "stated methodology against its actual trades for the past week. "
        "Rate compliance 0.0-1.0 and your confidence 0.0-1.0.\n"
        "Focus: (1) Did trades match stated approach? (2) Exit conditions honored? "
        "(3) Position sizing consistent with methodology?\n"
        "Output: COMPLIANCE: <0.XX>\nCONFIDENCE: <0.XX>\nBRIEF_REASON: <one sentence>"
    )
    user = (
        f"Shadow: {shadow_id}\nWindow: {ws} to {we}\n\n"
        f"METHODOLOGY:\n{methodology[:1500] or 'No methodology.'}\n\n"
        f"TRADES:\n{_trades_text(trades)}\n\n"
        f"SNAPSHOTS:\n{_snapshots_text(snapshots)}\n\n"
        f"Assess compliance and confidence."
    )
    try:
        r = await chat_with_integrity(
            model="flash", system_prompt=sys, user_prompt=user,
            caller_agent=f"ael_weekly_flash:compliance:{shadow_id}", temperature=0.2,
        )
        return _parse_compliance(r.get("content", ""))
    except Exception:
        logger.warning("ael_weekly_flash: compliance failed for %s", shadow_id, exc_info=True)
        return (0.0, 0.0)


async def _generate_corrections(shadow_id, methodology, trades, snapshots,
                                ws, we, z, compliance):
    """Flash: generate 1-2 actionable bullet corrections."""
    from marketmind.gateway.async_client import chat_with_integrity

    sys = (
        "You are a tactical execution coach. The shadow had poor returns AND low "
        "methodology compliance — likely execution mistake. Produce 1-2 ACTIONABLE "
        "bullet corrections (max 60 chars each). Specific behavior changes only. "
        "No hedge language. One bullet per line, starting with '- '."
    )
    user = (
        f"Shadow: {shadow_id}\nWeek: {ws}-{we}\n"
        f"Z-score: {z:.2f} Compliance: {compliance:.2f}\n\n"
        f"METHODOLOGY:\n{methodology[:1500]}\n\n"
        f"TRADES:\n{_trades_text(trades)}\n\n"
        f"Generate 1-2 specific corrections."
    )
    try:
        r = await chat_with_integrity(
            model="flash", system_prompt=sys, user_prompt=user,
            caller_agent=f"ael_weekly_flash:correct:{shadow_id}", temperature=0.2,
        )
        return _parse_bullets(r.get("content", ""))
    except Exception:
        logger.warning("ael_weekly_flash: corrections failed for %s", shadow_id, exc_info=True)
        return []


def _parse_compliance(text: str) -> tuple[float, float]:
    comp = _extract_float(r'COMPLIANCE:\s*([\d.]+)', text)
    conf = _extract_float(r'CONFIDENCE:\s*([\d.]+)', text)
    return (comp, conf)


def _extract_float(pattern: str, text: str) -> float:
    m = re.search(pattern, text)
    if m:
        try:
            return min(1.0, max(0.0, float(m.group(1))))
        except ValueError:
            pass
    return 0.0


def _parse_bullets(text: str) -> list[str]:
    lines = [l.strip() for l in text.split("\n") if l.strip().startswith("-")]
    return [l.lstrip("- ").strip() for l in lines if len(l) > 2][:2]
