"""Weekly tactical audit — Flash-driven pipeline stage health check.

Layer 2 of the main pipeline evolution system. Runs every 7 days using
Flash to audit stage-level performance trends and produce concrete
adjustment suggestions.

Modeled after shadows/ael_weekly_flash.py (shadow execution audit) but
applied to the main pipeline stages: Flash Triage → HVR → L1 → L2/L3 →
Red Team → Resonance → Decision.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from marketmind.pipeline.pipeline_metrics import load_recent_metrics, record_metrics

logger = logging.getLogger("marketmind.pipeline.weekly_audit")

REVIEW_WINDOW_DAYS = 7


@dataclass
class WeeklyAuditResult:
    week_start: str
    week_end: str
    days_with_data: int

    # Stage-level findings
    flash_findings: list[str] = field(default_factory=list)
    l1_findings: list[str] = field(default_factory=list)
    l2_l3_findings: list[str] = field(default_factory=list)
    red_team_findings: list[str] = field(default_factory=list)
    resonance_findings: list[str] = field(default_factory=list)
    decision_findings: list[str] = field(default_factory=list)

    # Actionable suggestions (1-2 bullets, injected into next week's prompts)
    suggestions: list[str] = field(default_factory=list)

    # Raw Flash response
    raw_response: str = ""


def _build_audit_prompt(metrics: list[dict]) -> str:
    """Build the audit user prompt from a week of pipeline metrics."""
    if not metrics:
        return "No pipeline data available for this week."

    lines: list[str] = []
    for m in metrics:
        date = m.get("date", "?")
        lines.append(
            f"{date}: "
            f"Flash(scored={m.get('flash_total_scored',0)} high_impact={m.get('flash_high_impact',0)} "
            f"avg_impact={m.get('flash_avg_impact',0):.1f}), "
            f"HVR(investigated={m.get('hvr_articles_investigated',0)} signals={m.get('hvr_signals_found',0)}), "
            f"L1(grade={m.get('l1_grade','?')} quadrant={m.get('l1_quadrant','?')} "
            f"direction={m.get('l1_direction','?')} price_in={m.get('l1_price_in',0):.2f}), "
            f"L2(candidates={m.get('l2_ticker_candidates',0)}) "
            f"L3(green={m.get('l3_green_lights',0)} yellow={m.get('l3_yellow_lights',0)} "
            f"red={m.get('l3_red_lights',0)}), "
            f"RedTeam(challenges={m.get('red_team_challenges',0)} severe={m.get('red_team_severe',0)}), "
            f"Resonance(dsr={m.get('resonance_dsr',0):.2f} pbo={m.get('resonance_pbo',0):.2f} "
            f"passed={m.get('resonance_passed',False)}), "
            f"Decision(cards={m.get('decision_cards',0)} no_trade={m.get('decision_no_trade',False)})"
        )
    return "\n".join(lines)


AUDIT_SYSTEM_PROMPT = """You are a pipeline performance auditor. Review the past week's metrics for each stage and identify:

1. **Flash Triage**: Are high-impact scores being validated by downstream? Is the impact threshold calibrated?
2. **HVR Investigation**: Is investigation producing incremental signals, or just burning API budget?
3. **L1 Narrative**: Are grade assignments consistent? Is the quadrant useful? Is price_in_score meaningful?
4. **L2/L3 Ticker Selection**: Green-light rate (green / total) — too strict (all red) or too loose (all green)?
5. **Red Team**: Are challenges being generated? Are severe challenges correlated with actual poor outcomes?
6. **Resonance**: Is DSR threshold appropriate? False-positive rate vs missed opportunity rate?
7. **Decision**: No-trade rate — too high (paralysis) or too low (overconfidence)?

For each stage, provide 1 finding. Then produce 1-2 actionable suggestions for next week.

Output JSON:
{
  "flash_finding": "One sentence on Flash Triage health",
  "l1_finding": "One sentence on L1 health",
  "l2_l3_finding": "One sentence on L2/L3 health",
  "red_team_finding": "One sentence on Red Team health",
  "resonance_finding": "One sentence on Resonance health",
  "decision_finding": "One sentence on Decision health",
  "suggestions": ["Suggestion 1", "Suggestion 2"],
  "overall": "One sentence overall assessment"
}"""


async def run_weekly_audit(shadow_db=None) -> WeeklyAuditResult | None:
    """Run the weekly tactical audit using Flash.

    Loads the past 7 days of pipeline metrics, sends them to Flash for
    analysis, and returns structured findings with actionable suggestions.

    Returns None if insufficient data (fewer than 3 days of metrics).
    """
    metrics = load_recent_metrics(days=REVIEW_WINDOW_DAYS)
    if len(metrics) < 3:
        logger.info("Weekly audit: insufficient data (%d days < 3)", len(metrics))
        return None

    today = datetime.now(timezone.utc).date()
    week_start = (today - timedelta(days=REVIEW_WINDOW_DAYS)).isoformat()
    week_end = today.isoformat()

    user_prompt = (
        f"Week: {week_start} to {week_end}\n"
        f"Days with data: {len(metrics)}\n\n"
        f"{_build_audit_prompt(metrics)}\n\n"
        f"Audit each stage and provide suggestions. Return ONLY JSON."
    )

    try:
        from marketmind.gateway.async_client import chat_flash

        result = await chat_flash(
            system_prompt=AUDIT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=2048,
        )
        content = result.get("content", "") if isinstance(result, dict) else str(result)
    except Exception as exc:
        logger.warning("Weekly audit Flash call failed: %s", exc)
        return None

    parsed = _parse_audit_response(content)
    return WeeklyAuditResult(
        week_start=week_start,
        week_end=week_end,
        days_with_data=len(metrics),
        flash_findings=[parsed.get("flash_finding", "")],
        l1_findings=[parsed.get("l1_finding", "")],
        l2_l3_findings=[parsed.get("l2_l3_finding", "")],
        red_team_findings=[parsed.get("red_team_finding", "")],
        resonance_findings=[parsed.get("resonance_finding", "")],
        decision_findings=[parsed.get("decision_finding", "")],
        suggestions=parsed.get("suggestions", []),
        raw_response=content,
    )


def _parse_audit_response(content: str) -> dict:
    """Parse Flash audit response JSON."""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:]) if len(lines) > 1 else content
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
    content = re.sub(r",\s*([}\]])", r"\1", content)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(content[start:end + 1])
            except json.JSONDecodeError:
                pass
    return {}


def get_suggestion_context(shadow_db=None) -> str:
    """Get the weekly audit suggestions for injection into prompts.

    Called by the orchestrator before L1 analysis. If a weekly audit has been
    run recently, its suggestions are injected as calibration context.

    Returns empty string if no audit data or audit is stale (>7 days).
    """
    from pathlib import Path

    audit_dir = Path(__file__).resolve().parent.parent / ".claude" / "metrics"
    audit_path = audit_dir / "weekly_audit_latest.json"
    if not audit_path.exists():
        return ""

    try:
        with open(audit_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return ""

    audit_date = data.get("week_end", "")
    if not audit_date:
        return ""

    try:
        audit_dt = datetime.strptime(audit_date, "%Y-%m-%d").date()
        age = (datetime.now(timezone.utc).date() - audit_dt).days
        if age > 7:
            return ""
    except ValueError:
        return ""

    suggestions = data.get("suggestions", [])
    if not suggestions:
        return ""

    lines = ["## Weekly Tactical Audit Suggestions"]
    for s in suggestions:
        lines.append(f"- {s}")
    lines.append("(Apply these in today's analysis)\n")
    return "\n".join(lines)


def save_latest_audit(result: WeeklyAuditResult) -> None:
    """Save the most recent audit result for prompt injection."""
    from pathlib import Path

    audit_dir = Path(__file__).resolve().parent.parent / ".claude" / "metrics"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / "weekly_audit_latest.json"

    data = {
        "week_start": result.week_start,
        "week_end": result.week_end,
        "suggestions": result.suggestions,
        "flash_findings": result.flash_findings,
        "l1_findings": result.l1_findings,
        "l2_l3_findings": result.l2_l3_findings,
        "red_team_findings": result.red_team_findings,
        "resonance_findings": result.resonance_findings,
        "decision_findings": result.decision_findings,
    }
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
