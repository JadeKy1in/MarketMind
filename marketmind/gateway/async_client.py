"""Unified async DeepSeek gateway. All LLM calls route through here."""
from __future__ import annotations
import os
import re
import time
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
import httpx

from marketmind.gateway.token_budget import TokenBudget, Priority
from marketmind.gateway import usage_tracker
from marketmind.gateway.circuit_breaker import (
    CircuitBreaker, CircuitState, CircuitOpenError, _extract_status_code,
)

# ── KeyRotator extracted to gateway/key_rotator.py ──────────────────────
from marketmind.gateway.key_rotator import KeyRotator, KEY_ROTATE_THRESHOLD, SHARED_POOL_WARNED  # noqa: F811 re-exported
from marketmind.notification.alert_schema import Severity, ImpactScope
from marketmind.notification.alert_manager import emit_alert

logger = logging.getLogger("marketmind.gateway.async_client")

DEEPSEEK_BASE = "https://api.deepseek.com/v1"
DEFAULT_TIMEOUT = httpx.Timeout(120.0)
MAX_CONNECTIONS = 20

# Model ids. /models on 2026-09-27 listed "deepseek-flash" and "deepseek-v4-pro"
# (the old "deepseek-v4-flash" id is no longer listed). Override via env.
FLASH_MODEL = os.environ.get("MARKETMIND_FLASH_MODEL", "deepseek-flash")
PRO_MODEL = os.environ.get("MARKETMIND_PRO_MODEL", "deepseek-v4-pro")


# deepseek-flash reasons before answering. With max_tokens=4096 the reasoning used
# the whole budget and `content` came back empty for 3 of 4 news batches
# (2026-09-27 live run). Floor the output cap; unused tokens are refunded by settle().
FLASH_MIN_MAX_TOKENS = int(os.environ.get("MARKETMIND_FLASH_MIN_MAX_TOKENS", "16384"))


def pro_routed_to_flash() -> bool:
    """Owner decision 2026-09-27: Pro is too expensive and underperforms Flash,
    so Pro-tier calls run on Flash unless MARKETMIND_PRO_AS_FLASH=0."""
    return os.environ.get("MARKETMIND_PRO_AS_FLASH", "1").strip().lower() not in ("0", "false", "no")


# Model name mapping for fallback providers that do not support DeepSeek model names
_FALLBACK_MODEL_MAP: dict[str, str] = {
    FLASH_MODEL: "gpt-4o-mini",
    PRO_MODEL: "gpt-4o",
}


class RateLimitError(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Retry after {retry_after}s")


def _extract_json_from_reasoning(text: str) -> str:
    """Extract the likely JSON output from the end of a reasoning chain.

    When DeepSeek thinking is enabled, the final structured answer sometimes
    appears at the tail of reasoning_content rather than in a separate content
    field. This extracts it without losing the thinking quality.
    """
    import json as _json
    # Try to find JSON after the last markdown code fence
    last_fence = text.rfind("```json")
    if last_fence != -1:
        after = text[last_fence + 7:]
        end_fence = after.find("```")
        if end_fence != -1:
            candidate = after[:end_fence].strip()
            try:
                _json.loads(candidate)
                return candidate
            except (_json.JSONDecodeError, ValueError):
                pass
    # Try last balanced {...} block
    last_open = text.rfind("{")
    if last_open != -1:
        candidate = text[last_open:]
        try:
            _json.loads(candidate)
            return candidate
        except (_json.JSONDecodeError, ValueError):
            # Try to find the balanced closing brace
            depth = 0
            for i, ch in enumerate(candidate):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = candidate[:i + 1]
                        try:
                            _json.loads(candidate)
                            return candidate
                        except (_json.JSONDecodeError, ValueError):
                            break
    return ""


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
        response_format: dict | None = None,
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
        if response_format:
            payload["response_format"] = response_format
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
        # and leave content empty/None.
        reasoning_content = msg.get("reasoning_content", "") or ""
        raw_content = msg.get("content") or ""
        # When content is empty but reasoning exists, try to extract the final
        # structured output from the end of the reasoning chain. Never use raw
        # reasoning as the final answer — it's chain-of-thought, not output.
        if not raw_content.strip() and reasoning_content.strip():
            extracted = _extract_json_from_reasoning(reasoning_content)
            if extracted:
                raw_content = extracted
                logger.info("DeepSeek: extracted JSON from reasoning tail (%d chars)",
                            len(raw_content))
                emit_alert(
                    Severity.WARN, "gateway", ImpactScope.MAIN_PIPELINE,
                    "JSON extracted from reasoning tail — content field was empty",
                    f"Recovered {len(raw_content)} chars from reasoning_content",
                    "检查Pro响应格式，当前已自动恢复", degraded_output=False,
                )
            else:
                logger.warning("DeepSeek: content empty, reasoning_content=%d chars — no JSON found "
                               "(model=%s, max_tokens=%d, finish_reason=%s)",
                               len(reasoning_content), model, max_tokens,
                               (data.get("choices") or [{}])[0].get("finish_reason"))
                emit_alert(
                    Severity.ERROR, "gateway", ImpactScope.MAIN_PIPELINE,
                    "Pro response content empty — no JSON recovered",
                    f"reasoning_content={len(reasoning_content)} chars, no extractable JSON",
                    "检查API响应格式，可能影响分析质量", degraded_output=True,
                )
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
_mock_mode: bool = False


def set_mock_mode(enabled: bool = True) -> None:
    """Enable/disable mock LLM mode — chat_flash/chat_pro return minimal
    valid responses without making any API calls."""
    global _mock_mode
    _mock_mode = enabled


_MOCK_PRO_RESPONSE = {
    "content": "{}",
    "usage": {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0},
}
_MOCK_FLASH_RESPONSE = {
    "content": "[]",
    "usage": {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0},
}


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
            logger.debug(
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
    if _mock_mode:
        return dict(_MOCK_FLASH_RESPONSE)
    claude = await _try_claude(system_prompt, user_prompt, "flash")
    if claude is not None:
        return claude
    gw = await get_gateway()
    budget = await get_budget()
    max_tokens = max(max_tokens, FLASH_MIN_MAX_TOKENS)
    estimated = max_tokens + 1024
    if not budget.reserve_flash(estimated):
        logger.warning("Budget exhausted for flash model call")
        emit_alert(
            Severity.CRITICAL, "gateway", ImpactScope.INFRASTRUCTURE,
            "Flash token budget exhausted",
            "今日Flash调用预算已用完，部分数据采集可能不完整",
            "增加预算或减少调用频率", degraded_output=True,
        )
        return {"content": "", "error": "budget_exhausted", "usage": {}}
    result = None
    try:
        result = await _call_with_retry(
            gw, FLASH_MODEL, system_prompt, user_prompt,
            temperature, max_tokens, ""  # Flash does not take reasoning_effort
        )
        return result
    finally:
        budget.settle_flash(estimated, _used_tokens(result, estimated))
        usage_tracker.record(result)


async def chat_pro(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 32768,
    reasoning_effort: str = "max",
) -> dict[str, Any]:
    """Internal: raw Pro call without integrity protocol injection.
    Shadow agents MUST use chat_with_integrity() instead."""
    if _mock_mode:
        return dict(_MOCK_PRO_RESPONSE)
    claude = await _try_claude(system_prompt, user_prompt, "pro")
    if claude is not None:
        return claude
    gw = await get_gateway()
    budget = await get_budget()
    estimated = max_tokens + 2048
    if not budget.reserve_pro(estimated):
        logger.warning("Budget exhausted for pro model call")
        emit_alert(
            Severity.CRITICAL, "gateway", ImpactScope.INFRASTRUCTURE,
            "Pro token budget exhausted",
            "今日Pro调用预算已用完，分析结果将不可靠",
            "增加预算，今日分析可能需重新运行", degraded_output=True,
        )
        return {"content": "", "error": "budget_exhausted", "usage": {}}
    result = None
    try:
        if pro_routed_to_flash():
            model, effort = FLASH_MODEL, ""
            max_tokens = max(max_tokens, FLASH_MIN_MAX_TOKENS)
        else:
            model, effort = PRO_MODEL, reasoning_effort
        result = await _call_with_retry(
            gw, model, system_prompt, user_prompt,
            temperature, max_tokens, effort
        )
        return result
    finally:
        budget.settle_pro(estimated, _used_tokens(result, estimated))
        usage_tracker.record(result)


_claude_failures = 0
CLAUDE_FAILURES_BEFORE_PAUSE = 3


async def _try_claude(system_prompt: str, user_prompt: str, tier: str) -> dict[str, Any] | None:
    """Claude via the local CLI when MARKETMIND_LLM=claude (docs/LLM_PROVIDER.md).

    Returns the result, or None to fall through to DeepSeek: provider not
    selected, or the call failed (logged). After 3 failures in a row (e.g. the
    subscription's usage limit) the rest of the run goes straight to DeepSeek.
    """
    global _claude_failures
    from marketmind.gateway import claude_cli
    if claude_cli.provider() != "claude" or _claude_failures >= CLAUDE_FAILURES_BEFORE_PAUSE:
        return None
    result = await claude_cli.call(system_prompt, user_prompt, tier)
    if result.get("error") or not result.get("content"):
        _claude_failures += 1
        logger.warning("Claude call failed (%s); this call falls back to DeepSeek",
                       result.get("error") or "empty reply")
        if _claude_failures == CLAUDE_FAILURES_BEFORE_PAUSE:
            logger.warning("Claude failed %d times in a row; DeepSeek for the rest of this run",
                           CLAUDE_FAILURES_BEFORE_PAUSE)
            emit_alert(Severity.WARN, "gateway", ImpactScope.INFRASTRUCTURE,
                       "Claude unavailable, switched to DeepSeek",
                       f"连续 {CLAUDE_FAILURES_BEFORE_PAUSE} 次 Claude 调用失败（{result.get('error')}），"
                       "本次运行其余调用改用 DeepSeek", "检查 Claude 登录或额度")
        return None
    _claude_failures = 0
    usage_tracker.record(result)
    return result


def _used_tokens(result: dict[str, Any] | None, reserved: int) -> int | None:
    """Tokens billed for a call; None if it did not complete (full refund).

    A call that returned content but no usage block is charged the full
    reservation (conservative), not refunded.
    """
    if not isinstance(result, dict) or result.get("error"):
        return None
    usage = result.get("usage") or {}
    total = usage.get("total_tokens")
    if total is None:
        total = (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
    if total:
        return int(total)
    return reserved if result.get("content") else None


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
    same_provider = "deepseek" in gw.fallback_url.lower()
    # reasoning_effort is a DeepSeek parameter; other providers may reject the call.
    if reasoning_effort and same_provider:
        payload["reasoning_effort"] = reasoning_effort
    # Never send the DeepSeek key to a different provider.
    if gw.fallback_api_key:
        fallback_key = gw.fallback_api_key
    elif same_provider:
        fallback_key = gw.key_rotator.current()
    else:
        raise CircuitOpenError(
            "Circuit breaker is OPEN and the fallback provider has no fallback_api_key "
            "(refusing to send the primary key to another provider)"
        )
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
            emit_alert(
                Severity.WARN, "gateway", ImpactScope.INFRASTRUCTURE,
                "Circuit breaker OPEN — routing to fallback provider",
                f"Primary API circuit open, using fallback: {gw.fallback_model or 'configured'}",
                "检查主API状态，当前使用备用提供商", degraded_output=True,
            )
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
    # SINGLE SOURCE OF TRUTH for time — injected at gateway level so all
    # LLM calls (including shadows that don't use SessionContext) share the
    # same temporal anchor.  UTC eliminates timezone ambiguity.
    time_context = (
        f"TIME_CONTEXT: TODAY is {datetime.now(timezone.utc).strftime('%Y-%m-%d')} (UTC). "
        "Use this as the SINGLE SOURCE OF TRUTH for the current date in all "
        "analysis, reasoning, and date references.\n\n"
    )
    full_system = integrity_header + time_context
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
