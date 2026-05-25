"""Integration tests for AEL (Adaptive Evolution Layer) experiment."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Workspace root on path for `from marketmind.xxx` imports
sys.path.insert(0, str(Path(__file__).resolve().parents[3].parent))


@pytest.fixture
def temp_shadow_db():
    from marketmind.shadows.shadow_state import ShadowStateDB
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = ShadowStateDB(path)
        db.init_schema()
        yield db
    finally:
        db.close()
        os.unlink(path)


@pytest.fixture
def ael_config():
    from marketmind.config.settings import ShadowSettings
    cfg = ShadowSettings()
    cfg.ael_experiment_enabled = True
    cfg.ael_debrief_day = 22  # Today's day to trigger debrief
    return cfg


def _make_mock_performance(shadow_id, wr=0.55, cum_ret=0.05, trades=20):
    from unittest.mock import MagicMock
    perf = MagicMock()
    perf.shadow_id = shadow_id
    perf.win_rate = wr
    perf.cumulative_return = cum_ret
    perf.total_trades = trades
    perf.profitable_trades = int(trades * wr)
    perf.losing_trades = trades - int(trades * wr)
    perf.daily_returns = [0.001] * trades
    return perf


TREATMENT_IDS = [
    "daredevil:range_bound:sideways_scout",
    "daredevil:weekly:trend_rider",
    "expert:tech:silicon_oracle",
    "expert:macro:cycle_reader",
]


@pytest.mark.asyncio
async def test_ael_disabled_skips_debrief(ael_config, temp_shadow_db):
    """When ael_experiment_enabled=False, run_ael_step returns immediately."""
    from marketmind.shadows.step_ael import run_ael_step
    ael_config.ael_experiment_enabled = False

    result = MagicMock()
    result.ael_debriefs = []

    await run_ael_step(ael_config, temp_shadow_db, {}, {}, "2026-05-22", result)
    assert len(result.ael_debriefs) == 0


@pytest.mark.asyncio
async def test_ael_wrong_day_skips_debrief(ael_config, temp_shadow_db):
    """When today is not debrief_day, no debrief fires."""
    from marketmind.shadows.step_ael import run_ael_step
    ael_config.ael_debrief_day = 1  # only fires on day 1

    result = MagicMock()
    result.ael_debriefs = []

    await run_ael_step(ael_config, temp_shadow_db, {}, {}, "2026-05-22", result)
    assert len(result.ael_debriefs) == 0


@pytest.mark.asyncio
async def test_ael_debrief_day_triggers(ael_config, temp_shadow_db):
    """On debrief day, AEL fires for treatment shadows with mock LLM."""
    from marketmind.shadows.step_ael import run_ael_step
    from marketmind.shadows.ael_evolution import AELDebriefResult

    today = "2026-05-22"
    ael_config.ael_debrief_day = 22

    performances = {
        sid: _make_mock_performance(sid) for sid in TREATMENT_IDS
    }
    market_data = {"VIX": 18.5, "SPY": 5200.0}

    result = MagicMock()
    result.ael_debriefs = []

    mock_debrief = AELDebriefResult(
        shadow_id="test",
        month="2026-05",
        win_rate=0.55,
        cumulative_return=0.05,
        total_trades=20,
        failure_patterns=["trend reversal losses"],
        success_patterns=["range-bound scalping"],
        lessons_learned="Reduce position size during trend reversals.",
    )

    with patch("marketmind.shadows.ael_evolution.AELEvolutionEngine") as MockEngine:
        engine_instance = MockEngine.return_value
        engine_instance.run_monthly_debrief = AsyncMock(return_value=mock_debrief)
        engine_instance.inject_lesson.return_value = True
        engine_instance.get_active_lessons.return_value = ["Reduce position size during trend reversals."]

        with patch("marketmind.shadows.methodology_injector.MethodologyInjector") as MockInjector:
            injector_instance = MockInjector.return_value
            injector_instance.inject_lessons.return_value = None

            await run_ael_step(ael_config, temp_shadow_db, performances,
                              market_data, today, result)

    assert len(result.ael_debriefs) == 4  # all 4 treatment shadows
    assert result.ael_debriefs[0].lessons_learned == "Reduce position size during trend reversals."
    assert engine_instance.run_monthly_debrief.call_count == 4


@pytest.mark.asyncio
async def test_ael_missing_performance_skipped(ael_config, temp_shadow_db):
    """Shadows without performance data are skipped gracefully."""
    from marketmind.shadows.step_ael import run_ael_step
    from marketmind.shadows.ael_evolution import AELDebriefResult

    ael_config.ael_debrief_day = 22
    performances = {}  # empty — no shadows have data

    result = MagicMock()
    result.ael_debriefs = []

    with patch("marketmind.shadows.ael_evolution.AELEvolutionEngine") as MockEngine:
        engine_instance = MockEngine.return_value
        engine_instance.run_monthly_debrief = AsyncMock()

        await run_ael_step(ael_config, temp_shadow_db, performances,
                          {}, "2026-05-22", result)

    # No performances → no debriefs attempted
    assert engine_instance.run_monthly_debrief.call_count == 0


@pytest.mark.asyncio
async def test_ael_lesson_parse_from_llm_output():
    """LLM output parsing extracts failure/success patterns and lesson."""
    from marketmind.shadows.ael_evolution import AELEvolutionEngine

    engine = AELEvolutionEngine(state_db=None)
    content = (
        "FAILURE_PATTERNS:\n"
        "- entering trades too early during Fed weeks\n"
        "- over-trading low conviction setups\n"
        "SUCCESS_PATTERNS:\n"
        "- holding winners past initial target\n"
        "- scaling into momentum positions\n"
        "LESSON:\n"
        "Wait for FOMC minutes release before entering new positions."
    )

    failures, successes, lesson, consolidation_note = engine._parse_debrief(content)

    assert len(failures) == 2
    assert "entering trades too early" in failures[0]
    assert len(successes) == 2
    assert "holding winners" in successes[0]
    assert "FOMC minutes" in lesson
    assert consolidation_note == ""  # not elite mode, no consolidation note


def test_ael_parse_empty_output():
    """Empty/None LLM output returns safe defaults."""
    from marketmind.shadows.ael_evolution import AELEvolutionEngine

    engine = AELEvolutionEngine(state_db=None)
    failures, successes, lesson, consolidation_note = engine._parse_debrief("")
    assert failures == []
    assert successes == []
    assert lesson == ""
    assert consolidation_note == ""


def test_ael_parse_no_pattern_match():
    """LLM output without expected markers returns empty."""
    from marketmind.shadows.ael_evolution import AELEvolutionEngine

    engine = AELEvolutionEngine(state_db=None)
    failures, successes, lesson, consolidation_note = engine._parse_debrief("Some random analysis text.")
    assert failures == []
    assert successes == []
    assert lesson == ""
    assert consolidation_note == ""


def test_ael_parse_elite_consolidation_mode():
    """ELITE consolidation output extracts SUCCESS_PATTERNS and CONSOLIDATION_NOTE."""
    from marketmind.shadows.ael_evolution import AELEvolutionEngine

    engine = AELEvolutionEngine(state_db=None)
    content = (
        "SUCCESS_PATTERNS:\n"
        "- consistently sizing positions based on volatility regime\n"
        "- rotating into defensive sectors before market downturns\n"
        "CONSOLIDATION_NOTE:\n"
        "This shadow demonstrates exceptional regime awareness. Its ability "
        "to anticipate sector rotations 3-5 days ahead of market moves is "
        "the primary driver of outperformance. Continue to trust these "
        "instincts — no changes recommended."
    )

    failures, successes, lesson, consolidation_note = engine._parse_debrief(content)

    assert len(successes) == 2
    assert "volatility regime" in successes[0]
    assert len(failures) == 0  # elite mode has no failure patterns
    assert lesson == ""        # elite mode has no lesson
    assert "regime awareness" in consolidation_note
    assert "no changes recommended" in consolidation_note
