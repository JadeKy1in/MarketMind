"""
test_sentiment_engine.py - Comprehensive pytest suite for Task 2.4 Sentiment Engine.

Tests cover:
  - No API key fallback (graceful degradation)
  - Successful DeepSeek API response parsing
  - API call failure (HTTP error, network timeout)
  - Malformed JSON from LLM (with markdown extraction fallback)
  - Emoji/non-ASCII cleaning on reasoning field
  - Field normalization (ticker uppercase, sentiment capitalization, magnitude clamping)
  - Empty / whitespace-only input handling
"""

from __future__ import annotations

from typing import Any
from unittest.mock import ANY, MagicMock, patch

import httpx
import pytest

from src.sentiment_engine import (
    SYSTEM_PROMPT_TEMPLATE,
    _build_system_prompt,
    _make_neutral_fallback,
    analyze_sentiment,
)


# =========================================================================
# Unit tests for internal helpers
# =========================================================================


class TestSentimentEngineHelpers:
    """Tests for _build_system_prompt and _make_neutral_fallback."""

    def test_build_system_prompt_contains_input_text(self):
        prompt = _build_system_prompt("Test headline")
        assert "{input_text}" not in prompt, "input_text placeholder not substituted"
        assert "Test headline" in prompt

    def test_build_system_prompt_template_has_required_keys(self):
        """Template must reference the input_text placeholder."""
        assert "{input_text}" in SYSTEM_PROMPT_TEMPLATE

    def test_make_neutral_fallback_returns_neutral(self):
        fallback = _make_neutral_fallback("Something went wrong")
        assert fallback["ticker"] == "UNKNOWN"
        assert fallback["sentiment"] == "Neutral"
        assert fallback["magnitude"] == 0
        assert "Something went wrong" in fallback["reasoning"]

    def test_make_neutral_fallback_cleans_ascii(self):
        """Even the fallback reasoning should be ASCII-cleaned."""
        fallback = _make_neutral_fallback("Test with emoji 😊")
        assert "😊" not in fallback["reasoning"]


# =========================================================================
# No API key fallback
# =========================================================================


class TestSentimentEngineNoAPIKey:
    """Graceful degradation when DEEPSEEK_API_KEY is not set."""

    def test_no_api_key_returns_neutral(self):
        result = analyze_sentiment("Some news text", api_key="")
        assert result["ticker"] == "UNKNOWN"
        assert result["sentiment"] == "Neutral"
        assert result["magnitude"] == 0
        assert "not configured" in result["reasoning"]

    def test_no_api_key_none_param(self):
        result = analyze_sentiment("More text", api_key=None)
        assert result["sentiment"] == "Neutral"

    @patch.dict("os.environ", {}, clear=True)
    def test_no_env_var_returns_fallback(self):
        """With no env var and no api_key param, should fall back."""
        result = analyze_sentiment("Some headline")
        assert result["sentiment"] == "Neutral"
        assert result["magnitude"] == 0


# =========================================================================
# API Mock tests (successful response)
# =========================================================================


def _mock_httpx_response(response_data: dict[str, Any]) -> MagicMock:
    """Create a mock httpx.Response that works with Python 3.14+
    
    httpx.Response(200, json=...) requires request attribute for raise_for_status
    in newer httpx versions. Use MagicMock to bypass this.
    """
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = response_data
    return mock_resp


def _mock_successful_response(
    ticker: str = "AAPL",
    sentiment: str = "Positive",
    magnitude: int = 75,
    reasoning: str = "Strong earnings beat and positive guidance.",
) -> dict[str, Any]:
    """Simulate a successful DeepSeek API JSON response dict."""
    return {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"ticker": "' + ticker + '", '
                        '"sentiment": "' + sentiment + '", '
                        '"magnitude": ' + str(magnitude) + ', '
                        '"reasoning": "' + reasoning + '"}'
                    )
                }
            }
        ]
    }


class TestSentimentEngineAPISuccess:
    """Tests for successful DeepSeek API responses."""

    @patch("src.sentiment_engine.httpx.post")
    def test_positive_sentiment(self, mock_post):
        mock_post.return_value = _mock_httpx_response(
            _mock_successful_response(
                ticker="AAPL", sentiment="Positive", magnitude=75,
                reasoning="Strong earnings beat and positive guidance.",
            )
        )
        result = analyze_sentiment("Apple beats earnings", api_key="test-key")
        assert result["ticker"] == "AAPL"
        assert result["sentiment"] == "Positive"
        assert result["magnitude"] == 75
        assert "earnings" in result["reasoning"]

    @patch("src.sentiment_engine.httpx.post")
    def test_negative_sentiment(self, mock_post):
        mock_post.return_value = _mock_httpx_response(
            _mock_successful_response(
                ticker="TSLA", sentiment="Negative", magnitude=60,
                reasoning="Delivery numbers miss expectations.",
            )
        )
        result = analyze_sentiment("Tesla deliveries disappoint", api_key="test-key")
        assert result["ticker"] == "TSLA"
        assert result["sentiment"] == "Negative"
        assert result["magnitude"] == 60

    @patch("src.sentiment_engine.httpx.post")
    def test_neutral_sentiment(self, mock_post):
        mock_post.return_value = _mock_httpx_response(
            _mock_successful_response(
                ticker="MSFT", sentiment="Neutral", magnitude=20,
                reasoning="No material news to drive price action.",
            )
        )
        result = analyze_sentiment("Microsoft announces routine update", api_key="test-key")
        assert result["ticker"] == "MSFT"
        assert result["sentiment"] == "Neutral"
        assert result["magnitude"] == 20

    @patch("src.sentiment_engine.httpx.post")
    def test_all_fields_returned(self, mock_post):
        mock_post.return_value = _mock_httpx_response(
            _mock_successful_response()
        )
        result = analyze_sentiment("Test", api_key="test-key")
        assert set(result.keys()) == {"ticker", "sentiment", "magnitude", "reasoning"}
        assert isinstance(result["ticker"], str)
        assert isinstance(result["sentiment"], str)
        assert isinstance(result["magnitude"], int)
        assert isinstance(result["reasoning"], str)

    @patch("src.sentiment_engine.httpx.post")
    def test_api_key_passed_correctly(self, mock_post):
        """Verify the API key is sent in the Authorization header."""
        mock_post.return_value = _mock_httpx_response(
            _mock_successful_response()
        )
        analyze_sentiment("Test", api_key="my-secret-key")
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["headers"]["Authorization"] == "Bearer my-secret-key"

    @patch("src.sentiment_engine.httpx.post")
    def test_unknown_ticker_preserved(self, mock_post):
        """When LLM returns UNKNOWN, it should be preserved."""
        mock_post.return_value = _mock_httpx_response(
            _mock_successful_response(
                ticker="UNKNOWN", sentiment="Neutral", magnitude=0,
                reasoning="No specific company mentioned.",
            )
        )
        result = analyze_sentiment("General market commentary", api_key="test-key")
        assert result["ticker"] == "UNKNOWN"


# =========================================================================
# Exception / Degradation tests
# =========================================================================


class TestSentimentEngineDegradation:
    """Graceful degradation under API failures."""

    @patch("src.sentiment_engine.httpx.post")
    def test_http_error_returns_neutral(self, mock_post):
        """HTTP 500 should return neutral fallback."""
        mock_post.side_effect = httpx.HTTPStatusError(
            "500 Server Error",
            request=MagicMock(spec=httpx.Request),
            response=httpx.Response(500),
        )
        result = analyze_sentiment("Some text", api_key="test-key")
        assert result["sentiment"] == "Neutral"
        assert result["magnitude"] == 0
        assert "failed" in result["reasoning"]

    @patch("src.sentiment_engine.httpx.post")
    def test_timeout_returns_neutral(self, mock_post):
        """Network timeout should return neutral fallback."""
        mock_post.side_effect = httpx.TimeoutException("Connection timed out")
        result = analyze_sentiment("Some text", api_key="test-key")
        assert result["sentiment"] == "Neutral"
        assert result["magnitude"] == 0
        assert "failed" in result["reasoning"]

    @patch("src.sentiment_engine.httpx.post")
    def test_connection_error_returns_neutral(self, mock_post):
        """Connection refused should return neutral fallback."""
        mock_post.side_effect = httpx.ConnectError("Connection refused")
        result = analyze_sentiment("Some text", api_key="test-key")
        assert result["sentiment"] == "Neutral"
        assert result["magnitude"] == 0

    @patch("src.sentiment_engine.httpx.post")
    def test_malformed_json_returns_neutral(self, mock_post):
        """LLM returns non-JSON text -> neutral fallback."""
        mock_post.return_value = _mock_httpx_response(
            {"choices": [{"message": {"content": "This is not JSON at all"}}]}
        )
        result = analyze_sentiment("Some text", api_key="test-key")
        assert result["sentiment"] == "Neutral"
        assert result["magnitude"] == 0

    @patch("src.sentiment_engine.httpx.post")
    def test_json_with_markdown_wrapper(self, mock_post):
        """LLM wraps JSON in ```json ... ``` -> should extract and parse."""
        mock_post.return_value = _mock_httpx_response(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                "```json\n"
                                '{"ticker": "GOOGL", "sentiment": "Positive", '
                                '"magnitude": 65, "reasoning": "Strong ad revenue growth."}\n'
                                "```"
                            )
                        }
                    }
                ]
            },
        )
        result = analyze_sentiment("Google ad revenue up", api_key="test-key")
        assert result["ticker"] == "GOOGL"
        assert result["sentiment"] == "Positive"
        assert result["magnitude"] == 65

    @patch("src.sentiment_engine.httpx.post")
    def test_api_response_missing_choices_key(self, mock_post):
        """Missing 'choices' key in API response -> neutral fallback."""
        mock_post.return_value = _mock_httpx_response({"error": "bad request"})
        result = analyze_sentiment("Some text", api_key="test-key")
        assert result["sentiment"] == "Neutral"
        assert result["magnitude"] == 0


# =========================================================================
# Emoji / non-ASCII cleaning tests
# =========================================================================


class TestSentimentEngineEmojiCleaning:
    """Verify clean_ascii_only() intercepts emoji in reasoning."""

    @patch("src.sentiment_engine.httpx.post")
    def test_emoji_in_reasoning_stripped(self, mock_post):
        """LLM returns emoji in reasoning -> should be removed."""
        mock_post.return_value = _mock_httpx_response(
            _mock_successful_response(
                ticker="AAPL", sentiment="Positive", magnitude=80,
                reasoning="Strong earnings beat! 🚀🚀 This is amazing! 😊",
            )
        )
        result = analyze_sentiment("Apple earnings", api_key="test-key")
        assert "🚀" not in result["reasoning"]
        assert "😊" not in result["reasoning"]
        assert "Strong earnings beat" in result["reasoning"]

    @patch("src.sentiment_engine.httpx.post")
    def test_chinese_chars_in_reasoning_stripped(self, mock_post):
        """Non-ASCII Chinese characters in reasoning -> stripped."""
        mock_post.return_value = _mock_httpx_response(
            _mock_successful_response(
                ticker="BABA", sentiment="Positive", magnitude=70,
                reasoning="Good results 很好的业绩增长",
            )
        )
        result = analyze_sentiment("Alibaba results", api_key="test-key")
        assert "很好的业绩增长" not in result["reasoning"]
        assert "Good results" in result["reasoning"]

    @patch("src.sentiment_engine.httpx.post")
    def test_fancy_quotes_stripped(self, mock_post):
        """Unicode fancy quotes should be replaced with ASCII."""
        mock_post.return_value = _mock_httpx_response(
            _mock_successful_response(
                ticker="NVDA", sentiment="Positive", magnitude=90,
                reasoning="Analyst says \u2018this is a game changer\u2019 for AI chips",
            )
        )
        result = analyze_sentiment("NVDA analyst upgrade", api_key="test-key")
        assert "\u2018" not in result["reasoning"]
        assert "\u2019" not in result["reasoning"]

    @patch("src.sentiment_engine.httpx.post")
    def test_reasoning_with_only_emoji_becomes_ascii_only(self, mock_post):
        """If reasoning is purely emoji, should become empty and trigger fallback."""
        mock_post.return_value = _mock_httpx_response(
            _mock_successful_response(
                ticker="TSLA", sentiment="Positive", magnitude=50,
                reasoning="🎉🎉🎉😍😍",
            )
        )
        result = analyze_sentiment("Tesla news", api_key="test-key")
        # After clean_ascii_only, reasoning becomes empty -> fallback text
        assert result["reasoning"] == "LLM returned empty reasoning. Neutral assessment applied."
        # But ticker/sentiment/magnitude should still be preserved from LLM
        # (only reasoning gets cleaned, ticker/sentiment/magnitude are separate)
        assert result["ticker"] == "TSLA"
        assert result["sentiment"] == "Positive"
        assert result["magnitude"] == 50


# =========================================================================
# Field normalization tests
# =========================================================================


class TestSentimentEngineNormalization:
    """Tests for field-level normalization."""

    @patch("src.sentiment_engine.httpx.post")
    def test_ticker_converted_to_uppercase(self, mock_post):
        """Lowercase ticker from LLM should be uppercased."""
        mock_post.return_value = _mock_httpx_response(
            _mock_successful_response(ticker="aapl")
        )
        result = analyze_sentiment("Apple", api_key="test-key")
        assert result["ticker"] == "AAPL"

    @patch("src.sentiment_engine.httpx.post")
    def test_sentiment_capitalized(self, mock_post):
        """Lowercase sentiment should be capitalized."""
        mock_post.return_value = _mock_httpx_response(
            _mock_successful_response(sentiment="positive")
        )
        result = analyze_sentiment("Apple", api_key="test-key")
        assert result["sentiment"] == "Positive"

    @patch("src.sentiment_engine.httpx.post")
    def test_invalid_sentiment_defaults_to_neutral(self, mock_post):
        """Unknown sentiment value -> Neutral."""
        mock_post.return_value = _mock_httpx_response(
            _mock_successful_response(sentiment="Extreme")
        )
        result = analyze_sentiment("Some text", api_key="test-key")
        assert result["sentiment"] == "Neutral"

    @patch("src.sentiment_engine.httpx.post")
    def test_magnitude_clamped_above_100(self, mock_post):
        """Magnitude > 100 should be clamped."""
        mock_post.return_value = _mock_httpx_response(
            _mock_successful_response(magnitude=200)
        )
        result = analyze_sentiment("Test", api_key="test-key")
        assert result["magnitude"] == 100

    @patch("src.sentiment_engine.httpx.post")
    def test_magnitude_clamped_below_0(self, mock_post):
        """Magnitude < 0 should be clamped."""
        mock_post.return_value = _mock_httpx_response(
            _mock_successful_response(magnitude=-50)
        )
        result = analyze_sentiment("Test", api_key="test-key")
        assert result["magnitude"] == 0

    @patch("src.sentiment_engine.httpx.post")
    def test_magnitude_non_integer_defaults_to_0(self, mock_post):
        """Non-integer magnitude -> 0."""
        mock_post.return_value = _mock_httpx_response(
            _mock_successful_response(magnitude="not-a-number")
        )
        result = analyze_sentiment("Test", api_key="test-key")
        assert result["magnitude"] == 0

    @patch("src.sentiment_engine.httpx.post")
    def test_empty_text_handled(self, mock_post):
        """Empty text should still result in a valid API call."""
        mock_post.return_value = _mock_httpx_response(
            _mock_successful_response(
                ticker="UNKNOWN", sentiment="Neutral", magnitude=0,
                reasoning="No meaningful content to analyze.",
            )
        )
        result = analyze_sentiment("", api_key="test-key")
        assert result["sentiment"] == "Neutral"
        assert result["magnitude"] == 0