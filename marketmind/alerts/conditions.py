"""Big-move alert decision (docs/S8_DESIGN.md, SPEC_v3 §10; owner decisions 2026-09-29).
Pure code, no LLM.

Trunk: an alert candidate is an owner-executable instrument whose trend state switched
today - CASH/WATCH/EXIT -> TREND ("entry", long) or TREND -> CASH/WATCH/EXIT ("exit") -
as reported by the configured trend-signal source (alerts/trend_source.py).

Annotations (never required, never blocking):
- advisor votes, aggregated by asset group (alerts/asset_groups.py): each voter's latest
  decision in the group within WINDOW_DAYS with hold >= MIN_VOTE_HOLD_BARS. The alert's
  direction is long for an entry and short for an exit.
    no_votes   nobody voted in the group
    vetoed     strictly more than half of the voters voted against  (flag shown)
    supported  >= MIN_SUPPORT voters for, from >= MIN_SUPPORT_GROUPS roster groups,
               and voters against <= MAX_OPPOSE_RATIO x voters for
    weak       anything else
- evidence: evidence-layer divergence records in the same group within WINDOW_DAYS; the
  ones in the alert's direction are a supporting note, the others are listed as against.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from marketmind.alerts import config as C
from marketmind.alerts.asset_groups import asset_group
from marketmind.alerts.trend_source import TREND, WATCH, TrendReading

ENTRY, EXIT = "entry", "exit"
VOTER_SOURCES = ("shadow", "playground")
SUPPORTED, VETOED, WEAK, NO_VOTES = "supported", "vetoed", "weak", "no_votes"
STATUS_CN = {SUPPORTED: "顾问支持", VETOED: "顾问反对（否决标记）", WEAK: "支持不足",
             NO_VOTES: "无顾问意见"}


@dataclass
class Candidate:
    ticker: str
    kind: str                                   # entry | exit | watch (near miss)
    group: str
    trend: dict = field(default_factory=dict)   # the source's state record
    votes_for: list[dict] = field(default_factory=list)
    votes_against: list[dict] = field(default_factory=list)
    status: str = NO_VOTES
    evidence: list[dict] = field(default_factory=list)          # in the alert's direction
    evidence_against: list[dict] = field(default_factory=list)

    @property
    def direction(self) -> str:
        return "short" if self.kind == EXIT else "long"

    @property
    def roster_groups(self) -> list[str]:
        return sorted({v["group"] for v in self.votes_for})

    @property
    def key(self) -> str:
        """Identity of the trend event, for de-duplication across runs."""
        t = self.trend
        when = t.get("entry_signal_date") if self.kind == ENTRY else None
        return f"{self.ticker}:{self.kind}:{when or t.get('as_of')}"


def _recent(entries, now: datetime, days: int = C.WINDOW_DAYS):
    cutoff = (now - timedelta(days=days)).isoformat()
    return [e for e in entries if e.created_at >= cutoff]


def group_votes(entries, now: datetime, voters: dict[str, str]) -> dict[str, dict[str, list[dict]]]:
    """asset group -> {"long": [...], "short": [...]}: each voter's latest qualifying
    decision in the group (hold >= MIN_VOTE_HOLD_BARS, within WINDOW_DAYS)."""
    latest: dict[tuple[str, str], object] = {}
    for e in _recent(entries, now):
        if e.source_type not in VOTER_SOURCES or e.source_id not in voters:
            continue
        if (e.hold_bars or 0) < C.MIN_VOTE_HOLD_BARS or e.direction not in ("long", "short"):
            continue
        key = (asset_group(e.ticker), e.source_id)
        if key not in latest or e.created_at > latest[key].created_at:
            latest[key] = e
    out: dict[str, dict[str, list[dict]]] = {}
    for (group, sid), e in sorted(latest.items()):
        out.setdefault(group, {"long": [], "short": []})[e.direction].append(
            {"voter": sid, "group": voters[sid], "ticker": e.ticker.upper(),
             "entry_id": e.entry_id, "hold_bars": e.hold_bars, "confidence": e.confidence})
    return out


def vote_status(votes_for: list[dict], votes_against: list[dict]) -> str:
    n_for, n_against = len(votes_for), len(votes_against)
    voting = n_for + n_against
    if voting == 0:
        return NO_VOTES
    if n_against > voting / 2:
        return VETOED
    if (n_for >= C.MIN_SUPPORT and len({v["group"] for v in votes_for}) >= C.MIN_SUPPORT_GROUPS
            and n_against <= C.MAX_OPPOSE_RATIO * n_for):
        return SUPPORTED
    return WEAK


def group_evidence(entries, now: datetime) -> dict[str, dict[str, list[dict]]]:
    out: dict[str, dict[str, list[dict]]] = {}
    for e in _recent(entries, now):
        if e.source_type != "evidence" or e.direction not in ("long", "short"):
            continue
        out.setdefault(asset_group(e.ticker), {"long": [], "short": []})[e.direction].append(
            {"entry_id": e.entry_id, "ticker": e.ticker.upper(),
             "claim": (e.meta or {}).get("claim", ""), "type": (e.meta or {}).get("claim_type")})
    return out


def annotate(c: Candidate, votes: dict, evidence: dict) -> Candidate:
    v = votes.get(c.group, {"long": [], "short": []})
    ev = evidence.get(c.group, {"long": [], "short": []})
    against = "long" if c.direction == "short" else "short"
    c.votes_for, c.votes_against = list(v[c.direction]), list(v[against])
    c.status = vote_status(c.votes_for, c.votes_against)
    c.evidence, c.evidence_against = list(ev[c.direction]), list(ev[against])
    return c


def evaluate(reading: TrendReading, entries, now: datetime, voters: dict[str, str],
             tradable, include=lambda t: True) -> tuple[list[Candidate], list[Candidate], list[dict]]:
    """(alerts, near misses, skipped). Alerts = today's entries / exits of executable
    instruments passing `include`; near misses = executable WATCH instruments (one
    breakout away). `skipped` lists changes dropped as not owner-executable."""
    if not reading.available:
        return [], [], []
    votes, evidence = group_votes(entries, now, voters), group_evidence(entries, now)
    alerts: list[Candidate] = []
    skipped: list[dict] = []
    for kind, tickers in ((ENTRY, reading.entries), (EXIT, reading.exits)):
        for t in sorted(set(tickers)):
            if not include(t):
                continue
            state = reading.states.get(t, {})
            if not tradable(t):
                skipped.append({"ticker": t, "kind": kind, "reason": "所有人无法执行"})
                continue
            alerts.append(annotate(Candidate(t, kind, asset_group(t), dict(state)), votes, evidence))
    near = [annotate(Candidate(t, "watch", asset_group(t), dict(s)), votes, evidence)
            for t, s in sorted(reading.states.items())
            if s.get("state") == WATCH and include(t) and tradable(t)]
    alerts.sort(key=lambda c: (c.kind != EXIT, c.status != SUPPORTED, c.ticker))
    return alerts, near, skipped


__all__ = ["Candidate", "ENTRY", "EXIT", "TREND", "WATCH", "evaluate", "group_votes",
           "group_evidence", "vote_status", "annotate", "STATUS_CN"]
