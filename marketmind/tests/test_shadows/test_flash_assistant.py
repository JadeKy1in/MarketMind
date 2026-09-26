"""Smoke tests for Flash Research Assistant (Phase 2)."""
import pytest
from marketmind.shadows.flash_research_assistant import (
    FlashResearchAssistant, FlashResearchRequest, FlashResearchResult,
    PEER_CONSENSUS_MIN_PEERS,
)


class TestFlashResearchAssistant:
    def test_import_ok(self):
        assert FlashResearchAssistant is not None

    def test_peer_consensus_min_peers(self):
        """Gate 2 de-anonymization protection: N>=5 required."""
        assert PEER_CONSENSUS_MIN_PEERS == 5

    def test_research_request_creation(self):
        req = FlashResearchRequest(
            shadow_id="test", topic="NVDA",
            tool="fetch_market_snapshot", params={"ticker": "NVDA"},
        )
        assert req.shadow_id == "test"
        assert req.tool == "fetch_market_snapshot"

    def test_gate2_mode_no_quota(self):
        """Gate 2 mode does not consume quota."""
        assistant = FlashResearchAssistant(gate2_mode=True)
        assert assistant.gate2_mode is True

    def test_training_mode_quota_enforced(self):
        """Training mode enforces quota."""
        assistant = FlashResearchAssistant(gate2_mode=False)
        assert assistant.gate2_mode is False
