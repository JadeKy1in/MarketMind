"""Tests for flow_decomposition.py — entity-level capital flow attribution."""
import pytest
from unittest.mock import AsyncMock, patch

from marketmind.config.asset_class_routing import route_asset_class
from marketmind.pipeline.flow_decomposition import (
    FlowAttribution,
    FlowEntity,
    _compute_flow_imbalance,
    _detect_change_trend,
    _parse_json,
    attribute_flows,
)
from marketmind.pipeline.investigation_types import HypothesisResult
from marketmind.pipeline.verification_chain import VerificationResult


# ── Helpers ──────────────────────────────────────────────────────────

def _make_hypothesis(text: str) -> HypothesisResult:
    """Build a minimal HypothesisResult for testing."""
    v = VerificationResult(
        claim=text,
        layer_1_market=0.5,
        layer_2_fundamental=0.5,
        layer_3_multisource=0.5,
        layer_4_historical=0.5,
        weighted_confidence=0.5,
        verdict="LIKELY",
    )
    return HypothesisResult(
        hypothesis=text,
        expectation_gap=0.20,
        verification=v,
        refined_hypothesis=text,
        confidence=0.60,
        bear_case="Counter argument",
        bear_case_confidence=0.30,
        verdict="MONITOR",
    )


# ── Unit tests (no LLM) ─────────────────────────────────────────────

class TestEntityTypesFromAssetClass:
    """Routing should pick correct entity types per asset class."""

    def test_us_fixed_income_entities(self):
        """US_FIXED_INCOME should use US-centric entities (FED, US_HOUSEHOLD, etc.)."""
        config, conf = route_asset_class("Treasury yields are falling, Fed likely to cut rates")
        assert config is not None
        assert config.class_id == "US_FIXED_INCOME"
        assert "FED" in config.entity_types
        assert "US_HOUSEHOLD" in config.entity_types
        assert "FOREIGN_OFFICIAL" in config.entity_types
        assert conf > 0.3

    def test_japanese_equities_entities(self):
        """JAPANESE_EQUITIES should use BOJ/GPIF, NOT US-centric entities."""
        config, conf = route_asset_class("Nikkei 225 surges as BOJ maintains dovish stance")
        assert config is not None
        assert config.class_id == "JAPANESE_EQUITIES"
        assert "BOJ" in config.entity_types
        assert "GPIF" in config.entity_types
        assert "US_HOUSEHOLD" not in config.entity_types
        assert conf > 0.3

    def test_multiple_classes_picks_highest(self):
        """When keywords overlap, highest match count wins."""
        # Contains both Japan keywords and general equity keywords
        config, conf = route_asset_class("Tokyo Nikkei Japanese GPIF yen BOJ carry trade")
        assert config is not None
        assert config.class_id == "JAPANESE_EQUITIES"


class TestFlowImbalance:
    """Verify flow_imbalance = (BUY - SELL) / total."""

    def test_mixed_directions(self):
        """2 BUY + 1 SELL + 2 NEUTRAL -> flow_imbalance = 0.2."""
        entities = [
            FlowEntity("A", "BUY", "X", "moderate", ""),
            FlowEntity("B", "BUY", "X", "moderate", ""),
            FlowEntity("C", "SELL", "X", "moderate", ""),
            FlowEntity("D", "NEUTRAL", "X", "small", ""),
            FlowEntity("E", "NEUTRAL", "X", "small", ""),
        ]
        assert _compute_flow_imbalance(entities) == pytest.approx(0.2)

    def test_all_buying(self):
        """All BUY -> flow_imbalance = 1.0."""
        entities = [
            FlowEntity("A", "BUY", "X", "significant", ""),
            FlowEntity("B", "BUY", "X", "moderate", ""),
            FlowEntity("C", "BUY", "X", "small", ""),
        ]
        assert _compute_flow_imbalance(entities) == 1.0

    def test_all_selling(self):
        """All SELL -> flow_imbalance = -1.0."""
        entities = [
            FlowEntity("A", "SELL", "X", "significant", ""),
            FlowEntity("B", "SELL", "X", "small", ""),
        ]
        assert _compute_flow_imbalance(entities) == -1.0

    def test_balanced(self):
        """Equal BUY and SELL -> flow_imbalance = 0.0."""
        entities = [
            FlowEntity("A", "BUY", "X", "moderate", ""),
            FlowEntity("B", "SELL", "X", "moderate", ""),
        ]
        assert _compute_flow_imbalance(entities) == 0.0

    def test_empty_entities(self):
        """Empty list -> 0.0."""
        assert _compute_flow_imbalance([]) == 0.0


class TestDetectChangeTrend:
    """Verify trend detection from rationale text patterns."""

    def test_accelerating_inflow(self):
        rationales = ["Capital is accelerating into Treasuries", "Surging demand from foreign buyers"]
        assert _detect_change_trend(rationales) == "加速流入"

    def test_slowing_inflow(self):
        rationales = ["Inflows are slowing as yields stabilize", "Tapering demand from institutions"]
        assert _detect_change_trend(rationales) == "流入放缓"

    def test_outflow_reversal(self):
        rationales = ["Rotation out of equities accelerating", "Outflow reversal as sentiment shifts"]
        assert _detect_change_trend(rationales) == "转向流出"

    def test_stable_default(self):
        rationales = ["Steady accumulation continues", "No significant change in positioning"]
        assert _detect_change_trend(rationales) == "稳定"

    def test_empty_rationales(self):
        assert _detect_change_trend([]) == "稳定"

    def test_priority_outflow_beats_others(self):
        """Outflow keywords take priority even when acceleration keywords present."""
        rationales = ["Surge of outflow from institutional investors"]
        assert _detect_change_trend(rationales) == "转向流出"


class TestParseJson:
    """Verify JSON parser handles normal and markdown-wrapped responses."""

    def test_plain_json(self):
        assert _parse_json('{"key": "val"}') == {"key": "val"}

    def test_markdown_wrapped(self):
        assert _parse_json('```json\n{"key": "val"}\n```') == {"key": "val"}

    def test_embedded_json(self):
        assert _parse_json('text before {"key": "val"} after') == {"key": "val"}

    def test_invalid_json(self):
        assert _parse_json("not json at all") is None

    def test_empty_and_none(self):
        assert _parse_json("") is None
        assert _parse_json(None) is None  # type: ignore


# ── Async tests (with mock) ──────────────────────────────────────────

class TestAttributeFlows:
    """Integration-style tests for attribute_flows with mocked chat_pro."""

    @pytest.mark.asyncio
    async def test_unclassifiable_returns_none(self):
        """No matching asset class -> None without calling chat_pro."""
        h = _make_hypothesis("xyzzy unclassifiable gibberish text here 12345")
        result = await attribute_flows(h)
        assert result is None

    @pytest.mark.asyncio
    async def test_dominant_buyer_seller_populated(self):
        """Valid flow attribution should identify dominant buyer and seller."""
        mock_response = {
            "content": '{"entities": ['
                       '{"name": "FED", "direction": "BUY", "estimated_size": "significant", "rationale": "QE tapering boosts demand"}, '
                       '{"name": "US_HOUSEHOLD", "direction": "BUY", "estimated_size": "moderate", "rationale": "Yield-seeking behavior"}, '
                       '{"name": "FOREIGN_OFFICIAL", "direction": "SELL", "estimated_size": "moderate", "rationale": "Diversification away from USD"}'
                       '], "dominant_buyer": "FED", "dominant_seller": "FOREIGN_OFFICIAL", "change_trend": "加速流入", "confidence": 0.85}',
            "error": None,
        }
        h = _make_hypothesis("Treasury yields are falling as Fed signals dovish pivot")

        with patch(
            "marketmind.pipeline.flow_decomposition.chat_pro",
            AsyncMock(return_value=mock_response),
        ):
            result = await attribute_flows(h)

        assert result is not None
        assert result.asset_class == "US_FIXED_INCOME"
        assert len(result.entities) == 3
        assert result.dominant_buyer == "FED"
        assert result.dominant_seller == "FOREIGN_OFFICIAL"
        assert result.change_trend == "加速流入"
        assert result.confidence == pytest.approx(0.85)
        # 2 BUY + 1 SELL -> (2-1)/3 = 0.333...
        assert result.flow_imbalance == pytest.approx(1.0 / 3.0)

    @pytest.mark.asyncio
    async def test_budget_exhausted_returns_none(self):
        """When pro_calls_used >= MAX_PRO_CALLS_PER_SESSION, skip without calling."""
        h = _make_hypothesis("Treasury yields falling")
        result = await attribute_flows(h, pro_calls_used=[30])
        assert result is None

    @pytest.mark.asyncio
    async def test_pro_error_returns_none(self):
        """When chat_pro returns an error, attribute_flows returns None."""
        mock_response = {"content": "", "error": "budget_exhausted"}
        h = _make_hypothesis("Treasury yields are falling as Fed signals dovish pivot")

        with patch(
            "marketmind.pipeline.flow_decomposition.chat_pro",
            AsyncMock(return_value=mock_response),
        ):
            result = await attribute_flows(h)
        assert result is None

    @pytest.mark.asyncio
    async def test_unparseable_response_returns_none(self):
        """When Pro returns unparseable content, return None."""
        mock_response = {"content": "this is not json and has no braces", "error": None}
        h = _make_hypothesis("Treasury yields are falling as Fed signals dovish pivot")

        with patch(
            "marketmind.pipeline.flow_decomposition.chat_pro",
            AsyncMock(return_value=mock_response),
        ):
            result = await attribute_flows(h)
        assert result is None

    @pytest.mark.asyncio
    async def test_pro_calls_counter_increments(self):
        """After a successful Pro call, the counter increments."""
        mock_response = {
            "content": '{"entities": ['
                       '{"name": "FED", "direction": "BUY", "estimated_size": "significant", "rationale": "Dovish pivot"}], '
                       '"dominant_buyer": "FED", "dominant_seller": "", "change_trend": "稳定", "confidence": 0.70}',
            "error": None,
        }
        h = _make_hypothesis("Treasury yields are falling as Fed signals dovish pivot")
        counter = [0]

        with patch(
            "marketmind.pipeline.flow_decomposition.chat_pro",
            AsyncMock(return_value=mock_response),
        ):
            result = await attribute_flows(h, pro_calls_used=counter)

        assert result is not None
        assert counter[0] == 1

    @pytest.mark.asyncio
    async def test_change_trend_fallback_from_rationales(self):
        """When Pro returns invalid change_trend, detect from entity rationales."""
        mock_response = {
            "content": '{"entities": ['
                       '{"name": "FED", "direction": "BUY", "estimated_size": "significant", "rationale": "Accelerating Treasury purchases"}, '
                       '{"name": "US_HOUSEHOLD", "direction": "BUY", "estimated_size": "moderate", "rationale": "Surging into bond funds"}], '
                       '"dominant_buyer": "FED", "dominant_seller": "", "change_trend": "invalid_value", "confidence": 0.70}',
            "error": None,
        }
        h = _make_hypothesis("Treasury yields are falling as Fed signals dovish pivot")

        with patch(
            "marketmind.pipeline.flow_decomposition.chat_pro",
            AsyncMock(return_value=mock_response),
        ):
            result = await attribute_flows(h)

        assert result is not None
        # Fallback detected from "Accelerating", "Surging" in rationales
        assert result.change_trend == "加速流入"
