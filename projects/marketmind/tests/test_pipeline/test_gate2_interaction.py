"""Tests for Gate 2 signal confirmation interaction loop."""
from __future__ import annotations

import pytest
from marketmind.pipeline.gate2_interaction import (
    Gate2Session,
    run_gate2,
    _DEBIASING_NOTICE,
    _format_evidence_summary,
    _format_fragility,
    _format_regime,
    _format_signal_conflicts,
    _format_kill_criteria,
    _parse_conviction,
    _parse_outcome,
)
from marketmind.pipeline.decision import SignalConflict


# ── Helpers ─────────────────────────────────────────────────────────────────

def make_hypothesis(
    confidence: float = 0.81,
    direction: str = "EUR/USD 看涨",
    layer_1: str = "市场定价显示欧元被低估约5%",
    layer_2: str = "欧洲基本面改善，制造业PMI回升",
    layer_3: str = "多个数据源确认欧元区经济复苏趋势",
    layer_4: str = "历史数据显示类似环境下欧元平均上涨3%",
    bear_case: str = "如果美联储意外加息50基点，则欧元可能回落",
):
    """Build a minimal HypothesisResult-like object for Gate 2 testing."""
    from types import SimpleNamespace
    return SimpleNamespace(
        hypothesis="Test hypothesis",
        expectation_gap=0.15,
        confidence=confidence,
        bear_case=bear_case,
        bear_case_confidence=0.35,
        verdict="ACTIONABLE",
        direction=direction,
        risk_level="中等",
        time_window="2-4周",
        layer_1_narrative=layer_1,
        layer_2_narrative=layer_2,
        layer_3_narrative=layer_3,
        layer_4_narrative=layer_4,
        core_logic="ECB hiking drives EUR higher",
    )


def make_fragility_report(score: float = 0.35):
    """Build a minimal FragilityReport-like object."""
    from types import SimpleNamespace
    return SimpleNamespace(
        overall_fragility_score=score,
        crossed=[],
        warnings=[],
        staleness_warnings=[],
        summary="整体脆弱度处于中等水平，没有指标触发关键阈值。",
        generated_at="2026-05-18T00:00:00+00:00",
    )


def make_regime_mapping():
    """Build a minimal RegimeMapping-like object."""
    from types import SimpleNamespace
    return SimpleNamespace(
        current_quadrant="growth_up_inflation_up",
        top_analogues=[
            SimpleNamespace(regime_id="r1", regime_name="1995 Soft Landing", similarity=0.82,
                          forward_3m_equity=0.082, forward_6m_equity=0.15),
            SimpleNamespace(regime_id="r2", regime_name="2007 Pre-Crisis Peak", similarity=0.71,
                          forward_3m_equity=-0.041, forward_6m_equity=-0.08),
            SimpleNamespace(regime_id="r3", regime_name="2018 Late-Cycle", similarity=0.68,
                          forward_3m_equity=-0.123, forward_6m_equity=-0.20),
        ],
        anti_analogues=[],
        regime_consensus="Current conditions most resemble 1995 soft landing",
        bias_warning="Training range 1990-2024",
    )


def make_signal_conflicts():
    """Build SignalConflict objects."""
    return [
        SignalConflict(
            hypothesis="EUR/USD directional force vs flow imbalance",
            signal_a=("causal_decomposition", 0.65),
            signal_b=("flow_decomposition", -0.10),
            divergence=0.75,
            description="因果分解(Directional Force: +0.65) 与 资金流(Imbalance: -0.10) 分歧度 0.75",
        ),
    ]


def make_kill_criteria():
    """Build KillCriterion-like objects."""
    from types import SimpleNamespace
    return [
        SimpleNamespace(criterion_id="KC-001", description="EUR/USD 跌破 1.05",
                       observable="EUR/USD exchange rate", data_source="market_data:EURUSD",
                       threshold_value=1.05, threshold_direction="below",
                       deadline="", consequence="KILL", status="MONITORING", last_checked=""),
        SimpleNamespace(criterion_id="KC-002", description="德国CPI < 2.2%",
                       observable="German CPI YoY", data_source="FRED:DEUCPI",
                       threshold_value=2.2, threshold_direction="below",
                       deadline="", consequence="REDUCE_50", status="MONITORING", last_checked=""),
    ]


# ── Tests ───────────────────────────────────────────────────────────────────

class TestConvictionAskedBeforeAnalysis:
    """Step 2.1: conviction must be asked BEFORE any analysis is shown."""

    @pytest.mark.asyncio
    async def test_conviction_asked_before_evidence(self):
        """User receives conviction prompt before seeing any AI analysis."""
        hyps = [make_hypothesis()]
        messages: list[str] = []
        prompts: list[str] = []

        async def mock_io(prompt: str) -> str:
            prompts.append(prompt)
            return "7"

        async def mock_status(msg: str) -> None:
            messages.append(msg)

        result = await run_gate2(
            direction="EUR/USD 看涨",
            hypotheses=hyps,
            fragility_report=make_fragility_report(),
            regime_mapping=make_regime_mapping(),
            session_id="test-conviction-first",
            io_handler=mock_io,
            status_handler=mock_status,
        )

        # First message must be the conviction prompt
        first_msg = messages[0] if messages else ""
        assert "看到AI的分析结果之前" in first_msg or "信心" in first_msg

        # Conviction prompt must NOT contain analysis data
        assert "L1" not in first_msg
        assert "L2" not in first_msg
        assert "脆弱" not in first_msg
        assert "制度" not in first_msg

        # User's conviction must be recorded
        assert result.user_initial_conviction == "7"


class TestStateFlow:
    """Full state machine transitions."""

    @pytest.mark.asyncio
    async def test_state_flow_start_to_end(self):
        """START → CONVICTION_FIRST → ANALYSE → CONFIRMING → END."""
        hyps = [make_hypothesis()]
        states_seen: list[str] = []

        # responses: conviction first, then confirm outcome
        responses = ["8", "维持原判，继续"]

        async def mock_io(prompt: str) -> str:
            return responses.pop(0) if responses else ""

        async def mock_status(msg: str) -> None:
            # Track state changes indirectly by looking for debiasing notice
            if "CONVICTION_FIRST" in msg or "ANALYSE" in msg:
                pass

        result = await run_gate2(
            direction="EUR/USD 看涨",
            hypotheses=hyps,
            fragility_report=make_fragility_report(),
            regime_mapping=make_regime_mapping(),
            session_id="test-state-flow",
            io_handler=mock_io,
            status_handler=mock_status,
        )

        assert result.state == "END"
        # Initial conviction was 8 → STRONG
        assert result.final_conviction == "STRONG"
        assert result.outcome == "CONTINUE"
        assert result.turns >= 2


class TestSignalConflictDisplay:
    """Signal conflicts must be presented to user."""

    @pytest.mark.asyncio
    async def test_conflict_display_included(self):
        """When signal conflicts exist, they appear in the analysis output."""
        hyps = [make_hypothesis()]
        conflicts = make_signal_conflicts()
        messages: list[str] = []

        responses = ["5", "继续"]

        async def mock_io(prompt: str) -> str:
            return responses.pop(0) if responses else ""

        async def mock_status(msg: str) -> None:
            messages.append(msg)

        result = await run_gate2(
            direction="EUR/USD 看涨",
            hypotheses=hyps,
            fragility_report=make_fragility_report(),
            regime_mapping=make_regime_mapping(),
            session_id="test-conflict-display",
            io_handler=mock_io,
            status_handler=mock_status,
            signal_conflicts=conflicts,
        )

        all_text = "\n".join(messages)
        assert "信号冲突" in all_text
        assert "因果分解" in all_text or "Directional Force" in all_text
        assert result.outcome == "CONTINUE"


class TestDebiasingNotice:
    """Debiasing notice must appear in the analysis display."""

    @pytest.mark.asyncio
    async def test_debiasing_notice_shown(self):
        """The overconfidence calibration notice is displayed with the analysis."""
        hyps = [make_hypothesis()]
        messages: list[str] = []

        responses = ["6", "确认"]

        async def mock_io(prompt: str) -> str:
            return responses.pop(0) if responses else ""

        async def mock_status(msg: str) -> None:
            messages.append(msg)

        await run_gate2(
            direction="XAU/USD 看涨",
            hypotheses=hyps,
            fragility_report=make_fragility_report(),
            regime_mapping=make_regime_mapping(),
            session_id="test-debias",
            io_handler=mock_io,
            status_handler=mock_status,
        )

        all_text = "\n".join(messages)
        assert "过度自信" in all_text or "0.75-0.85" in all_text

    def test_debiasing_constant_text(self):
        """The DEBIASING_NOTICE constant must contain the key calibration warning."""
        assert "0.75" in _DEBIASING_NOTICE
        assert "0.85" in _DEBIASING_NOTICE
        assert "15%" in _DEBIASING_NOTICE


class TestEvidenceSummaryFormatting:
    """Evidence summary must be structured and readable."""

    def test_evidence_summary_includes_all_layers(self):
        hyps = [make_hypothesis()]
        text = _format_evidence_summary(hyps)
        assert "L1" in text
        assert "L2" in text
        assert "L3" in text
        assert "L4" in text
        assert hyps[0].direction in text

    def test_evidence_summary_multiple_hypotheses(self):
        hyps = [
            make_hypothesis(direction="EUR/USD 看涨", confidence=0.81),
            make_hypothesis(direction="XAU/USD 看涨", confidence=0.72),
        ]
        text = _format_evidence_summary(hyps)
        assert "EUR/USD" in text
        assert "XAU/USD" in text


class TestFragilityFormatting:
    """Fragility report formatting."""

    def test_fragility_format_includes_score(self):
        fr = make_fragility_report(0.42)
        text = _format_fragility(fr)
        assert "0.42" in text
        assert "脆弱" in text

    def test_fragility_format_empty_crossed(self):
        fr = make_fragility_report(0.15)
        text = _format_fragility(fr)
        assert "CRITICAL" not in text  # no crossed thresholds


class TestRegimeFormatting:
    """Historical regime analogue formatting."""

    def test_regime_format_includes_top3(self):
        rm = make_regime_mapping()
        text = _format_regime(rm)
        assert "1995" in text
        assert "2007" in text
        assert "2018" in text

    def test_regime_format_has_caution(self):
        rm = make_regime_mapping()
        text = _format_regime(rm)
        assert "不是预测" in text


class TestSignalConflictFormatting:
    """Signal conflict display formatting."""

    def test_conflict_format_shows_description(self):
        conflicts = make_signal_conflicts()
        text = _format_signal_conflicts(conflicts)
        assert "信号冲突" in text
        assert "因果分解" in text

    def test_conflict_format_empty_list(self):
        text = _format_signal_conflicts([])
        assert text == ""


class TestKillCriteriaFormatting:
    """Kill criteria display formatting."""

    def test_kill_criteria_format_shows_ids(self):
        kcs = make_kill_criteria()
        text = _format_kill_criteria(kcs)
        assert "KC-001" in text
        assert "KC-002" in text
        assert "EUR/USD" in text

    def test_kill_criteria_format_empty_list(self):
        text = _format_kill_criteria([])
        assert text == ""


class TestConvictionParsing:
    """Conviction number extraction."""

    def test_parse_conviction_digit(self):
        assert _parse_conviction("我觉得7成吧") == "7"

    def test_parse_conviction_ten(self):
        assert _parse_conviction("10成信心") == "10"

    def test_parse_conviction_english(self):
        assert _parse_conviction("about 8 out of 10") == "8"

    def test_parse_conviction_none(self):
        assert _parse_conviction("不太确定") is None


class TestOutcomeParsing:
    """Outcome intent parsing."""

    def test_parse_outcome_continue(self):
        assert _parse_outcome("确定继续") == "CONTINUE"

    def test_parse_outcome_modify(self):
        assert _parse_outcome("我想调整一下方向") == "MODIFY"

    def test_parse_outcome_pause(self):
        assert _parse_outcome("先暂停，等等再看") == "PAUSE"

    def test_parse_outcome_pause_english(self):
        assert _parse_outcome("let's park this") == "PAUSE"

    def test_parse_outcome_empty(self):
        assert _parse_outcome("看看再说") == ""


class TestGate2SessionDataClass:
    """Gate2Session dataclass initialization."""

    def test_default_values(self):
        s = Gate2Session(
            session_id="test-1",
            selected_direction="EUR/USD 看涨",
            state="START",
        )
        assert s.session_id == "test-1"
        assert s.selected_direction == "EUR/USD 看涨"
        assert s.state == "START"
        assert s.user_initial_conviction == ""
        assert s.final_conviction == ""
        assert s.key_risks_acknowledged == []
        assert s.kill_criteria_confirmed == []
        assert not s.signal_conflicts_resolved
        assert s.turns == 0
        assert s.outcome == ""
