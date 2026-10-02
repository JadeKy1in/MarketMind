"""Resume after an interrupted attempt (docs/AUTOMATION.md, 2026-10-02): a retry of
the same day skips the steps an earlier attempt finished, and never a failed one."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from marketmind.pipeline import orchestration as orch
from marketmind.run_steps import KEEP_DAYS, RunSteps

KEY = "2026-10-02-weekday"
POST_STEPS = (("inspect_holdings_step", "holdings"), ("promotion_step", "promotion"),
              ("trend_step", "trend"), ("alerts_step", "alerts"), ("ecosystem_step", "ecosystem"),
              ("app_charts_step", "app charts"), ("daily_report_step", "daily report"))


@pytest.fixture(autouse=True)
def _clean_globals(monkeypatch):
    monkeypatch.setattr(orch, "_shadow_task", None)
    monkeypatch.setattr(orch, "_evidence_task", None)
    monkeypatch.setattr(orch, "_playground_task", None)
    monkeypatch.setattr(orch, "_shadow_entry_count", None)
    orch._reset_step_failures()
    yield
    orch._reset_step_failures()


class Daily:
    """Every step of the daily run stubbed; records calls, can fail chosen steps."""

    def __init__(self, monkeypatch, fail=(), raise_in=()):
        self.calls, self.fail, self.raise_in = [], set(fail), set(raise_in)
        self.watch_items_seen = None
        m = monkeypatch
        m.setattr(orch, "init_gateway", lambda *a: None)
        m.setattr(orch, "preload_universe", self._noop("preload"))
        m.setattr(orch, "_report_stage_progress", lambda *a, **k: None)
        m.setattr(orch, "_maybe_run_weekly_audit", self._noop("weekly audit"))
        m.setattr(orch, "settle_ledger", self._step("settle", "ledger settle"))
        m.setattr(orch, "_do_news_collection", self._news)
        m.setattr(orch, "run_discovery_step", self._noop("discovery"))
        m.setattr(orch, "_main_chain", self._main)
        m.setattr(orch, "watch_items", lambda decision, discovery: [{"ticker": "SPY", "direction": "long"}])
        m.setattr(orch, "_record_missed_path", self._sync_step("missed_path", "missed_path"))
        m.setattr(orch, "watchlist_step", self._watchlist)
        m.setattr(orch, "run_v3_shadows", self._shadows)
        m.setattr(orch, "run_playground", self._playground)
        m.setattr(orch, "run_evidence", self._evidence)
        for fn, name in POST_STEPS:
            m.setattr(orch, fn, self._step(name, name))
        import marketmind.reports.daily as daily
        m.setattr(daily, "save_headlines", lambda items: self.calls.append("headlines"))
        from marketmind.gateway import usage_tracker
        m.setattr(usage_tracker, "append_log", lambda *a, **k: None)

    def _noop(self, name):
        async def f(*a, **k):
            self.calls.append(name)
        return f

    def _step(self, name, label):
        async def f(*a, **k):
            self.calls.append(name)
            if name in self.raise_in:
                raise RuntimeError(f"{name} crashed")
            if name in self.fail:
                orch._step_failed(label)
            return "done"
        return f

    def _sync_step(self, name, label):
        def f(*a, **k):
            self.calls.append(name)
            if name in self.fail:
                orch._step_failed(label)
        return f

    async def _news(self, config, tracker, mock=False):
        self.calls.append("news")
        return ["item"]

    async def _main(self, config, tracker, news, discovery_task, mock):
        self.calls.append("main")
        if discovery_task is not None:
            await discovery_task
        if "main" in self.raise_in:
            raise RuntimeError("killed mid-pipeline")
        if "discovery" in self.fail:
            orch._step_failed("discovery")
        if "ledger record" in self.fail:
            orch._step_failed("ledger record")
        return SimpleNamespace(watch_cards=[]), None

    async def _watchlist(self, config, decision=None, discovery=None, crypto_only=False, items=None):
        self.calls.append("watchlist")
        self.watch_items_seen = items
        if "watchlist" in self.fail:
            orch._step_failed("watchlist")

    async def _shadows(self, config, news, limit=None):
        self.calls.append("shadows")
        if "shadows" in self.raise_in:
            raise RuntimeError("roster broke")
        status = "missed" if "shadows" in self.fail else "submitted"
        return SimpleNamespace(results=[SimpleNamespace(status=status)])

    async def _playground(self, config, news):
        self.calls.append("playground")
        if "playground" in self.fail:
            orch._step_failed("playground")
            return None
        return {"recorded": {}}

    async def _evidence(self, config, news):
        self.calls.append("evidence")
        return SimpleNamespace(status="llm_failed" if "evidence" in self.fail else "ok")


def _config(tmp_path):
    return SimpleNamespace(deepseek_api_key="x", deepseek_base_url="x", data_dir=str(tmp_path),
                           shadow=SimpleNamespace(shadows_enabled=True))


def _args(mock=False):
    return SimpleNamespace(no_shadows=False, shadows=None, mock=mock, verbose=False)


def _attempt(monkeypatch, tmp_path, **kw):
    steps = tmp_path / "steps.json"
    monkeypatch.setenv("MARKETMIND_RUN_KEY", KEY)
    monkeypatch.setenv("MARKETMIND_STEPS_FILE", str(steps))
    d = Daily(monkeypatch, **kw)
    orch._reset_step_failures()
    code = asyncio.run(orch._run_daily_with_shadows(_config(tmp_path), _args()))
    return d, code


def _marked(tmp_path) -> dict:
    return json.loads((tmp_path / "steps.json").read_text(encoding="utf-8")).get(KEY, {})


ALL_STEPS = {"settle", "main", "shadows", "playground", "evidence", "missed_path", "watchlist",
             "holdings", "promotion", "trend", "alerts", "ecosystem", "app charts", "daily report"}


def test_retry_skips_every_step_the_first_attempt_finished(monkeypatch, tmp_path, capsys):
    first, code = _attempt(monkeypatch, tmp_path)
    assert code == 0 and set(_marked(tmp_path)) == ALL_STEPS
    assert {"news", "main", "shadows", "daily report"} <= set(first.calls)

    second, code = _attempt(monkeypatch, tmp_path)
    assert code == 0
    # nothing left to do: no news fetch, no LLM step, no second report push
    assert set(second.calls) <= {"preload", "weekly audit"}
    out = capsys.readouterr().out
    for step in ("main", "shadows", "settle", "daily report"):
        assert f"[resume] skipped {step}" in out


def test_failed_steps_are_not_marked_and_rerun(monkeypatch, tmp_path, capsys):
    _, code = _attempt(monkeypatch, tmp_path,
                       fail={"settle", "holdings", "promotion", "missed_path", "evidence",
                             "playground", "shadows"})
    assert code == orch.DEGRADED_EXIT
    marked = set(_marked(tmp_path))
    assert not marked & {"settle", "holdings", "promotion", "missed_path", "evidence",
                         "playground", "shadows"}
    assert {"main", "watchlist", "trend", "daily report"} <= marked

    again, _ = _attempt(monkeypatch, tmp_path)
    assert {"settle", "news", "holdings", "promotion", "missed_path", "evidence", "playground",
            "shadows"} <= set(again.calls)
    assert not {"main", "watchlist", "trend", "daily report", "headlines"} & set(again.calls)


def test_crashed_background_task_is_not_marked(monkeypatch, tmp_path):
    _, code = _attempt(monkeypatch, tmp_path, raise_in={"shadows"})
    assert code == orch.DEGRADED_EXIT and "shadows" not in _marked(tmp_path)


def test_interrupted_main_pipeline_leaves_no_marker(monkeypatch, tmp_path):
    with pytest.raises(RuntimeError):
        _attempt(monkeypatch, tmp_path, raise_in={"main"})
    marked = set(_marked(tmp_path)) if (tmp_path / "steps.json").exists() else set()
    assert "main" not in marked and "daily report" not in marked
    again, _ = _attempt(monkeypatch, tmp_path)
    assert "main" in again.calls and "news" in again.calls


def test_unrecorded_ledger_calls_rerun_the_main_pipeline(monkeypatch, tmp_path):
    _attempt(monkeypatch, tmp_path, fail={"ledger record"})
    assert "main" not in _marked(tmp_path)


def test_watch_items_are_kept_for_a_resumed_watchlist(monkeypatch, tmp_path):
    _attempt(monkeypatch, tmp_path, fail={"watchlist"})
    assert "watchlist" not in _marked(tmp_path)
    again, _ = _attempt(monkeypatch, tmp_path)
    assert "main" not in again.calls and "watchlist" in again.calls
    assert again.watch_items_seen == [{"ticker": "SPY", "direction": "long"}]


def test_carried_discovery_failure_still_degrades_the_resumed_run(monkeypatch, tmp_path, capsys):
    # attempt 1: discovery failed inside main, then the process died before the report
    with pytest.raises(RuntimeError):
        _attempt(monkeypatch, tmp_path, fail={"discovery"}, raise_in={"daily report"})
    assert _marked(tmp_path)["main"]["failed"] == ["discovery"]
    capsys.readouterr()
    again, code = _attempt(monkeypatch, tmp_path)
    assert "main" not in again.calls and "daily report" in again.calls
    assert code == orch.DEGRADED_EXIT
    assert "[degraded] discovery" in capsys.readouterr().out


def test_without_scheduler_env_nothing_is_skipped_or_written(monkeypatch, tmp_path):
    d = Daily(monkeypatch)
    assert asyncio.run(orch._run_daily_with_shadows(_config(tmp_path), _args())) == 0
    assert not (tmp_path / "steps.json").exists() and "main" in d.calls


def test_weekend_retry_skips_finished_steps(monkeypatch, tmp_path, capsys):
    import marketmind.pipeline.scout as scout
    import marketmind.shadows.v3.runner as runner
    from marketmind.gateway import usage_tracker
    calls = []

    async def rec(name, *a, **k):
        calls.append(name)

    async def settled(config):
        calls.append("settle")
        return "0 settled"

    async def news(config):
        calls.append("news")
        return []

    async def shadow_day(*a, **k):
        calls.append("shadows")
        return SimpleNamespace(results=[], summary=lambda: "ok")

    monkeypatch.setattr(orch, "init_gateway", lambda *a: None)
    monkeypatch.setattr(orch, "preload_universe", lambda: rec("preload"))
    monkeypatch.setattr(orch, "settle_ledger", settled)
    monkeypatch.setattr(orch, "_ledger_store", lambda config: None)
    monkeypatch.setattr(orch, "crypto_shadows", lambda: [])
    monkeypatch.setattr(orch, "crypto_registry", lambda: [])
    monkeypatch.setattr(orch, "run_discovery_step", lambda *a, **k: rec("discovery"))
    monkeypatch.setattr(orch, "watchlist_step", lambda *a, **k: rec("watchlist"))
    monkeypatch.setattr(orch, "trend_step", lambda *a, **k: rec("trend"))
    monkeypatch.setattr(orch, "alerts_step", lambda *a, **k: rec("alerts"))
    monkeypatch.setattr(orch, "app_charts_step", lambda *a, **k: rec("app charts"))
    monkeypatch.setattr(scout, "fetch_all_sources", news)
    monkeypatch.setattr(runner, "run_shadow_day", shadow_day)
    monkeypatch.setattr(usage_tracker, "append_log", lambda *a, **k: None)
    monkeypatch.setenv("MARKETMIND_RUN_KEY", "2026-10-03-weekend")
    monkeypatch.setenv("MARKETMIND_STEPS_FILE", str(tmp_path / "steps.json"))
    config = SimpleNamespace(deepseek_api_key="x", deepseek_base_url="x")

    assert asyncio.run(orch.run_weekend(config)) == 0
    assert {"settle", "news", "shadows", "discovery", "watchlist", "trend", "alerts",
            "app charts"} <= set(calls)
    calls.clear()
    assert asyncio.run(orch.run_weekend(config)) == 0
    assert calls == ["preload"]
    assert "[resume] skipped shadows" in capsys.readouterr().out


# ── marketmind/run_steps.py ─────────────────────────────────────────────────

def test_markers_are_per_day_key(tmp_path):
    path = tmp_path / "steps.json"
    today = RunSteps(path, "2026-10-02-weekday")
    today.mark("main", watch_items=[])
    assert today.done("main")["watch_items"] == []
    assert RunSteps(path, "2026-10-05-weekday").done("main") is None      # tomorrow: fresh
    today.reset()
    assert today.done("main") is None


def test_disabled_markers_do_nothing(tmp_path):
    steps = RunSteps(None, KEY)
    steps.mark("main")
    assert steps.done("main") is None and not steps.enabled
    assert not RunSteps(tmp_path / "s.json", None).enabled


def test_unreadable_marker_file_skips_nothing(tmp_path):
    path = tmp_path / "steps.json"
    path.write_text("{not json", encoding="utf-8")
    steps = RunSteps(path, KEY)
    assert steps.done("main") is None
    steps.mark("main")                                     # rewritten atomically
    assert steps.done("main") is not None
    assert not list(tmp_path.glob("*.tmp"))


def test_marker_file_keeps_recent_days_only(tmp_path):
    path = tmp_path / "steps.json"
    for day in range(1, KEEP_DAYS + 5):
        RunSteps(path, f"2026-09-{day:02d}-weekday").mark("main")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data) == KEEP_DAYS and f"2026-09-{KEEP_DAYS + 4:02d}-weekday" in data
