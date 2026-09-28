"""Code-built daily context for each shadow (docs/S3_DESIGN.md §3.4, §3.5).

Everything numeric comes from completed daily bars (gateway.price_history,
pipeline.l3_indicators). A ticker without data is shown as "no data" and is
not tradable that day. Shadows never see main-pipeline output or other
shadows' reasoning; fade_master alone gets yesterday's direction counts.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from marketmind.gateway.price_history import PriceHistory, completed_history
from marketmind.markets import market_for
from marketmind.pipeline.l3_indicators import TechnicalSnapshot, compute_snapshot
from marketmind.shadows.v3.roster import RosterEntry

logger = logging.getLogger("marketmind.shadows.v3.context")

MAX_HEADLINES = 20
MAX_NEWS_TICKERS = 10
FADE_MASTER_ID = "contrarian:consensus:fade_master"
NEWS_HOUND_ID = "momentum:event:news_hound"
BEAR_TRACKER_ID = "expert:short:bear_tracker"
SQUEEZE_WATCH_ID = "short:squeeze:squeeze_watch"
OPTIONS_READER_ID = "derivatives:options:options_reader"
SEC_FLAGS_SOURCE = "SEC EDGAR Full-Text Flags"
_PAREN_TICKER = re.compile(r"\(([A-Z]{1,5}(?:[.-][A-Z])?)\)")

_NEWS_TICKER = re.compile(
    r"\$([A-Z]{1,5}(?:[.-][A-Z])?)\b"
    r"|\((?:NYSE|NASDAQ|Nasdaq|NYSE American|NYSEAMERICAN|AMEX)\s*[:：]\s*([A-Z]{1,5}(?:\.[A-Z])?)\)")


@dataclass
class TickerView:
    ticker: str
    snap: TechnicalSnapshot | None
    ret_5d: float | None = None
    ret_20d: float | None = None
    high_20d: float | None = None
    low_20d: float | None = None

    def line(self) -> str:
        s = self.snap
        if s is None:
            return f"- {self.ticker}: no data today (do not trade it)"
        wma = f"{s.wma200:.2f} ({'above' if s.above_200wma else 'below'})" \
            if s.wma200 is not None else "n/a (history too short)"
        res = f"{s.key_resistance:.2f}" if s.key_resistance is not None else "none overhead"
        return (
            f"- {self.ticker} [{market_for(self.ticker).code}] | {s.as_of} close {s.close:.6g} | "
            f"1d {_pct(s.daily_return_pct)} 5d {_pct(self.ret_5d)} 20d {_pct(self.ret_20d)} | "
            f"200WMA {wma} | ATR14 {s.atr14:.6g} | "
            f"20d range {self.low_20d:.6g}-{self.high_20d:.6g} | "
            f"support {s.support_low:.6g}-{s.support_high:.6g} | resistance {res} | "
            f"light {s.light.upper()}, structure {'intact' if s.structure_intact else 'broken'}, "
            f"long-setup R/R {s.reward_risk_ratio:.2f}"
        )


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:+.1f}%"


def ticker_view(ticker: str, hist: PriceHistory | None) -> TickerView:
    if hist is None or not hist.daily:
        return TickerView(ticker, None)
    hist = completed_history(hist)
    snap = compute_snapshot(hist)
    if snap is None:
        return TickerView(ticker, None)
    closes = [b.close for b in hist.daily]

    def ret(n: int) -> float | None:
        if len(closes) <= n or not closes[-1 - n]:
            return None
        return (closes[-1] / closes[-1 - n] - 1) * 100

    last20 = hist.daily[-20:]
    return TickerView(ticker, snap, ret(5), ret(20),
                      max(b.high for b in last20), min(b.low for b in last20))


def filter_news(news_items: list, keywords: tuple[str, ...], limit: int = MAX_HEADLINES) -> list:
    """Headlines matching any keyword (word-start, case-insensitive); all news if none given."""
    if not keywords:
        return list(news_items[:limit])
    # word-start match for Latin keywords; CJK text has no spaces, so match anywhere
    parts = [(r"\b" if k[:1].isascii() else "") + re.escape(k) for k in keywords]
    pattern = re.compile("(" + "|".join(parts) + ")", re.I)
    out = []
    for item in news_items:
        text = f"{_attr(item, 'title')} {_attr(item, 'summary')[:300]}"
        if pattern.search(text):
            out.append(item)
            if len(out) >= limit:
                break
    return out


def _attr(item, name: str) -> str:
    v = getattr(item, name, None)
    if v is None and isinstance(item, dict):
        v = item.get(name)
    return str(v or "")


def news_lines(items: list) -> list[str]:
    lines = []
    for item in items:
        when = _attr(item, "published_at")[:16].replace("T", " ")
        src = _attr(item, "source_name")
        lines.append(f"- [{src}{', ' + when if when else ''}] {_attr(item, 'title')[:220]}")
    return lines


def news_tickers(news_items: list, tradable, limit: int = MAX_NEWS_TICKERS) -> list[str]:
    """Most-mentioned tradable tickers named explicitly ($XYZ or '(NYSE: XYZ)') in the news."""
    counts: Counter[str] = Counter()
    for item in news_items:
        for m in _NEWS_TICKER.finditer(_attr(item, "title") + " " + _attr(item, "summary")):
            t = (m.group(1) or m.group(2)).replace(".", "-")
            counts[t] += 1
    return [t for t, _ in counts.most_common() if tradable(t)][:limit]


def red_flag_tickers(news_items: list, tradable, limit: int = MAX_NEWS_TICKERS) -> list[str]:
    """Tickers of companies in SEC full-text red-flag filings ('Acme Corp (ACME) 8-K: ...')."""
    counts: Counter[str] = Counter()
    for item in news_items:
        if _attr(item, "source_name") != SEC_FLAGS_SOURCE:
            continue
        for m in _PAREN_TICKER.finditer(_attr(item, "title")):
            counts[m.group(1).replace(".", "-")] += 1
    return [t for t, _ in counts.most_common() if tradable(t)][:limit]


FRED_UNAVAILABLE_LINE = "- FRED data unavailable today (fetch failed); do not assume any macro values."


def fred_lines(series: dict[str, dict]) -> list[str]:
    lines = []
    for key, r in series.items():
        if not isinstance(r, dict) or r.get("error") or r.get("value") is None:
            lines.append(f"- {key}: unavailable")
            continue
        lines.append(f"- {r.get('label', key)} ({key}): {r['value']} {r.get('unit', '')} "
                     f"as of {r.get('date', '?')}".rstrip())
    return lines


def consensus_lines(rows: list[tuple[str, str, str]], exclude: str = FADE_MASTER_ID) -> list[str]:
    """rows: (source_id, ticker, direction) of yesterday's shadow records -> direction share."""
    by_ticker: dict[str, Counter] = {}
    for source_id, ticker, direction in rows:
        if source_id == exclude:
            continue
        by_ticker.setdefault(ticker, Counter())[direction] += 1
    lines = []
    for ticker, c in sorted(by_ticker.items(), key=lambda kv: -sum(kv[1].values())):
        n = sum(c.values())
        lines.append(f"- {ticker}: {n} shadows, {c['long'] / n:.0%} long / "
                     f"{c['short'] / n:.0%} short")
    return lines


@dataclass
class ShadowContext:
    entry: RosterEntry
    views: list[TickerView]
    headlines: list[str]
    fred: list[str] = field(default_factory=list)
    consensus: list[str] = field(default_factory=list)
    short_interest: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)
    today: str = ""
    off_context: dict[str, float] = field(default_factory=dict)  # priced after the reply

    @property
    def closes(self) -> dict[str, float]:
        return {v.ticker: v.snap.close for v in self.views if v.snap is not None}

    def render(self) -> str:
        parts = [f"Date (UTC): {self.today}",
                 f"You are {self.entry.display_name}; domain: {self.entry.domain}.",
                 f"Your results are compared with {self.entry.domain_benchmark} "
                 f"and with a random pick from your watchlist.",
                 "", "## Prices (completed daily bars, computed by code)", *[v.line() for v in self.views]]
        if self.entry.notes and "intraday_approx" in self.entry.notes:
            parts += ["", "Every decision you make is held exactly 1 session "
                          "(next open to that close)."]
        if self.fred:
            parts += ["", "## Macro data (FRED, latest observation)", *self.fred]
        if self.consensus:
            parts += ["", "## Yesterday's shadow consensus (direction share only)",
                      *self.consensus]
        if self.short_interest:
            parts += ["", "## Short interest (Nasdaq, exchange settlement, twice a month)",
                      *self.short_interest]
        if self.options:
            parts += ["", "## Option chains (Nasdaq, delayed; computed by code)",
                      "Implied move = at-the-money straddle mid / spot to the near expiry. "
                      "OTM put/call price ratio compares ~5% OTM put and call mids "
                      "(higher = more downside protection demand). Walls = largest open "
                      "interest strikes.", *self.options]
        parts += ["", "## Today's headlines", *(self.headlines or ["- (no relevant headlines today)"])]
        return "\n".join(parts)


def build_context(entry: RosterEntry, histories: dict[str, PriceHistory | None],
                  news_items: list, fred: dict[str, dict] | None = None,
                  consensus_rows: list | None = None, extra_tickers: list[str] | None = None,
                  today: str | None = None, short_interest: list[str] | None = None,
                  options: list[str] | None = None,
                  fred_failed: bool = False) -> ShadowContext:
    tickers = list(dict.fromkeys([*entry.watchlist, *(extra_tickers or [])]))
    views = [ticker_view(t, histories.get(t)) for t in tickers]
    headlines = news_lines(filter_news(news_items, entry.news_keywords))
    return ShadowContext(
        entry=entry, views=views, headlines=headlines,
        # A failed FRED fetch is stated, not silently dropped (the section would vanish).
        fred=[FRED_UNAVAILABLE_LINE] if fred_failed else fred_lines(fred or {}),
        consensus=consensus_lines(consensus_rows or []) if entry.shadow_id == FADE_MASTER_ID else [],
        short_interest=list(short_interest or []), options=list(options or []),
        today=today or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )
