"""Circuit breaker for LLM gateway resilience (P3-3).

State machine:
  CLOSED: Normal operation, count consecutive failures
    → After *threshold* consecutive failures → OPEN
  OPEN: All calls immediately fail (fast-fail), route to fallback
    → After timeout → HALF_OPEN
  HALF_OPEN: Allow 1 probe request
    → Success → CLOSED (reset counter)
    → Failure → OPEN (reset timer, apply exponential backoff)
    → Error type matters:
      - 429: use Retry-After header value as timeout
      - 5xx: use 30 s timeout
      - Quota exhausted: stay OPEN with 10 min cooldown
"""
from __future__ import annotations
import time
import random
import logging
from enum import Enum

import httpx

logger = logging.getLogger("marketmind.gateway.circuit_breaker")


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is OPEN and calls are fast-failing."""

    def __init__(self, message: str = "Circuit breaker is OPEN — calls are fast-failing"):
        super().__init__(message)


class CircuitBreaker:
    """Circuit breaker for LLM gateway resilience (P3-3).

    State machine:
      CLOSED: Normal operation, count consecutive failures
        → After *threshold* consecutive failures → OPEN
      OPEN: All calls immediately fail (fast-fail), route to fallback
        → After timeout → HALF_OPEN
      HALF_OPEN: Allow 1 probe request
        → Success → CLOSED (reset counter)
        → Failure → OPEN (reset timer, apply exponential backoff)
        → Error type matters:
          - 429: use Retry-After header value as timeout
          - 5xx: use 30 s timeout
          - Quota exhausted: stay OPEN with 10 min cooldown
    """

    def __init__(self, threshold: int = 3, timeout_s: int = 30):
        if threshold < 1:
            raise ValueError("threshold must be >= 1")
        if timeout_s < 1:
            raise ValueError("timeout_s must be >= 1")
        self.threshold = threshold
        self.base_timeout_s = timeout_s
        self.state: CircuitState = CircuitState.CLOSED
        self.failure_count: int = 0
        self._consecutive_open_count: int = 0
        self._open_until: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        """Check if the circuit is currently OPEN (fast-fail mode).

        Side-effect: if the OPEN timeout has expired the circuit automatically
        transitions to HALF_OPEN so the next call becomes a probe.
        """
        if self.state != CircuitState.OPEN:
            return False
        if time.monotonic() >= self._open_until:
            logger.debug("CircuitBreaker: OPEN → HALF_OPEN (timeout expired)")
            self.state = CircuitState.HALF_OPEN
            return False
        return True

    def record_success(self) -> None:
        """Notify the breaker that a call succeeded."""
        if self.state == CircuitState.HALF_OPEN:
            logger.info("CircuitBreaker: HALF_OPEN probe succeeded → CLOSED")
            self._transition_to_closed()
        elif self.state == CircuitState.CLOSED:
            self.failure_count = 0

    def record_failure(
        self,
        status_code: int | None = None,
        retry_after: int | None = None,
        is_quota_exhausted: bool = False,
    ) -> None:
        """Notify the breaker that a call failed.

        Args:
            status_code: HTTP status code (429, 5xx, etc.).
            retry_after: Seconds from Retry-After header (429 responses).
            is_quota_exhausted: True when the provider signals quota/balance
                exhaustion. Overrides normal backoff — stays OPEN for 10 min.
        """
        if self.state == CircuitState.HALF_OPEN:
            logger.warning(
                "CircuitBreaker: HALF_OPEN probe failed → OPEN (status=%s, quota=%s)",
                status_code, is_quota_exhausted,
            )
            self._transition_to_open(status_code, retry_after, is_quota_exhausted)
        elif self.state == CircuitState.CLOSED:
            self.failure_count += 1
            logger.debug(
                "CircuitBreaker: failure %d/%d", self.failure_count, self.threshold,
            )
            if self.failure_count >= self.threshold:
                logger.warning(
                    "CircuitBreaker: CLOSED → OPEN (threshold %d reached, status=%s)",
                    self.threshold, status_code,
                )
                self._transition_to_open(status_code, retry_after, is_quota_exhausted)

    def reset(self) -> None:
        """Force the breaker back to CLOSED (e.g. manual intervention)."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self._consecutive_open_count = 0
        self._open_until = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _transition_to_closed(self) -> None:
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self._consecutive_open_count = 0

    def _transition_to_open(
        self,
        status_code: int | None,
        retry_after: int | None,
        is_quota_exhausted: bool,
    ) -> None:
        self.state = CircuitState.OPEN
        timeout: float

        if is_quota_exhausted:
            # Skip HALF_OPEN, stay OPEN for a long cooldown
            timeout = 600.0  # 10 minutes
            self._consecutive_open_count = 0
        elif retry_after is not None:
            # Respect the server's Retry-After directive
            timeout = float(retry_after)
            # Don't accumulate exponential backoff — server told us when
        elif status_code is not None and 500 <= status_code < 600:
            timeout = 30.0
            self._consecutive_open_count += 1
        else:
            self._consecutive_open_count += 1
            timeout = float(self.base_timeout_s)

        # Exponential backoff for non-429, non-quota errors
        if retry_after is None and not is_quota_exhausted:
            backoff = 2 ** (self._consecutive_open_count - 1)
            timeout = min(timeout * backoff, 600.0)  # cap at 10 min

        # Jitter: randomise ±25 % to avoid thundering-herd
        jitter_factor = 1.0
        if retry_after is None and not is_quota_exhausted:
            jitter_factor = random.uniform(0.75, 1.25)

        self._open_until = time.monotonic() + max(timeout * jitter_factor, 1.0)
        logger.info(
            "CircuitBreaker: OPEN until +%.1fs (timeout=%.1f, jitter=%.2f, "
            "status=%s, quota=%s, consecutive_open=%d)",
            self._open_until - time.monotonic(), timeout, jitter_factor,
            status_code, is_quota_exhausted, self._consecutive_open_count,
        )


def _extract_status_code(exc: Exception) -> int | None:
    """Pull the HTTP status code from an httpx exception if available."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    return None
