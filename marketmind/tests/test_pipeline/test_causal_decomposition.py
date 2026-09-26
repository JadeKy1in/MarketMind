"""Tests for causal_decomposition.py — Phase H-1 Module 1."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from marketmind.pipeline.causal_decomposition import (
    CausalDecomposition,
    decompose_hypothesis,
    _extract_tickers,
    _clamp,
    _parse_decomposition_json,
)
from marketmind.pipeline.investigation_types import HypothesisResult
from marketmind.pipeline.verification_chain import VerificationResult


def _make_hypothesis(hypothesis: str, refined: str = "") -> HypothesisResult:
    """Create a minimal HypothesisResult for testing."""
    return HypothesisResult(
        hypothesis=hypothesis,
        expectation_gap=0.25,
        verification=VerificationResult(
            claim=hypothesis,
            layer_1_market=0.6,
            layer_2_fundamental=0.5,
            layer_3_multisource=0.7,
            layer_4_historical=0.4,
            weighted_confidence=0.55,
            verdict="LIKELY",
        ),
        refined_hypothesis=refined or hypothesis,
        confidence=0.65,
        bear_case="Test bear case.",
        bear_case_confidence=0.3,
        verdict="ACTIONABLE",
    )


_VALID_DECOMPOSITION_JSON = """{
    "factors": [
        {"name": "UST issuance surge", "impact": -0.6},
        {"name": "Fed QT continuation", "impact": -0.4},
        {"name": "Foreign official demand", "impact": 0.5}
    ],
    "net_directional_force": -0.25,
    "mechanism_chain": [
        "Treasury increases auction sizes to fund deficit",
        "Net supply overwhelms dealer balance sheet capacity",
        "Yields push higher as primary dealers demand concession"
    ],
    "confidence": 0.72
}"""


# ── Unit tests (no async) ──────────────────────────────────────────────────────

def test_clamp():
    assert _clamp(0.5) == 0.5
    assert _clamp(1.5) == 1.0
    assert _clamp(-2.0) == -1.0
    assert _clamp(0.0) == 0.0


def test_parse_decomposition_json_valid():
    result = _parse_decomposition_json(_VALID_DECOMPOSITION_JSON)
    assert result is not None
    assert len(result["factors"]) == 3
    assert result["factors"][0]["name"] == "UST issuance surge"


def test_parse_decomposition_json_markdown_wrapped():
    wrapped = "```json\n" + _VALID_DECOMPOSITION_JSON + "\n```"
    result = _parse_decomposition_json(wrapped)
    assert result is not None
    assert result["confidence"] == 0.72


def test_parse_decomposition_json_garbage():
    assert _parse_decomposition_json("") is None
    assert _parse_decomposition_json("not json at all") is None


def test_extract_tickers_finds_match():
    text = "TLT yields are rising as the Fed signals QT remains on track"
    tickers = _extract_tickers(text)
    assert "TLT" in tickers


def test_extract_tickers_no_match():
    tickers = _extract_tickers("xyzzy foo bar nothing here")
    assert tickers == []


# ── Async integration tests ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_decompose_us_fixed_income():
    """US Treasury hypothesis should use balance_sheet lens."""
    hyp = _make_hypothesis(
        "Fed QT and Treasury issuance surge will push 10Y yields higher, "
        "bearish for TLT and duration-sensitive fixed income"
    )

    mock_budget = MagicMock()
    mock_budget.can_call_pro.return_value = True

    with patch(
        "marketmind.pipeline.causal_decomposition.chat_pro",
        new_callable=AsyncMock,
    ) as mock_chat_pro, patch(
        "marketmind.pipeline.causal_decomposition.get_budget",
        new_callable=AsyncMock,
    ) as mock_get_budget:
        mock_get_budget.return_value = mock_budget
        mock_chat_pro.return_value = {"content": _VALID_DECOMPOSITION_JSON}

        result = await decompose_hypothesis(hyp)

    assert result is not None
    assert isinstance(result, CausalDecomposition)
    assert result.asset_class == "US_FIXED_INCOME"
    assert result.decomposition_lens == "balance_sheet"
    assert len(result.factors) >= 2
    assert -1.0 <= result.net_directional_force <= 1.0
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.asyncio
async def test_decompose_commodity():
    """Oil hypothesis should use supply_demand_inventory lens."""
    hyp = _make_hypothesis(
        "Crude oil WTI prices face downside as OPEC+ increases supply quotas "
        "while global demand weakens on slowing China industrial output"
    )

    mock_budget = MagicMock()
    mock_budget.can_call_pro.return_value = True

    with patch(
        "marketmind.pipeline.causal_decomposition.chat_pro",
        new_callable=AsyncMock,
    ) as mock_chat_pro, patch(
        "marketmind.pipeline.causal_decomposition.get_budget",
        new_callable=AsyncMock,
    ) as mock_get_budget:
        mock_get_budget.return_value = mock_budget

        commodity_json = """{
            "factors": [
                {"name": "OPEC+ supply increase", "impact": -0.7},
                {"name": "China demand weakness", "impact": -0.5},
                {"name": "SPR releases", "impact": -0.3}
            ],
            "net_directional_force": -0.50,
            "mechanism_chain": ["OPEC+ raises quotas", "Surplus builds", "Price slides"],
            "confidence": 0.68
        }"""
        mock_chat_pro.return_value = {"content": commodity_json}

        result = await decompose_hypothesis(hyp)

    assert result is not None
    assert result.asset_class == "COMMODITIES"
    assert result.decomposition_lens == "supply_demand_inventory"
    assert len(result.factors) >= 2


@pytest.mark.asyncio
async def test_decompose_unclassifiable_returns_none():
    """Gibberish hypothesis with no matching keywords -> None."""
    hyp = _make_hypothesis("xyzzy foo bar quux, nothing market-related whatsoever here")

    mock_budget = MagicMock()
    mock_budget.can_call_pro.return_value = True

    with patch(
        "marketmind.pipeline.causal_decomposition.get_budget",
        new_callable=AsyncMock,
    ) as mock_get_budget:
        mock_get_budget.return_value = mock_budget
        result = await decompose_hypothesis(hyp)

    assert result is None


@pytest.mark.asyncio
async def test_net_directional_force_range():
    """Output net_directional_force should be clamped to [-1, +1]."""
    hyp = _make_hypothesis(
        "Fed rate cut expectations send Treasury yields sharply lower, "
        "massive bond rally as duration bets pay off"
    )

    mock_budget = MagicMock()
    mock_budget.can_call_pro.return_value = True

    with patch(
        "marketmind.pipeline.causal_decomposition.chat_pro",
        new_callable=AsyncMock,
    ) as mock_chat_pro, patch(
        "marketmind.pipeline.causal_decomposition.get_budget",
        new_callable=AsyncMock,
    ) as mock_get_budget:
        mock_get_budget.return_value = mock_budget

        # Pro returns out-of-range values to test clamping
        out_of_range_json = """{
            "factors": [
                {"name": "Rate cut pricing", "impact": 1.5},
                {"name": "Dovish forward guidance", "impact": 2.0}
            ],
            "net_directional_force": 3.0,
            "mechanism_chain": ["Fed signals cuts", "Bonds rally"],
            "confidence": 0.9
        }"""
        mock_chat_pro.return_value = {"content": out_of_range_json}

        result = await decompose_hypothesis(hyp)

    assert result is not None
    assert -1.0 <= result.net_directional_force <= 1.0
    for _, impact in result.factors:
        assert -1.0 <= impact <= 1.0
    assert result.factors[0][1] == 1.0   # 1.5 clamped to 1.0


@pytest.mark.asyncio
async def test_factors_non_empty_for_valid_input():
    """Valid hypothesis should produce at least 2 factors."""
    hyp = _make_hypothesis(
        "The Fed balance sheet reduction combined with heavy Treasury issuance "
        "creates a supply overhang that will push yields higher across the curve"
    )

    mock_budget = MagicMock()
    mock_budget.can_call_pro.return_value = True

    with patch(
        "marketmind.pipeline.causal_decomposition.chat_pro",
        new_callable=AsyncMock,
    ) as mock_chat_pro, patch(
        "marketmind.pipeline.causal_decomposition.get_budget",
        new_callable=AsyncMock,
    ) as mock_get_budget:
        mock_get_budget.return_value = mock_budget
        mock_chat_pro.return_value = {"content": _VALID_DECOMPOSITION_JSON}

        result = await decompose_hypothesis(hyp)

    assert result is not None
    assert len(result.factors) >= 2
    assert len(result.mechanism_chain) >= 1


@pytest.mark.asyncio
async def test_budget_exhausted_returns_none():
    """When pro budget is exhausted, skip and return None."""
    hyp = _make_hypothesis(
        "Fed QT and Treasury issuance surge will push 10Y yields higher"
    )

    mock_budget = MagicMock()
    mock_budget.can_call_pro.return_value = False

    with patch(
        "marketmind.pipeline.causal_decomposition.get_budget",
        new_callable=AsyncMock,
    ) as mock_get_budget:
        mock_get_budget.return_value = mock_budget
        result = await decompose_hypothesis(hyp)

    assert result is None


@pytest.mark.asyncio
async def test_chat_pro_error_returns_none():
    """When chat_pro returns an error, gracefully return None."""
    hyp = _make_hypothesis(
        "Fed QT and Treasury issuance surge will push 10Y yields higher"
    )

    mock_budget = MagicMock()
    mock_budget.can_call_pro.return_value = True

    with patch(
        "marketmind.pipeline.causal_decomposition.chat_pro",
        new_callable=AsyncMock,
    ) as mock_chat_pro, patch(
        "marketmind.pipeline.causal_decomposition.get_budget",
        new_callable=AsyncMock,
    ) as mock_get_budget:
        mock_get_budget.return_value = mock_budget
        mock_chat_pro.return_value = {"content": "", "error": "budget_exhausted"}

        result = await decompose_hypothesis(hyp)

    assert result is None
