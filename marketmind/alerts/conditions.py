"""Big-move alert conditions (docs/S8_DESIGN.md, SPEC_v3 §10). Pure code, no LLM.

A  advisors agree : >= 3 advisors long the same ticker within 5 days, from >= 2
                    roster groups, with shorts at most half the longs
B  evidence       : an evidence-layer divergence record on the same ticker and
                    direction within 5 days
C  trend          : L3 three lights green
Only owner-executable instruments (Robinhood-tradable, no options), long only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

WINDOW_DAYS = 5
MIN_ADVISORS = 3
MIN_GROUPS = 2
MAX_SHORT_RATIO = 0.5


@dataclass
class Candidate:
    ticker: str
    a_ok: bool = False
    b_ok: bool = False
    c_ok: bool | None = None           # None = not evaluated (A and B both false)
    advisors_long: list[dict] = field(default_factory=list)
    advisors_short: list[dict] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    l3: dict = field(default_factory=dict)

    @property
    def met(self) -> int:
        return int(self.a_ok) + int(self.b_ok) + int(bool(self.c_ok))

    @property
    def fired(self) -> bool:
        return self.a_ok and self.b_ok and bool(self.c_ok)


def _recent(entries, now: datetime, days: int = WINDOW_DAYS):
    cutoff = (now - timedelta(days=days)).isoformat()
    return [e for e in entries if e.created_at >= cutoff]


def advisor_votes(entries, now: datetime, advisors: dict[str, str],
                  tradable) -> dict[str, dict[str, list[dict]]]:
    """ticker -> {"long": [...], "short": [...]} of the latest vote per advisor."""
    latest: dict[tuple[str, str], object] = {}
    for e in _recent(entries, now):
        if e.source_type != "shadow" or e.source_id not in advisors:
            continue
        key = (e.ticker.upper(), e.source_id)
        if key not in latest or e.created_at > latest[key].created_at:
            latest[key] = e
    votes: dict[str, dict[str, list[dict]]] = {}
    for (ticker, sid), e in latest.items():
        if not tradable(ticker):
            continue
        votes.setdefault(ticker, {"long": [], "short": []})[e.direction].append(
            {"shadow_id": sid, "group": advisors[sid], "entry_id": e.entry_id,
             "confidence": e.confidence})
    return votes


def check_a(v: dict[str, list[dict]]) -> tuple[bool, list[str]]:
    longs, shorts = v.get("long", []), v.get("short", [])
    groups = sorted({x["group"] for x in longs})
    ok = (len(longs) >= MIN_ADVISORS and len(groups) >= MIN_GROUPS
          and len(shorts) <= MAX_SHORT_RATIO * len(longs))
    return ok, groups


def evidence_for(entries, now: datetime) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for e in _recent(entries, now):
        if e.source_type == "evidence" and e.direction == "long":
            out.setdefault(e.ticker.upper(), []).append(
                {"entry_id": e.entry_id, "claim": (e.meta or {}).get("claim", ""),
                 "type": (e.meta or {}).get("claim_type")})
    return out


def trend_ok(snap) -> tuple[bool, dict]:
    if snap is None:
        return False, {"available": False}
    return snap.light == "green", {
        "available": True, "light": snap.light, "close": snap.close, "as_of": snap.as_of,
        "entry_low": snap.entry_low, "entry_high": snap.entry_high, "stop": snap.stop_loss,
        "target": snap.target_price, "reward_risk": snap.reward_risk_ratio,
        "recommendation": snap.recommendation}


async def evaluate(entries, now: datetime, advisors: dict[str, str], tradable,
                   snapshot_fn) -> list[Candidate]:
    """All tickers with at least one condition met; C is only computed where A or B holds."""
    votes = advisor_votes(entries, now, advisors, tradable)
    evidence = {t: ev for t, ev in evidence_for(entries, now).items() if tradable(t)}
    out = []
    for ticker in sorted(set(votes) | set(evidence)):
        v = votes.get(ticker, {"long": [], "short": []})
        a_ok, groups = check_a(v)
        c = Candidate(ticker, a_ok=a_ok, b_ok=bool(evidence.get(ticker)),
                      advisors_long=v["long"], advisors_short=v["short"], groups=groups,
                      evidence=evidence.get(ticker, []))
        if c.a_ok or c.b_ok:
            c.c_ok, c.l3 = trend_ok(await snapshot_fn(ticker))
        if c.met >= 1:
            out.append(c)
    out.sort(key=lambda c: (-c.met, -len(c.advisors_long), c.ticker))
    return out
