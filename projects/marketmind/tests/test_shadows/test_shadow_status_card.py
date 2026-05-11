"""Tests for ShadowStatusCard — individual shadow detail widget."""
import pytest
from unittest.mock import MagicMock, patch


# ── Mock customtkinter (no display in CI) ─────────────────────────────────

@pytest.fixture
def mock_ctk():
    """Mock all customtkinter classes used by ShadowStatusCard."""
    with patch("customtkinter.CTkFrame.__init__", return_value=None), \
         patch("customtkinter.CTkFrame.pack", return_value=None), \
         patch("customtkinter.CTkFrame.grid", return_value=None), \
         patch("customtkinter.CTkFrame.configure", return_value=None), \
         patch("customtkinter.CTkFrame.destroy", return_value=None), \
         patch("customtkinter.CTkFrame.winfo_children", return_value=[]), \
         patch("customtkinter.CTkLabel.__init__", return_value=None), \
         patch("customtkinter.CTkLabel.configure", return_value=None), \
         patch("customtkinter.CTkLabel.pack", return_value=None), \
         patch("customtkinter.CTkLabel.grid", return_value=None), \
         patch("customtkinter.CTkLabel.bind", return_value=None), \
         patch("customtkinter.CTkButton.__init__", return_value=None), \
         patch("customtkinter.CTkButton.configure", return_value=None), \
         patch("customtkinter.CTkButton.pack", return_value=None), \
         patch("customtkinter.CTkButton.grid", return_value=None), \
         patch("customtkinter.CTkFont", return_value=("Arial", 12)), \
         patch("customtkinter.StringVar", return_value=MagicMock()):
        yield


@pytest.fixture
def sample_shadow_data():
    """Sample shadow detail data for status card display."""
    return {
        "shadow_id": "expert:gold:agent_00",
        "display_name": "Gold Bug",
        "shadow_type": "expert",
        "tier": "elite",
        "rank": 1,
        "total_shadows": 15,
        "percentile": 92.0,
        "composite_score": 0.92,
        "deflated_score": 0.77,
        "mppm": 0.88,
        "calmar": 1.42,
        "omega": 4.2,
        "win_rate": 0.61,
        "virtual_capital": 54230.0,
        "capital_change_90d": 8.5,
        "max_drawdown": -12.4,
        "positions": ["GLD (long)", "SLV (long)"],
        "integrity_score": 97,
    }


# ── Tests ─────────────────────────────────────────────────────────────────

def test_status_card_displays_data(mock_ctk, sample_shadow_data):
    """Status card should accept and store shadow data without errors."""
    from projects.marketmind.ui.shadow_status_card import ShadowStatusCard

    card = ShadowStatusCard(MagicMock())
    card.display_shadow(sample_shadow_data)

    assert card._shadow_data is not None
    assert card._shadow_data["display_name"] == "Gold Bug"
    assert card._shadow_data["tier"] == "elite"
    assert card._shadow_data["composite_score"] == 0.92


def test_status_card_clear_clears_all_fields(mock_ctk, sample_shadow_data):
    """Clear should reset shadow data to None."""
    from projects.marketmind.ui.shadow_status_card import ShadowStatusCard

    card = ShadowStatusCard(MagicMock())
    card.display_shadow(sample_shadow_data)
    assert card._shadow_data is not None

    card.clear()
    assert card._shadow_data is None


def test_status_card_tier_color_mapping(mock_ctk):
    """Tier to color mapping should return correct hex codes."""
    from projects.marketmind.ui.shadow_status_card import ShadowStatusCard

    card = ShadowStatusCard(MagicMock())

    colors = card._get_tier_color
    assert colors("elite") == "#DAA520"
    assert colors("excellent") == "#2E8B57"
    assert colors("normal") == "#808080"
    assert colors("watch") == "#FF8C00"
    assert colors("endangered") == "#DC143C"


def test_status_card_handles_missing_keys(mock_ctk):
    """Card should not crash when optional keys are missing from shadow_data."""
    from projects.marketmind.ui.shadow_status_card import ShadowStatusCard

    card = ShadowStatusCard(MagicMock())
    minimal_data = {
        "shadow_id": "expert:crypto:agent_01",
        "display_name": "Crypto Oracle",
        "tier": "excellent",
    }
    # Should not raise any exception
    card.display_shadow(minimal_data)
    assert card._shadow_data is not None
    assert card._shadow_data["display_name"] == "Crypto Oracle"
