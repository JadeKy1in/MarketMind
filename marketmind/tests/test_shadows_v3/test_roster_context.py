"""Roster completeness and the code-built shadow context (docs/S3_DESIGN.md §3.1, §3.4, §3.5)."""
from datetime import date, timedelta
from types import SimpleNamespace

from marketmind.gateway.fred_client import SHADOW_FRED_SERIES
from marketmind.gateway.price_history import Bar, PriceHistory, to_weekly
from marketmind.shadows.v3 import roster
from marketmind.shadows.v3.context import (
    build_context, consensus_lines, filter_news, fred_lines, news_tickers, red_flag_tickers,
)

REQUIRED_SECTIONS = ["## Identity and edge", "## Universe", "## Signals", "## Entry rules",
                     "## Exit and holding period", "## Falsifier",
                     "## Confidence calibration", "## Never"]


def history(ticker, n=1100, start=50.0, step=0.05):
    d, bars = date(2021, 1, 4), []
    for i in range(n):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        c = start + step * i + (0.3 if i % 5 == 0 else 0.0)
        bars.append(Bar(d.isoformat(), c, c * 1.01, c * 0.99, c, 1e6))
        d += timedelta(days=1)
    return PriceHistory(ticker, "synthetic", daily=bars, weekly=to_weekly(bars))


def news(title, summary="", source="Test"):
    return SimpleNamespace(title=title, summary=summary, source_name=source,
                           published_at="2026-09-28T01:00:00Z")


def test_roster_matches_spec_and_launch_decision():
    assert len(roster.ROSTER) == 32
    assert len({r.shadow_id for r in roster.ROSTER}) == 32
    assert len({r.name for r in roster.ROSTER}) == 32
    groups = {}
    for r in roster.ROSTER:
        groups[r.group] = groups.get(r.group, 0) + 1
    assert groups == {"fundamental": 17, "momentum": 4, "contrarian": 4, "short": 2,
                      "derivatives": 2, "cross_market": 3}
    # 2026-09-28: 31 live; odds_analyst is blocked (no reachable prediction-market data),
    # deferred not dropped — see SPEC_v3 §13.1 and AGENTS.md
    active = roster.active()
    assert len(active) == 31
    pending = [r for r in roster.ROSTER if r.status == roster.PENDING_PROMPT]
    assert [r.name for r in pending] == ["odds_analyst"]
    assert "BLOCKED" in pending[0].notes


def test_every_active_prompt_is_complete():
    for r in roster.active():
        text = roster.load_prompt(r)
        missing = [s for s in REQUIRED_SECTIONS if s not in text]
        assert not missing, f"{r.name} prompt lacks {missing}"
        assert 250 <= len(text.split()) <= 800, r.name
        assert "Output format" not in text  # appended by the runner only


def test_fred_mapping_uses_roster_ids():
    ids = {r.shadow_id for r in roster.ROSTER}
    assert set(SHADOW_FRED_SERIES) <= ids


def test_context_renders_real_fields_and_no_data_rows():
    entry = roster.by_id()["expert:gold:bullion_broker"]
    hists = {"GLD": history("GLD")}
    ctx = build_context(entry, hists, [news("Gold hits record as real yields fall"),
                                       news("Chip stocks rally")],
                        fred={"DFII10": {"label": "10y TIPS", "value": 2.1, "unit": "%",
                                         "date": "2026-09-25"}}, today="2026-09-28")
    text = ctx.render()
    assert "GLD [US] |" in text and "200WMA" in text and "ATR14" in text and "20d range" in text
    assert "SLV: no data today" in text
    assert "Gold hits record" in text and "Chip stocks" not in text
    assert "10y TIPS (DFII10): 2.1 %" in text
    assert set(ctx.closes) == {"GLD"}
    assert "consensus" not in text.lower()


def test_only_fade_master_sees_consensus():
    rows = [("expert:tech:silicon_oracle", "SPY", "long"), ("momentum:weekly:trend_rider", "SPY", "long"),
            ("contrarian:crash:hunter", "SPY", "short"),
            ("contrarian:consensus:fade_master", "SPY", "short")]
    assert consensus_lines(rows) == ["- SPY: 3 shadows, 67% long / 33% short"]
    by = roster.by_id()
    fade = build_context(by["contrarian:consensus:fade_master"], {}, [], consensus_rows=rows)
    other = build_context(by["contrarian:crash:hunter"], {}, [], consensus_rows=rows)
    assert "67% long" in fade.render() and "67% long" not in other.render()


def test_news_filter_word_start_and_news_tickers():
    items = [news("Bank lending slows"), news("Embankment repairs"), news("Oil falls")]
    assert [i.title for i in filter_news(items, ("bank",))] == ["Bank lending slows"]
    assert len(filter_news(items, ())) == 3
    tick = [news("Acme (NYSE: ACME) jumps"), news("$ZZZ and $ACME rally"), news("CEO says AI")]
    assert news_tickers(tick, lambda t: t != "ZZZ") == ["ACME"]


def test_fred_lines_mark_unavailable():
    assert fred_lines({"X": {"error": "source_unavailable"}}) == ["- X: unavailable"]


def test_red_flag_tickers_only_from_sec_flags_and_cjk_keywords():
    items = [news('Acme Corp (ACME) 10-K: "going concern"', source="SEC EDGAR Full-Text Flags"),
             news('Beta Inc (BETA) 8-K: "material weakness"', source="SEC EDGAR Full-Text Flags"),
             news("Gamma (GAMA) wins award", source="Reuters")]
    assert red_flag_tickers(items, lambda t: t != "BETA") == ["ACME"]
    cn = [news("中国央行降准，港股大涨"), news("Oil falls")]
    assert [i.title for i in filter_news(cn, ("央行",))] == ["中国央行降准，港股大涨"]


def test_derivative_sections_render():
    by = roster.by_id()
    ctx = build_context(by["short:squeeze:squeeze_watch"], {}, [],
                        short_interest=["- UPST: short interest 1 shares"])
    assert "## Short interest (Nasdaq" in ctx.render() and "UPST: short interest" in ctx.render()
    ctx = build_context(by["derivatives:options:options_reader"], {}, [], options=["- SPY options"])
    assert "## Option chains" in ctx.render() and "Implied move" in ctx.render()


def test_failed_fred_fetch_is_stated_not_omitted():
    entry = roster.by_id()["expert:gold:bullion_broker"]
    ctx = build_context(entry, {}, [], fred={}, fred_failed=True, today="2026-09-28")
    text = ctx.render()
    assert "## Macro data (FRED" in text
    assert "FRED data unavailable" in text
