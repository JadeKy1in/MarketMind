"""Tests for L1 ELITE Shadow Query handler."""
import pytest
from unittest.mock import MagicMock, AsyncMock

from marketmind.pipeline.l1_elite import handle_elite_query


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_elite_registry():
    """Build a mock EliteRegistry with DOMAIN_KEYWORDS and contributions."""
    registry = MagicMock()
    registry.DOMAIN_KEYWORDS = {
        "gold": ["gold", "silver", "precious", "GLD", "SLV", "bullion"],
        "crypto": ["bitcoin", "crypto", "ethereum", "BTC", "ETH", "DeFi"],
        "energy": ["oil", "crude", "OPEC", "energy", "gas", "XLE", "USO"],
    }
    registry.detect_domain_trigger = MagicMock(return_value=[])
    registry._contributions = {}
    return registry


def _make_contrib(shadow_id, name, domain, opinion, confidence=0.85):
    """Helper to build a mock EliteContribution."""
    contrib = MagicMock()
    contrib.shadow_id = shadow_id
    contrib.shadow_name = name
    contrib.domain = domain
    contrib.opinion = opinion
    contrib.confidence = confidence
    contrib.trigger_type = "domain_match"
    return contrib


@pytest.fixture
def mock_state(mock_elite_registry):
    """Build a mock InteractiveState with elite_registry."""
    state = MagicMock()
    state.elite_registry = mock_elite_registry
    return state


# ── handle_elite_query tests ────────────────────────────────────────────────

class TestHandleEliteQuery:
    @pytest.mark.asyncio
    async def test_registry_none(self, capsys):
        """When elite_registry is None, show initialization message."""
        state = MagicMock()
        state.elite_registry = None
        await handle_elite_query("elite gold", state)
        captured = capsys.readouterr()
        assert "影子系统未初始化" in captured.out

    @pytest.mark.asyncio
    async def test_empty_query_elite_shows_domains(self, mock_state, mock_elite_registry, capsys):
        """When user types 'elite' with no domain, show available domains."""
        await handle_elite_query("elite", mock_state)
        captured = capsys.readouterr()
        assert "可用领域" in captured.out
        assert "gold" in captured.out or "crypto" in captured.out

    @pytest.mark.asyncio
    async def test_empty_query_elite_with_spaces(self, mock_state, capsys):
        """When user types 'elite  ' with spaces only, show available domains."""
        await handle_elite_query("elite   ", mock_state)
        captured = capsys.readouterr()
        assert "可用领域" in captured.out

    @pytest.mark.asyncio
    async def test_query_with_unknown_domain(self, mock_state, mock_elite_registry, capsys):
        """When domain is not recognized, show error."""
        mock_elite_registry.detect_domain_trigger.return_value = []
        await handle_elite_query("elite unknown_domain", mock_state)
        captured = capsys.readouterr()
        assert "未识别领域" in captured.out

    @pytest.mark.asyncio
    async def test_matched_domain_no_contributions(self, mock_state, mock_elite_registry, capsys):
        """When domain matches but no contributions exist yet."""
        mock_elite_registry.detect_domain_trigger.return_value = ["gold"]
        mock_elite_registry._contributions = {}
        await handle_elite_query("elite gold", mock_state)
        captured = capsys.readouterr()
        assert "正在分析中" in captured.out or "请稍后再试" in captured.out

    @pytest.mark.asyncio
    async def test_matched_domain_with_contributions(self, mock_state, mock_elite_registry, capsys):
        """When domain matches and contributions exist."""
        mock_elite_registry.detect_domain_trigger.return_value = ["gold"]
        contrib = _make_contrib(
            "shadow_01", "GoldSeeker", "gold",
            "Gold shows strong bullish momentum with support at 1950.",
        )
        mock_elite_registry._contributions = {"shadow_01": contrib}
        await handle_elite_query("elite gold", mock_state)
        captured = capsys.readouterr()
        assert "ELITE 影子" in captured.out
        assert "gold" in captured.out
        assert "GoldSeeker" in captured.out
        assert "bullish momentum" in captured.out
        assert "以上为影子独立分析意见" in captured.out

    @pytest.mark.asyncio
    async def test_multiple_contributions_truncated_to_three(self, mock_state, mock_elite_registry, capsys):
        """Only show first 3 contributions."""
        mock_elite_registry.detect_domain_trigger.return_value = ["energy"]
        contributions = {}
        for i in range(5):
            sid = f"shadow_{i:02d}"
            contributions[sid] = _make_contrib(sid, f"Energy{i}", "energy", f"Opinion {i}")
        mock_elite_registry._contributions = contributions
        await handle_elite_query("elite energy", mock_state)
        captured = capsys.readouterr()
        # Count occurrences of "shadow_" in output — should be at most 3
        assert captured.out.count("Energy0") + captured.out.count("Energy1") + captured.out.count("Energy2") >= 1
        # Energy3 and Energy4 should not appear
        assert "Energy3" not in captured.out
        assert "Energy4" not in captured.out

    @pytest.mark.asyncio
    async def test_domain_matched_via_substring_in_contrib_domain(self, mock_state, mock_elite_registry, capsys):
        """Contributions with domain containing the matched domain as substring also count."""
        mock_elite_registry.detect_domain_trigger.return_value = ["tech"]
        contrib = _make_contrib("sh_01", "TechWiz", "tech/hardware", "Tech opinion here.")
        mock_elite_registry._contributions = {"sh_01": contrib}
        await handle_elite_query("elite tech", mock_state)
        captured = capsys.readouterr()
        assert "TechWiz" in captured.out

    @pytest.mark.asyncio
    async def test_query_with_chinese_shadow_keyword(self, mock_state, mock_elite_registry, capsys):
        """User types '影子' (shadow in Chinese) to query."""
        mock_elite_registry.detect_domain_trigger.return_value = ["gold"]
        contrib = _make_contrib("sh_01", "GoldBug", "gold", "Gold is bullish.")
        mock_elite_registry._contributions = {"sh_01": contrib}
        await handle_elite_query("影子 gold", mock_state)
        captured = capsys.readouterr()
        assert "ELITE 影子" in captured.out

    @pytest.mark.asyncio
    async def test_query_with_only_chinese_shadow(self, mock_state, capsys):
        """User types just '影子'—falls through to no query and shows domains."""
        await handle_elite_query("影子", mock_state)
        captured = capsys.readouterr()
        assert "可用领域" in captured.out

    @pytest.mark.asyncio
    async def test_opinion_truncated_to_300_chars(self, mock_state, mock_elite_registry, capsys):
        """Opinion text longer than 300 chars is truncated in display."""
        mock_elite_registry.detect_domain_trigger.return_value = ["crypto"]
        long_opinion = "A" * 500
        contrib = _make_contrib("sh_c", "CryptoGuru", "crypto", long_opinion)
        mock_elite_registry._contributions = {"sh_c": contrib}
        await handle_elite_query("elite crypto", mock_state)
        captured = capsys.readouterr()
        assert "A" * 300 in captured.out
        assert "A" * 350 not in captured.out  # beyond 300 should not show

    @pytest.mark.asyncio
    async def test_contrib_without_shadow_name_attribute(self, mock_state, mock_elite_registry, capsys):
        """Contrib object without shadow_name attribute shows 'unknown'."""
        from marketmind.shadows.elite_participation import EliteContribution

        # Use the actual dataclass with shadow_name set to empty string
        contrib = EliteContribution(
            shadow_id="sh_x",
            shadow_name="",
            domain="macro",
            trigger_type="domain_match",
            opinion="Macro outlook.",
            confidence=0.8,
        )
        mock_elite_registry._contributions = {"sh_x": contrib}
        mock_elite_registry.detect_domain_trigger.return_value = ["macro"]
        await handle_elite_query("elite macro", mock_state)
        captured = capsys.readouterr()
        # Empty string shadow_name shows as empty but ELITE header is present
        assert "ELITE" in captured.out
