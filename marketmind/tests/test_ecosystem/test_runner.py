"""Ecosystem runner: read-only ledger, atomic report file, read function, pipeline step."""
import asyncio
import json
from types import SimpleNamespace

from marketmind.ecosystem import read_report, run_ecosystem
from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.pipeline import orchestration as orch
from marketmind.shadows.v3 import roster


def _ledger(tmp_path, days=("2026-01-05", "2026-01-06", "2026-01-07")):
    store = LedgerStore(tmp_path / "ledger.db")
    for d in days:
        for r in roster.active(tmp_path):
            store.add(LedgerEntry(source_type="shadow", source_id=r.shadow_id, ticker="SPY",
                                  direction="long", hold_bars=1, confidence=0.55, position_usd=100.0,
                                  falsifier="x", meta={"run_date": d, "llm": "m"}),
                      created_at=f"{d}T15:00:00Z")
    (tmp_path / "trend").mkdir()
    for d in days:
        (tmp_path / "trend" / f"{d}.json").write_text(
            json.dumps({"full": {"SPY": {"state": "WATCH"}}}), encoding="utf-8")
    return store


def test_run_writes_report_and_read_function_returns_it(tmp_path):
    _ledger(tmp_path)
    doc = run_ecosystem(tmp_path, today="2026-01-07")
    path = tmp_path / "ecosystem" / "2026-01-07.json"
    assert path.exists() and not list((tmp_path / "ecosystem").glob(".*.tmp"))
    flag = doc["herding"]["flags"][0]
    assert (flag["group"], flag["verdict"]) == ("us_equity_index", "behavioural")
    assert doc["integrity"]["zombies"] == [] and doc["integrity"]["orphans"] == []
    assert doc["homogenisation"]["llm"]["flag"] is True
    assert doc["summary"].startswith("[ecosystem] herding: us_equity_index long 3d behavioural, "
                                     "N_eff n/a (0 eligible), dup clusters 0, zombies 0")
    assert read_report("2026-01-07", tmp_path)["summary"] == doc["summary"]
    assert read_report(root=tmp_path)["date"] == "2026-01-07"
    assert read_report("2026-01-08", tmp_path) is None
    assert doc["thresholds"]["HERDING_SHARE"] == 0.8


def test_dry_run_writes_nothing_and_never_touches_the_ledger(tmp_path):
    _ledger(tmp_path)
    before = (tmp_path / "ledger.db").stat().st_mtime_ns
    doc = run_ecosystem(tmp_path, today="2026-01-07", write=False)
    assert not (tmp_path / "ecosystem").exists()
    assert (tmp_path / "ledger.db").stat().st_mtime_ns == before
    assert doc["population"]["full_run_days"] == 3


def test_missing_ledger_gives_an_empty_report(tmp_path):
    doc = run_ecosystem(tmp_path, today="2026-01-07", write=False)
    assert not (tmp_path / "ledger.db").exists()             # not created
    assert doc["population"]["records"] == 0
    # every active roster shadow is silent, but there are no run days to count
    assert doc["integrity"]["zombies"] == []


def test_read_report_skips_a_corrupt_latest_file(tmp_path):
    folder = tmp_path / "ecosystem"
    folder.mkdir()
    (folder / "2026-01-06.json").write_text('{"date": "2026-01-06"}', encoding="utf-8")
    (folder / "2026-01-07.json").write_text("{broken", encoding="utf-8")
    assert read_report(root=tmp_path)["date"] == "2026-01-06"
    assert read_report(root=tmp_path / "nowhere") is None


def test_pipeline_step_prints_summary_and_records_failure(tmp_path, monkeypatch, capsys):
    orch._reset_step_failures()
    _ledger(tmp_path)
    monkeypatch.setattr("marketmind.ecosystem.runner.ny_today", lambda: "2026-01-07")
    asyncio.run(orch.ecosystem_step(SimpleNamespace(data_dir=str(tmp_path))))
    assert "[ecosystem] herding: us_equity_index long 3d" in capsys.readouterr().out
    assert orch._step_failures == []

    def boom(*a, **k):
        raise RuntimeError("broken")
    monkeypatch.setattr("marketmind.ecosystem.runner.run_ecosystem", boom)
    asyncio.run(orch.ecosystem_step(SimpleNamespace(data_dir=str(tmp_path))))
    assert "[ecosystem] failed" in capsys.readouterr().out
    assert orch._step_failures == ["ecosystem"]
    orch._reset_step_failures()


def test_daily_run_calls_ecosystem_after_alerts_before_report():
    import inspect
    src = inspect.getsource(orch._run_daily_with_shadows)
    assert src.index("await alerts_step(config)") < src.index("await ecosystem_step(config)") \
        < src.index("await daily_report_step(config)")
