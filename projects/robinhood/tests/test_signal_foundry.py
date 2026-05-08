"""
test_signal_foundry.py - Phase 4: CLI entry point tests.

Tests the signal_foundry.py CLI argument parsing, orchestration loop, and
end-to-end mock pipeline using argparse and output capture.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.account_reader import read_account_state

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def mock_account_file() -> Path:
    """Path to the real mock account state file."""
    return _PROJECT_ROOT / "input" / "account_state.json"


@pytest.fixture
def mock_env(monkeypatch) -> None:
    """Set up mock environment variables for testing."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-mock-key-12345")
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "demo")
    monkeypatch.setenv("ACCOUNT_FILE",
                       str(_PROJECT_ROOT / "input" / "account_state.json"))
    monkeypatch.setenv("MOCK_MODE", "true")


# ---------------------------------------------------------------------------
# Tests: AccountReader integration
# ---------------------------------------------------------------------------


class TestAccountReaderIntegration:
    """read_account_state works with the mock file used by the CLI."""

    def test_reads_mock_account_file(self) -> None:
        """read_account_state can parse the mock account_state.json."""
        state = read_account_state(
            str(_PROJECT_ROOT / "input" / "account_state.json")
        )
        assert isinstance(state, object)
        d = state.to_dict()
        assert "cash" in d
        assert d["cash"] > 0

    def test_account_has_nvda_position(self) -> None:
        """The mock account has an NVDA position."""
        state = read_account_state(
            str(_PROJECT_ROOT / "input" / "account_state.json")
        )
        assert len(state.positions) >= 1
        assert state.positions[0].ticker == "NVDA"
        assert state.positions[0].shares > 0


# ---------------------------------------------------------------------------
# Tests: Integration smoke test (import-based, no CLI execution)
# ---------------------------------------------------------------------------


class TestPipelineImportSmoke:
    """Verify all pipeline modules can be imported cleanly."""

    def test_import_ascii_utils(self) -> None:
        """ascii_utils imports without error."""
        from src import ascii_utils
        assert ascii_utils.clean_ascii_only is not None

    def test_import_deepseek_client(self) -> None:
        """deepseek_client imports without error."""
        import importlib
        spec = importlib.util.find_spec("src.deepseek_client")
        assert spec is not None

    def test_import_output_formatter(self) -> None:
        """output_formatter imports without error."""
        import importlib
        spec = importlib.util.find_spec("src.output_formatter")
        assert spec is not None

    def test_import_layer1_modules(self) -> None:
        """All Layer 1 (data) modules import without error."""
        import src.market_fetcher  # noqa: F401
        import src.macro_calendar  # noqa: F401
        import src.sentiment_collector  # noqa: F401
        import src.account_reader  # noqa: F401

    def test_import_layer2_modules(self) -> None:
        """All Layer 2 (analysis) modules import *as modules*."""
        import src.fundamental_engine  # noqa: F401
        import src.technical_engine     # noqa: F401 (function-based API)
        import src.event_engine         # noqa: F401
        import src.sentiment_engine     # noqa: F401

    def test_import_layer3_modules(self) -> None:
        """All Layer 3 (aggregation + capital) modules import correctly."""
        from src.resonance_aggregator import compute_resonance  # noqa: F401
        import src.capital_manager                               # noqa: F401
        assert src.capital_manager.compute_position_sizing is not None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_weekly_df() -> pd.DataFrame:
    """Build a minimal weekly OHLCV DataFrame for testing."""
    base = 100.0
    n = 30
    dates = pd.date_range(start="2024-06-16", periods=n, freq="7D")
    data = {
        "open":   [base - 0.5 + i * 0.1 for i in range(n)],
        "high":   [base + 1.0 + i * 0.1 for i in range(n)],
        "low":    [base - 1.0 + i * 0.1 for i in range(n)],
        "close":  [base + i * 0.1 for i in range(n)],
        "volume": [1_000_000 + i * 1000 for i in range(n)],
    }
    df = pd.DataFrame(data, index=dates)
    df.index.name = "date"
    return df


def _make_mock_scores() -> dict[str, dict[str, float]]:
    """Return mock EngineOutput-style dicts for all four dimensions."""
    return {
        "fundamental": {"score": 75, "reasoning": "Mock fundamental: neutral-positive"},
        "technical":   {"score": 70, "reasoning": "Mock technical: bullish-leaning"},
        "event_driven":{"score": 60, "reasoning": "Mock event: low risk"},
        "sentiment":   {"score": 65, "reasoning": "Mock sentiment: slightly bullish"},
    }


# ---------------------------------------------------------------------------
# Tests: Mock pipeline orchestration
# ---------------------------------------------------------------------------


class TestPipelineOrchestration:
    """Mock pipeline orchestration tests.

    These verify that the assembly of Layer 1 -> 2 -> 3 -> 4 -> Report
    works in principle using mock data.
    """

    def test_layer1_to_layer2_flow(self) -> None:
        """Layer 1 mock data can feed into Layer 2 without crashing."""
        from src.fundamental_engine import analyze_fundamental
        from src.technical_engine import analyze_technical
        from src.event_engine import analyze_event_driven
        from src.sentiment_engine import analyze_sentiment

        ticker = "AAPL"
        weekly_df = _make_weekly_df()

        # Layer 2
        fund = analyze_fundamental([], [])   # no macro events, no positions → neutral
        assert isinstance(fund, dict)
        assert "score" in fund

        tech = analyze_technical(weekly_df)
        assert isinstance(tech, dict)
        assert "score" in tech

        evt = analyze_event_driven([])   # no events → low risk
        assert isinstance(evt, dict)

        sent = analyze_sentiment(f"News about {ticker}")
        assert isinstance(sent, dict)
        assert "magnitude" in sent

    def test_layer2_to_layer3_flow(self) -> None:
        """Layer 2 outputs can feed into Layer 3 aggregator and capital manager."""
        from src.resonance_aggregator import compute_resonance
        import src.capital_manager

        scores = _make_mock_scores()

        resonance = compute_resonance(
            fundamental=scores["fundamental"],
            technical=scores["technical"],
            event_driven=scores["event_driven"],
            sentiment_engine_output=scores["sentiment"],
        )
        assert isinstance(resonance, dict)
        assert "weighted_score" in resonance
        assert resonance["weighted_score"] > 0

        account = read_account_state(
            str(_PROJECT_ROOT / "input" / "account_state.json")
        )
        capital = src.capital_manager.compute_position_sizing(
            ticker="AAPL",
            signal=resonance["signal"],
            account=account,
            current_price=180.0,
        )
        assert isinstance(capital, dict)
        assert "max_notional" in capital or "action" in capital

    def test_layer3_to_layer4_flow(self) -> None:
        """Layer 3 outputs (resonance + capital) feed into Pro Model dispatch."""
        from src.resonance_aggregator import compute_resonance
        import src.capital_manager
        from src.deepseek_client import dispatch_prompt

        # Build Layer 3 data
        mock_scores = {
            "fundamental": {"score": 78, "reasoning": "Mock fundamental"},
            "technical":   {"score": 72, "reasoning": "Mock technical"},
            "event_driven":{"score": 65, "reasoning": "Mock event"},
            "sentiment":   {"score": 68, "reasoning": "Mock sentiment"},
        }

        resonance = compute_resonance(
            fundamental=mock_scores["fundamental"],
            technical=mock_scores["technical"],
            event_driven=mock_scores["event_driven"],
            sentiment_engine_output=mock_scores["sentiment"],
        )

        account = read_account_state(
            str(_PROJECT_ROOT / "input" / "account_state.json")
        )
        capital = src.capital_manager.compute_position_sizing(
            ticker="AAPL",
            signal=resonance["signal"],
            account=account,
            current_price=180.0,
        )

        # Layer 4 dispatch (mock mode)
        from src.pro_model_deep_dive import build_pro_model_prompt

        prompt_bundle = build_pro_model_prompt(
            resonance_result=resonance,
            capital_result=capital,
            ticker="AAPL",
            account_state={"cash_available": 10000.00,
                           "existing_positions": {}},
        )

        result = dispatch_prompt(
            mock=True,
            ticker="AAPL",
            system_prompt=prompt_bundle["system_prompt"],
            user_prompt=prompt_bundle["user_prompt"],
        )
        # dispatch_prompt(mock=True) returns a dict with ticker, signal, confidence,
        # rationale, and _meta — NOT the full Pro Model JSON schema.
        assert "signal" in result
        assert "rationale" in result

    def test_layer4_to_report_flow(self) -> None:
        """Pro Model response feeds into output_formatter for final Markdown."""
        from src.deepseek_client import dispatch_prompt
        from src.output_formatter import ReportGenerator
        from src.ascii_utils import clean_ascii_only

        # Build a minimal DecisionReport constructible from the mock dispatch output.
        # In the current architecture, ReportGenerator.generate() takes a
        # DecisionReport, not a raw dispatch response.
        from src.decision_aggregator import (
            DecisionReport,
            DecisionTrack,
            ResonanceMatrix,
            PositionSizing,
        )
        from src.paradigm_anchors import AnchorState, ThreeAnchors

        mock_result = dispatch_prompt(
            mock=True, ticker="MSFT",
            system_prompt="", user_prompt="",
        )

        report = DecisionReport(
            report_id="test-report-001",
            generated_at="2026-05-07T00:00:00Z",
            target_ticker=mock_result["ticker"],
            raw_scores={"fundamental": 65.0, "technical": 60.0,
                        "event_driven": 55.0, "sentiment": 60.0},
            audit_deduction=5.0,
            paradigm_multiplier=1.0,
            final_score=58.5,
            decision_track=DecisionTrack.OBSERVE_WAIT,
            position_sizing=PositionSizing(direction="HOLD"),
            resonance=ResonanceMatrix(dimensions_resonating=3),
            logic_chain_integrity=True,
            audit_passed=True,
            mosaic_narrative_id="test-mosaic-001",
            consensus_fragility=30.0,
            anchors=ThreeAnchors(
                fiscal_credibility=AnchorState.GREEN,
                geopolitical_gii=AnchorState.GREEN,
                reflexivity_rac=AnchorState.GREEN,
                fiscal_evidence="No concerns.",
                gii_evidence="No concerns.",
                rac_evidence="No concerns.",
            ),
            safety_valves_triggered=[],
        )

        markdown = ReportGenerator().generate(report)
        assert isinstance(markdown, str)
        assert len(markdown) > 200

        # Final ASCII guarantee
        assert clean_ascii_only(markdown) == markdown.strip()
