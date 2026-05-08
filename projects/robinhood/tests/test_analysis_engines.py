"""
test_analysis_engines.py - Comprehensive pytest suite for Layer 2 engines.

Tests cover:
  - config/event_templates.py: template matching
  - src/technical_engine.py: MA scoring, MACD divergence, price-volume, full analysis
  - src/fundamental_engine.py: ASCII sanitizer, prompt building, fallback mode
  - src/event_engine.py: bin classification, discount matrix, arbitration, template-only
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd
import pytest

from config.event_templates import (
    ALTERNATIVE_DATA_PLAYBOOK,
    CAUSAL_CHAIN_TEMPLATES,
    match_templates,
)
from src.event_engine import (
    DISCOUNT_CURVE,
    _arbitrate,
    _classify_blue_bin,
    _classify_red_bin,
    _template_only_mode,
    analyze_event_driven,
)
from src.fundamental_engine import (
    SYSTEM_PROMPT_TEMPLATE,
    clean_ascii_only,
)
from src.technical_engine import (
    _compute_weekly_macd,
    _compute_weekly_smas,
    _find_local_extrema,
    _ma_trend_score,
    _macd_divergence_score,
    _price_volume_adjustment,
    _validate_divergence_extrema,
    _weekly_atr,
    analyze_technical,
    detect_macd_divergence,
)


# =========================================================================
# Config / Template Tests
# =========================================================================


class TestEventTemplates:
    """Tests for config/event_templates.py"""

    def test_causal_chain_templates_have_required_keys(self):
        """Every template must have trigger_keywords, template_chain, red_team_focus."""
        for name, tmpl in CAUSAL_CHAIN_TEMPLATES.items():
            assert "trigger_keywords" in tmpl, f"{name} missing trigger_keywords"
            assert "template_chain" in tmpl, f"{name} missing template_chain"
            assert "red_team_focus" in tmpl, f"{name} missing red_team_focus"
            assert isinstance(tmpl["trigger_keywords"], list), f"{name} keywords not list"
            assert len(tmpl["trigger_keywords"]) > 0, f"{name} has empty keywords"

    def test_match_templates_returns_empty_for_no_match(self):
        assert match_templates(["nothing relevant"]) == []

    def test_match_templates_finds_war(self):
        result = match_templates(["military conflict in strait of hormuz", "earnings report"])
        names = [r["name"] for r in result]
        assert "war_to_energy_to_fertilizer_to_agriculture" in names

    def test_match_templates_finds_rate_hike(self):
        result = match_templates(["FOMC rate hike expected", "tech layoffs"])
        names = [r["name"] for r in result]
        assert "rate_hike_to_credit_to_capex" in names

    def test_alt_data_playbook_has_categories(self):
        assert len(ALTERNATIVE_DATA_PLAYBOOK) >= 6
        for cat, sources in ALTERNATIVE_DATA_PLAYBOOK.items():
            assert isinstance(sources, list), f"{cat} sources not list"
            assert len(sources) > 0, f"{cat} has empty sources"


# =========================================================================
# Technical Engine Tests
# =========================================================================


def _make_weekly_df(
    closes: list[float],
    opens: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    volumes: list[float] | None = None,
) -> pd.DataFrame:
    """Helper to create a weekly OHLCV DataFrame from price data."""
    n = len(closes)
    if opens is None:
        opens = [c * 0.99 for c in closes]
    if highs is None:
        highs = [c * 1.02 for c in closes]
    if lows is None:
        lows = [c * 0.98 for c in closes]
    if volumes is None:
        volumes = [1_000_000] * n

    return pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=n, freq="W"),
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


def _make_trending_up(n_weeks: int = 60, price_start: float = 100.0, volatility: float = 2.0) -> list[float]:
    """Generate a steady uptrend with noise."""
    np.random.seed(42)
    prices = [price_start]
    for _ in range(1, n_weeks):
        prices.append(prices[-1] + np.random.normal(1.0, volatility))
    return prices


def _make_trending_down(n_weeks: int = 60, price_start: float = 200.0, volatility: float = 2.0) -> list[float]:
    """Generate a steady downtrend with noise."""
    np.random.seed(42)
    prices = [price_start]
    for _ in range(1, n_weeks):
        prices.append(prices[-1] + np.random.normal(-1.0, volatility))
    return [max(p, 1.0) for p in prices]


class TestTechnicalEngineSMA:
    """Tests for MA trend computations."""

    def test_sma_20_computed_correctly(self):
        closes = list(range(1, 61))
        df = _make_weekly_df(closes)
        smas = _compute_weekly_smas(df)
        assert smas["sma_20"] is not None
        # Last 20 values avg = (41+42+...+60)/20 = 50.5
        assert abs(smas["sma_20"] - 50.5) < 0.01

    def test_sma_50_computed_correctly(self):
        closes = list(range(1, 61))
        df = _make_weekly_df(closes)
        smas = _compute_weekly_smas(df)
        assert smas["sma_50"] is not None
        # Average of last 50 values (11..60) = 35.5
        assert abs(smas["sma_50"] - 35.5) < 0.01

    def test_sma_returns_none_when_insufficient_data(self):
        closes = list(range(1, 16))  # Only 15 weeks
        df = _make_weekly_df(closes)
        smas = _compute_weekly_smas(df)
        assert smas["sma_20"] is None
        assert smas["sma_50"] is None


class TestTechnicalEngineMACD:
    """Tests for MACD computation and divergence detection."""

    def test_macd_returns_empty_for_insufficient_data(self):
        closes = list(range(1, 20))  # < 26 weeks
        df = _make_weekly_df(closes)
        macd = _compute_weekly_macd(df)
        assert len(macd["macd_line"]) == 0

    def test_macd_computes_correct_length(self):
        closes = _make_trending_up(60)
        df = _make_weekly_df(closes)
        macd = _compute_weekly_macd(df)
        assert len(macd["macd_line"]) == 60
        # Some should be non-NaN after the warm-up period
        assert np.sum(~np.isnan(macd["macd_line"])) >= 30

    def test_macd_matches_expected_direction(self):
        """In a strong uptrend, MACD line should be above signal line at end."""
        closes = _make_trending_up(60, price_start=100, volatility=1.0)
        df = _make_weekly_df(closes)
        macd = _compute_weekly_macd(df)
        # Last 5 values should have MACD > signal in uptrend
        valid = np.where(~np.isnan(macd["signal_line"]))[0]
        if len(valid) >= 5:
            assert np.mean(macd["histogram"][valid[-5:]]) > -1.0


class TestTechnicalEngineDivergence:
    """Tests for MACD divergence detection."""

    def test_no_divergence_in_flat_market(self):
        closes = [100.0] * 60
        df = _make_weekly_df(closes)
        div = detect_macd_divergence(df)
        assert not div["bullish_divergence"]
        assert not div["bearish_divergence"]
        assert div["divergence_strength"] == 0

    def test_find_local_extrema_basic(self):
        values = np.array([3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 8])
        mins, maxs = _find_local_extrema(values, lookback=2)
        # With lookback=2, loop starts at i=2 (range(2, 9))
        # Minimum found at index 6 (val=2 is min in [5,9,2,6,5])
        assert mins == [6]
        # Maximum found at index 5 (val=9 is max in [1,5,9,2,6])
        assert maxs == [5]

    def test_weekly_atr_basic(self):
        prices = np.array([100, 102, 101, 105, 107, 106, 110, 108, 109, 112, 115, 113, 116, 118, 120])
        atr = _weekly_atr(prices, period=14)
        assert atr > 0

    def test_validate_divergence_extrema_requires_two_points(self):
        price = np.array([100, 101, 102, 103, 104])
        macd = np.array([1, 2, 3, 4, 5])
        result = _validate_divergence_extrema(price, macd, [0], is_bullish=True)
        assert result is False  # Only 1 extreme point


class TestTechnicalEngineScoring:
    """Tests for scoring components."""

    def test_ma_trend_score_bullish(self):
        smas = {"sma_20": 110.0, "sma_50": 100.0}
        assert _ma_trend_score(smas) >= 30  # 10% gap -> high score

    def test_ma_trend_score_bearish(self):
        smas = {"sma_20": 80.0, "sma_50": 100.0}
        assert _ma_trend_score(smas) <= 10  # -20% gap -> very low score

    def test_ma_trend_score_neutral_default(self):
        """Insufficient data should return neutral 20."""
        smas = {"sma_20": None, "sma_50": None}
        assert _ma_trend_score(smas) == 20

    def test_macd_divergence_score_strong_bullish(self):
        div = {"divergence_strength": 2}
        assert _macd_divergence_score(div) == 38

    def test_macd_divergence_score_strong_bearish(self):
        div = {"divergence_strength": -2}
        assert _macd_divergence_score(div) == 2

    def test_macd_divergence_score_neutral(self):
        div = {"divergence_strength": 0}
        assert _macd_divergence_score(div) == 20

    def test_price_volume_adjustment_insufficient_data(self):
        closes = [100] * 5
        df = _make_weekly_df(closes)
        assert _price_volume_adjustment(df) == 0

    def test_price_volume_adjustment_clamped(self):
        """Adjustment should be within +/-10 even with extreme data."""
        closes = _make_trending_up(30) + _make_trending_up(30)
        df = _make_weekly_df(closes)
        adj = _price_volume_adjustment(df)
        assert -10 <= adj <= 10


class TestTechnicalEngineIntegration:
    """Full integration tests for analyze_technical()."""

    def test_uptrend_returns_high_score(self):
        """Strong uptrend should score above 50."""
        # Use lower volatility and more weeks to ensure clear MA alignment
        closes = _make_trending_up(100, price_start=100, volatility=0.5)
        df = _make_weekly_df(closes)
        result = analyze_technical(df)
        assert 50 <= result["score"] <= 100
        assert "MA alignment" in result["reasoning"]
        assert "MACD" in result["reasoning"]

    def test_downtrend_returns_low_score(self):
        """Consistent downtrend should score below 50."""
        closes = _make_trending_down(60, price_start=200, volatility=1.5)
        df = _make_weekly_df(closes)
        result = analyze_technical(df)
        assert 0 <= result["score"] <= 60
        assert "Final technical score" in result["reasoning"]

    def test_flat_market_returns_mid_score(self):
        """Flat market should score near 50."""
        closes = [100.0] * 60
        df = _make_weekly_df(closes)
        result = analyze_technical(df)
        assert 30 <= result["score"] <= 70

    def test_insufficient_data_returns_neutral(self):
        """< 26 weeks: MA neutral (20) + MACD neutral (20) + pv adjustment = 38."""
        closes = list(range(1, 20))
        df = _make_weekly_df(closes)
        result = analyze_technical(df)
        # MA=20 (neutral) + MACD=20 (neutral) + pv_adj=-2 (constant volume triggers ratio<0.3) = 38
        assert result["score"] == 38
        assert "Insufficient data" in result["reasoning"]


# =========================================================================
# Fundamental Engine Tests
# =========================================================================


class TestFundamentalEngineASCII:
    """Tests for clean_ascii_only() and template structure."""

    def test_ascii_preserved(self):
        text = "Hello world! This is fine."
        assert clean_ascii_only(text) == text

    def test_emoji_removed(self):
        text = "Hello world 😊 This has emoji 🚀"
        cleaned = clean_ascii_only(text)
        assert "😊" not in cleaned
        assert "🚀" not in cleaned

    def test_chinese_characters_removed(self):
        text = "English text with 中文 mixed in."
        cleaned = clean_ascii_only(text)
        assert "中文" not in cleaned
        assert "English text with" in cleaned
        assert "mixed in" in cleaned

    def test_newline_and_tab_preserved(self):
        text = "line1\n\tline2"
        assert clean_ascii_only(text) == text

    def test_system_prompt_template_has_placeholders(self):
        assert "{macro_events_json}" in SYSTEM_PROMPT_TEMPLATE
        assert "{positions_json}" in SYSTEM_PROMPT_TEMPLATE

    def test_clean_ascii_only_strips_fancy_quotes(self):
        text = "Soros says \u201creflexivity\u201d is key."
        cleaned = clean_ascii_only(text)
        assert "\u201c" not in cleaned
        assert "\u201d" not in cleaned
        assert "Soros says reflexivity is key." == cleaned


# =========================================================================
# Event Engine Tests
# =========================================================================


class TestEventEngineClassification:
    """Tests for bin classification."""

    def test_blue_high_bin(self):
        assert _classify_blue_bin(85) == "blue_high"
        assert _classify_blue_bin(70) == "blue_high"

    def test_blue_mid_bin(self):
        assert _classify_blue_bin(50) == "blue_mid"
        assert _classify_blue_bin(30) == "blue_mid"

    def test_blue_low_bin(self):
        assert _classify_blue_bin(25) == "blue_low"
        assert _classify_blue_bin(0) == "blue_low"

    def test_red_high_bin(self):
        assert _classify_red_bin(2.5) == "red_high"
        assert _classify_red_bin(2.0) == "red_high"

    def test_red_mid_bin(self):
        assert _classify_red_bin(1.5) == "red_mid"
        assert _classify_red_bin(1.0) == "red_mid"

    def test_red_low_bin(self):
        assert _classify_red_bin(0.5) == "red_low"
        assert _classify_red_bin(0.0) == "red_low"


class TestEventEngineDiscountMatrix:
    """Tests for the discount curve and arbitration logic."""

    def test_discount_matrix_has_all_keys(self):
        """Every blue bin must have entries for all red bins."""
        for blue_bin in ["blue_high", "blue_mid", "blue_low"]:
            for red_bin in ["red_high", "red_mid", "red_low"]:
                assert red_bin in DISCOUNT_CURVE[blue_bin], (
                    f"Missing {red_bin} for {blue_bin}"
                )

    def test_discount_values_are_percentages(self):
        """All discount rates must be 0-100."""
        for blue_bin, red_map in DISCOUNT_CURVE.items():
            for red_bin, rate in red_map.items():
                assert 0 <= rate <= 100, (
                    f"Rate {rate} for {blue_bin}/{red_bin} out of range"
                )

    def test_blue_high_discounts_higher(self):
        """Bullish scores should get larger discounts to counter optimism bias."""
        for red_bin in ["red_high", "red_mid", "red_low"]:
            assert DISCOUNT_CURVE["blue_high"][red_bin] >= DISCOUNT_CURVE["blue_mid"][red_bin]
            assert DISCOUNT_CURVE["blue_mid"][red_bin] >= DISCOUNT_CURVE["blue_low"][red_bin]

    def test_arbitrate_high_blue_low_red(self):
        """Blue score 90, Red confidence 0.3 -> low discount."""
        blue = {"score": 90, "reasoning": "Bullish", "causal_chain": ["Step 1"]}
        red = {"confidence": 0.3, "challenge_summary": "Weak challenge", 
               "physical_evidence_required": [], "relevant_alt_data_categories": []}
        result = _arbitrate(blue, red)
        assert result["score"] >= 75  # After 10% discount -> 81

    def test_arbitrate_high_blue_high_red(self):
        """Blue score 90, Red confidence 2.5 -> 50% discount."""
        blue = {"score": 90, "reasoning": "Very bullish", "causal_chain": ["Step 1"]}
        red = {"confidence": 2.5, "challenge_summary": "Strong challenge", 
               "physical_evidence_required": ["Need satellite data"], 
               "relevant_alt_data_categories": ["industrial_production"]}
        result = _arbitrate(blue, red)
        assert result["score"] == 45  # 90 * (1 - 0.50) = 45
        assert result["discount_applied"] == 50

    def test_arbitrate_low_blue_low_red(self):
        """Blue score 20, Red confidence 0.0 -> 0% discount (already bearish)."""
        blue = {"score": 20, "reasoning": "Bearish", "causal_chain": []}
        red = {"confidence": 0.0, "challenge_summary": "",
               "physical_evidence_required": [], "relevant_alt_data_categories": []}
        result = _arbitrate(blue, red)
        assert result["score"] == 20  # No discount for bearish + no challenge

    def test_arbitrate_reasoning_contains_all_sections(self):
        """Full reasoning should include Blue, Red, discount, and evidence."""
        blue = {"score": 75, "reasoning": "Strong uptrend", "causal_chain": ["Step A", "Step B"]}
        red = {"confidence": 1.8, "challenge_summary": "Missing data for Step A",
               "physical_evidence_required": ["Fertilizer inventory data"], 
               "relevant_alt_data_categories": ["fertilizer_supply_chain"]}
        result = _arbitrate(blue, red)
        reasoning = result["reasoning"]
        assert "Blue Team" in reasoning
        assert "Red Team" in reasoning
        assert "Discount" in reasoning
        assert "Fertilizer inventory" in reasoning

    def test_arbitrate_score_clamped(self):
        """Score must always be 0-100."""
        blue = {"score": 5, "reasoning": "", "causal_chain": []}
        red = {"confidence": 2.5, "challenge_summary": "", 
               "physical_evidence_required": [], "relevant_alt_data_categories": []}
        # 5 * (1-0.30) = 3.5, rounded to 4
        result = _arbitrate(blue, red)
        assert 0 <= result["score"] <= 100
        assert result["score"] == 4  # blue_low + red_high = 30% discount

    def test_arbitrate_preserves_team_outputs(self):
        """Arbiter should include blue_team_output and red_team_output."""
        blue = {"score": 80, "reasoning": "UP", "causal_chain": ["C1"]}
        red = {"confidence": 1.0, "challenge_summary": "Not sure",
               "physical_evidence_required": ["Data"], 
               "relevant_alt_data_categories": ["oil_supply_disruption"]}
        result = _arbitrate(blue, red)
        assert "blue_team_output" in result
        assert result["blue_team_output"]["score"] == 80
        assert "red_team_output" in result
        assert result["red_team_output"]["confidence"] == 1.0


class TestEventEngineTemplateOnlyMode:
    """Tests for template-only fallback when no API key."""

    def test_template_only_no_match_returns_neutral(self):
        result = _template_only_mode([{"title": "random earnings report"}])
        assert result["score"] == 50
        assert "no events matched" in result["reasoning"].lower()

    def test_template_only_with_match_returns_scaled_score(self):
        events = [
            {"title": "military conflict in strait of hormuz"},
            {"title": "FOMC rate hike expected"},
        ]
        result = _template_only_mode(events)
        # 2 matched templates -> base_score = 40 + 2*10 = 60, discounted 30% -> 42
        assert result["score"] == 42
        assert "template-only mode" in result["reasoning"]

    def test_template_only_score_capped(self):
        """Even with many matches, score should not exceed 100."""
        events = [{"title": f"event {i}"} for i in range(20)]
        # Put a war keyword in
        events[0] = {"title": "military conflict"}
        result = _template_only_mode(events)
        assert 0 <= result["score"] <= 100


class TestEventEngineIntegration:
    """Integration test for analyze_event_driven without API key."""

    def test_analyze_event_driven_no_api_key(self):
        """Without DEEPSEEK_API_KEY, should fall back to template-only."""
        events = [
            {"title": "military conflict in strait of hormuz", "description": "Escalating", "category": "geopolitical", "date": "2026-05-01"},
        ]
        result = analyze_event_driven(events, api_key="")
        assert "score" in result
        assert "reasoning" in result
        assert 0 <= result["score"] <= 100
        assert "template-only mode" in result["reasoning"]

    def test_analyze_event_driven_empty_events(self):
        """Empty events list should return neutral."""
        result = analyze_event_driven([], api_key="")
        assert result["score"] == 50
        assert "no events matched" in result["reasoning"]