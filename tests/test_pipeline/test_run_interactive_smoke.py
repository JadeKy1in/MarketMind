"""Smoke test for the full interactive flow — verifies run_interactive() returns 0
with all external dependencies mocked (no real API calls, no file I/O)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from marketmind.config.settings import MarketMindConfig, ShadowSettings
from marketmind.pipeline.session_context import SessionContext
from marketmind.pipeline.layer1_narrative import Layer1Result
from marketmind.pipeline.layer2_fundamental import Layer2Result
from marketmind.pipeline.layer3_technical import Layer3Result, Layer3BatchResult
from marketmind.pipeline.red_team import RedTeamReport, RedTeamChallenge
from marketmind.pipeline.resonance import ResonanceResult
from marketmind.pipeline.decision import DecisionOutput


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_config() -> MarketMindConfig:
    """Config with shadows disabled so no shadow DB init is attempted."""
    shadow_settings = ShadowSettings(shadows_enabled=False)
    return MarketMindConfig(deepseek_api_key="sk-test", shadow=shadow_settings)


def _make_l1_result() -> Layer1Result:
    return Layer1Result(
        event_grade="B", surprise_level="high", market_size="big",
        matrix_quadrant="core_opportunity", price_in_score=0.3,
        cascade_rank=1, cascade_hub=False,
        sentiment_direction="bullish", sentiment_intensity=0.7,
        sentiment_vs_attention="high_sentiment",
        expert_signals=[], institutional_surprise="",
        key_characters=[], tail_risk_flags=[],
        raw_analysis="Mock L1 analysis.",
    )


def _make_l2_result() -> Layer2Result:
    return Layer2Result(
        macro_quadrant="expansion", macro_direction="risk_on",
        preferred_assets=["equities"], sector_shortlist=["Tech"],
        sector_momentum={"Tech": "accelerating"},
        factor_scores={"AAPL": 0.85},
        ticker_candidates=["AAPL"], ticker_weights={"AAPL": 0.5},
        red_team_notes=[], raw_analysis="Mock L2 analysis.",
    )


def _make_l3_batch() -> Layer3BatchResult:
    return Layer3BatchResult(results=[
        Layer3Result(
            ticker="AAPL", light="green", recommendation="enter",
            above_200wma=True, daily_structure_intact=True,
            near_key_resistance=False, resistance_distance_pct=5.0,
            support_zone_low=140.0, support_zone_high=145.0,
            resistance_zone_low=160.0, resistance_zone_high=165.0,
            entry_zone_low=142.0, entry_zone_high=148.0,
            stop_loss=138.0, target_price=162.0,
            max_hold_days=30, reward_risk_ratio=2.5,
        ),
    ])


def _make_red_team_report() -> RedTeamReport:
    return RedTeamReport(
        challenges=[
            RedTeamChallenge(
                id="RT-1", target="layer1", severity="minor",
                challenge="Test challenge", evidence="Test evidence",
                suggested_fix="Test fix",
            ),
        ],
        overall_assessment="Clean analysis.",
    )


def _make_resonance() -> ResonanceResult:
    return ResonanceResult(
        passed=True, dsr=0.65, pbo=0.05,
        forward_validation_ratio=0.3, signal_count=2,
        dimensions_active=["technical"], verdict="WEAK_SIGNAL",
    )


# ── Side-effect functions for interactive stage mocks ────────────────────────

async def _mock_l2_interactive(ctx, cli_handler):
    """Simulate run_l2_interactive: populate ctx and return confirmed."""
    ctx.l2_result = _make_l2_result()
    ctx.selected_tickers = ["AAPL", "MSFT"]
    return True


async def _mock_l3_interactive(ctx, cli_handler):
    """Simulate run_l3_interactive: populate ctx and return confirmed."""
    ctx.l3_result = _make_l3_batch()
    return True


async def _mock_decision_interactive(ctx, cli_handler):
    """Simulate run_decision_interactive: return confirmed."""
    ctx.decision = DecisionOutput(summary="Mock decision.")
    return True


# ── Test ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_interactive_full_flow_confirm():
    """Run the full interactive flow with all external calls mocked.

    Verifies that run_interactive() reaches the end and returns 0 (success)
    without hitting any real APIs or performing file I/O.
    """
    config = _make_config()
    l1_result = _make_l1_result()
    l2_result = _make_l2_result()
    l3_batch = _make_l3_batch()
    red_team_report = _make_red_team_report()
    resonance = _make_resonance()

    # Mock archivist to avoid file I/O in _archive_session
    mock_archivist = MagicMock()
    mock_archivist.init_fts.return_value = None
    mock_archivist.index_document.return_value = None

    with patch("marketmind.app._setup_logging"):  # skip log dir creation
        with patch("marketmind.gateway.async_client.init_gateway"):  # skip API key validation
            with patch("marketmind.pipeline.scout.fetch_all_sources",
                       AsyncMock(return_value=[])):
                with patch("marketmind.pipeline.flash_preprocessor.preprocess_batch",
                           AsyncMock(return_value=[])):
                    with patch("marketmind.pipeline.layer1_interactive.run_l1_interactive",
                               AsyncMock(return_value=(l1_result, False, {}))):
                        with patch("marketmind.pipeline.l2_interactive.run_l2_interactive",
                                   side_effect=_mock_l2_interactive):
                            with patch("marketmind.pipeline.l3_interactive.run_l3_interactive",
                                       side_effect=_mock_l3_interactive):
                                with patch("marketmind.pipeline.red_team.run_red_team",
                                           AsyncMock(return_value=red_team_report)):
                                    with patch("marketmind.pipeline.resonance.evaluate_resonance",
                                               return_value=resonance):
                                        with patch(
                                            "marketmind.pipeline.decision_interactive.run_decision_interactive",
                                            side_effect=_mock_decision_interactive,
                                        ):
                                            with patch("marketmind.storage.archivist.get_archivist",
                                                       return_value=mock_archivist):
                                                from marketmind.app import run_interactive
                                                rc = await run_interactive(
                                                    config, mock=True, verbose=False,
                                                    shadow_count=None,
                                                )

    assert rc == 0
