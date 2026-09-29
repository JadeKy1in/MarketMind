"""The weekly audit runs at most once per ISO week; the daily path does not import
the interactive orchestration (red-team 2026-09-29)."""
import asyncio
import subprocess
import sys
from datetime import date
from pathlib import Path

from marketmind.pipeline import orchestration as orch


def _stub_audit(monkeypatch, calls):
    import marketmind.pipeline.methodology_evolution as me
    import marketmind.pipeline.pipeline_metrics as pm
    import marketmind.pipeline.weekly_tactical_audit as wta

    async def run_weekly_audit():
        calls.append("audit")
        return None                                  # finds nothing

    async def attribution(metrics):
        calls.append("attribution")
        return None

    monkeypatch.setattr(wta, "run_weekly_audit", run_weekly_audit)
    monkeypatch.setattr(me, "run_cross_stage_attribution", attribution)
    monkeypatch.setattr(pm, "load_recent_metrics", lambda days=30: [])
    # the legacy 7-day file check must not short-circuit the test
    monkeypatch.setattr(Path, "exists", lambda self, _orig=Path.exists: (
        False if self.name == "weekly_audit_latest.json" else _orig(self)))


def test_audit_that_finds_nothing_still_runs_once_per_week(monkeypatch, tmp_path):
    calls = []
    _stub_audit(monkeypatch, calls)
    asyncio.run(orch._maybe_run_weekly_audit(tmp_path))
    asyncio.run(orch._maybe_run_weekly_audit(tmp_path))
    assert calls == ["audit", "attribution"]
    markers = list((tmp_path / "weekly_audit").iterdir())
    assert len(markers) == 1 and markers[0].name.endswith(".done")


def test_marker_is_per_iso_week(tmp_path):
    assert orch._weekly_audit_marker(tmp_path, date(2026, 9, 28)).name == "2026-W40.done"
    assert orch._weekly_audit_marker(tmp_path, date(2027, 1, 1)).name == "2026-W53.done"


def test_audit_failure_still_writes_marker(monkeypatch, tmp_path):
    import marketmind.pipeline.weekly_tactical_audit as wta
    calls = []
    _stub_audit(monkeypatch, calls)

    async def boom():
        raise RuntimeError("flash down")

    monkeypatch.setattr(wta, "run_weekly_audit", boom)
    asyncio.run(orch._maybe_run_weekly_audit(tmp_path))
    assert orch._weekly_audit_marker(tmp_path).exists()


def test_daily_path_does_not_import_interactive_orchestration():
    root = Path(orch.__file__).resolve().parents[2]
    code = ("import sys; import marketmind.app, marketmind.pipeline.orchestration; "
            "print('marketmind.pipeline.interactive_orchestration' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True,
                         text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"
