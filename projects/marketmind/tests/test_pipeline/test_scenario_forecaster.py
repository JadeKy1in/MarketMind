"""Tests for scenario forecaster — branching scenario tree generation."""

import pytest
from unittest.mock import AsyncMock, patch

from marketmind.pipeline.scenario_forecaster import (
    ScenarioBranch,
    ScenarioTree,
    _parse_json_strict,
    _parse_branch,
    forecast_scenarios,
    _generate_tail_risk,
)
from marketmind.pipeline.investigation_loop import HypothesisResult
from marketmind.pipeline.verification_chain import VerificationResult
from marketmind.gateway.token_budget import TokenBudget


# ── Helpers ─────────────────────────────────────────────────────────────────────


def _make_vr(confidence: float = 0.81) -> VerificationResult:
    return VerificationResult(
        claim="Test claim",
        layer_1_market=confidence,
        layer_2_fundamental=confidence,
        layer_3_multisource=confidence,
        layer_4_historical=confidence,
        weighted_confidence=confidence,
        verdict="VERIFIED",
        sources_used=["source_a", "source_b"],
    )


def make_hypothesis(
    verdict: str = "ACTIONABLE",
    confidence: float = 0.75,
    hypothesis: str = "EUR/USD将在未来三个月走强",
    core_logic: str = "欧洲央行加息推动欧元升值",
    direction: str = "EUR/USD 看涨",
    risk_level: str = "中等",
    time_window: str = "2-4周",
    expectation_gap: float = 0.20,
    bear_case_confidence: float = 0.30,
) -> HypothesisResult:
    return HypothesisResult(
        hypothesis=hypothesis,
        expectation_gap=expectation_gap,
        verification=_make_vr(confidence),
        refined_hypothesis=hypothesis,
        confidence=confidence,
        bear_case="美联储可能意外降息",
        bear_case_confidence=bear_case_confidence,
        verdict=verdict,
        logic_chain=["Step 1"],
        direction=direction,
        risk_level=risk_level,
        time_window=time_window,
        core_logic=core_logic,
    )


_MOCK_SCENARIO_RESPONSE = {
    "content": """```json
{
  "key_condition_variables": ["欧洲央行利率政策", "美国通胀数据"],
  "base_case": {
    "conditions": {"欧洲央行利率": "维持加息路径至2026Q2", "美国CPI": "保持在3.0%以下"},
    "probability": 0.55,
    "outcome": "EUR/USD温和上涨至1.12-1.15区间",
    "confidence": 0.72,
    "timeline": "3-6个月"
  },
  "upside_case": {
    "conditions": {"欧洲央行利率": "加速加息，终端利率高于市场预期"},
    "probability": 0.25,
    "outcome": "EUR/USD突破1.18，年底前触及1.20",
    "confidence": 0.65,
    "timeline": "2-4个月"
  },
  "downside_case": {
    "conditions": {"美国通胀": "反弹超预期，美联储被迫加息"},
    "probability": 0.20,
    "outcome": "EUR/USD回落至1.05-1.08区间",
    "confidence": 0.68,
    "timeline": "1-3个月"
  },
  "disclaimer": "以下为条件预测，每个路径依赖假设条件成立。实际结果可能因未预期的外部冲击而偏离。"
}
```"""
}

_MOCK_TAIL_RISK_RESPONSE = {
    "content": """```json
{
  "tail_risk_case": {
    "conditions": {"系统性冲击": "欧洲爆发主权债务危机或美国经济硬着陆"},
    "probability": 0.05,
    "outcome": "EUR/USD暴跌至0.95-1.00，市场恐慌性避险",
    "confidence": 0.35,
    "timeline": "6-12个月"
  }
}
```"""
}

_BAD_JSON_RESPONSE = {"content": "not valid json at all just random text"}


# ── Unit tests: parse helpers ───────────────────────────────────────────────────


class TestParseJsonStrict:
    def test_plain_json(self):
        assert _parse_json_strict('{"key": "val"}') == {"key": "val"}

    def test_markdown_wrapped(self):
        result = _parse_json_strict('```json\n{"key": "val"}\n```')
        assert result == {"key": "val"}

    def test_markdown_no_lang(self):
        result = _parse_json_strict('```\n{"key": "val"}\n```')
        assert result == {"key": "val"}

    def test_embedded_json(self):
        result = _parse_json_strict('prefix {"key": "val"} suffix')
        assert result == {"key": "val"}

    def test_empty_string(self):
        assert _parse_json_strict("") is None

    def test_no_json(self):
        assert _parse_json_strict("just plain text") is None


class TestParseBranch:
    def test_full_branch(self):
        raw = {
            "conditions": {"CPI": "低于3%"},
            "probability": 0.60,
            "outcome": "温和上涨",
            "confidence": 0.70,
            "timeline": "3-6个月",
        }
        branch = _parse_branch(raw)
        assert branch.conditions == {"CPI": "低于3%"}
        assert branch.probability == 0.60
        assert branch.outcome == "温和上涨"
        assert branch.confidence == 0.70
        assert branch.timeline == "3-6个月"

    def test_missing_fields_default(self):
        branch = _parse_branch({})
        assert branch.conditions == {}
        assert branch.probability == 0.0
        assert branch.outcome == ""
        assert branch.confidence == 0.0
        assert branch.timeline == "N/A"

    def test_conditions_coerced_to_string(self):
        branch = _parse_branch({"conditions": {"rate": 5.0, "level": 3}})
        assert branch.conditions == {"rate": "5.0", "level": "3"}


# ── Integration tests: forecast_scenarios ───────────────────────────────────────


class TestForecastForActionable:
    @pytest.mark.asyncio
    async def test_actionable_produces_tree(self):
        """ACTIONABLE hypothesis should produce scenario tree."""
        h = make_hypothesis(verdict="ACTIONABLE")

        with patch(
            "marketmind.pipeline.scenario_forecaster.chat_pro",
            new=AsyncMock(return_value=_MOCK_SCENARIO_RESPONSE),
        ):
            tree = await forecast_scenarios(h)
            assert tree is not None
            assert isinstance(tree, ScenarioTree)
            assert tree.base_case.probability == 0.55
            assert tree.upside_case.probability == 0.25
            assert tree.downside_case.probability == 0.20
            assert tree.tail_risk_case is None

    @pytest.mark.asyncio
    async def test_all_three_branches_populated(self):
        """All 3 main branches must be populated with data."""
        h = make_hypothesis(verdict="ACTIONABLE")

        with patch(
            "marketmind.pipeline.scenario_forecaster.chat_pro",
            new=AsyncMock(return_value=_MOCK_SCENARIO_RESPONSE),
        ):
            tree = await forecast_scenarios(h)
            assert tree is not None

            # Base case must have positive probability and non-empty outcome
            assert tree.base_case.probability > 0
            assert len(tree.base_case.outcome) > 0
            assert len(tree.base_case.conditions) > 0

            # Upside case must have positive probability
            assert tree.upside_case.probability > 0
            assert len(tree.upside_case.outcome) > 0

            # Downside case must have positive probability
            assert tree.downside_case.probability > 0
            assert len(tree.downside_case.outcome) > 0

    @pytest.mark.asyncio
    async def test_key_condition_variables_present(self):
        """Key condition variables must be extracted from response."""
        h = make_hypothesis(verdict="ACTIONABLE")

        with patch(
            "marketmind.pipeline.scenario_forecaster.chat_pro",
            new=AsyncMock(return_value=_MOCK_SCENARIO_RESPONSE),
        ):
            tree = await forecast_scenarios(h)
            assert tree is not None
            assert len(tree.key_condition_variables) >= 2
            assert "欧洲央行利率政策" in tree.key_condition_variables

    @pytest.mark.asyncio
    async def test_disclaimer_in_output(self):
        """Output must include conditional forecasting disclaimer."""
        h = make_hypothesis(verdict="ACTIONABLE")

        with patch(
            "marketmind.pipeline.scenario_forecaster.chat_pro",
            new=AsyncMock(return_value=_MOCK_SCENARIO_RESPONSE),
        ):
            tree = await forecast_scenarios(h)
            assert tree is not None
            assert "条件预测" in tree.disclaimer
            assert len(tree.disclaimer) > 20

    @pytest.mark.asyncio
    async def test_generated_at_is_utc(self):
        """Timestamp must be present and in UTC format."""
        h = make_hypothesis(verdict="ACTIONABLE")

        with patch(
            "marketmind.pipeline.scenario_forecaster.chat_pro",
            new=AsyncMock(return_value=_MOCK_SCENARIO_RESPONSE),
        ):
            tree = await forecast_scenarios(h)
            assert tree is not None
            assert len(tree.generated_at) > 0
            assert tree.generated_at.endswith("Z")


class TestSkipForDiscard:
    @pytest.mark.asyncio
    async def test_discard_returns_none(self):
        """DISCARD hypothesis should return None without calling Pro."""
        h = make_hypothesis(verdict="DISCARD")

        mock_chat = AsyncMock()
        with patch(
            "marketmind.pipeline.scenario_forecaster.chat_pro", mock_chat
        ):
            tree = await forecast_scenarios(h)
            assert tree is None
            mock_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_priced_in_returns_none(self):
        """PRICED_IN hypothesis should return None."""
        h = make_hypothesis(verdict="PRICED_IN")

        mock_chat = AsyncMock()
        with patch(
            "marketmind.pipeline.scenario_forecaster.chat_pro", mock_chat
        ):
            tree = await forecast_scenarios(h)
            assert tree is None
            mock_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_monitor_without_tail_flag_returns_none(self):
        """MONITOR without include_tail_risk should return None."""
        h = make_hypothesis(verdict="MONITOR")

        mock_chat = AsyncMock()
        with patch(
            "marketmind.pipeline.scenario_forecaster.chat_pro", mock_chat
        ):
            tree = await forecast_scenarios(h)
            assert tree is None
            mock_chat.assert_not_called()


class TestTailRiskForMonitor:
    @pytest.mark.asyncio
    async def test_monitor_with_tail_risk_produces_tree(self):
        """MONITOR with include_tail_risk=True should produce tree with tail case."""
        h = make_hypothesis(verdict="MONITOR", confidence=0.55)

        with patch(
            "marketmind.pipeline.scenario_forecaster.chat_pro",
            new=AsyncMock(return_value=_MOCK_SCENARIO_RESPONSE),
        ):
            with patch(
                "marketmind.pipeline.scenario_forecaster._generate_tail_risk",
                new=AsyncMock(
                    return_value={
                        "conditions": {"系统性冲击": "主权债务危机"},
                        "probability": 0.05,
                        "outcome": "EUR/USD暴跌",
                        "confidence": 0.35,
                        "timeline": "6-12个月",
                    }
                ),
            ):
                tree = await forecast_scenarios(h, include_tail_risk=True)
                assert tree is not None
                assert tree.tail_risk_case is not None
                assert tree.tail_risk_case.probability < 0.10
                assert len(tree.tail_risk_case.outcome) > 0

    @pytest.mark.asyncio
    async def test_tail_risk_low_probability(self):
        """Tail risk case must have low probability (< 10%)."""
        h = make_hypothesis(verdict="MONITOR", confidence=0.55)

        with patch(
            "marketmind.pipeline.scenario_forecaster.chat_pro",
            new=AsyncMock(return_value=_MOCK_SCENARIO_RESPONSE),
        ):
            with patch(
                "marketmind.pipeline.scenario_forecaster._generate_tail_risk",
                new=AsyncMock(
                    return_value={
                        "conditions": {"黑天鹅": "事件"},
                        "probability": 0.03,
                        "outcome": "极端情况",
                        "confidence": 0.25,
                        "timeline": "N/A",
                    }
                ),
            ):
                tree = await forecast_scenarios(h, include_tail_risk=True)
                assert tree is not None
                assert tree.tail_risk_case is not None
                assert tree.tail_risk_case.probability < 0.10


class TestBudgetControl:
    @pytest.mark.asyncio
    async def test_budget_exhausted_returns_none(self):
        """When budget has no Pro calls remaining, return None."""
        h = make_hypothesis(verdict="ACTIONABLE")
        exhausted_budget = TokenBudget(
            daily_limit=100000, pro_call_limit=0, flash_call_limit=50
        )

        mock_chat = AsyncMock()
        with patch(
            "marketmind.pipeline.scenario_forecaster.chat_pro", mock_chat
        ):
            tree = await forecast_scenarios(h, budget=exhausted_budget)
            assert tree is None
            mock_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_budget_available_proceeds(self):
        """When budget has Pro calls remaining, proceed normally."""
        h = make_hypothesis(verdict="ACTIONABLE")
        budget = TokenBudget(
            daily_limit=100000, pro_call_limit=5, flash_call_limit=50
        )

        with patch(
            "marketmind.pipeline.scenario_forecaster.chat_pro",
            new=AsyncMock(return_value=_MOCK_SCENARIO_RESPONSE),
        ):
            tree = await forecast_scenarios(h, budget=budget)
            assert tree is not None


class TestParseFailureGraceful:
    @pytest.mark.asyncio
    async def test_bad_json_returns_none(self):
        """When Pro returns unparseable content, return None gracefully."""
        h = make_hypothesis(verdict="ACTIONABLE")

        with patch(
            "marketmind.pipeline.scenario_forecaster.chat_pro",
            new=AsyncMock(return_value=_BAD_JSON_RESPONSE),
        ):
            tree = await forecast_scenarios(h)
            assert tree is None

    @pytest.mark.asyncio
    async def test_missing_base_case_returns_none(self):
        """When parsed JSON lacks base_case, still produce tree with defaults (doesn't crash)."""
        h = make_hypothesis(verdict="ACTIONABLE")
        malformed = {"content": '{"key_condition_variables": [], "disclaimer": "test"}'}

        with patch(
            "marketmind.pipeline.scenario_forecaster.chat_pro",
            new=AsyncMock(return_value=malformed),
        ):
            tree = await forecast_scenarios(h)
            # Should still produce a tree with default branches (no crash)
            assert tree is not None
            assert tree.base_case.probability == 0.0
