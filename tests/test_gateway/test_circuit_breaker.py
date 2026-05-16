"""Tests for P3-3: LLM Gateway Redundancy — CircuitBreaker + fallback routing."""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from marketmind.gateway.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitOpenError,
)
from marketmind.gateway.async_client import (
    DeepSeekGateway,
    init_gateway,
    _call_with_retry,
    RateLimitError,
)
from marketmind.config.settings import ShadowSettings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(data, status_code=200, headers=None):
    """Build a MagicMock HTTP response."""
    resp = MagicMock()
    resp.json.return_value = data
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.raise_for_status.return_value = None
    return resp


def _mock_client(mock_response):
    """Build a mock httpx.AsyncClient whose .post is an AsyncMock."""
    client = MagicMock()
    client.post = AsyncMock(return_value=mock_response)
    return client


def _sleep_zero():
    """Fast-forward time for OPEN→HALF_OPEN transitions."""
    time.sleep(0)


# ---------------------------------------------------------------------------
# Test 1: CLOSED → OPEN transition after threshold failures
# ---------------------------------------------------------------------------

class TestClosedToOpenTransition:
    """Circuit breaker must transition CLOSED → OPEN after *threshold* failures."""

    def test_three_failures_open_circuit(self):
        cb = CircuitBreaker(threshold=3, timeout_s=30)
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

        cb.record_failure(status_code=500)
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 1

        cb.record_failure(status_code=503)
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 2

        cb.record_failure(status_code=502)
        assert cb.state == CircuitState.OPEN
        assert cb.is_open is True

    def test_success_resets_counter_in_closed(self):
        cb = CircuitBreaker(threshold=3, timeout_s=30)
        cb.record_failure(status_code=500)
        cb.record_failure(status_code=500)
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_threshold_1_opens_immediately(self):
        cb = CircuitBreaker(threshold=1, timeout_s=30)
        cb.record_failure(status_code=500)
        assert cb.state == CircuitState.OPEN

    def test_threshold_must_be_positive(self):
        with pytest.raises(ValueError):
            CircuitBreaker(threshold=0)
        with pytest.raises(ValueError):
            CircuitBreaker(timeout_s=0)


# ---------------------------------------------------------------------------
# Test 2: Fallback routing when circuit OPEN
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestFallbackRouting:
    """When the circuit is OPEN, calls must route to the fallback provider URL/model."""

    async def test_open_routes_to_fallback_url(self):
        """Circuit OPEN → request goes to fallback_url instead of primary."""
        fallback_response_data = {
            "choices": [{"message": {"content": "Fallback response"}}],
            "usage": {"total_tokens": 10},
        }

        # Build mock for fallback client
        mock_fb = _mock_client(_mock_response(fallback_response_data))

        with patch("httpx.AsyncClient") as mock_client_cls:
            # First call: primary client; second call: fallback client
            mock_client_cls.side_effect = [
                MagicMock(),  # primary (unused in this test path)
                mock_fb,
            ]

            init_gateway(
                "test-key",
                fallback_url="https://fallback.api.example.com/v1",
                fallback_model="fallback-model-v1",
                circuit_breaker_threshold=1,
            )

            from marketmind.gateway.async_client import _gateway
            # Force circuit OPEN
            _gateway.circuit_breaker.record_failure(status_code=500)
            _gateway.circuit_breaker.record_failure(status_code=500)
            assert _gateway.circuit_breaker.is_open is True

            from marketmind.gateway.async_client import chat_flash
            result = await chat_flash("system", "user")
            assert result["content"] == "Fallback response"
            assert "usage" in result
            assert "latency_ms" in result

            # Verify the request went to the fallback URL
            post_call = mock_fb.post.call_args
            assert "fallback.api.example.com" in str(post_call)
            sent_payload = post_call[1]["json"]
            assert sent_payload["model"] == "fallback-model-v1"

    async def test_open_no_fallback_raises_circuit_open_error(self):
        """Circuit OPEN + no fallback → CircuitOpenError."""
        with patch("httpx.AsyncClient", return_value=MagicMock()):
            init_gateway("test-key", circuit_breaker_threshold=1)
            from marketmind.gateway.async_client import _gateway
            _gateway.circuit_breaker.record_failure(status_code=500)
            _gateway.circuit_breaker.record_failure(status_code=500)
            assert _gateway.circuit_breaker.is_open is True

            from marketmind.gateway.async_client import chat_flash
            # chat_flash reserves budget then calls _call_with_retry
            # The circuit is open and no fallback → CircuitOpenError
            # But chat_flash would call _call_with_retry which raises
            # We test _call_with_retry directly
            with pytest.raises(CircuitOpenError):
                await _call_with_retry(
                    _gateway, "test-model", "system", "user",
                    0.3, 100, "max",
                )


# ---------------------------------------------------------------------------
# Test 3: HALF_OPEN probe success → CLOSED
# ---------------------------------------------------------------------------

class TestHalfOpenSuccess:
    """A successful probe in HALF_OPEN must transition to CLOSED and reset counter."""

    def test_half_open_success_goes_closed(self):
        cb = CircuitBreaker(threshold=1, timeout_s=30)
        cb.record_failure(status_code=500)
        assert cb.state == CircuitState.OPEN

        # Manually transition to HALF_OPEN to simulate timeout expiry
        cb.state = CircuitState.HALF_OPEN
        cb.failure_count = 1  # preserved from before

        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0


# ---------------------------------------------------------------------------
# Test 4: HALF_OPEN probe failure → back to OPEN
# ---------------------------------------------------------------------------

class TestHalfOpenFailure:
    """A failed probe in HALF_OPEN must transition back to OPEN."""

    def test_half_open_failure_goes_open(self):
        cb = CircuitBreaker(threshold=1, timeout_s=30)
        cb.record_failure(status_code=500)
        assert cb.state == CircuitState.OPEN

        # Manually transition to HALF_OPEN
        cb.state = CircuitState.HALF_OPEN

        cb.record_failure(status_code=503)
        assert cb.state == CircuitState.OPEN
        assert cb.is_open is True


# ---------------------------------------------------------------------------
# Test 5: 429 Retry-After respected
# ---------------------------------------------------------------------------

class Test429RetryAfter:
    """When a 429 with Retry-After is recorded, the OPEN timeout must use that value."""

    def test_429_uses_retry_after_as_timeout(self):
        cb = CircuitBreaker(threshold=1, timeout_s=30)
        cb.record_failure(status_code=429, retry_after=15)
        assert cb.state == CircuitState.OPEN

        # OPEN timeout should be approximately 15 s (with jitter on non-429 errors,
        # but 429 with retry_after *disables* jitter).
        remaining = cb._open_until - time.monotonic()
        # Should be close to 15 (within a small delta for execution time)
        assert 14.0 <= remaining <= 16.0, f"Expected ~15s timeout, got {remaining:.1f}s"

    def test_429_without_retry_after_defaults(self):
        """429 without explicit Retry-After header — should still work."""
        cb = CircuitBreaker(threshold=1, timeout_s=30)
        # If retry_after is None but status is 429, it uses normal backoff
        cb.record_failure(status_code=429, retry_after=None)
        assert cb.state == CircuitState.OPEN
        # Uses base timeout with jitter
        remaining = cb._open_until - time.monotonic()
        # base=30 with jitter 0.75-1.25 and backoff 1x → 22.5-37.5
        assert 20.0 <= remaining <= 40.0, f"Expected ~30s timeout, got {remaining:.1f}s"


# ---------------------------------------------------------------------------
# Test 6: Jitter in backoff timing
# ---------------------------------------------------------------------------

class TestJitterInBackoff:
    """Consecutive OPEN transitions must produce non-identical timeouts due to jitter."""

    def test_jitter_produces_variable_timeouts(self):
        """Multiple OPEN transitions should not have identical timeouts."""
        # Use a high threshold so we can test repeated transitions
        cb = CircuitBreaker(threshold=1, timeout_s=30)

        timeouts = []
        for _ in range(5):
            cb.state = CircuitState.CLOSED
            cb.failure_count = 0
            cb.record_failure(status_code=500)  # CLOSED → OPEN
            # Record timeout
            timeouts.append(cb._open_until - time.monotonic())

        # With jitter, not all values should be the same
        unique = set(round(t, 2) for t in timeouts)
        assert len(unique) > 1, f"Jitter did not produce variation: {timeouts}"

    def test_timeout_within_jitter_bounds(self):
        """Base timeout should fall within [0.75x, 1.25x] range (with backoff multiplier)."""
        cb = CircuitBreaker(threshold=1, timeout_s=30)
        cb.record_failure(status_code=500)
        remaining = cb._open_until - time.monotonic()
        # First OPEN: timeout=30, backoff=2^0=1, jitter 0.75-1.25
        assert 20.0 <= remaining <= 40.0, f"Timeout {remaining:.1f}s outside jitter band"


# ---------------------------------------------------------------------------
# Test 7: Fallback output format matches primary
# ---------------------------------------------------------------------------

class TestFallbackOutputFormat:
    """Fallback responses must return the same {content, usage, latency_ms} shape."""

    def test_fallback_response_has_required_keys(self):
        """_fallback_call result dict must contain content, usage, latency_ms."""
        # We can verify by looking at the function implementation —
        # it returns {"content": ..., "usage": ..., "latency_ms": ...}
        # which matches gw._call()'s return shape.
        import inspect
        from marketmind.gateway.async_client import _fallback_call

        source = inspect.getsource(_fallback_call)
        # Primary _call returns: {"content", "usage", "latency_ms"}
        assert '"content"' in source
        assert '"usage"' in source
        assert '"latency_ms"' in source

    @pytest.mark.asyncio
    async def test_fallback_returns_same_structure_as_primary(self):
        """End-to-end: fallback response has identical keys to primary."""
        primary_data = {
            "choices": [{"message": {"content": "primary"}}],
            "usage": {"total_tokens": 100},
        }
        fallback_data = {
            "choices": [{"message": {"content": "fallback"}}],
            "usage": {"total_tokens": 50},
        }

        mock_primary = _mock_client(_mock_response(primary_data))
        mock_fallback = _mock_client(_mock_response(fallback_data))

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.side_effect = [mock_primary, mock_fallback]
            init_gateway(
                "test-key",
                fallback_url="https://fallback.example.com/v1",
                circuit_breaker_threshold=1,
            )
            from marketmind.gateway.async_client import _gateway, chat_flash

            # First call: primary (should succeed, CLOSED)
            result_primary = await chat_flash("sys", "user")
            expected_keys = {"content", "usage", "latency_ms", "reasoning_content"}
            assert set(result_primary.keys()) == expected_keys

            # Force circuit OPEN
            _gateway.circuit_breaker.record_failure(status_code=500)
            _gateway.circuit_breaker.record_failure(status_code=500)
            assert _gateway.circuit_breaker.is_open

            # Second call: should hit fallback
            result_fallback = await chat_flash("sys", "user")
            assert set(result_fallback.keys()) == expected_keys
            assert result_fallback["content"] == "fallback"


# ---------------------------------------------------------------------------
# Test 8: Config ordering (settings load correctly)
# ---------------------------------------------------------------------------

class TestConfigOrdering:
    """New ShadowSettings fields must have correct defaults and be accessible."""

    def test_default_values(self):
        s = ShadowSettings()
        assert s.fallback_provider_url == ""
        assert s.fallback_model == ""
        assert s.circuit_breaker_threshold == 3
        assert s.circuit_breaker_timeout_s == 30

    def test_custom_values(self):
        s = ShadowSettings(
            fallback_provider_url="https://custom.example.com/v1",
            fallback_model="custom-model",
            circuit_breaker_threshold=5,
            circuit_breaker_timeout_s=60,
        )
        assert s.fallback_provider_url == "https://custom.example.com/v1"
        assert s.fallback_model == "custom-model"
        assert s.circuit_breaker_threshold == 5
        assert s.circuit_breaker_timeout_s == 60

    def test_fields_present_in_dataclass(self):
        """Verify the fields actually exist on the dataclass (no typo in attribute name)."""
        s = ShadowSettings()
        # These should not raise AttributeError
        _ = s.fallback_provider_url
        _ = s.fallback_model
        _ = s.circuit_breaker_threshold
        _ = s.circuit_breaker_timeout_s
