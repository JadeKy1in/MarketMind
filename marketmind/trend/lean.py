"""Lean trend variant (docs/TREND_DESIGN.md §8, pre-registered 2026-09-29).

Asset-class representatives plus one "strongest sector" slot, at most one position per
correlated group, and an optional stricter entry filter (12-month excess-return rank).
Entry and exit rules are the merged design's, run by the same per-instrument
`state.Stepper`; this module only decides which entry signals are taken. A signal that
is not taken leaves the instrument flat (WATCH) - no phantom position - so it can enter
on a later breakout. With no gating the joint simulation equals `state.simulate`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Callable, Sequence

from marketmind.gateway.price_history import Bar
from marketmind.trend.rules import TrendConfig
from marketmind.trend.state import (
    SimResult, Stepper, TrendState, state_from_sim, unavailable_state,
)

LEAN_CORE: tuple[str, ...] = ("SPY", "QQQ", "GLD", "TLT", "USO", "BTC-USD", "ETH-USD")
SECTORS: tuple[str, ...] = ("XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "SMH")
SECTOR_SLOT = "SECTOR"          # stands for "whichever sector is strongest" inside a group

VETO_SECTOR = "not the strongest sector"
VETO_GROUP = "group already holds a position"
VETO_RANK = "12m excess-return rank"
VETO_PEER = "a stronger group member signalled the same day"


@dataclass(frozen=True)
class LeanConfig:
    core: tuple[str, ...] = LEAN_CORE
    sectors: tuple[str, ...] = SECTORS
    groups: tuple[tuple[str, ...], ...] = (("SPY", "QQQ", SECTOR_SLOT), ("BTC-USD", "ETH-USD"))
    top_n: int | None = None           # stricter filter: rank among core + strongest sector
    strongest_only: bool = True        # only the strongest sector may signal
    one_per_group: bool = True

    @property
    def tickers(self) -> tuple[str, ...]:
        return self.core + self.sectors

    def group_of(self, ticker: str) -> str:
        key = SECTOR_SLOT if ticker in self.sectors else ticker
        for g in self.groups:
            if key in g:
                return "+".join(g)
        return ticker


NO_GATING = LeanConfig(strongest_only=False, one_per_group=False)


@dataclass
class LeanResult:
    sims: dict[str, SimResult]
    strongest: dict[str, str] = field(default_factory=dict)     # date -> strongest sector
    vetoes: list[dict] = field(default_factory=list)            # signals not taken

    def last_strongest(self) -> str | None:
        return self.strongest[max(self.strongest)] if self.strongest else None


def simulate_lean(data: dict[str, Sequence[Bar]], cfg: TrendConfig,
                  hurdle: float | Callable[[str], float] = 0.0,
                  lean: LeanConfig = LeanConfig()) -> LeanResult:
    """Joint replay over the union calendar. `data` holds complete daily bars; tickers
    outside `lean.tickers` or with no bars are ignored."""
    tickers = [t for t in lean.tickers if data.get(t)]
    steps = {t: Stepper(t, data[t], cfg, hurdle) for t in tickers}
    pos = {t: {b.date: i for i, b in enumerate(data[t])} for t in tickers}
    last: dict[str, int] = {}
    out = LeanResult({t: s.res for t, s in steps.items()})
    sectors = [t for t in tickers if t in lean.sectors]
    for d in sorted({b.date for t in tickers for b in data[t]}):
        today = {t: pos[t][d] for t in tickers if d in pos[t]}
        last.update(today)
        ready = [t for t, i in today.items() if steps[t].manage(i)]

        def xs(t: str) -> float | None:
            return steps[t].excess(last[t]) if t in last else None

        ranked_sectors = [(xs(s), s) for s in sectors if xs(s) is not None]
        strongest = max(ranked_sectors)[1] if ranked_sectors else None
        if strongest is not None and any(s in today for s in sectors):
            out.strongest[d] = strongest
        signals = [t for t in ready if steps[t].signal(today[t])]
        if not signals:
            continue
        top: set[str] | None = None
        if lean.top_n:
            pool = [t for t in lean.core if t in steps] + ([strongest] if strongest else [])
            scored = sorted(((xs(t), t) for t in pool if xs(t) is not None), reverse=True)
            top = {t for _, t in scored[:lean.top_n]}
        held = {lean.group_of(t) for t in tickers if steps[t].open_trade is not None}
        chosen: dict[str, str] = {}
        for t in signals:
            why = None
            if lean.strongest_only and t in lean.sectors and t != strongest:
                why = f"{VETO_SECTOR} ({strongest})"
            elif top is not None and t not in top:
                why = f"{VETO_RANK} not top {lean.top_n}"
            elif lean.one_per_group and lean.group_of(t) in held:
                why = VETO_GROUP
            if why is None and lean.one_per_group:
                g = lean.group_of(t)
                rival = chosen.get(g)
                if rival is None or xs(t) > xs(rival):
                    if rival is not None:
                        _veto(out, steps[rival], today[rival], d, VETO_PEER + f" ({t})")
                    chosen[g] = t
                    continue
                why = VETO_PEER + f" ({rival})"
            elif why is None:
                chosen[t] = t
                continue
            _veto(out, steps[t], today[t], d, why)
        for t in chosen.values():
            steps[t].enter(today[t])
    return out


def _veto(out: LeanResult, step: Stepper, i: int, d: str, why: str) -> None:
    step.veto(i)
    out.vetoes.append({"ticker": step.res.ticker, "date": d, "why": why})


# ── today's lean states (daily run) ────────────────────────────────────────

def lean_states(histories: dict[str, Sequence[Bar] | None], hurdle: float = 0.0,
                cfg: TrendConfig | None = None, lean: LeanConfig = LeanConfig(),
                hurdle_source: str = "given", today: date | None = None,
                sources: dict[str, str] | None = None) -> dict:
    """Today's lean view: the strongest sector, and a TrendState for every core
    instrument, the strongest sector and any sector the lean system still holds.
    Replays the same joint simulator as the backtest on the given (complete) bars."""
    cfg = cfg or TrendConfig()
    today = today or datetime.now(timezone.utc).date()
    usable: dict[str, Sequence[Bar]] = {}
    states: dict[str, TrendState] = {}
    for t in lean.tickers:
        if t not in histories:
            continue
        bad = unavailable_state(t, histories[t], cfg, today, (sources or {}).get(t))
        if bad is not None:
            states[t] = bad
        else:
            usable[t] = histories[t]
    res = simulate_lean(usable, cfg, hurdle, lean)
    strongest = res.last_strongest()
    for t, sim in res.sims.items():
        st = state_from_sim(sim, cfg)
        st.hurdle_source, st.source = hurdle_source, (sources or {}).get(t)
        veto = [v for v in res.vetoes if v["ticker"] == t and v["date"] == st.as_of]
        if veto:
            st.reason = f"entry signal not taken: {veto[-1]['why']}"
        states[t] = st
    keep = {t for t in lean.core} | ({strongest} if strongest else set())
    keep |= {t for t, s in states.items() if s.state in ("TREND", "EXIT")}
    shown = {t: s for t, s in states.items() if t in keep}
    return {"strongest_sector": strongest, "top_n": lean.top_n,
            "groups": {t: lean.group_of(t) for t in shown}, "states": shown}
