"""Tests for gateway/reliable_api.py — reliable API client wrapper.

Minimum tests (per Phase A spec §18):
  test_fetch_success — returns parsed JSON
  test_fetch_retry — succeeds on 2nd attempt after 1st failure
  test_fetch_fallback — switches to fallback URL when primary fails
"""
from __future__ import annotations
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from marketmind.gateway.reliable_api import ReliableAPIClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Create a mock httpx.Response with .json() and .raise_for_status()."""
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.status_code = status_code

    def raise_for_status():
        if status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {status_code}",
                request=MagicMock(),
                response=resp,
            )

    resp.raise_for_status = raise_for_status
    return resp


# ---------------------------------------------------------------------------
# Test 1: fetch_success
# ---------------------------------------------------------------------------

class TestFetchSuccess:
    """ReliableAPIClient.fetch() — successful fetch."""

    @pytest.mark.asyncio
    async def test_fetch_success_returns_parsed_json(self):
        """fetch() returns the parsed JSON dict from the response."""
        client = ReliableAPIClient(timeout=10.0, max_retries=0)

        expected_data = {"value": 42.0, "date": "2026-05-21"}

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_resp = _mock_response(expected_data)
            mock_instance.get.return_value = mock_resp
            MockClient.return_value = mock_instance

            result = await client.fetch("fred", "https://api.example.com/data")

        assert result == expected_data
        assert "error" not in result


# ---------------------------------------------------------------------------
# Test 2: fetch_retry
# ---------------------------------------------------------------------------

class TestFetchRetry:
    """ReliableAPIClient.fetch() — retry on failure."""

    @pytest.mark.asyncio
    async def test_fetch_retry_succeeds_on_second_attempt(self):
        """Succeeds on 2nd attempt after 1st attempt raises HTTPStatusError."""
        client = ReliableAPIClient(timeout=10.0, max_retries=2, backoff_base=0.01)

        expected_data = {"value": 99.0}
        call_count = [0]

        async def mock_get(url, params=None):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call fails
                resp = MagicMock()
                resp.status_code = 500
                resp.raise_for_status = MagicMock(
                    side_effect=httpx.HTTPStatusError(
                        "Server Error",
                        request=MagicMock(),
                        response=resp,
                    )
                )
                return resp
            else:
                # Second call succeeds
                return _mock_response(expected_data)

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.get = mock_get
            MockClient.return_value = mock_instance

            result = await client.fetch("api_source", "https://api.example.com/data")

        assert result == expected_data
        assert call_count[0] == 2, f"Expected 2 attempts, got {call_count[0]}"


# ---------------------------------------------------------------------------
# Test 3: fetch_fallback
# ---------------------------------------------------------------------------

class TestFetchFallback:
    """ReliableAPIClient.fetch_with_fallback() — fallback URL support."""

    @pytest.mark.asyncio
    async def test_fetch_fallback_switches_to_fallback_when_primary_fails(self):
        """When primary URL fails, falls back to secondary URL successfully."""
        client = ReliableAPIClient(timeout=10.0, max_retries=0)

        primary_data = {"error": "primary_down"}
        fallback_data = {"result": "from_fallback", "value": 100}

        url_called = []

        async def mock_get(url, params=None):
            url_called.append(url)
            if "primary" in url:
                resp = MagicMock()
                resp.status_code = 503
                resp.raise_for_status = MagicMock(
                    side_effect=httpx.HTTPStatusError(
                        "Service Unavailable",
                        request=MagicMock(),
                        response=resp,
                    )
                )
                return resp
            else:
                return _mock_response(fallback_data)

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.get = mock_get
            MockClient.return_value = mock_instance

            result = await client.fetch_with_fallback(
                "multi_source",
                "https://primary.example.com/data",
                "https://fallback.example.com/data",
            )

        assert result == fallback_data
        assert len(url_called) == 2
        assert "primary" in url_called[0]
        assert "fallback" in url_called[1]

    @pytest.mark.asyncio
    async def test_fetch_fallback_returns_primary_when_it_succeeds(self):
        """When primary succeeds, never calls fallback."""
        client = ReliableAPIClient(timeout=10.0, max_retries=0)
        primary_data = {"result": "primary_ok"}

        url_called = []

        async def mock_get(url, params=None):
            url_called.append(url)
            return _mock_response(primary_data)

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.get = mock_get
            MockClient.return_value = mock_instance

            result = await client.fetch_with_fallback(
                "multi_source",
                "https://primary.example.com/data",
                "https://fallback.example.com/data",
            )

        assert result == primary_data
        assert len(url_called) == 1, "Fallback should not be called when primary succeeds"


# ---------------------------------------------------------------------------
# Additional tests
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    """ReliableAPIClient circuit breaker behavior."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_five_consecutive_failures(self):
        """After 5 consecutive failures, circuit breaker opens and blocks calls."""
        client = ReliableAPIClient(timeout=10.0, max_retries=0)

        call_count = [0]

        async def mock_get(url, params=None):
            call_count[0] += 1
            resp = MagicMock()
            resp.status_code = 500
            resp.raise_for_status = MagicMock(
                side_effect=httpx.HTTPStatusError(
                    "Server Error", request=MagicMock(), response=resp,
                )
            )
            return resp

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.get = mock_get
            MockClient.return_value = mock_instance

            # 5 failing calls
            for _ in range(5):
                result = await client.fetch("broken_api", "https://broken.example.com/data")
                assert "error" in result

            # 6th call should be blocked by circuit breaker
            result = await client.fetch("broken_api", "https://broken.example.com/data")
            assert result["error"] == "circuit_open"
            # The 6th call should NOT have hit httpx
            assert call_count[0] == 5

    @pytest.mark.asyncio
    async def test_reset_circuit_allows_future_calls(self):
        """reset_circuit() closes the breaker and resets failure count."""
        client = ReliableAPIClient(timeout=10.0, max_retries=0)
        client._circuit_open["broken_api"] = True
        client._failure_counts["broken_api"] = 5

        client.reset_circuit("broken_api")

        assert client._circuit_open["broken_api"] is False
        assert client._failure_counts["broken_api"] == 0


class TestValidation:
    """ReliableAPIClient constructor validation."""

    def test_negative_timeout_raises(self):
        with pytest.raises(ValueError, match="timeout"):
            ReliableAPIClient(timeout=-1.0)

    def test_zero_timeout_raises(self):
        with pytest.raises(ValueError, match="timeout"):
            ReliableAPIClient(timeout=0.0)

    def test_negative_max_retries_raises(self):
        with pytest.raises(ValueError, match="max_retries"):
            ReliableAPIClient(max_retries=-1)

    def test_zero_backoff_raises(self):
        with pytest.raises(ValueError, match="backoff_base"):
            ReliableAPIClient(backoff_base=0.0)
