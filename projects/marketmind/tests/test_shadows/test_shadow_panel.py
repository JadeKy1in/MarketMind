"""Tests for ShadowPanel — ranking dashboard UI widget."""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_bridge():
    """Mock AsyncBridge for async loading."""
    bridge = MagicMock()
    bridge.submit = MagicMock()
    bridge.poll = MagicMock()
    bridge.pending_count = 0
    return bridge


@pytest.fixture
def sample_rankings():
    """15 shadows ranked by composite score."""
    domains = ["Gold Bug", "Crypto Oracle", "Energy Hawk", "Bond Whisperer",
               "Volatility Seer", "Emerging Scout", "Tech Visionary",
               "Financials Sage", "Healthcare Analyst", "Consumer Tracker",
               "Metals Prospector", "Agriculture Watcher", "Real Estate Eye",
               "FX Strategist", "Rates Maven"]
    tiers = ["elite", "excellent", "excellent", "excellent", "normal",
             "normal", "normal", "normal", "normal", "watch",
             "watch", "watch", "watch", "endangered", "endangered"]
    rankings = []
    for i, (domain, tier) in enumerate(zip(domains, tiers)):
        score = 0.95 - (i * 0.04)
        trend = 3 - i if i <= 3 else (-i * 0.5) if i <= 8 else (-2 - i * 0.3)
        rankings.append({
            "rank": i + 1,
            "shadow_id": f"expert:{domain.lower().replace(' ', '_')}:agent_{i:02d}",
            "display_name": domain,
            "tier": tier,
            "composite_score": round(score, 2),
            "deflated_score": round(score * 0.85, 2),
            "percentile_rank": round(1.0 - (i / 15), 3),
            "trend": round(trend, 1),
        })
    return rankings


# ── Mock CTk helpers ─────────────────────────────────────────────────────

def _start_ctk_mocks():
    """Start all necessary CTk patches so widgets can be constructed in tests."""
    p = []
    p += [patch("customtkinter.CTkFrame.__init__", return_value=None)]
    p += [patch("customtkinter.CTkFrame.pack", return_value=None)]
    p += [patch("customtkinter.CTkFrame.grid", return_value=None)]
    p += [patch("customtkinter.CTkFrame.destroy", return_value=None)]
    p += [patch("customtkinter.CTkFrame.configure", return_value=None)]
    p += [patch("customtkinter.CTkFrame.bind", return_value=None)]
    p += [patch("customtkinter.CTkFrame.winfo_children", return_value=[])]
    p += [patch("customtkinter.CTkLabel.__init__", return_value=None)]
    p += [patch("customtkinter.CTkLabel.pack", return_value=None)]
    p += [patch("customtkinter.CTkLabel.grid", return_value=None)]
    p += [patch("customtkinter.CTkLabel.configure", return_value=None)]
    p += [patch("customtkinter.CTkLabel.bind", return_value=None)]
    p += [patch("customtkinter.CTkScrollableFrame.__init__", return_value=None)]
    p += [patch("customtkinter.CTkScrollableFrame.pack", return_value=None)]
    p += [patch("customtkinter.CTkScrollableFrame.grid", return_value=None)]
    p += [patch("customtkinter.CTkScrollableFrame.configure", return_value=None)]
    p += [patch("customtkinter.CTkScrollableFrame.destroy", return_value=None)]
    p += [patch("customtkinter.CTkScrollableFrame.winfo_children", return_value=[])]
    p += [patch("customtkinter.CTkFont", return_value=MagicMock())]
    for x in p:
        x.start()
    return p


def _stop_mocks(patches):
    for x in reversed(patches):
        x.stop()


# ── Tests ─────────────────────────────────────────────────────────────────

def test_shadow_panel_renders_rankings(mock_bridge, sample_rankings):
    """Panel should create row widgets for all 15 shadows without error."""
    mocks = _start_ctk_mocks()
    try:
        from projects.marketmind.ui.shadow_panel import ShadowPanel
        panel = ShadowPanel(MagicMock(), mock_bridge)
        panel.load_rankings(sample_rankings)

        assert panel._rankings is not None
        assert len(panel._rankings) == 15
    finally:
        _stop_mocks(mocks)


def test_shadow_panel_sort_order(mock_bridge, sample_rankings):
    """Rank 1 (highest composite) should appear first in the list."""
    mocks = _start_ctk_mocks()
    try:
        from projects.marketmind.ui.shadow_panel import ShadowPanel
        panel = ShadowPanel(MagicMock(), mock_bridge)
        panel.load_rankings(sample_rankings)

        assert panel._rankings[0]["rank"] == 1
        assert panel._rankings[0]["display_name"] == "Gold Bug"
        assert panel._rankings[0]["tier"] == "elite"
    finally:
        _stop_mocks(mocks)


def test_shadow_panel_click_callback(mock_bridge, sample_rankings):
    """Clicking a shadow row should fire the registered callback with shadow_id."""
    mocks = _start_ctk_mocks()
    try:
        from projects.marketmind.ui.shadow_panel import ShadowPanel

        callback_calls = []

        def on_click(shadow_id):
            callback_calls.append(shadow_id)

        panel = ShadowPanel(MagicMock(), mock_bridge)
        panel.load_rankings(sample_rankings)
        panel.set_on_click_callback(on_click)

        # Verify callback is stored
        assert panel._on_shadow_click is not None
        assert panel._on_shadow_click is on_click

        # Simulate a shadow click via the internal handler
        panel._handle_row_click("expert:gold_bug:agent_00")
        assert len(callback_calls) == 1
        assert "agent_00" in callback_calls[0]
    finally:
        _stop_mocks(mocks)


def test_shadow_panel_clear_removes_rankings(mock_bridge, sample_rankings):
    """Clearing the panel should remove all stored rankings."""
    mocks = _start_ctk_mocks()
    try:
        from projects.marketmind.ui.shadow_panel import ShadowPanel
        panel = ShadowPanel(MagicMock(), mock_bridge)
        panel.load_rankings(sample_rankings)
        assert len(panel._rankings) == 15

        panel.clear()
        assert panel._rankings == []
    finally:
        _stop_mocks(mocks)
