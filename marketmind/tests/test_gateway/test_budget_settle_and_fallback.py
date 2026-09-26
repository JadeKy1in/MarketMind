"""S1 fixes: token budget actually decrements; fallback never leaks the primary key."""
import pytest

from marketmind.gateway.async_client import DeepSeekGateway, _fallback_call, _used_tokens
from marketmind.gateway.circuit_breaker import CircuitOpenError
from marketmind.gateway.token_budget import TokenBudget


def test_successful_call_is_charged_actual_usage():
    b = TokenBudget(daily_limit=100_000, pro_call_limit=10, flash_call_limit=10)
    assert b.reserve_pro(40_000)
    b.settle_pro(40_000, 12_000)
    assert b.tokens_remaining == 88_000
    assert b.pro_calls_remaining == 9          # the call counts


def test_overrun_is_charged():
    b = TokenBudget(daily_limit=100_000, pro_call_limit=10, flash_call_limit=10)
    b.reserve_flash(5_000)
    b.settle_flash(5_000, 8_000)
    assert b.tokens_remaining == 92_000


def test_failed_call_is_refunded():
    b = TokenBudget(daily_limit=100_000, pro_call_limit=10, flash_call_limit=10)
    b.reserve_pro(40_000)
    b.settle_pro(40_000, None)
    assert (b.tokens_remaining, b.pro_calls_remaining) == (100_000, 10)


def test_limit_now_triggers_after_repeated_calls():
    b = TokenBudget(daily_limit=100_000, pro_call_limit=3, flash_call_limit=3)
    for _ in range(3):
        assert b.reserve_pro(1_000)
        b.settle_pro(1_000, 900)
    assert b.reserve_pro(1_000) is False       # previously never happened


def test_used_tokens_parsing():
    assert _used_tokens(None, 100) is None
    assert _used_tokens({"content": "", "error": "budget_exhausted"}, 100) is None
    assert _used_tokens({"content": "x", "usage": {"total_tokens": 42}}, 100) == 42
    assert _used_tokens({"content": "x", "usage": {"prompt_tokens": 5, "completion_tokens": 7}}, 100) == 12
    assert _used_tokens({"content": "x", "usage": {}}, 100) == 100   # conservative charge


@pytest.mark.asyncio
async def test_fallback_refuses_to_send_primary_key_to_other_provider():
    gw = DeepSeekGateway(keys=["sk-primary-secret"], fallback_url="https://api.openai.com/v1")
    with pytest.raises(CircuitOpenError, match="fallback_api_key"):
        await _fallback_call(gw, "deepseek-v4-pro", "s", "u", 0.2, 10, "max")
