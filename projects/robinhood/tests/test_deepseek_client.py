"""
test_deepseek_client.py - Phase 4: DeepSeek API client tests.

Tests dispatch_prompt(), format_pro_model_response(), and build_pro_model_prompt()
under mock mode, error conditions, and edge cases.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# Use the standalone sub-functions imported from their origin modules
from src.deepseek_client import dispatch_prompt
from src.ascii_utils import clean_ascii_only
from src.pro_model_deep_dive import build_pro_model_prompt, format_pro_model_response

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def mock_resonance_result() -> dict:
    return {
        "weighted_score": 72.5,
        "signal": "BUY",
        "resonance_condition_met": True,
        "soft_veto_triggered": False,
        "override_available": False,
        "scores": {
            "fundamental": {"score": 78, "weight": 0.30},
            "technical": {"score": 72, "weight": 0.30},
            "event": {"score": 65, "weight": 0.20},
            "sentiment": {"score": 68, "weight": 0.20},
        },
    }


@pytest.fixture
def mock_capital_result() -> dict:
    return {
        "max_allocation": 2500.00,
        "cash_reserve_kept": 7500.00,
        "max_shares": 15,
        "price_target": "$210 within next 6 months",
        "stop_loss_level": "$160",
    }


@pytest.fixture
def mock_account_state() -> dict:
    return {
        "cash_available": 10000.00,
        "existing_positions": {
            "AAPL": {"shares": 10, "avg_cost": 165.00},
            "MSFT": {"shares": 5, "avg_cost": 380.00},
        },
    }


# ---------------------------------------------------------------------------
# Tests: dispatch_prompt
# ---------------------------------------------------------------------------


class TestDispatchPrompt:
    """Tests for dispatch_prompt()."""

    def test_mock_mode_returns_valid_json(self) -> None:
        """Mock mode returns a dict with expected V4 fields."""
        result = dispatch_prompt(
            system_prompt="test system prompt",
            user_prompt="test user prompt",
            mock=True,
            ticker="AAPL",
        )
        assert isinstance(result, dict)
        assert "ticker" in result
        assert result["ticker"] == "AAPL"
        assert "signal" in result
        assert "confidence" in result
        assert "rationale" in result
        assert "_meta" in result

    def test_mock_mode_signal_valid(self) -> None:
        """Mock response has a valid signal field."""
        result = dispatch_prompt(mock=True, ticker="AAPL",
                                 system_prompt="", user_prompt="")
        assert result.get("signal") in ("BUY", "SELL", "HOLD", "NEUTRAL")

    def test_mock_mode_has_meta(self) -> None:
        """Mock response includes _meta diagnostic block."""
        result = dispatch_prompt(mock=True, ticker="MSFT",
                                 system_prompt="", user_prompt="")
        meta = result.get("_meta", {})
        assert isinstance(meta, dict)
        assert "model" in meta
        assert "temperature" in meta

    def test_mock_mode_no_api_key_needed(self) -> None:
        """Mock mode should not raise even if DEEPSEEK_API_KEY is unset."""
        old_key = os.environ.pop("DEEPSEEK_API_KEY", None)
        try:
            result = dispatch_prompt(mock=True, ticker="AAPL",
                                     system_prompt="", user_prompt="")
            assert "ticker" in result
        finally:
            if old_key is not None:
                os.environ["DEEPSEEK_API_KEY"] = old_key


# ---------------------------------------------------------------------------
# Tests: build_pro_model_prompt
# ---------------------------------------------------------------------------


class TestBuildProModelPrompt:
    """Tests for build_pro_model_prompt()."""

    def test_returns_both_prompts(self, mock_resonance_result, mock_capital_result,
                                  mock_account_state) -> None:
        """Returns dict with system_prompt and user_prompt keys."""
        bundle = build_pro_model_prompt(
            resonance_result=mock_resonance_result,
            capital_result=mock_capital_result,
            ticker="AAPL",
            account_state=mock_account_state,
        )
        assert "system_prompt" in bundle
        assert "user_prompt" in bundle

    def test_system_prompt_contains_non_ascii(self, mock_resonance_result,
                                               mock_capital_result,
                                               mock_account_state) -> None:
        """System prompt may contain non-ASCII characters (em dash, smart quotes)."""
        bundle = build_pro_model_prompt(
            resonance_result=mock_resonance_result,
            capital_result=mock_capital_result,
            ticker="AAPL",
            account_state=mock_account_state,
        )
        # clean_ascii_only still works — it strips non-ASCII chars,
        # but the raw prompt is allowed to contain them per the Emoji Policy override
        cleaned = clean_ascii_only(bundle["system_prompt"])
        assert cleaned != bundle["system_prompt"].strip()

    def test_user_prompt_contains_ticker(self, mock_resonance_result,
                                          mock_capital_result,
                                          mock_account_state) -> None:
        """User prompt mentions the target ticker."""
        bundle = build_pro_model_prompt(
            resonance_result=mock_resonance_result,
            capital_result=mock_capital_result,
            ticker="AAPL",
            account_state=mock_account_state,
        )
        assert "AAPL" in bundle["user_prompt"]

    def test_user_prompt_contains_resonance_score(self, mock_resonance_result,
                                                   mock_capital_result,
                                                   mock_account_state) -> None:
        """User prompt includes the weighted resonance score."""
        bundle = build_pro_model_prompt(
            resonance_result=mock_resonance_result,
            capital_result=mock_capital_result,
            ticker="MSFT",
            account_state=mock_account_state,
        )
        assert "72.5" in bundle["user_prompt"]


# ---------------------------------------------------------------------------
# Tests: format_pro_model_response
# ---------------------------------------------------------------------------


class TestFormatProModelResponse:
    """Tests for format_pro_model_response()."""

    def test_valid_json_returns_dict(self) -> None:
        """A valid JSON string is parsed into a dict."""
        raw = json.dumps({"executive_summary": {"signal": "BUY"}})
        result = format_pro_model_response(raw)
        assert isinstance(result, dict)
        assert result["executive_summary"]["signal"] == "BUY"

    def test_invalid_json_returns_error_dict(self) -> None:
        """Malformed JSON returns dict with 'error' and 'raw' keys."""
        raw = "{this is not json}"
        result = format_pro_model_response(raw)
        assert "error" in result
        assert "raw" in result
        assert "this is not json" in result["raw"]

    def test_empty_string_returns_error(self) -> None:
        """Empty string triggers error response."""
        result = format_pro_model_response("")
        assert "error" in result

    def test_full_mock_response_parses(self) -> None:
        """The full mock_pro_response.json can be round-tripped."""
        mock_path = _PROJECT_ROOT / "config" / "mock_pro_response.json"
        raw = mock_path.read_text(encoding="utf-8")
        result = format_pro_model_response(raw)
        assert "executive_summary" in result
        assert "deep_research" in result
        assert "macro_analysis" in result["deep_research"]

    def test_non_ascii_retained(self) -> None:
        """Parsed response fields retain non-ASCII characters (Emoji Policy override)."""
        raw = '{"text": "Hello \U0001f4c8 World \u2014 2025"}'
        result = format_pro_model_response(raw)
        text = result.get("text", "")
        assert "Hello" in text
        assert "World" in text
        assert "2025" in text
        emoji_char = "\U0001f4c8"
        em_dash = "\u2014"
        assert emoji_char in text
        assert em_dash in text
        # clean_ascii_only strips non-ASCII when called explicitly downstream
        cleaned = clean_ascii_only(text)
        assert "Hello" in cleaned
        assert "World" in cleaned
        assert "2025" in cleaned
        assert emoji_char not in cleaned
        assert em_dash not in cleaned
