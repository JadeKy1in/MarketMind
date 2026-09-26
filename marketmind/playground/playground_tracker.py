"""Playground tracker — next-day settlement and performance tracking.

Compares each agent's past directional calls against actual market outcomes.
Maintains per-agent performance records in append-only JSONL format.

Only tracks agents that produce directional calls. Agents that produce
other output types (sentiment scores, regime labels, etc.) accumulate
their records but are not evaluated on direction accuracy.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("marketmind.playground.tracker")

PERFORMANCE_LOG_NAME = "playground_performance.jsonl"
DECISIONS_LOG_NAME = "playground_decisions.jsonl"


@dataclass
class SettledCall:
    """A single directional call that has been settled against actual return."""
    ticker: str
    direction: str           # "bullish" | "bearish"
    confidence: float
    call_date: str
    settlement_date: str
    actual_return_pct: float | None  # None if data unavailable
    correct: bool | None     # None if cannot determine
    pnl_bps: float | None    # basis points, signed by direction


@dataclass
class AgentPerformance:
    """Running performance record for a single agent."""
    agent_id: str
    computed_at: str
    total_calls: int
    settled_calls: int       # calls with available settlement data
    correct_calls: int
    direction_accuracy: float | None  # correct / settled
    cumulative_pnl_bps: float
    win_rate: float | None
    # Risk metrics (computed when sufficient data)
    sharpe_ratio: float | None = None
    max_drawdown_bps: float | None = None
    profit_factor: float | None = None
    # Metadata
    observation_days: int = 0
    first_call_date: str = ""
    last_call_date: str = ""

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "computed_at": self.computed_at,
            "total_calls": self.total_calls,
            "settled_calls": self.settled_calls,
            "correct_calls": self.correct_calls,
            "direction_accuracy": self.direction_accuracy,
            "cumulative_pnl_bps": self.cumulative_pnl_bps,
            "win_rate": self.win_rate,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown_bps": self.max_drawdown_bps,
            "profit_factor": self.profit_factor,
            "observation_days": self.observation_days,
            "first_call_date": self.first_call_date,
            "last_call_date": self.last_call_date,
        }


def _load_decisions(playground_dir: Path, agent_id: str | None = None,
                    since_date: str = "") -> list[dict]:
    """Load past decisions from the append-only audit log."""
    log_path = playground_dir / "data" / DECISIONS_LOG_NAME
    if not log_path.exists():
        return []
    decisions: list[dict] = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if agent_id and d.get("agent_id") != agent_id:
                continue
            if since_date and d.get("timestamp", "")[:10] < since_date:
                continue
            decisions.append(d)
    return decisions


def settle_calls(decisions: list[dict], shadow_db=None) -> list[SettledCall]:
    """Settle directional calls against actual next-day returns.

    For each directional call, looks up the actual return sign for the
    next trading day. A "bullish" call is correct if next-day return > 0.
    A "bearish" call is correct if next-day return < 0.

    Args:
        decisions: Raw decision records from the audit log.
        shadow_db: Shadow state DB with get_next_day_return_sign() method.
                   If None, calls are recorded with None settlement.

    Returns:
        List of SettledCall with settlement data where available.
    """
    settled: list[SettledCall] = []
    for dec in decisions:
        calls = dec.get("directional_calls", [])
        if not calls:
            # Agent doesn't produce directional calls — skip settlement
            continue
        call_date = dec.get("timestamp", "")[:10]
        for call in calls:
            ticker = call.get("ticker", "")
            direction = call.get("direction", "neutral")
            confidence = call.get("confidence", 0.5)

            if direction == "neutral" or not ticker:
                continue

            actual_sign = None
            if shadow_db and call_date:
                try:
                    actual_sign = shadow_db.get_next_day_return_sign(ticker, call_date)
                except Exception:
                    actual_sign = None

            correct = None
            pnl_bps = None
            if actual_sign is not None and actual_sign != 0:
                expected = 1 if direction == "bullish" else -1
                correct = (expected > 0 and actual_sign > 0) or (
                    expected < 0 and actual_sign < 0)
                # Simple PnL: if correct, +100bps * confidence; if wrong, -100bps * confidence
                pnl_bps = 100 * confidence if correct else -100 * confidence

            settled.append(SettledCall(
                ticker=ticker,
                direction=direction,
                confidence=confidence,
                call_date=call_date,
                settlement_date="",
                actual_return_pct=None,
                correct=correct,
                pnl_bps=pnl_bps,
            ))
    return settled


def _compute_sharpe(pnl_series: list[float]) -> float | None:
    """Compute annualized Sharpe ratio from a series of per-trade PnL in bps."""
    if len(pnl_series) < 5:
        return None
    import math
    mean = sum(pnl_series) / len(pnl_series)
    if mean == 0:
        return 0.0
    variance = sum((x - mean) ** 2 for x in pnl_series) / (len(pnl_series) - 1)
    if variance == 0:
        return 0.0
    std = math.sqrt(variance)
    # Annualize: assume avg 1 trade per day, 252 trading days
    return (mean / std) * math.sqrt(252) if std > 0 else 0.0


def _compute_max_drawdown(pnl_series: list[float]) -> float:
    """Compute maximum drawdown in bps from cumulative PnL."""
    if not pnl_series:
        return 0.0
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnl_series:
        cumulative += pnl
        peak = max(peak, cumulative)
        dd = peak - cumulative
        max_dd = max(max_dd, dd)
    return max_dd


def _compute_profit_factor(pnl_series: list[float]) -> float | None:
    """Ratio of gross profit to gross loss."""
    gross_profit = sum(x for x in pnl_series if x > 0)
    gross_loss = abs(sum(x for x in pnl_series if x < 0))
    if gross_loss == 0:
        return None if gross_profit == 0 else float('inf')
    return gross_profit / gross_loss


def compute_agent_performance(
    agent_id: str,
    playground_dir: Path | None = None,
    shadow_db=None,
    since_date: str = "",
) -> AgentPerformance:
    """Compute running performance for a single agent.

    Loads all past decisions, settles directional calls against actual
    returns, and computes standard performance metrics.

    Args:
        agent_id: Agent to compute performance for.
        playground_dir: Override playground directory.
        shadow_db: Shadow state DB for settlement data.
        since_date: Only consider decisions on or after this date (YYYY-MM-DD).

    Returns:
        AgentPerformance with all computed metrics.
    """
    pg_dir = playground_dir or Path(__file__).resolve().parent
    decisions = _load_decisions(pg_dir, agent_id=agent_id, since_date=since_date)
    settled = settle_calls(decisions, shadow_db)

    total_calls = len(settled)
    settled_calls = sum(1 for s in settled if s.correct is not None)
    correct_calls = sum(1 for s in settled if s.correct is True)
    accuracy = correct_calls / settled_calls if settled_calls > 0 else None

    pnl_series = [s.pnl_bps for s in settled if s.pnl_bps is not None]
    cumulative_pnl = sum(pnl_series)

    win_rate = None
    if pnl_series:
        wins = sum(1 for x in pnl_series if x > 0)
        win_rate = wins / len(pnl_series)

    dates = sorted(set(s.call_date for s in settled if s.call_date))
    observation_days = 0
    if len(dates) >= 2:
        try:
            first = datetime.strptime(dates[0], "%Y-%m-%d")
            last = datetime.strptime(dates[-1], "%Y-%m-%d")
            observation_days = (last - first).days
        except ValueError:
            pass

    return AgentPerformance(
        agent_id=agent_id,
        computed_at=datetime.now(timezone.utc).isoformat(),
        total_calls=total_calls,
        settled_calls=settled_calls,
        correct_calls=correct_calls,
        direction_accuracy=accuracy,
        cumulative_pnl_bps=cumulative_pnl,
        win_rate=win_rate,
        sharpe_ratio=_compute_sharpe(pnl_series),
        max_drawdown_bps=_compute_max_drawdown(pnl_series),
        profit_factor=_compute_profit_factor(pnl_series),
        observation_days=observation_days,
        first_call_date=dates[0] if dates else "",
        last_call_date=dates[-1] if dates else "",
    )


def compute_all_performances(
    playground_dir: Path | None = None,
    shadow_db=None,
) -> dict[str, AgentPerformance]:
    """Compute performance for all agents that have decisions recorded."""
    pg_dir = playground_dir or Path(__file__).resolve().parent
    decisions = _load_decisions(pg_dir)
    agent_ids = sorted(set(d.get("agent_id", "") for d in decisions if d.get("agent_id")))
    return {aid: compute_agent_performance(aid, pg_dir, shadow_db) for aid in agent_ids}


def record_performance(perf: AgentPerformance,
                       playground_dir: Path | None = None) -> None:
    """Append a performance snapshot to the performance log."""
    pg_dir = playground_dir or Path(__file__).resolve().parent
    log_path = pg_dir / "data" / PERFORMANCE_LOG_NAME
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(perf.to_dict(), ensure_ascii=False) + "\n")


def load_performance_history(agent_id: str,
                             playground_dir: Path | None = None) -> list[dict]:
    """Load all historical performance snapshots for an agent."""
    pg_dir = playground_dir or Path(__file__).resolve().parent
    log_path = pg_dir / "data" / PERFORMANCE_LOG_NAME
    if not log_path.exists():
        return []
    history: list[dict] = []
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
                history.append(d)
    return history
