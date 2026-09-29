"""Decision brief for the dashboard: card "confidence" is the stated probability, not the size."""
import json

from marketmind.pipeline import orchestration as orch
from marketmind.pipeline.decision import DecisionCard, DecisionOutput


def _card(**kw):
    base = dict(ticker="COIN", direction="long", position_size_pct=6.0, entry_low=191.2,
                entry_high=196.1, stop_loss=149.6, target_price=387.3, max_hold_days=30,
                reward_risk_ratio=4.2, thesis="t", risk_statement="r", red_team_note="n",
                cash_reframing="c", confidence=0.55)
    base.update(kw)
    return DecisionCard(**base)


def test_brief_card_confidence_is_not_position_size(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETMIND_CLAUDE_DIR", str(tmp_path / ".claude"))
    decision = DecisionOutput(decision_cards=[_card(), _card(ticker="SPY", confidence=None)])
    orch._save_decision_brief(None, None, None, None, None, decision)
    files = list((tmp_path / ".claude" / "briefs").glob("*.json"))
    assert len(files) == 1
    cards = json.loads(files[0].read_text(encoding="utf-8"))["decision_cards"]
    assert [c["confidence"] for c in cards] == [0.55, None]
    assert cards[0]["position_size_pct"] == 6.0
