"""Daily/weekend runs: failed steps give a distinct "degraded" exit code, and the
shadow wait never cancels the shadow task (red-team 2026-09-29)."""
import asyncio
from types import SimpleNamespace

import pytest

from marketmind.pipeline import orchestration as orch


@pytest.fixture(autouse=True)
def _clean_globals(monkeypatch):
    monkeypatch.setattr(orch, "_shadow_task", None)
    monkeypatch.setattr(orch, "_evidence_task", None)
    monkeypatch.setattr(orch, "_playground_task", None)
    monkeypatch.setattr(orch, "_shadow_entry_count", None)
    orch._reset_step_failures()
    yield
    orch._reset_step_failures()


def _args(mock=False):
    return SimpleNamespace(no_shadows=False, shadows=None, mock=mock, verbose=False)


def _stub_daily(monkeypatch, fail_step=None):
    async def fake_run_daily(config, **kw):
        return 0

    async def ok(config):
        return None

    def failing(name):
        async def step(config):
            orch._step_failed(name)
        return step

    monkeypatch.setattr(orch, "run_daily", fake_run_daily)
    for fn, name in (("inspect_holdings_step", "holdings"), ("promotion_step", "promotion"),
                     ("alerts_step", "alerts"), ("daily_report_step", "daily report"),
                     ("trend_step", "trend"), ("ecosystem_step", "ecosystem"), ("app_charts_step", "app charts")):
        monkeypatch.setattr(orch, fn, failing(name) if name == fail_step else ok)
    from marketmind.gateway import usage_tracker
    monkeypatch.setattr(usage_tracker, "append_log", lambda *a, **k: None)


def test_clean_daily_run_exits_zero(monkeypatch):
    _stub_daily(monkeypatch)
    assert asyncio.run(orch._run_daily_with_shadows(object(), _args())) == 0


@pytest.mark.parametrize("step", ["holdings", "promotion", "alerts", "daily report", "trend", "app charts",
                                  "ecosystem"])
def test_failed_step_makes_daily_run_degraded(monkeypatch, capsys, step):
    _stub_daily(monkeypatch, fail_step=step)
    assert asyncio.run(orch._run_daily_with_shadows(object(), _args())) == orch.DEGRADED_EXIT == 3
    assert f"[degraded] {step}" in capsys.readouterr().out


def test_real_step_handlers_record_failure(monkeypatch, capsys):
    import marketmind.alerts.runner as alerts_runner

    async def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(alerts_runner, "run_alerts", boom)
    monkeypatch.setattr(orch, "_ledger_store", lambda config: None)
    asyncio.run(orch.alerts_step(object()))
    assert orch._step_failures == ["alerts"]


def test_existing_failure_code_is_kept():
    orch._step_failed("alerts")
    assert orch._finish_exit_code(1) == 1
    orch._reset_step_failures()
    assert orch._finish_exit_code(0) == 0


def test_shadow_timeout_does_not_cancel_the_task(monkeypatch, capsys):
    """The first wait times out; the task keeps running and its result lands before exit."""
    _stub_daily(monkeypatch)
    monkeypatch.setattr(orch, "SHADOW_WAIT_S", 0.05)
    monkeypatch.setattr(orch, "SHADOW_PER_ENTRY_S", 0)
    monkeypatch.setattr(orch, "SHADOW_FINAL_GRACE_S", 5)
    finished = []

    async def shadows():
        await asyncio.sleep(0.3)
        finished.append("report written")

    async def main():
        orch._shadow_task = asyncio.create_task(shadows())
        return await orch._run_daily_with_shadows(object(), _args())

    assert asyncio.run(main()) == 0
    assert finished == ["report written"]
    assert "still running" in capsys.readouterr().out


def test_shadow_task_unfinished_at_exit_is_degraded(monkeypatch, capsys):
    _stub_daily(monkeypatch)
    monkeypatch.setattr(orch, "SHADOW_WAIT_S", 0.02)
    monkeypatch.setattr(orch, "SHADOW_PER_ENTRY_S", 0)
    monkeypatch.setattr(orch, "SHADOW_FINAL_GRACE_S", 0.02)

    async def main():
        orch._shadow_task = asyncio.create_task(asyncio.sleep(30))
        try:
            return await orch._run_daily_with_shadows(object(), _args())
        finally:
            orch._shadow_task.cancel()

    assert asyncio.run(main()) == 3
    assert "[degraded] shadows timeout" in capsys.readouterr().out


def test_shadow_task_exception_is_degraded_not_a_crash(monkeypatch, capsys):
    _stub_daily(monkeypatch)

    async def shadows():
        raise RuntimeError("roster broke")

    async def main():
        orch._shadow_task = asyncio.create_task(shadows())
        return await orch._run_daily_with_shadows(object(), _args())

    assert asyncio.run(main()) == 3
    assert "[degraded] shadows" in capsys.readouterr().out


def test_shadow_wait_is_sized_from_the_roster(monkeypatch):
    monkeypatch.setattr(orch, "_shadow_entry_count", 10)
    assert orch.shadow_wait_s() == orch.SHADOW_WAIT_S == 900
    monkeypatch.setattr(orch, "_shadow_entry_count", 40)
    assert orch.shadow_wait_s() == 40 * 45


def test_weekend_run_degraded_on_failed_step(monkeypatch, capsys):
    import marketmind.pipeline.scout as scout
    import marketmind.shadows.v3.runner as runner
    from marketmind.gateway import usage_tracker

    async def none(*a, **k):
        return None

    async def settled(config):
        return "0 settled"

    async def news(config):
        return []

    async def shadow_day(*a, **k):
        raise RuntimeError("shadows broke")

    async def watch(*a, **k):
        orch._step_failed("watchlist")

    monkeypatch.setattr(orch, "init_gateway", lambda *a: None)
    monkeypatch.setattr(orch, "preload_universe", none)
    monkeypatch.setattr(orch, "settle_ledger", settled)
    monkeypatch.setattr(orch, "_ledger_store", lambda config: None)
    monkeypatch.setattr(orch, "crypto_shadows", lambda: [])
    monkeypatch.setattr(orch, "crypto_registry", lambda: [])
    monkeypatch.setattr(orch, "run_discovery_step", none)
    monkeypatch.setattr(orch, "watchlist_step", watch)
    trend_calls = []

    async def trend(config, crypto_only=False):
        trend_calls.append(crypto_only)
    monkeypatch.setattr(orch, "trend_step", trend)
    alert_calls = []

    async def alerts(config, crypto_only=False):
        alert_calls.append(crypto_only)
    monkeypatch.setattr(orch, "alerts_step", alerts)
    monkeypatch.setattr(scout, "fetch_all_sources", news)
    monkeypatch.setattr(runner, "run_shadow_day", shadow_day)
    monkeypatch.setattr(usage_tracker, "append_log", lambda *a, **k: None)
    config = SimpleNamespace(deepseek_api_key="x", deepseek_base_url="x")
    assert asyncio.run(orch.run_weekend(config)) == 3
    assert "[degraded] shadows, watchlist" in capsys.readouterr().out
    assert trend_calls == [True]                 # weekend: crypto instruments only
    assert alert_calls == [True]                 # weekend alerts: crypto instruments only
