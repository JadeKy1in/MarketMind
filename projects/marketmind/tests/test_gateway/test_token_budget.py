"""Tests for TokenBudget manager."""
from projects.marketmind.gateway.token_budget import TokenBudget, Priority


def test_reserve_pro_deducts_correctly():
    tb = TokenBudget(daily_limit=10000, pro_call_limit=5, flash_call_limit=10)
    assert tb.can_call_pro()
    assert tb.reserve_pro(2000)
    assert tb.pro_calls_remaining == 4
    assert tb.tokens_remaining == 8000


def test_reserve_denies_when_empty():
    tb = TokenBudget(daily_limit=1000, pro_call_limit=1, flash_call_limit=0)
    assert tb.reserve_pro(1500) is False
    assert tb.reserve_pro(500)
    assert tb.reserve_pro(100) is False


def test_release_restores_tokens():
    tb = TokenBudget(daily_limit=10000, pro_call_limit=5, flash_call_limit=10)
    tb.reserve_pro(3000)
    tb.release_pro(2500)
    assert tb.tokens_remaining == 9500
    assert tb.pro_calls_remaining == 5


def test_handle_429_sets_backoff():
    tb = TokenBudget(daily_limit=10000, pro_call_limit=5, flash_call_limit=10)
    assert not tb.is_backing_off()
    tb.handle_429(10)
    assert tb.is_backing_off()


def test_report_returns_expected_keys():
    tb = TokenBudget(daily_limit=10000, pro_call_limit=5, flash_call_limit=10)
    r = tb.report()
    for k in ("tokens_remaining", "tokens_pct_used", "pro_calls_remaining",
              "flash_calls_remaining", "backoff_active"):
        assert k in r


def test_reserve_flash_works():
    tb = TokenBudget(daily_limit=10000, pro_call_limit=5, flash_call_limit=10)
    assert tb.can_call_flash()
    assert tb.reserve_flash(500)
    assert tb.flash_calls_remaining == 9
    assert tb.tokens_remaining == 9500


def test_release_flash_restores():
    tb = TokenBudget(daily_limit=10000, pro_call_limit=5, flash_call_limit=10)
    tb.reserve_flash(500)
    tb.release_flash(400)
    assert tb.tokens_remaining == 9900
    assert tb.flash_calls_remaining == 10


def test_priority_enum():
    assert Priority.CRITICAL < Priority.HIGH < Priority.NORMAL < Priority.SHADOW < Priority.LOW
    assert int(Priority.CRITICAL) == 1
    assert int(Priority.SHADOW) == 4
    assert int(Priority.LOW) == 5


def test_initial_values():
    tb = TokenBudget(daily_limit=50000, pro_call_limit=3, flash_call_limit=7)
    assert tb.tokens_remaining == 50000
    assert tb.pro_calls_remaining == 3
    assert tb.flash_calls_remaining == 7
    assert not tb.is_backing_off()
