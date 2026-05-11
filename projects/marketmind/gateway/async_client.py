"""Unified async DeepSeek gateway. All LLM calls route through here."""
from __future__ import annotations
import time
import asyncio
from typing import Any
import httpx

DEEPSEEK_BASE = "https://api.deepseek.com/v1"
DEFAULT_TIMEOUT = httpx.Timeout(120.0)
MAX_CONNECTIONS = 20


class RateLimitError(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Retry after {retry_after}s")


class DeepSeekGateway:
    def __init__(self, api_key: str, base_url: str = DEEPSEEK_BASE):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            limits=httpx.Limits(max_connections=MAX_CONNECTIONS),
            headers={"Authorization": f"Bearer {api_key}"}
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
        headers = {}
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
        data = resp.json()
        return {
            "content": data["choices"][0]["message"]["content"],
            "usage": data.get("usage", {}),
            "latency_ms": elapsed_ms,
        }


_gateway: DeepSeekGateway | None = None


def init_gateway(api_key: str, base_url: str = DEEPSEEK_BASE) -> None:
    global _gateway
    _gateway = DeepSeekGateway(api_key, base_url)


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
    return await gw._call(
        "deepseek-v4-flash", system_prompt, user_prompt, temperature, max_tokens, reasoning_effort
    )


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
    return await gw._call(
        "deepseek-v4-pro", system_prompt, user_prompt, temperature, max_tokens, reasoning_effort
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
