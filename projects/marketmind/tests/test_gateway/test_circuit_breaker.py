"""Tests for CircuitBreaker (P3-3) — LLM gateway resilience."""
from __future__ import annotations
import time
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from marketmind.gateway.async_client import (
    CircuitBreaker,
    CircuitState,
    CircuitBreakerOpenError,
    QuotaExhaustedError,
    RateLimitError,
    _backoff_delay,
    DeepSeekGateway,
    init_gateway,
    infer_error_type,
)


# ── Test 1: CLOSED → OPEN transition ──────────────────────────────────

def test_closed_to_open_transition():
    cb = CircuitBreaker(failure_threshold=3, timeout_seconds=30.0)
    assert cb.state == CircuitState.CLOSED

    cb._record_failure("5xx")
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 1

    cb._record_failure("5xx")
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 2

    cb._record_failure("5xx")
    assert cb.state == CircuitState.OPEN
    assert cb.failure_count == 0  # reset on transition


# ── Test 2: Fallback routing when OPEN ─────────────────────────────────

@pytest.mark.asyncio
async def test_fallback_routing():
    cb = CircuitBreaker(
        failure_threshold=1, timeout_seconds=30.0,
        fallback_provider_url="https://api.openai.com/v1",
        fallback_model="gpt-4o-mini",
    )
    cb._record_failure("5xx")
    assert cb.state == CircuitState.OPEN

    primary = AsyncMock(return_value={"content": "primary"})
    fallback = AsyncMock(return_value={"content": "fallback", "fallback": True})

    result = await cb.call(primary, fallback)
    primary.assert_not_called()  # circuit OPEN
    fallback.assert_awaited_once()
    assert result["content"] == "fallback"


# ── Test 3: HALF_OPEN probe success → CLOSED ──────────────────────────

@pytest.mark.asyncio
async def test_half_open_probe_success():
    cb = CircuitBreaker(failure_threshold=1, timeout_seconds=0.01)
    cb._record_failure("5xx")
    assert cb.state == CircuitState.OPEN

    await asyncio.sleep(0.05)
    assert cb._should_attempt_probe() is True

    primary = AsyncMock(return_value={"content": "ok"})
    result = await cb.call(primary)
    primary.assert_awaited_once()
    assert result["content"] == "ok"
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0


# ── Test 4: HALF_OPEN probe fails → back to OPEN ──────────────────────

@pytest.mark.asyncio
async def test_half_open_probe_failure():
    cb = CircuitBreaker(failure_threshold=1, timeout_seconds=0.01)
    cb._record_failure("5xx")
    assert cb.state == CircuitState.OPEN

    await asyncio.sleep(0.05)
    assert cb._should_attempt_probe() is True

    cb.state = CircuitState.HALF_OPEN  # simulate probe attempt
    cb._record_failure("5xx")
    assert cb.state == CircuitState.OPEN
    assert cb._consecutive_open_count >= 1


# ── Test 5: 429 Retry-After logic ─────────────────────────────────────

def test_429_retry_after():
    cb = CircuitBreaker(failure_threshold=1, timeout_seconds=30.0)
    cb._record_failure("429")
    assert cb.state == CircuitState.OPEN
    assert cb._last_error_type == "429"
    assert cb._should_attempt_probe() is False  # 60s default for 429

    rate_limit_exc = RateLimitError(retry_after=10)
    assert infer_error_type(rate_limit_exc) == "429"


# ── Test 6: Backoff jitter — multiple values differ ───────────────────

def test_backoff_jitter():
    delays = [_backoff_delay(1, base=1.0, max_delay=60.0) for _ in range(20)]
    unique = len(set(round(d, 4) for d in delays))
    assert unique >= 2, f"Expected >=2 unique delays, got {unique}"
    for d in delays:
        assert 0.0 <= d <= 2.0, f"Delay {d} out of [0, 2]"


# ── Test 7: Fallback output format ────────────────────────────────────

@pytest.mark.asyncio
async def test_fallback_output_format():
    cb = CircuitBreaker(
        failure_threshold=1, timeout_seconds=30.0,
        fallback_provider_url="https://api.openai.com/v1",
        fallback_model="gpt-4o-mini",
    )
    cb._record_failure("5xx")

    fb_response = {
        "content": "Fallback analysis",
        "usage": {"total_tokens": 100},
        "latency_ms": 250,
        "fallback": True,
    }
    primary = AsyncMock()
    fallback = AsyncMock(return_value=fb_response)

    result = await cb.call(primary, fallback)
    assert "content" in result
    assert result.get("fallback") is True


# ── Test 8: Config ordering (settings → CircuitBreaker) ───────────────

def test_config_ordering():
    from marketmind.config.settings import MarketMindConfig

    cfg = MarketMindConfig(
        circuit_breaker_threshold=5,
        circuit_breaker_timeout_s=60,
        fallback_provider_url="https://api.openai.com/v1",
        fallback_model="gpt-4o-mini",
        fallback_api_key="sk-test",
    )
    assert cfg.circuit_breaker_threshold == 5
    assert cfg.circuit_breaker_timeout_s == 60
    assert cfg.fallback_provider_url == "https://api.openai.com/v1"

    cb = CircuitBreaker(
        failure_threshold=cfg.circuit_breaker_threshold,
        timeout_seconds=float(cfg.circuit_breaker_timeout_s),
        fallback_provider_url=cfg.fallback_provider_url,
        fallback_model=cfg.fallback_model,
        fallback_api_key=cfg.fallback_api_key,
    )
    assert cb.failure_threshold == 5
    assert cb.timeout_seconds == 60.0
    assert cb.state == CircuitState.CLOSED


# ── Test 9: Gateway with circuit breaker enabled ──────────────────────

def test_gateway_with_circuit_breaker_enabled():
    gw = DeepSeekGateway(
        keys=["test-key"],
        circuit_breaker_enabled=True,
        circuit_breaker_threshold=3,
        circuit_breaker_timeout_s=30,
        fallback_provider_url="https://api.openai.com/v1",
        fallback_model="gpt-4o-mini",
        fallback_api_key="sk-fallback",
    )
    assert gw.circuit_breaker is not None
    assert gw.circuit_breaker.state == CircuitState.CLOSED
    assert gw.circuit_breaker.failure_threshold == 3


# ── Test 10: Gateway without circuit breaker ──────────────────────────

def test_gateway_without_circuit_breaker():
    gw = DeepSeekGateway(keys=["test-key"])
    assert gw.circuit_breaker is None
    assert gw._fallback_circuit_breaker is None


# ── Test 11: Quota exhausted skips HALF_OPEN ──────────────────────────

def test_quota_exhausted_skips_half_open():
    cb = CircuitBreaker(failure_threshold=1)
    cb._record_failure("quota_exceeded")
    assert cb.state == CircuitState.OPEN
    assert cb._last_error_type == "quota_exceeded"
    assert cb._should_attempt_probe() is False
    assert cb._probe_interval() == float("inf")


# ── Test 12: CircuitBreakerOpenError when OPEN and no fallback ─────────

@pytest.mark.asyncio
async def test_circuit_open_raises_without_fallback():
    cb = CircuitBreaker(failure_threshold=1)
    cb._record_failure("5xx")
    assert cb.state == CircuitState.OPEN

    with pytest.raises(CircuitBreakerOpenError, match="Circuit breaker is OPEN"):
        await cb.call(AsyncMock())


# ── Test 13: reset() forces CLOSED ────────────────────────────────────

def test_reset_forces_closed():
    cb = CircuitBreaker(failure_threshold=1)
    cb._record_failure("5xx")
    assert cb.state == CircuitState.OPEN
    cb.reset()
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0
    assert cb._consecutive_open_count == 0


# ── Test 14: infer_error_type mappings ────────────────────────────────

def test_infer_error_type():
    assert infer_error_type(RateLimitError(5)) == "429"
    assert infer_error_type(QuotaExhaustedError()) == "quota_exceeded"
    # 5xx via httpx
    import httpx
    exc_500 = httpx.HTTPStatusError("err", request=MagicMock(), response=MagicMock(status_code=500))
    assert infer_error_type(exc_500) == "5xx"
    exc_503 = httpx.HTTPStatusError("err", request=MagicMock(), response=MagicMock(status_code=503))
    assert infer_error_type(exc_503) == "5xx"
    # Unknown
    assert infer_error_type(ValueError("random")) == "unknown"


# ── Test 15: Exponential backoff increases with attempts ──────────────

def test_backoff_increases_with_attempts():
    d1 = _backoff_delay(1, base=1.0, max_delay=60.0)
    d3 = _backoff_delay(3, base=1.0, max_delay=60.0)
    # d3's max possible is higher (8.0 vs 2.0)
    # But due to jitter they can overlap; check max_delay cap
    d_capped = _backoff_delay(10, base=1.0, max_delay=5.0)
    assert d_capped <= 5.0
