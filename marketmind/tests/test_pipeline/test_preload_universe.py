"""The tradable universe's blocking first download runs off the event loop in every mode."""
import asyncio
import inspect
import threading

from marketmind.pipeline import orchestration
from marketmind.universe import classifier


def test_preload_runs_the_load_in_a_worker_thread(monkeypatch):
    seen = []
    monkeypatch.setattr(classifier, "load_equity_universe",
                        lambda: seen.append(threading.current_thread()) or None)
    classifier.reset_equity_universe()
    asyncio.run(orchestration.preload_universe())
    assert len(seen) == 1 and seen[0] is not threading.main_thread()


def test_every_entry_mode_preloads():
    for fn in (orchestration.run_daily, orchestration.run_weekend,
               orchestration.run_evidence_only, orchestration.run_shadows_only):
        assert "await preload_universe()" in inspect.getsource(fn), fn.__name__
