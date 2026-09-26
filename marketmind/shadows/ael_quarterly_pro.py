"""Quarterly Pro AEL — structural bias detection and methodology rewrite gate.

Layer 3: Every 90d via Pro. Detects methodology drift, domain overfitting,
collusion risk, source stagnation. Rewrite needs 2-of-3 sign-off (Quarterly
AEL + Monthly AEL + Human). Human absent >14d → auto-defer. Max 1 rewrite/yr.
If multiple reviews propose rewrites, Q4 wins (most data).
"""
from __future__ import annotations
import logging, re
from dataclasses import dataclass, field
from datetime import datetime, timezone
logger = logging.getLogger("marketmind.shadows.ael_quarterly_pro")
HUMAN_ABSENT_DAYS = 14
MAX_REWRITES_PER_YEAR = 1

@dataclass
class QuarterlyStructuralReview:
    """Output from one quarterly Pro structural bias review."""
    shadow_id: str
    quarter: str
    methodology_drift_score: float
    domain_overfitting: bool
    collusion_risk: float
    source_stagnation: bool
    rewrite_proposed: bool
    rewrite_text: str = ""
    signoffs: dict = field(default_factory=lambda: {
        "quarterly_ael": False, "monthly_ael": False, "human": False,
    })
    deferred: bool = False
    defer_reason: str = ""

async def run_quarterly_review(
    shadow_id: str, state_db,
    monthly_debriefs: list | None = None,
    weekly_reports: list | None = None,
    *, human_last_active_at: str | None = None,
) -> QuarterlyStructuralReview | None:
    """Run quarterly structural bias review. Aggregates 3 monthly debriefs
    + 12 weekly Flash reports. Uses Pro for deep structural analysis."""
    config = state_db.get_shadow(shadow_id)
    if config is None:
        logger.warning("ael_quarterly_pro: shadow %s not found", shadow_id)
        return None
    quarter = _quarter()
    methodology = config.methodology_prompt or ""
    debriefs = monthly_debriefs or []
    reports = weekly_reports or []
    # Q4 wins rule: only Q4 applies rewrites. Non-Q4 proposals unconditionally deferred.
    if not quarter.endswith("Q4"):
        logger.info("ael_quarterly_pro: %s — non-Q4, deferring rewrite proposal to Q4", shadow_id)
        # Still run analysis (no early return) — just block rewrite_proposed at output
    # Q4: proceed with full analysis and rewrite capability

    monthly_ctx = _fmt(debriefs[-3:], "month", "win_rate", "failure_patterns",
                       lambda d: f"WR={getattr(d,'win_rate',0):.1%} "
                       f"fails={len(getattr(d,'failure_patterns',[]) or [])}")
    weekly_ctx = _fmt(reports[-12:], "week_start", "snorkel_z_score",
                      "corrections",
                      lambda r: f"z={getattr(r,'snorkel_z_score',0):.2f} "
                      f"c={getattr(r,'methodology_compliance',0):.2f} "
                      f"{len(getattr(r,'corrections',[]) or [])}crx")
    if not monthly_ctx and not weekly_ctx:
        logger.debug("ael_quarterly_pro: no data for %s", shadow_id)
        return None

    from marketmind.gateway.async_client import chat_with_integrity
    try:
        r = await chat_with_integrity(
            model="pro", system_prompt=_SYSTEM,
            user_prompt=_USER.format(shadow_id=shadow_id, quarter=quarter,
                methodology=methodology[:3000], monthly_context=monthly_ctx,
                weekly_context=weekly_ctx),
            caller_agent=f"ael_quarterly:{shadow_id}", temperature=0.3,
            reasoning_effort="max")
        content = r.get("content", "")
    except Exception as e:
        logger.error("ael_quarterly_pro: Pro failed for %s: %s", shadow_id, e)
        return None

    p = _parse(content)
    rewrite_proposed = bool(
        quarter.endswith("Q4") and  # Q4 wins: only Q4 can propose rewrites
        _rewrites_this_year(state_db, shadow_id) < MAX_REWRITES_PER_YEAR and
        p["rewrite_text"].strip() and (
            p["methodology_drift_score"] >= 0.6 or p["domain_overfitting"]
            or p["collusion_risk"] >= 0.6 or p["source_stagnation"]))
    signoffs = {"quarterly_ael": rewrite_proposed,
                "monthly_ael": _monthly_concurs(debriefs[-3:]), "human": False}
    deferred = False
    defer_reason = ""
    if rewrite_proposed and sum(1 for v in signoffs.values() if v) < 2:
        if human_last_active_at and _days_since(human_last_active_at) > HUMAN_ABSENT_DAYS:
            deferred = True
            defer_reason = f"Human absent >{HUMAN_ABSENT_DAYS}d. Deferred to {_next_quarter()}."
    return QuarterlyStructuralReview(
        shadow_id=shadow_id, quarter=quarter,
        methodology_drift_score=p["methodology_drift_score"],
        domain_overfitting=p["domain_overfitting"],
        collusion_risk=p["collusion_risk"],
        source_stagnation=p["source_stagnation"],
        rewrite_proposed=rewrite_proposed, rewrite_text=p["rewrite_text"],
        signoffs=signoffs, deferred=deferred, defer_reason=defer_reason)

# ── Prompts ─────────────────────────────────────────────────────────────────────
_SYSTEM = """\
You are a structural methodology auditor. Analyze across four dimensions:
1. METHODOLOGY DRIFT (0-1): Approach shifted from stated methodology?
2. DOMAIN OVERFITTING (YES/NO): Overly specific to one regime/sector?
3. COLLUSION RISK (0-1): Similar reasoning to other shadows (echoing)?
4. SOURCE STAGNATION (YES/NO): Same data sources, no diversification?

If structural issues are severe, provide REWRITE_TEXT (max 200 words).
Output strictly:
DRIFT: <0.XX>
OVERFITTING: <YES|NO>
COLLUSION: <0.XX>
STAGNATION: <YES|NO>
REWRITE_TEXT: <revised methodology or NONE>
REASONING: <2-3 sentence summary>"""
_USER = """\
Shadow: {shadow_id} | Quarter: {quarter}
METHODOLOGY: {methodology}
MONTHLY DEBRIEFS: {monthly_context}
WEEKLY REPORTS: {weekly_context}
Analyze for structural biases. Provide REWRITE_TEXT only if severe issues found."""

# ── Helpers ─────────────────────────────────────────────────────────────────────
def _fmt(items: list, date_attr: str, _score_attr: str, _list_attr: str,
         fmt_fn) -> str:
    if not items:
        return f"(No data)"
    return "\n".join(f"  [{getattr(i, date_attr, '?')}] {fmt_fn(i)}" for i in items)


def _parse(text: str) -> dict:
    def _f(pat):  # extract float
        m = re.search(pat, text)
        try: return float(m.group(1))
        except (ValueError, TypeError, AttributeError): return 0.0
    def _b(pat):  # extract boolean
        m = re.search(pat, text, re.I)
        return bool(m and "YES" in m.group(1).upper())
    rewrite = ""
    m = re.search(r'REWRITE_TEXT:\s*\n?(.*?)(?=\n[A-Z_]+:\s|$)', text, re.DOTALL)
    if m:
        c = m.group(1).strip()
        if c.upper() != "NONE" and len(c) > 10:
            rewrite = c[:2000]
    return {
        "methodology_drift_score": min(1.0, max(0.0, _f(r'DRIFT:\s*([\d.]+)'))),
        "domain_overfitting": _b(r'OVERFITTING:\s*(YES|NO)'),
        "collusion_risk": min(1.0, max(0.0, _f(r'COLLUSION:\s*([\d.]+)'))),
        "source_stagnation": _b(r'STAGNATION:\s*(YES|NO)'),
        "rewrite_text": rewrite}


def _monthly_concurs(debriefs: list) -> bool:
    """Monthly AEL signs off if any recent debrief flagged failure patterns."""
    return any(getattr(d, "failure_patterns", None) for d in debriefs)


def _days_since(iso_str: str) -> int:
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except (ValueError, TypeError):
        return 0


def _quarter() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year}-Q{(now.month - 1) // 3 + 1}"


def _next_quarter() -> str:
    now = datetime.now(timezone.utc)
    q = (now.month - 1) // 3 + 2
    yr = now.year + (q - 1) // 4
    return f"{yr}-Q{(q - 1) % 4 + 1}"


def _rewrites_this_year(state_db, shadow_id: str) -> int:
    try:
        history = state_db.get_methodology_history(shadow_id, limit=50)
    except Exception:
        return 0
    if not history:
        return 0
    yr = str(datetime.now(timezone.utc).year)
    return sum(1 for e in history
               if isinstance(e, dict)
               and "quarterly_rewrite" in str(e.get("change_type", ""))
               and yr in str(e.get("changed_at", "")))
