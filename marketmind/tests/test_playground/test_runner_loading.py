"""run_single_agent loads adapter.py by path: a dataclass under postponed annotations
needs the module in sys.modules (onchain_valuation failed every run until 2026-10-02)."""
import pytest

from marketmind.playground import playground_runner as pr
from marketmind.playground.agent_manifest import load_manifest

ADAPTER = '''from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Band:
    entry: float


async def analyze(context, *, mock=False):
    return {"directional_calls": [], "band": Band(1.0).entry}
'''


@pytest.mark.asyncio
async def test_dataclass_adapter_loads(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "_record_decision", lambda decision, d: None)   # no audit-log write
    (tmp_path / "adapter.py").write_text(ADAPTER, encoding="utf-8")

    class M:
        agent_id, version, public_data_sources = "dc_probe", "1", []
    decision = await pr.run_single_agent(M(), {}, tmp_path, mock=True)
    assert decision.output["band"] == 1.0


@pytest.mark.asyncio
async def test_onchain_valuation_adapter_loads(monkeypatch):
    monkeypatch.setattr(pr, "_record_decision", lambda decision, d: None)
    agent_dir = pr.DEFAULT_PLAYGROUND_DIR / "agents" / "onchain_valuation"
    decision = await pr.run_single_agent(load_manifest(agent_dir), {}, agent_dir, mock=True)
    assert decision.directional_calls == []
