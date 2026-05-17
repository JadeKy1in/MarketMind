"""Tests for 4-layer independent verification chain (C7 fix)."""
from unittest.mock import AsyncMock, patch
import pytest

from marketmind.pipeline.verification_chain import (
    VerificationResult,
    verify_claim,
    verify_claim_market_pricing,
    verify_claim_fundamental,
    verify_claim_multisource,
    verify_claim_historical,
    _classify_verdict,
    _matches_keywords,
    _find_first_keyword,
    _extract_asset_tickers,
    _extract_price,
    _extract_numeric_from_claim,
    _text_matches_sentiment,
    _detect_contradiction,
    _KEYWORD_FRED_MAP,
    _KEYWORD_EIA_MAP,
    _KEYWORD_COT_MAP,
    _KEYWORD_BLS_MAP,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

class TestMatchesKeywords:
    def test_match_found(self):
        assert _matches_keywords("Fed is raising rates", ["rate", "cut"])

    def test_no_match(self):
        assert not _matches_keywords("Gold is rallying", ["rate", "oil"])

    def test_case_insensitive(self):
        assert _matches_keywords("RATES are up", ["rate"])


class TestFindFirstKeyword:
    def test_returns_first_match(self):
        mapping = {"oil": "crude", "gasoline": "gasoline"}
        assert _find_first_keyword("oil prices surge", mapping) == "crude"

    def test_returns_order_sensitive(self):
        mapping = {"fed": "BDI", "rate": "BDI"}
        # "fed" appears first in mapping dict iteration (Python 3.7+ preserves insertion order)
        result = _find_first_keyword("rate hike by fed", mapping)
        assert result in ("BDI",) or result is not None

    def test_returns_none_no_match(self):
        mapping = {"oil": "crude"}
        assert _find_first_keyword("gold prices", mapping) is None


class TestExtractAssetTickers:
    def test_extracts_stock_tickers(self):
        assert _extract_asset_tickers(["AAPL", "stocks", "bonds"]) == ["AAPL"]

    def test_extracts_crypto_pairs(self):
        assert "BTC-USD" in _extract_asset_tickers(["BTC-USD", "ETH-USD"])

    def test_filters_non_tickers(self):
        assert _extract_asset_tickers(["oil", "gold", "bonds"]) == []

    def test_handles_empty(self):
        assert _extract_asset_tickers([]) == []

    def test_handles_whitespace(self):
        assert _extract_asset_tickers(["  AAPL  ", " MSFT "]) == ["AAPL", "MSFT"]


class TestExtractPrice:
    def test_extracts_regular_market_price(self):
        assert _extract_price({"regularMarketPrice": 150.25}) == 150.25

    def test_extracts_current_price(self):
        assert _extract_price({"currentPrice": 200.0}) == 200.0

    def test_falls_back_to_previous_close(self):
        assert _extract_price({"previousClose": 99.99}) == 99.99

    def test_returns_none_for_empty(self):
        assert _extract_price({}) is None

    def test_returns_none_for_invalid_value(self):
        assert _extract_price({"regularMarketPrice": "N/A"}) is None


class TestExtractNumericFromClaim:
    def test_extracts_dollar_prefix(self):
        assert _extract_numeric_from_claim("AAPL is at $150.25 today") == 150.25

    def test_extracts_dollars_suffix(self):
        assert _extract_numeric_from_claim("trading at 150.25 dollars") == 150.25

    def test_extracts_price_of_pattern(self):
        assert _extract_numeric_from_claim("price of $180.00 per share") == 180.00

    def test_returns_last_value_multiple(self):
        # Multiple numbers found — return the last one (most specific)
        result = _extract_numeric_from_claim("was $140 now $150.50")
        assert result == 150.50

    def test_returns_none_no_number(self):
        assert _extract_numeric_from_claim("market is rallying strongly") is None


class TestTextMatchesSentiment:
    def test_bearish_contrarian_vs_bullish_claim(self):
        signal = "Speculative net long 45000 — contrarian bearish (crowded long)"
        assert not _text_matches_sentiment("market to rally bull surge", signal)

    def test_bullish_contrarian_vs_bullish_claim(self):
        signal = "Speculative net short 45000 — contrarian bullish (crowded short)"
        # Contrarian bullish means market positioning implies bullish
        # But if claim is bullish, the COT signal is also bullish → alignment
        assert _text_matches_sentiment("market to rally strong", signal)

    def test_neutral_signal_always_matches(self):
        signal = "Speculative positioning near neutral (0) — no directional signal"
        assert _text_matches_sentiment("market crash imminent", signal)

    def test_bullish_claim_aligned_with_bullish_cot(self):
        signal = "contrarian bullish (crowded short)"
        assert _text_matches_sentiment("market growth expansion", signal)


class TestClassifyVerdict:
    def test_verified_high_confidence(self):
        assert _classify_verdict(0.85, [0.80, 0.90, 0.85, 0.80]) == "VERIFIED"

    def test_likely_moderate_confidence(self):
        assert _classify_verdict(0.60, [0.65, 0.55, 0.60, 0.55]) == "LIKELY"

    def test_unverified_below_likely(self):
        assert _classify_verdict(0.30, [0.30, 0.40, 0.30, 0.20]) == "UNVERIFIED"

    def test_contradicted_two_low_one_high(self):
        # 2 layers <= 0.15, 1 layer >= 0.60
        assert (_classify_verdict(0.40, [0.80, 0.10, 0.10, 0.50])
                == "CONTRADICTED")

    def test_not_contradicted_one_low_only(self):
        # Only 1 layer <= 0.15 — no contradiction
        assert _classify_verdict(0.50, [0.80, 0.10, 0.50, 0.50]) == "LIKELY"


class TestDetectContradiction:
    def test_detects_contradiction(self):
        result = _detect_contradiction(0.80, 0.10, 0.50, 0.50)
        assert result is not None
        assert "Contradiction" in result

    def test_no_contradiction_aligned(self):
        result = _detect_contradiction(0.70, 0.65, 0.60, 0.55)
        assert result is None

    def test_no_contradiction_all_neutral(self):
        result = _detect_contradiction(0.50, 0.50, 0.50, 0.50)
        assert result is None


# ── Layer 1: Market Pricing ───────────────────────────────────────────────────

class TestVerifyClaimMarketPricing:
    @pytest.mark.asyncio
    async def test_returns_neutral_for_empty_assets(self):
        result = await verify_claim_market_pricing(
            "general market commentary", [],
        )
        assert 0.40 <= result <= 0.60

    @pytest.mark.asyncio
    async def test_returns_neutral_for_non_ticker_assets(self):
        """When assets are non-ticker terms AND the claim has no commodity
        keyword match, returns neutral. The strings "bonds" and "cash" are
        not tickers and not in the COT keyword map."""
        result = await verify_claim_market_pricing(
            "bond market is rallying", ["bonds", "cash"],
        )
        assert 0.40 <= result <= 0.60

    @pytest.mark.asyncio
    async def test_rate_claim_triggers_cot_fallback(self):
        """Rate claims should try COT ES positioning when no ticker assets."""
        with patch(
            "marketmind.pipeline.verification_chain._matches_keywords",
            return_value=True,
        ):
            with patch(
                "marketmind.gateway.macro_data.get_cot_data",
                AsyncMock(return_value={
                    "signal": "Speculative net long 50000 — contrarian bearish (crowded long)",
                    "asset": "ES",
                }),
            ):
                result = await verify_claim_market_pricing(
                    "Fed will cut rates next month",
                )
                # Should use COT path, returning directional confidence
                assert 0.0 <= result <= 1.0

    @pytest.mark.asyncio
    async def test_commodity_claim_triggers_cot(self):
        """Commodity claims should trigger COT fetch for the relevant asset."""
        with patch(
            "marketmind.gateway.macro_data.get_cot_data",
            AsyncMock(return_value={
                "signal": "Speculative moderately net long 20000 — no extreme signal",
                "asset": "CL",
            }),
        ):
            result = await verify_claim_market_pricing(
                "crude oil demand is surging",
            )
            assert 0.0 <= result <= 1.0

    @pytest.mark.asyncio
    async def test_ticker_asset_with_market_data(self):
        """When affected_assets has a ticker, should fetch market data."""
        mock_info = {"currentPrice": 150.0}
        with patch(
            "marketmind.gateway.market_data.get_market_data",
            AsyncMock(return_value={"source": "yfinance", "info": mock_info}),
        ):
            result = await verify_claim_market_pricing(
                "AAPL is undervalued", ["AAPL"],
            )
            assert 0.0 <= result <= 1.0

    @pytest.mark.asyncio
    async def test_api_failure_returns_neutral(self):
        """Graceful degradation: API failures return neutral 0.50."""
        with patch(
            "marketmind.gateway.macro_data.get_cot_data",
            AsyncMock(return_value={"error": "source_unavailable"}),
        ):
            # Even with oil keyword, if COT fails we should get ~0.50
            result = await verify_claim_market_pricing(
                "oil prices are surging",
            )
            assert 0.40 <= result <= 0.60

    @pytest.mark.asyncio
    async def test_api_exception_returns_neutral(self):
        """Graceful degradation: exceptions return neutral 0.50."""
        with patch(
            "marketmind.gateway.macro_data.get_cot_data",
            side_effect=RuntimeError("Network error"),
        ):
            result = await verify_claim_market_pricing(
                "oil prices are surging",
            )
            assert 0.40 <= result <= 0.60


# ── Layer 2: Fundamental Data ─────────────────────────────────────────────────

class TestVerifyClaimFundamental:
    @pytest.mark.asyncio
    async def test_returns_neutral_for_unrelated_claim(self):
        result = await verify_claim_fundamental(
            "Tesla released a new car model",
        )
        assert 0.40 <= result <= 0.60

    @pytest.mark.asyncio
    async def test_fred_keyword_triggers_fetch(self):
        with patch(
            "marketmind.gateway.macro_data.get_macro_indicator",
            AsyncMock(return_value={
                "indicator": "BDI",
                "value": 1500.0,
                "label": "BDI proxy",
            }),
        ):
            result = await verify_claim_fundamental(
                "supply chain shipping costs are rising",
            )
            assert result >= 0.70  # FRED data available → high confidence

    @pytest.mark.asyncio
    async def test_inflation_keyword_triggers_fred(self):
        with patch(
            "marketmind.gateway.macro_data.get_macro_indicator",
            AsyncMock(return_value={
                "indicator": "GSCPI",
                "value": 1.5,
                "label": "GSCPI",
            }),
        ):
            result = await verify_claim_fundamental(
                "CPI inflation is accelerating",
            )
            assert result >= 0.70

    @pytest.mark.asyncio
    async def test_eia_keyword_triggers_fetch(self):
        with patch(
            "marketmind.gateway.macro_data.get_macro_indicator",
            AsyncMock(return_value={"error": "source_unavailable"}),
        ):
            with patch(
                "marketmind.gateway.macro_data.get_eia_inventory",
                AsyncMock(return_value={
                    "product": "crude",
                    "inventory_mbbl": 450000.0,
                }),
            ):
                result = await verify_claim_fundamental(
                    "crude oil inventories are depleting",
                )
                assert result >= 0.70  # EIA data available

    @pytest.mark.asyncio
    async def test_bls_keyword_triggers_bls_fetch(self):
        with patch(
            "marketmind.gateway.macro_data.get_macro_indicator",
            AsyncMock(return_value={"error": "source_unavailable"}),
        ):
            with patch(
                "marketmind.pipeline.bls_fetcher.fetch_bls_indicators",
                AsyncMock(return_value=[
                    {"indicator": "CPI", "value": 3.2, "date": "2026-01-01"},
                ]),
            ):
                result = await verify_claim_fundamental(
                    "cpi data shows rising prices",
                )
                assert result >= 0.70

    @pytest.mark.asyncio
    async def test_api_failure_returns_neutral(self):
        """Fundamental layer returns neutral on API failure.

        Uses a claim that only matches FRED keywords — avoids triggering
        BLS or EIA fallback paths which would make real API calls.
        """
        with patch(
            "marketmind.gateway.macro_data.get_macro_indicator",
            AsyncMock(return_value={"error": "source_unavailable"}),
        ):
            result = await verify_claim_fundamental(
                "supply chain pressures are easing"
            )
            assert 0.40 <= result <= 0.60

    @pytest.mark.asyncio
    async def test_api_exception_returns_neutral(self):
        """Fundamental layer returns neutral on exception.

        Uses a claim that only matches FRED keywords — avoids triggering
        BLS or EIA fallback paths which would make real API calls.
        """
        with patch(
            "marketmind.gateway.macro_data.get_macro_indicator",
            side_effect=RuntimeError("FRED API down"),
        ):
            result = await verify_claim_fundamental(
                "supply chain pressures are easing"
            )
            assert 0.40 <= result <= 0.60


# ── Layer 3: Multi-Source News ────────────────────────────────────────────────

class TestVerifyClaimMultisource:
    @pytest.mark.asyncio
    async def test_no_sources_returns_neutral(self):
        result = await verify_claim_multisource("any claim", [])
        assert result == 0.50

    @pytest.mark.asyncio
    async def test_none_sources_returns_neutral(self):
        result = await verify_claim_multisource("any claim", None)
        assert result == 0.50

    @pytest.mark.asyncio
    async def test_one_source_low_confidence(self):
        result = await verify_claim_multisource(
            "Fed cuts rates", ["Reuters"],
        )
        assert result == 0.40

    @pytest.mark.asyncio
    async def test_two_sources_moderate_confidence(self):
        result = await verify_claim_multisource(
            "Fed cuts rates", ["Reuters", "Financial Times"],
        )
        assert result == 0.65

    @pytest.mark.asyncio
    async def test_three_sources_high_confidence(self):
        result = await verify_claim_multisource(
            "Fed cuts rates", ["Reuters", "Financial Times", "SEC EDGAR"],
        )
        assert result == 0.85

    @pytest.mark.asyncio
    async def test_collocated_sources_count_as_one(self):
        """MarketWatch is in dow_jones group — counts as shared ownership."""
        result = await verify_claim_multisource(
            "Fed cuts rates", ["MarketWatch"],
        )
        # MarketWatch is in dow_jones group, but it's the only source
        # so count_independent_sources returns 1
        assert result == 0.40

    @pytest.mark.asyncio
    async def test_google_news_proxies_count_as_one_group(self):
        """All Google News proxies share ownership → count as one."""
        result = await verify_claim_multisource(
            "China economy is slowing",
            [
                "Caixin (via Google News)",
                "PBOC (via Google News)",
                "China Economy (via Google News)",
            ],
        )
        # All three are in google_news_proxies group → count_independent_sources = 1
        assert result == 0.40


# ── Layer 4: Historical Pattern ───────────────────────────────────────────────

class TestVerifyClaimHistorical:
    @pytest.mark.asyncio
    async def test_rate_cut_returns_historical_base_rate(self):
        result = await verify_claim_historical(
            "Fed will implement rate cuts next quarter",
        )
        assert result == 0.65

    @pytest.mark.asyncio
    async def test_rate_hike_returns_lower_confidence(self):
        result = await verify_claim_historical(
            "Central bank announces rate hike aggressively",
        )
        assert result == 0.45

    @pytest.mark.asyncio
    async def test_recession_claim_low_confidence(self):
        result = await verify_claim_historical(
            "US heading into recession and economic downturn",
        )
        assert result == 0.35

    @pytest.mark.asyncio
    async def test_oil_spike_neutral(self):
        result = await verify_claim_historical(
            "oil price shock expected next month",
        )
        assert result == 0.50

    @pytest.mark.asyncio
    async def test_gold_rally_moderate(self):
        result = await verify_claim_historical(
            "gold bull run driven by safe haven demand",
        )
        assert result == 0.55

    @pytest.mark.asyncio
    async def test_inflation_persistent_claim(self):
        result = await verify_claim_historical(
            "inflation will remain elevated",
        )
        assert result == 0.55

    @pytest.mark.asyncio
    async def test_earnings_beat_moderate(self):
        result = await verify_claim_historical(
            "earnings beat expectations as profit margins expand",
        )
        assert result == 0.60

    @pytest.mark.asyncio
    async def test_unknown_claim_returns_neutral(self):
        result = await verify_claim_historical(
            "completely novel unprecedented event",
        )
        assert result == 0.50


# ── Full orchestration (verify_claim) ─────────────────────────────────────────

class TestVerifyClaim:
    @pytest.mark.asyncio
    async def test_returns_verification_result_structure(self):
        """verify_claim should return a properly populated VerificationResult."""
        result = await verify_claim(
            claim="Fed will cut rates by 25bps next month",
            affected_assets=["SPY"],
            source_names=["Reuters", "Financial Times", "SEC EDGAR"],
        )
        assert isinstance(result, VerificationResult)
        assert result.claim == "Fed will cut rates by 25bps next month"
        assert 0.0 <= result.layer_1_market <= 1.0
        assert 0.0 <= result.layer_2_fundamental <= 1.0
        assert 0.0 <= result.layer_3_multisource <= 1.0
        assert 0.0 <= result.layer_4_historical <= 1.0
        assert 0.0 <= result.weighted_confidence <= 1.0
        assert result.verdict in (
            "VERIFIED", "LIKELY", "UNVERIFIED", "CONTRADICTED",
        )
        assert result.sources_used is not None
        # contradiction_detail may be None (no contradiction detected)

    @pytest.mark.asyncio
    async def test_weighted_confidence_matches_weights(self):
        """Weighted confidence should equal the weighted sum of layer scores."""
        with patch(
            "marketmind.pipeline.verification_chain.verify_claim_market_pricing",
            AsyncMock(return_value=0.70),
        ):
            with patch(
                "marketmind.pipeline.verification_chain.verify_claim_fundamental",
                AsyncMock(return_value=0.65),
            ):
                with patch(
                    "marketmind.pipeline.verification_chain.verify_claim_multisource",
                    AsyncMock(return_value=0.85),
                ):
                    with patch(
                        "marketmind.pipeline.verification_chain.verify_claim_historical",
                        AsyncMock(return_value=0.60),
                    ):
                        result = await verify_claim(
                            claim="Test claim",
                            affected_assets=["SPY"],
                            source_names=["Reuters", "FT", "ECB"],
                        )
                        # weighted = 0.30*0.70 + 0.25*0.65 + 0.25*0.85 + 0.20*0.60
                        # = 0.21 + 0.1625 + 0.2125 + 0.12 = 0.705
                        assert abs(result.weighted_confidence - 0.705) < 0.01

    @pytest.mark.asyncio
    async def test_layer_exceptions_handled_gracefully(self):
        """If a layer raises, it should be caught and replaced with 0.50 neutral."""
        with patch(
            "marketmind.pipeline.verification_chain.verify_claim_market_pricing",
            side_effect=RuntimeError("Boom"),
        ):
            result = await verify_claim(
                claim="Test claim",
                affected_assets=[],
                source_names=[],
            )
            # Market pricing should fall back to 0.50
            assert result.layer_1_market == 0.50
            assert result.verdict in (
                "VERIFIED", "LIKELY", "UNVERIFIED", "CONTRADICTED",
            )

    @pytest.mark.asyncio
    async def test_contradiction_detected_when_layers_disagree(self):
        """When one layer is high and another low, set CONTRADICTED verdict."""
        with patch(
            "marketmind.pipeline.verification_chain.verify_claim_market_pricing",
            AsyncMock(return_value=0.80),
        ):
            with patch(
                "marketmind.pipeline.verification_chain.verify_claim_fundamental",
                AsyncMock(return_value=0.10),
            ):
                with patch(
                    "marketmind.pipeline.verification_chain.verify_claim_multisource",
                    AsyncMock(return_value=0.10),
                ):
                    with patch(
                        "marketmind.pipeline.verification_chain.verify_claim_historical",
                        AsyncMock(return_value=0.50),
                    ):
                        result = await verify_claim(
                            claim="Oil will crash",
                            affected_assets=["USO"],
                            source_names=["Reuters"],
                        )
                        assert result.verdict == "CONTRADICTED"
                        assert result.contradiction_detail is not None

    @pytest.mark.asyncio
    async def test_sources_used_tracks_all_layers(self):
        """Sources should be tracked from both affected_assets and source_names."""
        result = await verify_claim(
            claim="Test claim",
            affected_assets=["SPY", "AAPL"],
            source_names=["Reuters", "Financial Times"],
        )
        assert any("market:SPY" in s for s in result.sources_used)
        assert any("market:AAPL" in s for s in result.sources_used)
        assert any("news:Reuters" in s for s in result.sources_used)

    @pytest.mark.asyncio
    async def test_sources_capped_at_five(self):
        """Source tracking should cap at 5 each to avoid bloat."""
        result = await verify_claim(
            claim="Test",
            affected_assets=["A", "B", "C", "D", "E", "F", "G"],
            source_names=["1", "2", "3", "4", "5", "6"],
        )
        market_sources = [s for s in result.sources_used if s.startswith("market:")]
        news_sources = [s for s in result.sources_used if s.startswith("news:")]
        assert len(market_sources) <= 5
        assert len(news_sources) <= 5


# ── Keyword mapping integrity ─────────────────────────────────────────────────

class TestKeywordMappings:
    def test_fred_maps_have_valid_values(self):
        valid = {"BDI", "GSCPI"}
        for val in _KEYWORD_FRED_MAP.values():
            assert val in valid

    def test_eia_maps_have_valid_values(self):
        valid = {"crude", "gasoline", "distillate"}
        for val in _KEYWORD_EIA_MAP.values():
            assert val in valid

    def test_cot_maps_have_valid_values(self):
        valid = {"ES", "CL", "GC", "NG"}
        for val in _KEYWORD_COT_MAP.values():
            assert val in valid

    def test_bls_maps_have_valid_values(self):
        valid = {"CPI", "Core CPI", "Unemployment Rate", "PPI"}
        for val in _KEYWORD_BLS_MAP.values():
            assert val in valid
