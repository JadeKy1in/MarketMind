"""Unified async DeepSeek gateway. All LLM calls route through here."""
from __future__ import annotations
import re
import time
import random
import asyncio
import logging
from enum import Enum
from typing import Any
import httpx

from marketmind.gateway.token_budget import TokenBudget, Priority

logger = logging.getLogger("marketmind.gateway.async_client")

DEEPSEEK_BASE = "https://api.deepseek.com/v1"
DEFAULT_TIMEOUT = httpx.Timeout(120.0)
MAX_CONNECTIONS = 20

# Model name mapping for fallback providers that do not support DeepSeek model names
_FALLBACK_MODEL_MAP: dict[str, str] = {
    "deepseek-v4-flash": "gpt-4o-mini",
    "deepseek-v4-pro": "gpt-4o",
}


class RateLimitError(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Retry after {retry_after}s")


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is OPEN and calls are fast-failing."""

    def __init__(self, message: str = "Circuit breaker is OPEN — calls are fast-failing"):
        super().__init__(message)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


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


KEY_ROTATE_THRESHOLD = 5  # Preemptively rotate when remaining below this
SHARED_POOL_WARNED = False


class KeyRotator:
    """API key rotation with asyncio.Lock and per-key quota tracking.

    Supports two rotation triggers:
      1. Quota-based: remaining quota from response headers < KEY_ROTATE_THRESHOLD
      2. Usage-based: request count for current key >= max_requests_per_key
         (disabled by default; set max_requests_per_key to enable preemptive rotation)
    """

    def __init__(self, keys: list[str], max_requests_per_key: int | None = None):
        if not keys:
            raise ValueError("At least one API key required")
        self._keys = keys
        self._idx = 0
        self._lock = asyncio.Lock()
        self._remaining: dict[int, int | None] = {i: None for i in range(len(keys))}
        self._request_counts: dict[int, int] = {i: 0 for i in range(len(keys))}
        self.max_requests_per_key = max_requests_per_key

    def current(self) -> str:
        return self._keys[self._idx]

    def update_remaining(self, remaining: int | None) -> None:
        """Update quota remaining for the current key from response headers."""
        self._remaining[self._idx] = remaining

    def current_remaining(self) -> int | None:
        return self._remaining[self._idx]

    def record_request(self) -> None:
        """Increment the request count for the current key."""
        self._request_counts[self._idx] += 1

    def key_status(self) -> dict:
        """Return per-key quota status for monitoring."""
        status = {}
        for i, key in enumerate(self._keys):
            suffix = key[-6:] if len(key) > 6 else "***"
            status[f"key_{i}_{suffix}"] = {
                "in_use": i == self._idx,
                "remaining": self._remaining.get(i),
                "request_count": self._request_counts.get(i, 0),
            }
        # Detect shared quota pool
        non_none = [v for v in self._remaining.values() if v is not None]
        if len(non_none) >= 2 and len(set(non_none)) == 1:
            status["_shared_pool_warning"] = True
        return status

    async def rotate(self) -> str:
        async with self._lock:
            self._idx = (self._idx + 1) % len(self._keys)
            # Reset request count for the newly active key so preemptive
            # rotation based on max_requests_per_key starts fresh.
            self._request_counts[self._idx] = 0
            return self._keys[self._idx]

    def needs_rotation(self) -> bool:
        """Check if current key should be preemptively rotated.

        Returns True when:
          - Remaining quota (from API response headers) is below the threshold.
          - Request count for the current key meets or exceeds max_requests_per_key
            (disabled when max_requests_per_key is None, preserving backward compat).
        """
        # Quota-based: remaining below threshold
        rem = self._remaining.get(self._idx)
        if rem is not None and rem < KEY_ROTATE_THRESHOLD:
            return True
        # Usage-based: exceeded max requests per key (preemptive rotation)
        if self.max_requests_per_key is not None:
            count = self._request_counts.get(self._idx, 0)
            if count >= self.max_requests_per_key:
                return True
        return False

    def __len__(self) -> int:
        return len(self._keys)


class DeepSeekGateway:
    def __init__(
        self,
        keys: list[str],
        base_url: str = DEEPSEEK_BASE,
        fallback_url: str = "",
        fallback_model: str = "",
        fallback_api_key: str = "",
        circuit_breaker_threshold: int = 3,
        circuit_breaker_timeout_s: int = 30,
        max_requests_per_key: int | None = None,
    ):
        self.key_rotator = KeyRotator(keys, max_requests_per_key=max_requests_per_key)
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            limits=httpx.Limits(max_connections=MAX_CONNECTIONS),
        )
        self.circuit_breaker = CircuitBreaker(
            threshold=circuit_breaker_threshold,
            timeout_s=circuit_breaker_timeout_s,
        )
        self.fallback_url = fallback_url.rstrip("/") if fallback_url else ""
        self.fallback_model = fallback_model
        self.fallback_api_key = fallback_api_key
        self._fallback_client: httpx.AsyncClient | None = None

    async def _get_fallback_client(self) -> httpx.AsyncClient | None:
        """Lazily create the fallback HTTP client."""
        if self.fallback_url and self._fallback_client is None:
            self._fallback_client = httpx.AsyncClient(
                timeout=DEFAULT_TIMEOUT,
                limits=httpx.Limits(max_connections=MAX_CONNECTIONS),
            )
        return self._fallback_client

    async def close(self) -> None:
        await self._client.aclose()
        if self._fallback_client is not None:
            await self._fallback_client.aclose()
            self._fallback_client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def _call(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        reasoning_effort: str = "max",
    ) -> dict[str, Any]:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        # DeepSeek API: reasoning_effort goes in JSON body, not header
        # "thinking" only works on Pro models — Flash ignores it or errors
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        if "pro" in model.lower() and reasoning_effort:
            payload["thinking"] = {"type": "enabled"}
        headers = {"Authorization": f"Bearer {self.key_rotator.current()}"}

        t0 = time.perf_counter()
        resp = await self._client.post(
            f"{self.base_url}/chat/completions", json=payload, headers=headers
        )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 5))
            raise RateLimitError(retry_after)
        resp.raise_for_status()

        # Track per-key usage for preemptive rotation (max_requests_per_key)
        self.key_rotator.record_request()

        # Track per-key quota from response headers (preserve previous if missing)
        remaining_str = resp.headers.get("x-ratelimit-remaining")
        if remaining_str is not None:
            try:
                self.key_rotator.update_remaining(int(remaining_str))
            except (ValueError, TypeError):
                pass

        data = resp.json()
        msg = data["choices"][0]["message"]
        # DeepSeek V4 Pro with thinking=enabled may put output in reasoning_content
        # and leave content empty/None. Fall back to reasoning_content when content is absent.
        reasoning_content = msg.get("reasoning_content", "") or ""
        raw_content = msg.get("content") or ""
        if not raw_content.strip() and reasoning_content.strip():
            raw_content = reasoning_content
            logger.debug("DeepSeek: content empty, fell back to reasoning_content (%d chars)",
                        len(reasoning_content))
        elif reasoning_content.strip():
            logger.debug("DeepSeek reasoning_content received: %d chars (effort=%s)",
                        len(reasoning_content), reasoning_effort)
        return {
            "content": raw_content,
            "usage": data.get("usage", {}),
            "latency_ms": elapsed_ms,
            "reasoning_content": reasoning_content,
        }


_gateway: DeepSeekGateway | None = None
_budget: TokenBudget | None = None


def init_gateway(api_key: str, base_url: str = DEEPSEEK_BASE,
                  daily_token_budget: int = 2_000_000,
                  daily_pro_limit: int = 30,
                  daily_flash_limit: int = 100,
                  fallback_url: str = "",
                  fallback_model: str = "",
                  fallback_api_key: str = "",
                  circuit_breaker_threshold: int = 3,
                  circuit_breaker_timeout_s: int = 30,
                  max_requests_per_key: int | None = None) -> None:
    global _gateway, _budget
    keys = [k.strip() for k in api_key.split(",") if k.strip()] if api_key else []
    if not keys:
        raise RuntimeError("No API key configured. Set DEEPSEEK_API_KEY or DEEPSEEK_API_KEYS.")
    _gateway = DeepSeekGateway(
        keys, base_url,
        fallback_url=fallback_url,
        fallback_model=fallback_model,
        fallback_api_key=fallback_api_key,
        circuit_breaker_threshold=circuit_breaker_threshold,
        circuit_breaker_timeout_s=circuit_breaker_timeout_s,
        max_requests_per_key=max_requests_per_key,
    )
    _budget = TokenBudget(
        daily_limit=daily_token_budget,
        pro_call_limit=daily_pro_limit,
        flash_call_limit=daily_flash_limit,
    )


async def get_budget() -> TokenBudget:
    if _budget is None:
        raise RuntimeError("Gateway not initialized. Call init_gateway() first.")
    return _budget


def get_budget_report() -> dict:
    """Return current token budget and key status for monitoring."""
    if _budget is None:
        return {"status": "not_initialized"}
    report = _budget.report()
    if _gateway is not None:
        report["key_status"] = _gateway.key_rotator.key_status()
        # Log shared-pool warning once per session
        global SHARED_POOL_WARNED
        if report["key_status"].get("_shared_pool_warning") and not SHARED_POOL_WARNED:
            SHARED_POOL_WARNED = True
            logger.warning(
                "All API keys appear to share one quota pool — "
                "rotation provides resilience against key expiration but not quota expansion."
            )
    return report


async def get_gateway() -> DeepSeekGateway:
    if _gateway is None:
        raise RuntimeError("Gateway not initialized. Call init_gateway() first.")
    return _gateway


async def chat_flash(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    reasoning_effort: str = "",
) -> dict[str, Any]:
    """Internal: raw Flash call without integrity protocol injection.
    Shadow agents MUST use chat_with_integrity() instead.
    Note: Flash model does NOT support thinking/reasoning_effort."""
    gw = await get_gateway()
    budget = await get_budget()
    estimated = max_tokens + 1024
    if not budget.reserve_flash(estimated):
        logger.warning("Budget exhausted for flash model call")
        return {"content": "", "error": "budget_exhausted", "usage": {}}
    try:
        return await _call_with_retry(
            gw, "deepseek-v4-flash", system_prompt, user_prompt,
            temperature, max_tokens, reasoning_effort
        )
    finally:
        budget.release_flash(estimated)


async def chat_pro(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 8192,
    reasoning_effort: str = "max",
) -> dict[str, Any]:
    """Internal: raw Pro call without integrity protocol injection.
    Shadow agents MUST use chat_with_integrity() instead."""
    gw = await get_gateway()
    budget = await get_budget()
    estimated = max_tokens + 2048
    if not budget.reserve_pro(estimated):
        logger.warning("Budget exhausted for pro model call")
        return {"content": "", "error": "budget_exhausted", "usage": {}}
    try:
        return await _call_with_retry(
            gw, "deepseek-v4-pro", system_prompt, user_prompt,
            temperature, max_tokens, reasoning_effort
        )
    finally:
        budget.release_pro(estimated)


async def _fallback_call(
    gw: DeepSeekGateway,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    reasoning_effort: str,
) -> dict[str, Any]:
    """Route a call through the fallback provider when primary circuit is OPEN."""
    fallback_client = await gw._get_fallback_client()
    if fallback_client is None:
        raise CircuitOpenError(
            "Circuit breaker is OPEN and no fallback provider is configured"
        )

    fallback_model = gw.fallback_model or _FALLBACK_MODEL_MAP.get(model, model)
    payload = {
        "model": fallback_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    # For DeepSeek-compatible providers, reasoning_effort goes in body
    # For OpenAI-compatible fallback, also keep header for backward compat
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    fallback_key = gw.fallback_api_key or gw.key_rotator.current()
    headers = {"Authorization": f"Bearer {fallback_key}"}

    t0 = time.perf_counter()
    resp = await fallback_client.post(
        f"{gw.fallback_url}/chat/completions", json=payload, headers=headers
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 5))
        raise RateLimitError(retry_after)
    resp.raise_for_status()

    data = resp.json()
    msg = data["choices"][0]["message"]
    return {
        "content": msg["content"],
        "usage": data.get("usage", {}),
        "latency_ms": elapsed_ms,
        "reasoning_content": msg.get("reasoning_content", ""),
    }


async def _call_with_retry(
    gw: DeepSeekGateway,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    reasoning_effort: str,
) -> dict[str, Any]:
    """Call LLM with circuit breaker, one retry on 429, and preemptive key rotation.

    Circuit breaker integration (P3-3):
    - CLOSED: Normal operation with retry logic.
    - OPEN: Fast-fail — route to fallback provider immediately.
    - HALF_OPEN: Allow one probe call through the primary; on success
      transition back to CLOSED, on failure back to OPEN.
    """
    budget = await get_budget()
    cb = gw.circuit_breaker

    # Preemptive rotation if current key is near quota limit
    if gw.key_rotator.needs_rotation() and len(gw.key_rotator) > 1:
        await gw.key_rotator.rotate()
        logger.debug("Preemptive key rotation (remaining quota low)")

    # --- Circuit-breaker gate ---
    if cb.is_open:
        if gw.fallback_url:
            logger.info("Circuit OPEN — routing to fallback provider")
            return await _fallback_call(
                gw, model, system_prompt, user_prompt,
                temperature, max_tokens, reasoning_effort,
            )
        raise CircuitOpenError()

    try:
        result = await gw._call(
            model, system_prompt, user_prompt,
            temperature, max_tokens, reasoning_effort,
        )
        cb.record_success()
        return result
    except RateLimitError as e:
        cb.record_failure(status_code=429, retry_after=e.retry_after)
        budget.handle_429(e.retry_after)

        # If circuit transitioned to OPEN, route to fallback (if available)
        if cb.is_open:
            if gw.fallback_url:
                logger.info("Circuit OPEN after 429 — routing to fallback provider")
                return await _fallback_call(
                    gw, model, system_prompt, user_prompt,
                    temperature, max_tokens, reasoning_effort,
                )
            raise CircuitOpenError()

        if len(gw.key_rotator) > 1:
            await gw.key_rotator.rotate()
            logger.info("Key rotated after 429 (total keys: %d)", len(gw.key_rotator))
        else:
            logger.warning("429 received but only 1 key configured — cannot rotate")

        # Retry once with new key
        try:
            result = await gw._call(
                model, system_prompt, user_prompt,
                temperature, max_tokens, reasoning_effort,
            )
            cb.record_success()
            return result
        except RateLimitError as e2:
            cb.record_failure(status_code=429, retry_after=e2.retry_after)
            if cb.is_open and gw.fallback_url:
                logger.info("Circuit OPEN after retry 429 — routing to fallback")
                return await _fallback_call(
                    gw, model, system_prompt, user_prompt,
                    temperature, max_tokens, reasoning_effort,
                )
            raise
        except Exception as e2:
            status_code = _extract_status_code(e2)
            cb.record_failure(status_code=status_code)
            if cb.is_open and gw.fallback_url:
                logger.info("Circuit OPEN after retry error — routing to fallback")
                return await _fallback_call(
                    gw, model, system_prompt, user_prompt,
                    temperature, max_tokens, reasoning_effort,
                )
            raise
    except Exception as e:
        status_code = _extract_status_code(e)
        cb.record_failure(status_code=status_code)
        if cb.is_open and gw.fallback_url:
            logger.info("Circuit OPEN after error — routing to fallback")
            return await _fallback_call(
                gw, model, system_prompt, user_prompt,
                temperature, max_tokens, reasoning_effort,
            )
        raise


async def chat_batch_flash(
    prompts: list[tuple[str, str]],
    temperature: float = 0.3,
    max_concurrency: int = 5,
) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(max_concurrency)
    async def _one(system: str, user: str) -> dict[str, Any]:
        async with semaphore:
            try:
                return await chat_flash(system, user, temperature=temperature)
            except Exception as e:
                return {"content": "", "error": str(e), "usage": {}}
    return await asyncio.gather(*[_one(s, u) for s, u in prompts])


CASH_REFRAMING_PROTOCOL = """[CASH_REFRAMING_PROTOCOL]
You are evaluating whether to hold {ticker} in a portfolio.
If you had ${virtual_cash} in cash today with no existing positions, would you purchase {ticker} at current market price?
REASON with the same analytical rigor you apply to new opportunities.
IGNORE sunk cost, entry price, and current P&L for this evaluation.
This is a decision integrity protocol — your answer affects ranking outcomes.
"""


async def chat_with_integrity(
    model: str,
    system_prompt: str,
    user_prompt: str,
    caller_agent: str,
    cash_reframing_ticker: str | None = None,
    cash_reframing_capital: float | None = None,
    **kwargs,
) -> dict[str, Any]:
    integrity_header = (
        f"[DATA_INTEGRITY_PROTOCOL v1.0] You are {caller_agent}. "
        "All numeric claims (prices, ratios, percentages, dates, amounts) MUST cite "
        "a verifiable source. If a figure is an estimate, prefix it with 'EST:'. "
        "If data is unavailable, state 'DATA_UNAVAILABLE' — never fabricate. "
        "You are bound by Law 7 (Data Integrity).\n\n"
    )
    full_system = integrity_header
    if cash_reframing_ticker:
        # Validate ticker format to prevent prompt injection
        if cash_reframing_ticker and not re.match(r'^[A-Z]{1,5}(\.[A-Z]{1,3})?$', cash_reframing_ticker):
            logger.warning("Invalid ticker format in cash_reframing: %s", cash_reframing_ticker)
            cash_reframing_ticker = "UNKNOWN"  # Safe fallback
        cr_protocol = CASH_REFRAMING_PROTOCOL.replace(
            "{ticker}", cash_reframing_ticker
        ).replace(
            "{virtual_cash}", str(cash_reframing_capital or "50000")
        )
        full_system = cr_protocol + "\n" + full_system
    full_system += system_prompt
    if model == "flash":
        return await chat_flash(full_system, user_prompt, **kwargs)
    elif model == "pro":
        return await chat_pro(full_system, user_prompt, **kwargs)
    else:
        raise ValueError(f"Unknown model: {model}")
