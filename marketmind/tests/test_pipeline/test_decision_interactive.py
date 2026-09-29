"""Interactive decision display: position_size_pct is already a percent number."""
from types import SimpleNamespace

import pytest

from marketmind.pipeline import decision_interactive as di
from marketmind.pipeline.decision import DecisionCard, DecisionOutput


@pytest.mark.asyncio
async def test_card_size_prints_as_percent_number(monkeypatch, capsys):
    card = DecisionCard(ticker="SPY", direction="long", position_size_pct=10.0, entry_low=500.0,
                        entry_high=505.0, stop_loss=480.0, target_price=560.0, max_hold_days=20,
                        reward_risk_ratio=2.5, thesis="", risk_statement="", red_team_note="",
                        cash_reframing="")

    async def fake_generate(**_):
        return DecisionOutput(decision_cards=[card])

    async def answer(_):
        return "ok"

    monkeypatch.setattr(di, "generate_decision", fake_generate)
    ctx = SimpleNamespace(l1_result=None, l2_result=None, l3_result=None, red_team_report=None,
                          resonance=None, selected_strategy="", decision=None)
    assert await di.run_decision_interactive(ctx, answer) is True
    out = capsys.readouterr().out
    assert "10.0%" in out and "1000%" not in out
