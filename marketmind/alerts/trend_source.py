"""Pluggable trend-signal source: the trunk of the big-move alert (owner decision 2026-09-29).

A source answers one question for a day: each instrument's trend state, and which
instruments switched into TREND (entries) or out of it (exits). Which trend rule feeds
the alerts is not decided yet (a monthly rule is being backtested), so the choice is a
setting: `alerts/config.py::TREND_SOURCE`, overridden by MARKETMIND_ALERT_TREND_SOURCE.

- a name in `SOURCES` below, or
- "package.module:factory" - any zero-argument callable returning an object with
  `name` and `read(day) -> TrendReading` (a new rule plugs in without editing alerts/).

State vocabulary (docs/TREND_DESIGN.md §4): CASH, WATCH, TREND, EXIT, UNAVAILABLE.
"""
from __future__ import annotations

import importlib
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from marketmind.alerts import config as C

TREND, WATCH = "TREND", "WATCH"


@dataclass
class TrendReading:
    source: str
    date: str
    available: bool
    universe: str | None = None                   # e.g. "lean" / "full"
    states: dict[str, dict] = field(default_factory=dict)   # ticker -> state record
    entries: list[str] = field(default_factory=list)        # switched into TREND today
    exits: list[str] = field(default_factory=list)          # switched out of TREND today
    reason: str | None = None                     # why unavailable

    def summary(self) -> dict:
        d = asdict(self)
        d.pop("states")
        return d


class TrendSource(Protocol):
    name: str

    def read(self, day: str) -> TrendReading: ...


class DailyStateMachineSource:
    """data/trend/<New York date>.json written by trend.daily (docs/TREND_DESIGN.md §9).
    universe "auto" = the lean list when the file has one, else the full universe.
    Only the file of `day` itself is used: entries / exits are that day's changes."""

    def __init__(self, universe: str = "auto", data_dir: str | Path | None = None):
        if universe not in ("auto", "lean", "full"):
            raise ValueError(f"unknown universe {universe!r}")
        self.universe = universe
        self.data_dir = data_dir
        self.name = "daily_state_machine" + ("" if universe == "auto" else f":{universe}")

    def read(self, day: str) -> TrendReading:
        from marketmind.trend.daily import load
        data_dir = Path(self.data_dir or os.getenv("MARKETMIND_DATA_DIR", "data"))
        _, doc = load(data_dir, day)
        if doc is None:
            return TrendReading(self.name, day, False,
                                reason=f"trend/{day}.json missing (trend step not run or failed)")
        lean_states = (doc.get("lean") or {}).get("states") or {}
        section = "lean" if (self.universe == "lean" or (self.universe == "auto" and lean_states)) \
            else "full"
        states = lean_states if section == "lean" else (doc.get("full") or {})
        ch = (doc.get("changes") or {}).get(section) or {}
        if not states:
            return TrendReading(self.name, day, False, universe=section,
                                reason=f"trend/{day}.json has no {section} states")
        return TrendReading(self.name, day, True, universe=section, states=dict(states),
                            entries=list(ch.get("entries", [])), exits=list(ch.get("exits", [])))


SOURCES: dict[str, Callable[[], TrendSource]] = {
    "daily_state_machine": lambda: DailyStateMachineSource("auto"),
    "daily_state_machine:lean": lambda: DailyStateMachineSource("lean"),
    "daily_state_machine:full": lambda: DailyStateMachineSource("full"),
}


def get_source(spec: str | None = None) -> TrendSource:
    spec = spec or C.trend_source_name()
    if spec in SOURCES:
        return SOURCES[spec]()
    module, _, attr = spec.partition(":")
    if not attr or "." not in module:
        raise ValueError(f"unknown trend source {spec!r}; known: {', '.join(SOURCES)} "
                         "or package.module:factory")
    return getattr(importlib.import_module(module), attr)()
