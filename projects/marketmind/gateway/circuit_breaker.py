"""Circuit breaker for LLM gateway resilience (P3-3).

Extracted from gateway/async_client.py per modular architecture rules.
Contains: CircuitState, CircuitBreaker, error classes, backoff/jitter utils,
error classification, and fallback routing.

State machine:
  CLOSED → (threshold failures) → OPEN → (timeout) → HALF_OPEN
  HALF_OPEN → (success) → CLOSED  |  (failure) → OPEN
"""
from __future__ import annotations
import time
import asyncio
import logging
import random
from enum import Enum
from typing import Any
import httpx

logger = logging.getLogger("marketmind.gateway.circuit_breaker")

_DEFAULT_TIMEOUT = httpx.Timeout(120.0)


# ── Error Classes ────────────────────────────────────────────────────────

class RateLimitError(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Retry after {retry_after}s")


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpenError(Exception):
    """Raised when circuit is OPEN and no fallback is configured."""


class QuotaExhaustedError(Exception):
    """Raised when all providers (primary + fallback) are exhausted."""


# ── Backoff & Error Classification ───────────────────────────────────────

def _backoff_delay(attempt: int, base: float = 1.0, max_delay: float = 60.0) -> float:
    """Exponential backoff with full jitter."""
    exp = min(base * (2 ** attempt), max_delay)
    return random.uniform(0, exp)


def infer_error_type(exc: Exception) -> str:
    """Classify an exception for circuit breaker error-type handling."""
    if isinstance(exc, RateLimitError):
        return "429"
    if isinstance(exc, QuotaExhaustedError):
        return "quota_exceeded"
    # httpx.HTTPStatusError stores status in .response.status_code
    resp = getattr(exc, "response", None)
    if resp is not None:
        status = getattr(resp, "status_code", None)
        if status == 429:
            return "429"
        if status is not None and 500 <= status < 600:
            return "5xx"
    return "unknown"


# ── Circuit Breaker ──────────────────────────────────────────────────────

class CircuitBreaker:
    """Circuit breaker for LLM API calls (CLOSED → OPEN → HALF_OPEN).

    Prevents cascading failures when DeepSeek API is degraded.
    Fallback provider is configurable.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        timeout_seconds: float = 30.0,
        fallback_provider_url: str | None = None,
        fallback_model: str | None = None,
        fallback_api_key: str | None = None,
    ):
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: float = 0.0
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.fallback_provider_url = fallback_provider_url
        self.fallback_model = fallback_model
        self.fallback_api_key = fallback_api_key
        self._last_error_type: str = "unknown"
        self._consecutive_open_count: int = 0
        self._lock = asyncio.Lock()

    def _record_success(self) -> None:
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self._consecutive_open_count = 0

    def _record_failure(self, error_type: str = "5xx") -> None:
        self._last_error_type = error_type
        self.last_failure_time = time.time()
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            self._consecutive_open_count += 1
            return
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.failure_count = 0
            self._consecutive_open_count = 1

    def _should_attempt_probe(self) -> bool:
        if self.state != CircuitState.OPEN:
            return False
        return time.time() - self.last_failure_time >= self._probe_interval()

    def _probe_interval(self) -> float:
        if self._last_error_type == "quota_exceeded":
            return float("inf")
        if self._last_error_type == "429":
            return 60.0
        # Exponential backoff for repeated OPEN cycles
        if self._consecutive_open_count > 1:
            return min(self.timeout_seconds * (2 ** (self._consecutive_open_count - 1)), 600.0)
        return self.timeout_seconds

    async def call(
        self,
        primary_call,
        fallback_call=None,
    ):
        """Execute a call through the circuit breaker.

        If circuit is CLOSED or HALF_OPEN: attempt primary.
        If circuit is OPEN: check for probe window, else try fallback.
        """
        async with self._lock:
            if self.state == CircuitState.OPEN:
                if self._should_attempt_probe():
                    self.state = CircuitState.HALF_OPEN
                elif fallback_call is not None:
                    return await fallback_call()
                elif self.fallback_provider_url:
                    return await _try_fallback(
                        self.fallback_provider_url, self.fallback_model,
                        self.fallback_api_key,
                    )
                else:
                    raise CircuitBreakerOpenError("Circuit breaker is OPEN")

        # CLOSED or HALF_OPEN: attempt primary
        try:
            result = await primary_call()
            self._record_success()
            return result
        except Exception as e:
            error_type = infer_error_type(e)
            self._record_failure(error_type)
            if fallback_call is not None:
                return await fallback_call()
            if self.fallback_provider_url:
                return await _try_fallback(
                    self.fallback_provider_url, self.fallback_model,
                    self.fallback_api_key,
                )
            raise

    def reset(self) -> None:
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self._consecutive_open_count = 0


# ── Fallback Routing ─────────────────────────────────────────────────────

async def _try_fallback(
    url: str, model: str | None, api_key: str | None,
) -> dict[str, Any]:
    """Route a request to the fallback provider (e.g., OpenAI-compatible endpoint)."""
    # Fallback uses a simple, non-circuit-breaking call
    if not api_key:
        raise QuotaExhaustedError("Fallback API key not configured")
    client = httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
    try:
        resp = await client.post(
            f"{url.rstrip('/')}/chat/completions",
            json={
                "model": model or "gpt-4o-mini",
                "messages": [{"role": "user", "content": "system unavailable — fallback"}],
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "content": data["choices"][0]["message"]["content"],
            "usage": data.get("usage", {}),
            "latency_ms": 0,
            "fallback": True,
        }
    finally:
        await client.aclose()
