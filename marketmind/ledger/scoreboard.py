"""Per-source scores from the unified ledger (docs/S4_DESIGN.md).

Pure aggregation over LedgerEntry rows, no I/O. Return-based fields use settled
rows only and are None (not 0) when nothing has settled yet.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean

from marketmind.ledger.store import LedgerEntry

MIN_POSITION_USD = 100.0
PROBATION_DAYS = 60     # SPEC §8: >= 60 trading days before any promotion review


@dataclass
class SourceScore:
    source_type: str
    source_id: str
    records: int
    pending: int
    open: int
    settled: int
    void: int
    wins: int
    win_rate: float | None
    mean_net_return: float | None
    total_pnl_usd: float | None
    mean_excess_market: float | None
    mean_excess_domain: float | None
    mean_brier: float | None
    min_position_share: float
    first_date: str | None
    last_date: str | None
    active_days: int

    def to_dict(self) -> dict:
        return asdict(self)


def _avg(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(mean(vals), 6) if vals else None


def score(entries: list[LedgerEntry]) -> SourceScore:
    first = entries[0]
    by_status = {s: 0 for s in ("pending", "open", "settled", "void")}
    for e in entries:
        by_status[e.status] = by_status.get(e.status, 0) + 1
    settled = [e for e in entries if e.status == "settled"]
    wins = sum(1 for e in settled if (e.net_return or 0) > 0)
    days = sorted({e.created_at[:10] for e in entries if e.created_at})
    pnl = [e.pnl_usd for e in settled if e.pnl_usd is not None]
    return SourceScore(
        source_type=first.source_type, source_id=first.source_id, records=len(entries),
        pending=by_status["pending"], open=by_status["open"],
        settled=by_status["settled"], void=by_status["void"],
        wins=wins, win_rate=round(wins / len(settled), 4) if settled else None,
        mean_net_return=_avg([e.net_return for e in settled]),
        total_pnl_usd=round(sum(pnl), 2) if pnl else None,
        mean_excess_market=_avg([e.excess_market for e in settled]),
        mean_excess_domain=_avg([e.excess_domain for e in settled]),
        # An unstated confidence (the flagged 0.5 default, e.g. the forced trade) is not
        # a forecast, so it is not scored (owner decision 2026-09-29).
        mean_brier=_avg([e.brier for e in settled if not e.confidence_is_default]),
        min_position_share=round(
            sum(1 for e in entries if e.position_usd <= MIN_POSITION_USD) / len(entries), 4),
        first_date=days[0] if days else None, last_date=days[-1] if days else None,
        active_days=len(days),
    )


def scoreboard(entries: list[LedgerEntry]) -> list[SourceScore]:
    """One score per (source_type, source_id), sorted by type then id."""
    groups: dict[tuple[str, str], list[LedgerEntry]] = {}
    for e in entries:
        groups.setdefault((e.source_type, e.source_id), []).append(e)
    return [score(groups[k]) for k in sorted(groups)]


def benchmark_id_for(shadow_id: str) -> str:
    """Source id of a shadow's same-domain random benchmark (shadows/v3/runner.py)."""
    return f"random:{shadow_id}"
