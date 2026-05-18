"""Tests for Ecosystem Auditor — blind-spot detection mechanism (replaces Catfish).

ECOSYSTEM AUDITOR — NOT A SHADOW. Reads shadow output, does not produce votes.
Detection categories: direction concentration, asset class neglect,
methodology convergence, uncovered tickers.
"""
import pytest

from marketmind.shadows.ecosystem_auditor import EcosystemAuditor, EcosystemAlert
from marketmind.shadows.catfish_agent import (
    CatfishAgent, CATFISH_SYSTEM_PROMPT, create_catfish_agent
)
from marketmind.shadows.shadow_agent import ShadowVote


def make_vote(shadow_id, ticker, direction, confidence=0.5):
    return ShadowVote(
        shadow_id=shadow_id, shadow_type="expert",
        date="2026-05-18", ticker=ticker, direction=direction,
        confidence=confidence, thesis="test", risk_note="test",
    )


# ── EcosystemAuditor tests ─────────────────────────────────────────────

class TestEcosystemAuditor:
    """EcosystemAuditor is the replacement for Catfish — pure Python blind-spot scan."""

    def test_empty_votes_produces_no_alerts(self):
        auditor = EcosystemAuditor()
        alerts = auditor.run_audit([])
        assert len(alerts) == 0

    def test_direction_concentration_alert(self):
        auditor = EcosystemAuditor()
        # 9 long, 1 short = 90% long -> triggers direction concentration
        votes = [
            make_vote(f"s{i}", "SPY", "long") for i in range(9)
        ] + [make_vote("s9", "QQQ", "short")]
        alerts = auditor.run_audit(votes)
        direction_alerts = [a for a in alerts if a.category == "direction_concentration"]
        assert len(direction_alerts) >= 1
        assert "90%" in direction_alerts[0].title or "90%" in direction_alerts[0].detail

    def test_below_threshold_no_direction_alert(self):
        auditor = EcosystemAuditor()
        votes = [
            make_vote(f"s{i}", f"TICKER_{i}", "long") for i in range(5)
        ] + [
            make_vote(f"s{i+5}", f"TICKER_{i+5}", "short") for i in range(5)
        ]
        alerts = auditor.run_audit(votes)
        direction_alerts = [a for a in alerts if a.category == "direction_concentration"]
        assert len(direction_alerts) == 0

    def test_asset_class_neglect_alert(self):
        auditor = EcosystemAuditor()
        # Only vote on tech stocks, neglect everything else
        votes = [
            make_vote(f"s{i}", "QQQ", "long") for i in range(10)
        ]
        alerts = auditor.run_audit(votes)
        neglect_alerts = [a for a in alerts if a.category == "asset_class_neglect"]
        assert len(neglect_alerts) >= 1

    def test_ticker_convergence_alert(self):
        auditor = EcosystemAuditor()
        # All votes on same 3 tickers
        votes = []
        for i in range(9):
            votes.append(make_vote(f"s{i}", "SPY", "long"))
        for i in range(5):
            votes.append(make_vote(f"s{i+9}", "QQQ", "short"))
        for i in range(3):
            votes.append(make_vote(f"s{i+14}", "AAPL", "long"))
        alerts = auditor.run_audit(votes)
        convergence_alerts = [a for a in alerts if a.category == "methodology_convergence"]
        assert len(convergence_alerts) >= 1

    def test_uncovered_tickers_alert(self):
        auditor = EcosystemAuditor()
        # Only vote on a few tickers, miss major market-cap names
        votes = [
            make_vote("s1", "SPY", "long"),
            make_vote("s2", "QQQ", "short"),
        ]
        alerts = auditor.run_audit(votes)
        uncovered = [a for a in alerts if a.category == "uncovered_tickers"]
        assert len(uncovered) >= 1

    def test_max_5_alerts_output(self):
        """Ecosystem auditor output <= 5 blind spot alerts."""
        auditor = EcosystemAuditor()
        # Create conditions for all alert types
        votes = [
            make_vote(f"s{i}", "SPY", "long") for i in range(15)
        ]
        alerts = auditor.run_audit(votes)
        assert len(alerts) <= 5

    def test_alert_structure(self):
        auditor = EcosystemAuditor()
        votes = [
            make_vote(f"s{i}", "SPY", "long") for i in range(10)
        ]
        alerts = auditor.run_audit(votes)
        for alert in alerts:
            assert alert.alert_id
            assert alert.category in (
                "direction_concentration", "asset_class_neglect",
                "methodology_convergence", "uncovered_tickers",
            )
            assert alert.severity in ("info", "warning", "critical")
            assert alert.title
            assert alert.detail


# ── Backward-compat CatfishAgent tests ──────────────────────────────────

class TestCatfishBackwardCompat:
    """CatfishAgent is deprecated but must maintain backward compat for existing callers."""

    def test_catfish_agent_is_deprecated(self):
        with pytest.warns(DeprecationWarning):
            agent = CatfishAgent()
        assert agent._auditor is not None

    def test_create_catfish_agent_deprecated(self):
        with pytest.warns(DeprecationWarning):
            agent = create_catfish_agent()
        assert isinstance(agent, CatfishAgent)

    def test_catfish_no_longer_produces_votes(self):
        import asyncio
        agent = CatfishAgent()
        output = asyncio.run(agent._analyze([], {}))
        assert len(output.votes) == 0
        assert "CATFISH_DEPRECATED" in str(output.insights)

    def test_catfish_run_audit_delegates(self):
        agent = CatfishAgent()
        votes = [
            make_vote(f"s{i}", "SPY", "long") for i in range(10)
        ]
        alerts = agent.run_audit(votes)
        assert len(alerts) > 0
        for alert in alerts:
            assert isinstance(alert, EcosystemAlert)

    def test_catfish_check_consensus_backward_compat(self):
        agent = CatfishAgent()
        votes = [
            make_vote("s1", "SPY", "long"),
            make_vote("s2", "SPY", "long"),
            make_vote("s3", "SPY", "long"),
            make_vote("s4", "SPY", "long"),
        ]
        triggered, pct, direction = agent.check_consensus(votes, "SPY")
        assert triggered is True
        assert pct == 1.0
        assert direction == "long"

    def test_catfish_system_prompt_deprecation_notice(self):
        assert "DEPRECATED" in CATFISH_SYSTEM_PROMPT
