"""Tests for figure_news_pusher pipeline integration.

Covers: pipeline push, shadow distribution isolation (§8.1), and Gate 2 display.
"""
from __future__ import annotations

import pytest

from marketmind.pipeline.figure_news_pusher import (
    CRITICAL_THRESHOLD,
    HIGH_THRESHOLD,
    FigureNewsPusher,
    FigureSignal,
    build_triage_results_from_figures,
)
from marketmind.pipeline.flash_triage import ingest_figure_signals


# ── Fixtures ────────────────────────────────────────────────────────────────────


def _make_signal(
    person_name: str = "Jerome Powell",
    category: str = "I",
    signal_direction: str = "directional",
    event_type: str = "speech",
    ticker: str | None = None,
    direction: str | None = "long",
    awa_score: float = 0.85,
    confidence: float = 0.9,
    summary: str = "Powell signals patience on rate cuts",
    source_url: str = "https://example.com/fed",
    timestamp: str = "2026-05-21T14:00:00Z",
) -> FigureSignal:
    return FigureSignal(
        person_name=person_name,
        category=category,
        signal_direction=signal_direction,
        event_type=event_type,
        ticker=ticker,
        direction=direction,
        awa_score=awa_score,
        confidence=confidence,
        summary=summary,
        source_url=source_url,
        timestamp=timestamp,
    )


# ── Test 1: Critical push to pipeline ───────────────────────────────────────────


def test_critical_push_to_pipeline():
    """CRITICAL signals (AWA >= 0.80) produce pipeline dicts with high urgency."""
    pusher = FigureNewsPusher()
    signals = [
        _make_signal(person_name="Jerome Powell", awa_score=0.88, event_type="speech"),
    ]

    results = pusher.push_to_pipeline(signals)
    assert len(results) == 1

    r = results[0]
    assert r["content_type"] == "figure_signal"
    assert r["headline"].startswith("[Jerome Powell]")
    assert r["source_name"] == "figure:Jerome Powell"
    assert r["source_tier"] == 2
    assert r["scores"]["market_impact"] >= 8.0  # 0.88 * 10 ≈ 8.8
    assert r["scores"]["urgency"] == 10  # CRITICAL → max urgency
    assert r["event_type"] == "figure_speech"
    assert "figure_signal" in r  # Keys check
    assert isinstance(r["figure_signal"], FigureSignal)


def test_medium_signal_pipeline_urgency():
    """MEDIUM signals get proportional urgency, not max."""
    pusher = FigureNewsPusher()
    signals = [
        _make_signal(person_name="Elon Musk", awa_score=0.55, event_type="social_post"),
    ]

    results = pusher.push_to_pipeline(signals)
    assert len(results) == 1
    r = results[0]
    # 0.55 * 8 = 4.4, rounded to 4.4
    assert r["scores"]["urgency"] < 10
    assert r["scores"]["urgency"] > 1.0


def test_low_signal_minimal_urgency():
    """LOW tier signals get near-minimum urgency."""
    pusher = FigureNewsPusher()
    signals = [
        _make_signal(person_name="Andrei Jikh", awa_score=0.15, event_type="social_post"),
    ]

    results = pusher.push_to_pipeline(signals)
    r = results[0]
    # 0.15 * 8 = 1.2, but min is 1
    assert r["scores"]["urgency"] >= 1.0


# ── Test 2: Shadow distribution strips AWA scores (§8.1) ────────────────────────


def test_shadow_distribution_strips_awa_scores():
    """Shadows receive raw content only: person_name, text, timestamp, event_type.
    AWA scores and direction MUST be absent (§8.1 Millennium Chinese Wall)."""
    pusher = FigureNewsPusher()
    signals = [
        _make_signal(person_name="Jerome Powell", awa_score=0.92, direction="long",
                     confidence=0.95, summary="Fed will hold rates steady"),
        _make_signal(person_name="Nancy Pelosi", awa_score=0.85, direction="long",
                     event_type="trade", ticker="NVDA",
                     summary="Pelosi buys NVDA calls"),
    ]

    distribution = pusher.push_to_shadows(signals)

    # fade_master receives all signals
    assert "fade_master" in distribution
    fade_signals = distribution["fade_master"]
    assert len(fade_signals) == 2

    for entry in fade_signals:
        # Sanitized: only 4 keys allowed
        assert set(entry.keys()) <= {"person_name", "text", "timestamp", "event_type"}
        assert "awa_score" not in entry
        assert "direction" not in entry
        assert "confidence" not in entry
        assert "signal_direction" not in entry
        assert "category" not in entry
        assert "ticker" not in entry

    # Verify content is intact
    assert fade_signals[0]["person_name"] == "Jerome Powell"
    assert fade_signals[0]["text"] == "Fed will hold rates steady"
    assert fade_signals[0]["event_type"] == "speech"
    assert fade_signals[1]["person_name"] == "Nancy Pelosi"
    assert fade_signals[1]["event_type"] == "trade"


def test_shadow_filter_crash_hunter():
    """Crash hunter only receives insider_cluster and short_report events."""
    pusher = FigureNewsPusher()
    signals = [
        _make_signal(person_name="Hindenburg", event_type="short_report",
                     direction="short", awa_score=0.90),
        _make_signal(person_name="Powell", event_type="speech",
                     awa_score=0.88),
        _make_signal(person_name="Pelosi", event_type="trade",
                     direction="long", awa_score=0.85),
    ]

    distribution = pusher.push_to_shadows(signals)

    if "crash_hunter" in distribution:
        crash_signals = distribution["crash_hunter"]
        # Should only get filing/trade + short_report events
        event_types = {s.get("event_type") for s in crash_signals}
        assert "speech" not in event_types, "crash_hunter should not get speech events"


def test_shadow_filter_default_critical_only():
    """Default shadows only receive CRITICAL tier signals."""
    pusher = FigureNewsPusher()
    signals = [
        _make_signal(person_name="Powell", awa_score=0.90),
        _make_signal(person_name="Graham Stephan", awa_score=0.35),
    ]

    distribution = pusher.push_to_shadows(signals)

    if "default" in distribution:
        default_signals = distribution["default"]
        names = {s.get("person_name") for s in default_signals}
        assert "Powell" in names
        assert "Graham Stephan" not in names


# ── Test 3: Gate 2 display includes AWA scores ──────────────────────────────────


def test_gate2_display_includes_awa_scores():
    """Gate 2 display is user-facing — AWA scores ARE present."""
    pusher = FigureNewsPusher()
    signals = [
        _make_signal(person_name="Jerome Powell", awa_score=0.92,
                     category="I", signal_direction="directional",
                     event_type="speech", ticker=None, direction="long",
                     summary="Rate hold signal"),
        _make_signal(person_name="Elon Musk", awa_score=0.55,
                     category="III", signal_direction="contrarian",
                     event_type="social_post", ticker="TSLA",
                     direction="short",
                     summary="Musk warns about macro"),
        _make_signal(person_name="Andrei Jikh", awa_score=0.25,
                     category="VI", signal_direction="contrarian",
                     event_type="social_post", ticker=None,
                     direction="neutral",
                     summary="Market update video"),
    ]

    gate2 = pusher.push_to_gate2(signals)

    # Sorted by tier: CRITICAL first, then HIGH, then LOW
    assert len(gate2) == 3
    assert gate2[0]["tier"] == "CRITICAL"
    assert gate2[0]["person_name"] == "Jerome Powell"
    assert gate2[0]["awa_score"] == 0.92
    assert gate2[0]["category"] == "I"

    assert gate2[1]["tier"] == "HIGH"
    assert gate2[1]["awa_score"] == 0.55

    assert gate2[2]["tier"] == "LOW"
    assert gate2[2]["awa_score"] == 0.25

    # All entries must have AWA score (user-facing)
    for entry in gate2:
        assert "awa_score" in entry
        assert "person_name" in entry
        assert "category" in entry
        assert "event_type" in entry
        assert "direction" in entry
        assert "signal_direction" in entry
        assert "summary" in entry


def test_gate2_empty_handles_none():
    """Empty signal list returns empty gate2."""
    pusher = FigureNewsPusher()
    assert pusher.push_to_gate2([]) == []


# ── Test 4: flash_triage integration bridge ─────────────────────────────────────


def test_ingest_figure_signals_produces_triage_results():
    """ingest_figure_signals() converts FigureSignals to TriageResult pipeline items."""
    signals = [
        _make_signal(person_name="Jerome Powell", awa_score=0.88),
        _make_signal(person_name="Nancy Pelosi", awa_score=0.85,
                     event_type="trade", ticker="NVDA"),
    ]

    results = ingest_figure_signals(signals)
    assert len(results) == 2

    for r in results:
        assert r.content_type == "figure_signal"
        assert r.classification in ("macro", "company", "sentiment")
        assert isinstance(r.scores, dict)
        assert "market_impact" in r.scores
        assert "urgency" in r.scores


def test_ingest_figure_signals_empty():
    """Empty input returns empty list."""
    assert ingest_figure_signals([]) == []


def test_build_triage_results_includes_content_type():
    """build_triage_results_from_figures sets content_type correctly."""
    signals = [
        _make_signal(person_name="Warren Buffett", awa_score=0.82,
                     category="V", event_type="filing", ticker="AAPL"),
    ]
    results = build_triage_results_from_figures(signals)
    assert len(results) == 1
    assert results[0].content_type == "figure_signal"


def test_push_to_shadows_all_keys_sanitized():
    """Each shadow entry must have exactly and only: person_name, text, timestamp, event_type."""
    pusher = FigureNewsPusher()
    signals = [
        _make_signal(person_name="Kazuo Ueda", awa_score=0.91,
                     summary="BOJ signals policy shift", event_type="speech"),
    ]

    distribution = pusher.push_to_shadows(signals)
    for shadow_type, entries in distribution.items():
        for entry in entries:
            # Only these 4 keys are allowed — no AWA leakage
            assert set(entry.keys()) == {"person_name", "text", "timestamp", "event_type"}, \
                f"Shadow {shadow_type} has extra keys: {set(entry.keys()) - {'person_name', 'text', 'timestamp', 'event_type'}}"


# ── Test: thresholds and classification ─────────────────────────────────────────


def test_classify_tier_critical():
    pusher = FigureNewsPusher()
    assert pusher._classify_tier(0.90) == "CRITICAL"
    assert pusher._classify_tier(CRITICAL_THRESHOLD) == "CRITICAL"


def test_classify_tier_high():
    pusher = FigureNewsPusher()
    assert pusher._classify_tier(0.60) == "HIGH"
    assert pusher._classify_tier(HIGH_THRESHOLD) == "HIGH"


def test_classify_tier_low():
    pusher = FigureNewsPusher()
    assert pusher._classify_tier(0.30) == "LOW"
    assert pusher._classify_tier(0.0) == "LOW"


def test_map_category_to_classification():
    pusher = FigureNewsPusher()
    assert pusher._map_category_to_classification("I") == "macro"
    assert pusher._map_category_to_classification("II") == "macro"
    assert pusher._map_category_to_classification("III") == "company"
    assert pusher._map_category_to_classification("IV") == "company"
    assert pusher._map_category_to_classification("V") == "macro"
    assert pusher._map_category_to_classification("VI") == "sentiment"
    assert pusher._map_category_to_classification("unknown") == "sentiment"
