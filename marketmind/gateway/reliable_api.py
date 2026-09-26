"""Reliable API client wrapper for all external data fetchers.

Timeout protection, exponential backoff retry (3 attempts),
circuit breaker integration. All external API calls should route through here.

Phase A Module 2 — Data Foundation layer. Wraps httpx.
"""
from __future__ import annotations
import asyncio
import logging
import httpx

logger = logging.getLogger("marketmind.gateway.reliable_api")


class ReliableAPIClient:
    """Universal wrapper for external API calls with reliability patterns.

    Provides:
    - Configurable timeout (default 30s)
    - Exponential backoff retry (default 3 attempts, base 1.0s → 1s, 2s, 4s)
    - Circuit breaker: opens after 5 consecutive failures, blocks further calls
    - Fallback URL support: try primary, then secondary

    Usage:
        client = ReliableAPIClient(timeout=15.0, max_retries=3)
        data = await client.fetch("fred", "https://api.example.com/data")
        if "error" not in data:
            process(data)
    """

    def __init__(self, timeout: float = 30.0, max_retries: int = 3,
                 backoff_base: float = 1.0):
        """Initialize the reliable API client.

        Args:
            timeout: Per-request timeout in seconds.
            max_retries: Maximum retry attempts (1 initial + up to 3 retries = 4 total).
            backoff_base: Base delay in seconds for exponential backoff.
                         Delay on attempt k is backoff_base * 2^(k-1).
        """
        if timeout <= 0:
            raise ValueError(f"timeout must be > 0, got {timeout}")
        if max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got {max_retries}")
        if backoff_base <= 0:
            raise ValueError(f"backoff_base must be > 0, got {backoff_base}")

        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._failure_counts: dict[str, int] = {}
        self._circuit_open: dict[str, bool] = {}

    async def fetch(self, source_name: str, url: str,
                    params: dict | None = None) -> dict:
        """Fetch JSON from a URL with retry, timeout, and circuit breaker.

        Args:
            source_name: Logical name for the data source (e.g. "fred", "cftc").
                         Used for circuit breaker tracking.
            url: The URL to fetch.
            params: Optional query parameters dict.

        Returns:
            Parsed JSON dict on success, or {"error": "<type>", "detail": "..."} on failure.
            Error types: "circuit_open", "fetch_failed", "invalid_json", "timeout".
        """
        # Circuit breaker check
        if self._circuit_open.get(source_name, False):
            logger.warning(
                "Circuit breaker OPEN for %s — returning error without attempting fetch",
                source_name)
            return {
                "error": "circuit_open",
                "detail": f"Circuit breaker open for {source_name} after {self._failure_counts.get(source_name, 0)} consecutive failures",
            }

        last_error: Exception | None = None
        last_error_detail: str = ""

        for attempt in range(1, self.max_retries + 2):  # +2 because max_retries=0 means 1 attempt
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout)) as client:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    try:
                        data = resp.json()
                    except ValueError as e:
                        # Response body is not valid JSON
                        last_error_detail = f"Invalid JSON response: {e}"
                        logger.warning("API fetch %s attempt %d/%d: %s",
                                       source_name, attempt, self.max_retries + 2, last_error_detail)
                        if attempt <= self.max_retries + 1:
                            delay = self._backoff_delay(attempt)
                            await asyncio.sleep(delay)
                        continue

                    # Success — reset failure tracking
                    self._failure_counts[source_name] = 0
                    if self._circuit_open.get(source_name):
                        logger.info("Circuit breaker CLOSED for %s after successful fetch", source_name)
                        self._circuit_open[source_name] = False
                    return data

            except httpx.TimeoutException as e:
                last_error = e
                last_error_detail = f"Timeout after {self.timeout}s"
                logger.warning("API fetch %s attempt %d/%d: %s",
                               source_name, attempt, self.max_retries + 2, last_error_detail)
            except httpx.HTTPStatusError as e:
                last_error = e
                last_error_detail = f"HTTP {e.response.status_code}"
                logger.warning("API fetch %s attempt %d/%d: %s",
                               source_name, attempt, self.max_retries + 2, last_error_detail)
            except httpx.RequestError as e:
                last_error = e
                last_error_detail = f"Request error: {e}"
                logger.warning("API fetch %s attempt %d/%d: %s",
                               source_name, attempt, self.max_retries + 2, last_error_detail)

            # Backoff before retry (don't sleep after the last attempt)
            if attempt <= self.max_retries:
                delay = self._backoff_delay(attempt)
                logger.debug("Backing off %.1fs before retry %d for %s", delay, attempt + 1, source_name)
                await asyncio.sleep(delay)

        # All retries exhausted — increment failure count
        self._failure_counts[source_name] = self._failure_counts.get(source_name, 0) + 1
        fail_count = self._failure_counts[source_name]

        # Open circuit breaker after consecutive failures threshold
        if fail_count >= 5:
            self._circuit_open[source_name] = True
            logger.error(
                "Circuit breaker OPEN for %s after %d consecutive failures",
                source_name, fail_count)

        error_type = "timeout" if isinstance(last_error, httpx.TimeoutException) else "fetch_failed"
        return {"error": error_type, "detail": last_error_detail}

    async def fetch_with_fallback(self, source_name: str,
                                  primary_url: str,
                                  fallback_url: str) -> dict:
        """Fetch from primary URL, fall back to secondary on failure.

        Args:
            source_name: Logical name for the data source.
            primary_url: Primary URL to try first.
            fallback_url: Fallback URL to try if primary fails.

        Returns:
            Parsed JSON dict from whichever URL succeeds, or error dict if both fail.
        """
        result = await self.fetch(source_name, primary_url)
        if "error" not in result:
            return result

        logger.info(
            "Primary URL failed for %s (%s), trying fallback: %s",
            source_name, result.get("detail", "unknown"), fallback_url)

        fallback_result = await self.fetch(f"{source_name}_fallback", fallback_url)
        return fallback_result

    def reset_circuit(self, source_name: str) -> None:
        """Manually reset the circuit breaker for a source.

        Args:
            source_name: The source to reset.
        """
        was_open = self._circuit_open.get(source_name, False)
        self._circuit_open[source_name] = False
        self._failure_counts[source_name] = 0
        if was_open:
            logger.info("Circuit breaker manually reset for %s", source_name)

    def _backoff_delay(self, attempt: int) -> float:
        """Compute exponential backoff delay for the given attempt number (1-based)."""
        return self.backoff_base * (2 ** (attempt - 1))
