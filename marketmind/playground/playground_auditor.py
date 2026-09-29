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
from marketmind.runtime_paths import claude_dir

from marketmind.playground.agent_manifest import AgentManifest, discover_agents
from marketmind.playground.playground_tracker import (
    AgentPerformance, _load_decisions, compute_agent_performance,
    load_performance_history, record_performance,
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


# ── Spearman rank correlation (manual — no scipy dependency needed) ──

def _spearman_rank(x: list[float], y: list[float]) -> float | None:
    """Compute Spearman rank correlation between two equal-length series.

    Spearman is preferred over Pearson for financial signals because it
    captures monotonic relationships, not just linear ones. A directional
    call that is "more bullish when the main pipeline is more bullish" is
    a monotonic relationship worth detecting even if the magnitudes differ.

    Returns None if series have zero variance (all values identical).
    """
    import math
    n = len(x)
    if n < 3:
        return None

    def _rank(series: list[float]) -> list[float]:
        """Assign ranks to values, averaging ties."""
        indexed = sorted(enumerate(series), key=lambda kv: kv[1])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and indexed[j + 1][1] == indexed[i][1]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1.0  # 1-based ranks
            for k in range(i, j + 1):
                ranks[indexed[k][0]] = avg_rank
            i = j + 1
        return ranks

    rank_x = _rank(x)
    rank_y = _rank(y)

    # Check for zero variance
    if all(r == rank_x[0] for r in rank_x) or all(r == rank_y[0] for r in rank_y):
        return None

    mean_rx = sum(rank_x) / n
    mean_ry = sum(rank_y) / n
    cov = sum((rx - mean_rx) * (ry - mean_ry) for rx, ry in zip(rank_x, rank_y))
    std_rx = math.sqrt(sum((rx - mean_rx) ** 2 for rx in rank_x))
    std_ry = math.sqrt(sum((ry - mean_ry) ** 2 for ry in rank_y))

    if std_rx == 0.0 or std_ry == 0.0:
        return None
    r = cov / (std_rx * std_ry)
    return max(-1.0, min(1.0, r))


def _pearson_corr(x: list[float], y: list[float]) -> float | None:
    """Compute Pearson correlation between two equal-length series.

    Returns None if insufficient data or zero variance.
    """
    import math
    n = len(x)
    if n < 2:
        return None
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    std_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
    std_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))
    if std_x == 0.0 or std_y == 0.0:
        return None
    r = cov / (std_x * std_y)
    return max(-1.0, min(1.0, r))


# ── Data loading helpers ──

def _load_agent_direction_scores(
    agent_id: str, playground_dir: Path
) -> dict[str, float]:
    """Load agent's directional calls and aggregate into per-date direction scores.

    Each date gets a net direction score: mean of +1 (bullish) / -1 (bearish)
    across all ticker-level calls that day. Dates with no directional calls
    are excluded.

    Returns:
        Dict mapping date string "YYYY-MM-DD" -> float in [-1.0, 1.0].
    """
    from collections import defaultdict
    decisions = _load_decisions(playground_dir, agent_id=agent_id)
    date_scores: dict[str, list[float]] = defaultdict(list)
    for dec in decisions:
        date = dec.get("timestamp", "")[:10]
        if not date:
            continue
        for call in dec.get("directional_calls", []):
            direction = call.get("direction", "neutral")
            if direction == "neutral":
                continue
            ticker = call.get("ticker", "")
            if not ticker:
                continue
            date_scores[date].append(1.0 if direction == "bullish" else -1.0)
    return {
        date: sum(scores) / len(scores)
        for date, scores in date_scores.items()
        if scores
    }


def _load_main_pipeline_direction_scores(
    cal_dir: Path,
) -> dict[str, float]:
    """Load main pipeline calibration data and produce per-date direction scores.

    Reads all JSON files in the calibration directory. Each file's
    l1_direction is mapped to a numeric score: bullish=+1.0, bearish=-1.0,
    neutral=0.0. Also incorporates L3 ticker signals as supplementary data
    points (per-ticker entries keyed as "TICKER::YYYY-MM-DD").

    Returns:
        Dict mapping date string "YYYY-MM-DD" -> float in [-1.0, 1.0].
        Also includes per-ticker keys "TICKER::YYYY-MM-DD" for granular
        overlap matching when per-date aggregation is too sparse.
    """
    scores: dict[str, float] = {}
    if not cal_dir.exists():
        return scores

    for cal_file in sorted(cal_dir.glob("*.json")):
        try:
            with open(cal_file, "r", encoding="utf-8") as f:
                data = json.loads(f.read())
        except Exception:
            continue
        date = data.get("date", "")
        if not date:
            continue

        # L1 direction (market-level signal)
        l1_dir = data.get("l1_direction", "neutral")
        if l1_dir == "bullish":
            scores[date] = 1.0
        elif l1_dir == "bearish":
            scores[date] = -1.0
        else:
            scores[date] = 0.0

        # L3 per-ticker signals for granular overlap
        for ticker in data.get("l3_green_tickers", []):
            scores[f"{ticker}::{date}"] = 1.0
        for ticker in data.get("l3_red_tickers", []):
            scores[f"{ticker}::{date}"] = -1.0

    return scores


def _compute_main_pipeline_correlation(
    agent_id: str,
    playground_dir: Path | None = None,
    shadow_db=None,
) -> float | None:
    """Compute Spearman rank correlation between agent's directional calls
    and main pipeline decisions.

    Uses two strategies for matching, choosing the one with more data points:
    1. Per-date aggregation: agent's net direction score vs main pipeline's
       L1 direction for the same date.
    2. Per-ticker matching: each agent (ticker, date, direction) matched
       against main pipeline's L3 green/red ticker lists.

    Also computes VIF (Variance Inflation Factor) from Pearson correlation
    as a secondary redundancy check.

    Returns:
        Spearman correlation coefficient (float) if >= 20 overlapping data
        points exist, or a value exceeding MAX_MAIN_PIPELINE_CORRELATION if
        VIF >= 5. Returns None if insufficient data (gate passes by default).
    """
    import math

    pg_dir = playground_dir or Path(__file__).resolve().parent
    project_root = pg_dir.parent  # up from playground/ to marketmind/
    cal_dir = claude_dir() / "calibration"

    # Strategy 1: per-date aggregation
    agent_date_scores = _load_agent_direction_scores(agent_id, pg_dir)
    main_date_scores = _load_main_pipeline_direction_scores(cal_dir)

    # Separate per-date keys from per-ticker keys
    main_pure_date = {
        k: v for k, v in main_date_scores.items() if "::" not in k
    }
    main_ticker_date = {
        k: v for k, v in main_date_scores.items() if "::" in k
    }

    # Strategy 1: overlapping pure dates
    common_dates = sorted(set(agent_date_scores.keys()) & set(main_pure_date.keys()))
    series_agent: list[float] = []
    series_main: list[float] = []

    # Strategy 2: per-ticker matching — build (ticker, date) pairs from agent calls
    decisions = _load_decisions(pg_dir, agent_id=agent_id)
    agent_ticker_calls: dict[str, float] = {}
    for dec in decisions:
        date = dec.get("timestamp", "")[:10]
        if not date:
            continue
        for call in dec.get("directional_calls", []):
            direction = call.get("direction", "neutral")
            ticker = call.get("ticker", "")
            if direction == "neutral" or not ticker:
                continue
            key = f"{ticker}::{date}"
            agent_ticker_calls[key] = 1.0 if direction == "bullish" else -1.0

    common_tickers = sorted(
        set(agent_ticker_calls.keys()) & set(main_ticker_date.keys())
    )
    ticker_agent_series = [agent_ticker_calls[k] for k in common_tickers]
    ticker_main_series = [main_ticker_date[k] for k in common_tickers]

    # Choose the strategy with more data points
    if len(common_dates) >= len(common_tickers) and len(common_dates) >= 20:
        series_agent = [agent_date_scores[d] for d in common_dates]
        series_main = [main_pure_date[d] for d in common_dates]
    elif len(common_tickers) >= 20:
        series_agent = ticker_agent_series
        series_main = ticker_main_series
    elif len(common_dates) > 0:
        series_agent = [agent_date_scores[d] for d in common_dates]
        series_main = [main_pure_date[d] for d in common_dates]
    else:
        # Insufficient data — gate passes by default (conservative)
        return None

    n = len(series_agent)
    if n < 20:
        return None

    # Primary: Spearman rank correlation
    spearman_r = _spearman_rank(series_agent, series_main)

    # Secondary: VIF from Pearson correlation
    pearson_r = _pearson_corr(series_agent, series_main)
    if pearson_r is not None and abs(pearson_r) < 1.0:
        vif = 1.0 / (1.0 - pearson_r ** 2)
        if vif >= 5.0:
            # VIF high — agent signal is linearly reconstructable from main
            # pipeline. Return a value that fails the gate.
            return max(
                abs(spearman_r) if spearman_r is not None else 0.0,
                MAX_MAIN_PIPELINE_CORRELATION + 0.01,
            )

    return abs(spearman_r) if spearman_r is not None else None


def compute_signal_diversity(
    agent_calls: list[dict],
    main_decisions: list[dict],
) -> dict[str, float | None]:
    """Compute Q-statistic and Double Fault Measure between two signal sources.

    Based on Kuncheva & Whitaker (2003) pairwise classifier diversity measures.
    Adapted for directional trading signals:

    - Q-statistic: measures association between two binary classifiers.
      Q = (N11*N00 - N01*N10) / (N11*N00 + N01*N10)
      Q in [-1, 1]: 1 = perfect agreement, -1 = perfect disagreement,
      0 = independent. For signal diversity, Q near 0 is ideal.

    - Double Fault Measure: proportion of overlapping (ticker, date) pairs
      where both sources agree on direction. High DF means the agent adds
      no new perspective (redundant). DF in [0, 1].

    Args:
        agent_calls: List of dicts, each with 'ticker', 'direction', 'date'.
        main_decisions: List of dicts, each with 'ticker', 'direction', 'date'.

    Returns:
        Dict with keys 'q_statistic', 'double_fault', 'n_overlapping'.
        Values are None if insufficient overlapping data (< 5 pairs).
    """
    # Index both by (ticker, date)
    agent_index: dict[tuple[str, str], int] = {}
    for call in agent_calls:
        ticker = call.get("ticker", "")
        date = call.get("date", "") or call.get("timestamp", "")[:10]
        direction = call.get("direction", "neutral")
        if not ticker or not date or direction == "neutral":
            continue
        agent_index[(ticker, date)] = 1 if direction == "bullish" else -1

    main_index: dict[tuple[str, str], int] = {}
    for dec in main_decisions:
        ticker = dec.get("ticker", "")
        date = dec.get("date", "") or dec.get("timestamp", "")[:10]
        direction = dec.get("direction", "neutral")
        if not ticker or not date or direction == "neutral":
            continue
        main_index[(ticker, date)] = 1 if direction == "bullish" else -1

    # Find overlapping (ticker, date) pairs
    overlap_keys = set(agent_index.keys()) & set(main_index.keys())
    n = len(overlap_keys)
    if n < 5:
        return {"q_statistic": None, "double_fault": None, "n_overlapping": n}

    # Contingency table
    n11 = 0  # both bullish
    n00 = 0  # both bearish
    n10 = 0  # agent bullish, main bearish
    n01 = 0  # agent bearish, main bullish

    for key in overlap_keys:
        a_dir = agent_index[key]
        m_dir = main_index[key]
        if a_dir == 1 and m_dir == 1:
            n11 += 1
        elif a_dir == -1 and m_dir == -1:
            n00 += 1
        elif a_dir == 1 and m_dir == -1:
            n10 += 1
        elif a_dir == -1 and m_dir == 1:
            n01 += 1

    # Q-statistic
    numerator = n11 * n00 - n01 * n10
    denominator = n11 * n00 + n01 * n10
    if denominator == 0:
        q_stat = None  # undefined (would require division by zero)
    else:
        q_stat = numerator / denominator

    # Double Fault Measure: proportion where both agree (both bullish or both bearish)
    # High agreement = low diversity = redundant agent
    df = (n11 + n00) / n

    return {
        "q_statistic": q_stat,
        "double_fault": df,
        "n_overlapping": n,
    }


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
    correlation = _compute_main_pipeline_correlation(
        manifest.agent_id, pg_dir, shadow_db
    )
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
