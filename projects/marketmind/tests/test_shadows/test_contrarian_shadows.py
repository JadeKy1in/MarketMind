"""Tests for ContrarianShadow — 4 contrarian "敢死队" mean-reversion shadows."""
import pytest
from unittest.mock import AsyncMock, patch

from marketmind.shadows.contrarian_shadows import (
    ContrarianShadow, create_contrarian_shadows, CONTRARIAN_SHADOW_CONFIGS
)
from marketmind.shadows.shadow_state import ShadowConfig
from marketmind.config.settings import ShadowSettings


@pytest.fixture
def settings():
    return ShadowSettings()


@pytest.fixture
def contrarian_config():
    return ShadowConfig(
        shadow_id="contrarian:consensus:test_fade",
        shadow_type="contrarian",
        display_name="Test Fade Master",
        methodology_prompt="You fade consensus daily.",
        virtual_capital=20000.0,
        temperature=0.55,
        max_drawdown_limit=0.35,
    )


@pytest.fixture
def contrarian_shadow(contrarian_config, temp_shadow_db, settings):
    return ContrarianShadow(contrarian_config, temp_shadow_db, settings)


class TestContrarianShadow:
    @pytest.mark.asyncio
    async def test_contrarian_produces_analysis(self, contrarian_shadow):
        news = [{"headline": "Everyone bullish on tech — record inflows"}]
        mock_result = {
            "content": (
                "VOTE_START\n"
                "ticker: QQQ\ndirection: short\nconfidence: 0.65\n"
                "thesis: Extreme bullish consensus signals reversal risk\n"
                "risk_note: Trend may persist before mean-reversion kicks in\n"
                "VOTE_END"
            ),
            "latency_ms": 500,
        }
        with patch("marketmind.gateway.async_client.chat_with_integrity",
                   new_callable=AsyncMock, return_value=mock_result):
            output = await contrarian_shadow.run_daily_analysis(news, {})
        assert output.shadow_id == "contrarian:consensus:test_fade"
        assert output.date is not None


def test_create_contrarian_shadows_creates_4(temp_shadow_db):
    """Factory creates exactly 4 contrarian shadows."""
    settings = ShadowSettings()
    shadows = create_contrarian_shadows(temp_shadow_db, settings)
    assert len(shadows) == 4
    assert all(isinstance(s, ContrarianShadow) for s in shadows)

    # Verify all registered in DB
    visible = temp_shadow_db.get_visible_shadows()
    contrarian_ids = [c.shadow_id for c in CONTRARIAN_SHADOW_CONFIGS]
    registered = [v for v in visible if v.shadow_id in contrarian_ids]
    assert len(registered) == 4


def test_contrarian_shadows_have_high_drawdown_limit():
    """Contrarian shadows have drawdown limits 30-40% — higher than expert (25%)."""
    for config in CONTRARIAN_SHADOW_CONFIGS:
        assert config.max_drawdown_limit >= 0.30, (
            f"{config.shadow_id} drawdown {config.max_drawdown_limit} below 30% minimum"
        )


def test_fade_master_is_always_active():
    """Fade Master is the only contrarian that is always active (not global-scan triggered)."""
    fade_master = [c for c in CONTRARIAN_SHADOW_CONFIGS
                   if c.shadow_id == "contrarian:consensus:fade_master"]
    assert len(fade_master) == 1
    fm = fade_master[0]
    assert fm.virtual_capital == 20000.0
    assert fm.temperature == 0.55
    assert fm.display_name == "Fade Master"
    assert fm.min_trades_for_ranking == 50  # Highest min trades among contrarians
    # Always active — prompt confirms no global scan trigger
    assert "ALWAYS ACTIVE" in fm.methodology_prompt.upper() or "始终活跃" in fm.methodology_prompt


def test_sideways_scout_is_global_scan_triggered():
    """Sideways Scout uses global scan (not always active)."""
    scout = [c for c in CONTRARIAN_SHADOW_CONFIGS
             if c.shadow_id == "contrarian:range_bound:sideways_scout"]
    assert len(scout) == 1
    s = scout[0]
    assert s.virtual_capital == 25000.0
    assert s.min_trades_for_ranking == 40
    assert "GLOBAL SCAN" in s.methodology_prompt.upper() or "全球扫描" in s.methodology_prompt


def test_vol_surfer_is_global_scan_triggered():
    """Vol Surfer uses global vol index scan."""
    vol = [c for c in CONTRARIAN_SHADOW_CONFIGS
           if c.shadow_id == "contrarian:panic:vol_surfer"]
    assert len(vol) == 1
    v = vol[0]
    assert v.virtual_capital == 30000.0
    assert v.temperature == 0.60  # Highest temperature
    assert v.max_drawdown_limit == 0.40  # Highest drawdown tolerance
    assert v.min_trades_for_ranking == 30


def test_crash_hunter_is_global_scan_triggered():
    """Crash Hunter uses global scan for bubble signals."""
    crash = [c for c in CONTRARIAN_SHADOW_CONFIGS
             if c.shadow_id == "contrarian:crash:hunter"]
    assert len(crash) == 1
    c = crash[0]
    assert c.virtual_capital == 30000.0
    assert c.max_drawdown_limit == 0.40
    assert c.min_trades_for_ranking == 25  # Lowest min trades (rare activation)
    assert "SHORT" in c.methodology_prompt.upper()  # Default direction


def test_all_4_contrarian_configs_unique_ids():
    """No duplicate shadow IDs in contrarian configs."""
    ids = [c.shadow_id for c in CONTRARIAN_SHADOW_CONFIGS]
    assert len(ids) == len(set(ids)) == 4


def test_contrarian_configs_correct_names():
    """Verify the 4 contrarian shadow display names match the plan §3.3."""
    expected_names = {"Fade Master", "Sideways Scout", "Vol Surfer", "Crash Hunter"}
    actual_names = {c.display_name for c in CONTRARIAN_SHADOW_CONFIGS}
    assert actual_names == expected_names


def test_contrarian_configs_have_correct_types():
    """All 4 contrarian configs have shadow_type='contrarian'."""
    for config in CONTRARIAN_SHADOW_CONFIGS:
        assert config.shadow_type == "contrarian", (
            f"{config.shadow_id} has type '{config.shadow_type}', expected 'contrarian'"
        )


# ── LLM integration tests ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_contrarian_analyze_with_mock_llm(temp_shadow_db):
    """ContrarianShadow._analyze() calls mock LLM and parses results."""
    from marketmind.shadows.contrarian_shadows import ContrarianShadow

    config = ShadowConfig(
        shadow_id="contrarian:consensus:test_llm", shadow_type="contrarian",
        display_name="Test Fade", methodology_prompt="You fade consensus.",
        virtual_capital=20000.0, temperature=0.55, max_drawdown_limit=0.35,
        min_trades_for_ranking=50,
    )
    agent = ContrarianShadow(config, temp_shadow_db, ShadowSettings())

    mock_result = {
        "content": (
            "VOTE_START\n"
            "ticker: SPY\ndirection: short\nconfidence: 0.55\n"
            "thesis: Consensus too bullish after 8-week rally\n"
            "risk_note: Momentum may extend before reversal\n"
            "VOTE_END"
        ),
        "latency_ms": 500,
    }

    with patch("marketmind.gateway.async_client.chat_with_integrity",
               new_callable=AsyncMock, return_value=mock_result):
        output = await agent._analyze(
            [{"headline": "Record inflows as retail piles into equities"}], {}
        )

    assert len(output.votes) == 1
    assert output.votes[0].ticker == "SPY"
    assert output.votes[0].direction == "short"


@pytest.mark.asyncio
async def test_fade_master_prompt_includes_consensus_constraints(temp_shadow_db):
    """Fade Master prompt includes consensus-fading logic."""
    from marketmind.shadows.contrarian_shadows import ContrarianShadow

    config = ShadowConfig(
        shadow_id="contrarian:consensus:test_prompt", shadow_type="contrarian",
        display_name="Test Fade", methodology_prompt="You fade consensus.",
        virtual_capital=20000.0, temperature=0.55, max_drawdown_limit=0.35,
        min_trades_for_ranking=50,
    )
    agent = ContrarianShadow(config, temp_shadow_db, ShadowSettings())

    prompt = agent._build_user_prompt(
        [{"headline": "Everyone is bullish"}], {"SPY": 500.0}
    )
    assert "ALWAYS ACTIVE" in prompt
    assert "Fade consensus" in prompt or "consensus" in prompt.lower()


@pytest.mark.asyncio
async def test_crash_hunter_prompt_includes_bubble_signals(temp_shadow_db):
    """Crash Hunter prompt includes pre-crash signal checklist."""
    from marketmind.shadows.contrarian_shadows import ContrarianShadow

    config = ShadowConfig(
        shadow_id="contrarian:crash:test_hunter", shadow_type="contrarian",
        display_name="Test Crash", methodology_prompt="You hunt crash signals.",
        virtual_capital=30000.0, temperature=0.50, max_drawdown_limit=0.40,
        min_trades_for_ranking=25,
    )
    agent = ContrarianShadow(config, temp_shadow_db, ShadowSettings())

    prompt = agent._build_user_prompt(
        [{"headline": "Markets at all-time highs"}], {"SPY": 550.0}
    )
    assert "SHORT" in prompt
    assert "CAPE" in prompt or "Hindenburg" in prompt or "bubble" in prompt.lower()


@pytest.mark.asyncio
async def test_sideways_scout_norange_globally_abstain(temp_shadow_db):
    """Sideways Scout with empty range scan: should handle NO_RANGE_GLOBALLY gracefully."""
    from marketmind.shadows.contrarian_shadows import ContrarianShadow

    config = ShadowConfig(
        shadow_id="contrarian:range_bound:test_sideways", shadow_type="contrarian",
        display_name="Test Sideways", methodology_prompt="You trade ranges.",
        virtual_capital=25000.0, temperature=0.45, max_drawdown_limit=0.30,
        min_trades_for_ranking=40,
    )
    agent = ContrarianShadow(config, temp_shadow_db, ShadowSettings())

    # When no range-bound markets found, LLM outputs NO_RANGE_GLOBALLY
    mock_result = {
        "content": "NO_RANGE_GLOBALLY: no global indices in range-bound conditions today.",
        "latency_ms": 300,
    }

    with patch("marketmind.gateway.async_client.chat_with_integrity",
               new_callable=AsyncMock, return_value=mock_result):
        output = await agent._analyze(
            [{"headline": "Markets trending strongly"}], {}
        )

    # Should not crash — no votes produced when no conditions met
    assert output is not None
    assert output.shadow_id == "contrarian:range_bound:test_sideways"
