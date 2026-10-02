"""Trend tag on LLM-decided ledger records (docs/S7_DESIGN.md §六, owner decision 2026-10-02).

Annotate only: the tag never blocks or changes a decision. Each record gets
`meta["trend"]`: the code-computed state of its ticker at decision time, from the
trend state machine (marketmind.trend, docs/TREND_DESIGN.md: 12-month momentum over
the T-bill hurdle, close > SMA200, 55-day closing breakout, chandelier exit) on the
complete daily bars as of the last complete bar.

Inputs are the price histories the run already fetched (5 years, enough for the
260 / 366-bar minimum); no extra fetch. The hurdle comes from the most recent trend
state file (data/trend/<date>.json, written by the daily trend step) within
HURDLE_MAX_AGE_DAYS, else 0 with the source saying so (no network call here).
Tagging never fails a submission: any error becomes state UNAVAILABLE with the reason.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Sequence

from marketmind.gateway.price_history import Bar, complete_bars

logger = logging.getLogger("marketmind.ledger.trend_tag")

TAG_VERSION = 1
HURDLE_MAX_AGE_DAYS = 10
UNAVAILABLE = "UNAVAILABLE"
TREND = "TREND"
FLAT_STATES = ("CASH", "WATCH", "EXIT")     # not in an up-trend: the trend baseline holds cash


def resolve_hurdle(data_dir: str | Path | None = None, today: str | None = None
                   ) -> tuple[float, str]:
    """(annual T-bill hurdle, where it came from): the newest trend file dated <= today
    and at most HURDLE_MAX_AGE_DAYS old, else (0.0, reason)."""
    folder = Path(data_dir or os.getenv("MARKETMIND_DATA_DIR", "data")) / "trend"
    day = date.fromisoformat(today) if today else date.today()
    oldest = (day - timedelta(days=HURDLE_MAX_AGE_DAYS)).isoformat()
    try:
        files = sorted(folder.glob("????-??-??.json"), reverse=True) if folder.is_dir() else []
    except OSError:
        logger.warning("trend folder %s unreadable", folder, exc_info=True)
        files = []
    for p in files:
        if p.stem > day.isoformat():
            continue
        if p.stem < oldest:
            break
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            hurdle = float(doc["hurdle"])
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("trend file %s has no usable hurdle", p)
            continue
        return hurdle, f"trend file {p.stem}: {doc.get('hurdle_source') or 'unknown'}"
    return 0.0, f"unavailable -> 0 (no trend file within {HURDLE_MAX_AGE_DAYS} days)"


class TrendTagger:
    """Per-run tagger: one state computation per ticker (cached)."""

    def __init__(self, today: str, hurdle: float | None = None, hurdle_source: str | None = None,
                 data_dir: str | Path | None = None, cfg=None):
        if hurdle is None:
            hurdle, hurdle_source = resolve_hurdle(data_dir, today)
        self.today = date.fromisoformat(today)
        self.hurdle = float(hurdle)
        self.hurdle_source = hurdle_source or "given"
        self.cfg = cfg
        self._cache: dict[str, dict] = {}

    def tag(self, ticker: str, daily: Sequence[Bar] | None, source: str | None = None) -> dict:
        """meta["trend"] for `ticker` from its daily bars (a partial last bar is dropped)."""
        key = ticker.upper()
        if key not in self._cache:
            self._cache[key] = self._compute(ticker, daily, source)
        return dict(self._cache[key])

    def _compute(self, ticker: str, daily: Sequence[Bar] | None, source: str | None) -> dict:
        from marketmind.trend.state import compute_states
        try:
            bars = complete_bars(ticker, list(daily)) if daily else []
            st = compute_states({ticker: bars}, self.hurdle, self.cfg,
                                hurdle_source=self.hurdle_source, today=self.today,
                                sources={ticker: source} if source else None)[ticker]
        except Exception as exc:
            logger.warning("trend tag for %s failed; recorded as UNAVAILABLE", ticker, exc_info=True)
            return {"v": TAG_VERSION, "state": UNAVAILABLE, "as_of": None,
                    "reason": f"tag error: {type(exc).__name__}: {exc}"[:200]}
        out = {"v": TAG_VERSION, "state": st.state, "as_of": st.as_of,
               "hurdle": round(self.hurdle, 6), "hurdle_source": self.hurdle_source}
        if st.event:
            out["event"] = st.event
        if st.reason:
            out["reason"] = st.reason
        return out


def unavailable(reason: str) -> dict:
    return {"v": TAG_VERSION, "state": UNAVAILABLE, "as_of": None, "reason": reason}


def state_of(e) -> str | None:
    """The recorded trend state of a ledger row (None when it was never tagged)."""
    tag = (e.meta or {}).get("trend")
    return tag.get("state") if isinstance(tag, dict) else None
