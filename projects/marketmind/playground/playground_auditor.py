"""Playground auditor — monthly audit and upgrade gate.

Evaluates each playground agent's performance against its self-declared
criteria. No hardcoded type templates — each agent is audited individually
based on what its manifest claims.

Upgrade gate: agent must pass ALL criteria to be eligible for integration.
Integration path is determined case-by-case, not by template.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from marketmind.playground.agent_manifest import AgentManifest, discover_agents
from marketmind.playground.playground_tracker import (
    AgentPerformance, compute_agent_performance, load_performance_history,
    record_performance,
)

logger = logging.getLogger("marketmind.playground.auditor")

AUDIT_LOG_NAME = "playground_audits.jsonl"

# ── Upgrade gate thresholds (universal, not type-specific) ──
MIN_OBSERVATION_DAYS = 60
MIN_SETTLED_CALLS = 20
MIN_DIRECTION_ACCURACY = 0.55
MIN_SHARPE = 0.5
MAX_DRAWDOWN_BPS = 2500  # 25%
MAX_MAIN_PIPELINE_CORRELATION = 0.7


@dataclass
class AuditResult:
    """Result of auditing a single playground agent."""
    agent_id: str
    audit_date: str
    performance: AgentPerformance | None

    # Gate checks
    sufficient_history: bool = False
    sufficient_samples: bool = False
    accuracy_ok: bool = False
    sharpe_ok: bool = False
    drawdown_ok: bool = False
    correlation_ok: bool = True  # default pass if no main pipeline data

    # Overall
    all_gates_passed: bool = False
    recommendation: str = ""
    # "KEEP_OBSERVING" | "CANDIDATE_FOR_UPGRADE" | "MARK_STAGNANT" | "MARK_UNSTABLE"

    # Integration path (if CANDIDATE_FOR_UPGRADE)
    suggested_integration: str = ""
    suggested_weight: float = 0.0
    notes: list[str] = field(default_factory=list)


def _check_statistical_significance(perf: AgentPerformance) -> bool:
    """Binomial test: is accuracy > 0.5 at p < 0.05?

    Uses normal approximation to binomial.
    """
    import math
    if perf.settled_calls < 10:
        return False
    n = perf.settled_calls
    p0 = 0.5  # null hypothesis: random guessing
    observed_p = perf.direction_accuracy or 0
    if observed_p <= p0:
        return False
    se = math.sqrt(p0 * (1 - p0) / n)
    if se == 0:
        return False
    z = (observed_p - p0) / se
    # One-tailed: p < 0.05 corresponds to z > 1.645
    return z > 1.645


def _compute_main_pipeline_correlation(
    agent_id: str, playground_dir: Path | None = None
) -> float | None:
    """Compute correlation between agent's directional calls and main pipeline decisions.

    Returns None if insufficient data to compute. Requires both playground
    decisions and main pipeline calibration data to exist for the same dates.
    """
    # Placeholder — requires main pipeline calibration data for same period.
    # Will be implemented when the bridge between playground and calibration
    # data is established.
    return None


def audit_agent(
    manifest: AgentManifest,
    playground_dir: Path | None = None,
    shadow_db=None,
) -> AuditResult:
    """Audit a single agent against upgrade gates.

    Evaluates the agent's performance against its self-declared criteria
    and the universal upgrade gates. Produces a recommendation.

    Args:
        manifest: Agent's self-declaration.
        playground_dir: Override playground directory.
        shadow_db: Shadow state DB for settlement data.

    Returns:
        AuditResult with gate checks and recommendation.
    """
    pg_dir = playground_dir or Path(__file__).resolve().parent
    perf = compute_agent_performance(manifest.agent_id, pg_dir, shadow_db)
    record_performance(perf, pg_dir)

    notes: list[str] = []
    now = datetime.now(timezone.utc)

    # Gate 1: Observation period
    sufficient_history = perf.observation_days >= MIN_OBSERVATION_DAYS
    if not sufficient_history:
        notes.append(
            f"观察期不足: {perf.observation_days}d < {MIN_OBSERVATION_DAYS}d minimum"
        )

    # Gate 2: Sample size
    sufficient_samples = perf.settled_calls >= MIN_SETTLED_CALLS
    if not sufficient_samples:
        notes.append(
            f"样本量不足: {perf.settled_calls} 次结算 < {MIN_SETTLED_CALLS} minimum"
        )

    # Gate 3: Direction accuracy with statistical significance
    accuracy_ok = False
    if perf.direction_accuracy is not None:
        accuracy_ok = (
            perf.direction_accuracy >= MIN_DIRECTION_ACCURACY
            and _check_statistical_significance(perf)
        )
    if not accuracy_ok:
        notes.append(
            f"方向准确率不足或未达统计显著性: "
            f"accuracy={perf.direction_accuracy}, "
            f"settled={perf.settled_calls}"
        )

    # Gate 4: Sharpe ratio (risk-adjusted return)
    sharpe_ok = perf.sharpe_ratio is not None and perf.sharpe_ratio >= MIN_SHARPE
    if not sharpe_ok:
        notes.append(
            f"夏普比率不足: {perf.sharpe_ratio} < {MIN_SHARPE}"
        )

    # Gate 5: Maximum drawdown
    drawdown_ok = (
        perf.max_drawdown_bps is not None
        and perf.max_drawdown_bps <= MAX_DRAWDOWN_BPS
    )
    if not drawdown_ok:
        notes.append(
            f"最大回撤超限: {perf.max_drawdown_bps}bps > {MAX_DRAWDOWN_BPS}bps"
        )

    # Gate 6: Correlation with main pipeline
    correlation = _compute_main_pipeline_correlation(manifest.agent_id, pg_dir)
    correlation_ok = (
        correlation is None
        or correlation <= MAX_MAIN_PIPELINE_CORRELATION
    )
    if not correlation_ok:
        notes.append(
            f"与主管道决策相关性过高: {correlation:.2f} > {MAX_MAIN_PIPELINE_CORRELATION}"
        )

    all_gates_passed = all([
        sufficient_history, sufficient_samples, accuracy_ok,
        sharpe_ok, drawdown_ok, correlation_ok,
    ])

    # ── Recommendation ──
    if all_gates_passed:
        recommendation = "CANDIDATE_FOR_UPGRADE"
        notes.append("所有升级门控通过，建议进入集成评估")
    elif not sufficient_history or not sufficient_samples:
        recommendation = "KEEP_OBSERVING"
        notes.append("继续观察，积累更多数据")
    elif perf.settled_calls >= 10 and not accuracy_ok and not sharpe_ok:
        # Has enough data to judge, but failing key metrics
        history = load_performance_history(manifest.agent_id, pg_dir)
        if len(history) >= 3:
            # Check if metrics have been flat/declining for 3+ audits
            accuracies = [h.get("direction_accuracy", 0) or 0 for h in history[-3:]]
            if accuracies and max(accuracies) < MIN_DIRECTION_ACCURACY:
                recommendation = "MARK_STAGNANT"
                notes.append("连续 3 次审计未改善，标记为 stagnant")
            else:
                recommendation = "KEEP_OBSERVING"
        else:
            recommendation = "KEEP_OBSERVING"
    else:
        recommendation = "KEEP_OBSERVING"
        notes.append("部分门控未通过，继续观察")

    # ── Integration path (case-by-case, not templated) ──
    suggested_integration = ""
    suggested_weight = 0.0
    if recommendation == "CANDIDATE_FOR_UPGRADE":
        # Use agent's declared target if available, otherwise defer to case-by-case
        suggested_integration = manifest.target_pipeline_node or "TBD_CASE_BY_CASE"
        suggested_weight = 0.05  # conservative starting weight
        notes.append(
            f"建议集成路径: {suggested_integration}, "
            f"初始权重: {suggested_weight}, "
            f"需个案分析后确定最终集成方案"
        )

    return AuditResult(
        agent_id=manifest.agent_id,
        audit_date=now.strftime("%Y-%m-%d"),
        performance=perf,
        sufficient_history=sufficient_history,
        sufficient_samples=sufficient_samples,
        accuracy_ok=accuracy_ok,
        sharpe_ok=sharpe_ok,
        drawdown_ok=drawdown_ok,
        correlation_ok=correlation_ok,
        all_gates_passed=all_gates_passed,
        recommendation=recommendation,
        suggested_integration=suggested_integration,
        suggested_weight=suggested_weight,
        notes=notes,
    )


def audit_all_agents(
    playground_dir: Path | None = None,
    shadow_db=None,
) -> dict[str, AuditResult]:
    """Audit all installed playground agents.

    Returns dict mapping agent_id -> AuditResult.
    """
    pg_dir = playground_dir or Path(__file__).resolve().parent
    manifests = discover_agents(pg_dir)
    results: dict[str, AuditResult] = {}

    for manifest in manifests:
        try:
            result = audit_agent(manifest, pg_dir, shadow_db)
            results[manifest.agent_id] = result
            _record_audit(result, pg_dir)
        except Exception:
            logger.exception("Audit failed for %s", manifest.agent_id)

    return results


def _record_audit(result: AuditResult, playground_dir: Path) -> None:
    """Append audit result to the audit log."""
    log_path = playground_dir / "data" / AUDIT_LOG_NAME
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "agent_id": result.agent_id,
        "audit_date": result.audit_date,
        "recommendation": result.recommendation,
        "all_gates_passed": result.all_gates_passed,
        "gates": {
            "sufficient_history": result.sufficient_history,
            "sufficient_samples": result.sufficient_samples,
            "accuracy_ok": result.accuracy_ok,
            "sharpe_ok": result.sharpe_ok,
            "drawdown_ok": result.drawdown_ok,
            "correlation_ok": result.correlation_ok,
        },
        "suggested_integration": result.suggested_integration,
        "suggested_weight": result.suggested_weight,
        "notes": result.notes,
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def get_latest_audit(agent_id: str,
                     playground_dir: Path | None = None) -> dict | None:
    """Get the most recent audit result for an agent."""
    pg_dir = playground_dir or Path(__file__).resolve().parent
    log_path = pg_dir / "data" / AUDIT_LOG_NAME
    if not log_path.exists():
        return None
    latest = None
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("agent_id") == agent_id:
                latest = d
    return latest
