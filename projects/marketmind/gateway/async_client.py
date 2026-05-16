"""Unified async DeepSeek gateway. All LLM calls route through here."""
from __future__ import annotations
import time
import asyncio
import logging
from typing import Any
import httpx

from marketmind.gateway.token_budget import TokenBudget, Priority

logger = logging.getLogger("marketmind.gateway.async_client")

DEEPSEEK_BASE = "https://api.deepseek.com/v1"
DEFAULT_TIMEOUT = httpx.Timeout(120.0)
MAX_CONNECTIONS = 20


class RateLimitError(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Retry after {retry_after}s")


KEY_ROTATE_THRESHOLD = 5  # Preemptively rotate when remaining below this
SHARED_POOL_WARNED = False


class KeyRotator:
    """API key rotation with asyncio.Lock and per-key quota tracking."""

    def __init__(self, keys: list[str]):
        if not keys:
            raise ValueError("At least one API key required")
        self._keys = keys
        self._idx = 0
        self._lock = asyncio.Lock()
        self._remaining: dict[int, int | None] = {i: None for i in range(len(keys))}

    def current(self) -> str:
        return self._keys[self._idx]

    def update_remaining(self, remaining: int | None) -> None:
        """Update quota remaining for the current key from response headers."""
        self._remaining[self._idx] = remaining

    def current_remaining(self) -> int | None:
        return self._remaining[self._idx]

    def key_status(self) -> dict:
        """Return per-key quota status for monitoring."""
        status = {}
        for i, key in enumerate(self._keys):
            suffix = key[-6:] if len(key) > 6 else "***"
            status[f"key_{i}_{suffix}"] = {
                "in_use": i == self._idx,
                "remaining": self._remaining.get(i),
            }
        # Detect shared quota pool
        non_none = [v for v in self._remaining.values() if v is not None]
        if len(non_none) >= 2 and len(set(non_none)) == 1:
            status["_shared_pool_warning"] = True
        return status

    async def rotate(self) -> str:
        async with self._lock:
            self._idx = (self._idx + 1) % len(self._keys)
            return self._keys[self._idx]

    def needs_rotation(self) -> bool:
        """Check if current key should be preemptively rotated."""
        rem = self._remaining.get(self._idx)
        return rem is not None and rem < KEY_ROTATE_THRESHOLD

    def __len__(self) -> int:
        return len(self._keys)


class DeepSeekGateway:
    def __init__(self, keys: list[str], base_url: str = DEEPSEEK_BASE):
        self.key_rotator = KeyRotator(keys)
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            limits=httpx.Limits(max_connections=MAX_CONNECTIONS),
        )

    async def close(self) -> None:
        await self._client.aclose()

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
        headers = {"Authorization": f"Bearer {self.key_rotator.current()}"}
        if reasoning_effort:
            headers["X-Reasoning-Effort"] = reasoning_effort

        t0 = time.perf_counter()
        resp = await self._client.post(
            f"{self.base_url}/chat/completions", json=payload, headers=headers
        )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 5))
            raise RateLimitError(retry_after)
        resp.raise_for_status()

        # Track per-key quota from response headers (preserve previous if missing)
        remaining_str = resp.headers.get("x-ratelimit-remaining")
        if remaining_str is not None:
            try:
                self.key_rotator.update_remaining(int(remaining_str))
            except (ValueError, TypeError):
                pass

        data = resp.json()
        return {
            "content": data["choices"][0]["message"]["content"],
            "usage": data.get("usage", {}),
            "latency_ms": elapsed_ms,
        }


_gateway: DeepSeekGateway | None = None
_budget: TokenBudget | None = None


def init_gateway(api_key: str, base_url: str = DEEPSEEK_BASE,
                  daily_token_budget: int = 2_000_000,
                  daily_pro_limit: int = 30,
                  daily_flash_limit: int = 100) -> None:
    global _gateway, _budget
    keys = [k.strip() for k in api_key.split(",") if k.strip()] if api_key else []
    if not keys:
        raise RuntimeError("No API key configured. Set DEEPSEEK_API_KEY or DEEPSEEK_API_KEYS.")
    _gateway = DeepSeekGateway(keys, base_url)
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
    reasoning_effort: str = "max",
) -> dict[str, Any]:
    """Internal: raw Flash call without integrity protocol injection.
    Shadow agents MUST use chat_with_integrity() instead."""
    gw = await get_gateway()
    budget = await get_budget()
    estimated = max_tokens + 1024
    if not budget.reserve_flash(estimated):
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
        return {"content": "", "error": "budget_exhausted", "usage": {}}
    try:
        return await _call_with_retry(
            gw, "deepseek-v4-pro", system_prompt, user_prompt,
            temperature, max_tokens, reasoning_effort
        )
    finally:
        budget.release_pro(estimated)


async def _call_with_retry(
    gw: DeepSeekGateway,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    reasoning_effort: str,
) -> dict[str, Any]:
    """Call LLM with one retry on 429 and preemptive key rotation."""
    budget = await get_budget()

    # Preemptive rotation if current key is near quota limit
    if gw.key_rotator.needs_rotation() and len(gw.key_rotator) > 1:
        await gw.key_rotator.rotate()
        logger.debug("Preemptive key rotation (remaining quota low)")

    try:
        return await gw._call(
            model, system_prompt, user_prompt, temperature, max_tokens, reasoning_effort
        )
    except RateLimitError as e:
        budget.handle_429(e.retry_after)
        if len(gw.key_rotator) > 1:
            await gw.key_rotator.rotate()
            logger.info("Key rotated after 429 (total keys: %d)", len(gw.key_rotator))
        else:
            logger.warning("429 received but only 1 key configured — cannot rotate")
        # Retry once with new key
        return await gw._call(
            model, system_prompt, user_prompt, temperature, max_tokens, reasoning_effort
        )


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
