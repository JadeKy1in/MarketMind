"""Tests for async DeepSeek gateway."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from marketmind.gateway.async_client import (
    chat_flash, chat_pro, chat_batch_flash, chat_with_integrity,
    DeepSeekGateway, init_gateway, get_gateway, RateLimitError, KeyRotator,
)


def _mock_response(data):
    """Build a plain MagicMock response to avoid AsyncMock chain coroutine warnings."""
    resp = MagicMock()
    resp.json.return_value = data
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    return resp


def _mock_client(mock_response):
    client = MagicMock()
    client.post = AsyncMock(return_value=mock_response)
    return client


@pytest.mark.asyncio
async def test_chat_flash_returns_structured_response():
    mock_response = {
        "choices": [{"message": {"content": "Test analysis result"}}],
        "usage": {"total_tokens": 150, "prompt_tokens": 50, "completion_tokens": 100}
    }
    mock_http = _mock_client(_mock_response(mock_response))

    with patch("httpx.AsyncClient", return_value=mock_http):
        init_gateway("test-key")
        result = await chat_flash(
            system_prompt="You are an analyst.",
            user_prompt="Analyze AAPL."
        )
        assert "content" in result
        assert result["content"] == "Test analysis result"
        assert "usage" in result
        assert "latency_ms" in result
        assert result["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_chat_pro_returns_structured_response():
    mock_response = {
        "choices": [{"message": {"content": "Deep Pro analysis"}}],
        "usage": {"total_tokens": 500, "prompt_tokens": 100, "completion_tokens": 400}
    }
    mock_http = _mock_client(_mock_response(mock_response))

    with patch("httpx.AsyncClient", return_value=mock_http):
        init_gateway("test-key")
        result = await chat_pro(
            system_prompt="You are a senior analyst.",
            user_prompt="Deep dive on macro outlook."
        )
        assert result["content"] == "Deep Pro analysis"
        assert result["usage"]["total_tokens"] == 500
        assert result["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_chat_batch_flash_runs_concurrently():
    mock_response = {
        "choices": [{"message": {"content": "Batch item"}}],
        "usage": {"total_tokens": 100}
    }
    mock_http = _mock_client(_mock_response(mock_response))

    with patch("httpx.AsyncClient", return_value=mock_http):
        init_gateway("test-key")
        prompts = [("System", f"User {i}") for i in range(3)]
        results = await chat_batch_flash(prompts, max_concurrency=2)
        assert len(results) == 3
        for r in results:
            assert r["content"] == "Batch item"


@pytest.mark.asyncio
async def test_chat_with_integrity_injects_protocol():
    mock_response = {
        "choices": [{"message": {"content": "Verified analysis"}}],
        "usage": {"total_tokens": 200}
    }
    mock_http = _mock_client(_mock_response(mock_response))

    with patch("httpx.AsyncClient", return_value=mock_http):
        init_gateway("test-key")
        result = await chat_with_integrity(
            model="flash",
            system_prompt="Analyze markets.",
            user_prompt="What is SPY price?",
            caller_agent="builder-test"
        )
        assert result["content"] == "Verified analysis"
        # Verify the integrity header was injected into the system prompt
        call_args = mock_http.post.call_args
        sent_messages = call_args[1]["json"]["messages"]
        assert "DATA_INTEGRITY_PROTOCOL" in sent_messages[0]["content"]
        assert "builder-test" in sent_messages[0]["content"]


@pytest.mark.asyncio
async def test_rate_limit_error_raised_on_429():
    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.headers = {"Retry-After": "10"}
    mock_http = _mock_client(mock_response)

    with patch("httpx.AsyncClient", return_value=mock_http):
        init_gateway("test-key")
        with pytest.raises(RateLimitError) as exc_info:
            await chat_flash("system", "user")
        assert exc_info.value.retry_after == 10


@pytest.mark.asyncio
async def test_gateway_not_initialized_raises():
    from marketmind.gateway.async_client import _gateway
    with patch("marketmind.gateway.async_client._gateway", None):
        with pytest.raises(RuntimeError, match="Gateway not initialized"):
            await get_gateway()


def test_gateway_context_manager():
    mock_http = AsyncMock()
    with patch("httpx.AsyncClient", return_value=mock_http):
        gw = DeepSeekGateway(["test-key"])
        assert gw.key_rotator.current() == "test-key"
        assert gw.base_url == "https://api.deepseek.com/v1"
