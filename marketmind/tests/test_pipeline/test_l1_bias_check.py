"""Tests for L1 Bias Check (H8 PMV pattern-based bias detection)."""
import pytest
from unittest.mock import MagicMock, patch

from marketmind.pipeline.l1_bias_check import run_bias_check


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def state_no_evals():
    """State with no AI evaluations and no user ideas."""
    state = MagicMock()
    state.ai_evaluations = []
    state.user_ideas = []
    return state


@pytest.fixture
def state_normal():
    """State with moderate evaluations and user ideas — no warnings expected."""
    state = MagicMock()
    state.ai_evaluations = [
        "This idea has some risks but could work.",
        "I disagree with this approach, consider alternatives.",
    ]
    state.user_ideas = ["Buy AAPL if it drops 5%"]
    return state


# ── run_bias_check tests ───────────────────────────────────────────────────

class TestRunBiasCheck:
    def test_no_evals_no_warning(self, state_no_evals, capsys):
        run_bias_check(state_no_evals)
        captured = capsys.readouterr()
        assert "偏差预警" not in captured.out

    def test_few_evals_no_warning(self, capsys):
        """With fewer than 2 evaluations, no sycophancy warning even at 100% agree."""
        state = MagicMock()
        state.ai_evaluations = ["同意，这是一个好主意"]
        state.user_ideas = []
        run_bias_check(state)
        captured = capsys.readouterr()
        assert "偏差预警" not in captured.out

    def test_high_agreement_warning(self, capsys):
        """80%+ agreement with 2+ evals should trigger sycophancy warning."""
        state = MagicMock()
        state.ai_evaluations = [
            "同意这个分析",
            "你的判断合理",
            "有道理，支持",
            "Good analysis, agree",
        ]
        state.user_ideas = []
        run_bias_check(state)
        captured = capsys.readouterr()
        assert "阿谀偏差" in captured.out

    def test_low_agreement_no_warning(self, capsys):
        """Below 80% agreement should not trigger warning."""
        state = MagicMock()
        state.ai_evaluations = [
            "不同意这个观点",
            "有风险需要注意",
            "I disagree with parts of this",
            "同意部分内容",
        ]
        state.user_ideas = []
        run_bias_check(state)
        captured = capsys.readouterr()
        assert "阿谀偏差" not in captured.out

    def test_boundary_80_percent_2_evals(self, capsys):
        """Exactly 80% agreement with 2 evaluations: one agree, one not."""
        state = MagicMock()
        state.ai_evaluations = [
            "我觉得很有道理",      # agree
            "not sure about this",  # not agree
        ]
        state.user_ideas = []
        run_bias_check(state)
        captured = capsys.readouterr()
        # 1 out of 2 = 50%, not >= 80%
        assert "阿谀偏差" not in captured.out

    def test_all_agree_english_markers(self, capsys):
        """Test with English agree markers."""
        state = MagicMock()
        state.ai_evaluations = [
            "I agree with your assessment",
            "Your analysis is correct",
            "That is a valid point",
        ]
        state.user_ideas = []
        run_bias_check(state)
        captured = capsys.readouterr()
        assert "阿谀偏差" in captured.out

    # Counterfactual checks
    def test_counterfactual_in_ideas_no_warning(self, capsys):
        """User has counterfactual phrases — no counterfactual warning."""
        state = MagicMock()
        state.ai_evaluations = ["good idea"]
        state.user_ideas = [
            "Buy AAPL",
            "如果市场反转怎么办",
        ]
        run_bias_check(state)
        captured = capsys.readouterr()
        assert "反向情景" not in captured.out

    def test_no_counterfactual_with_two_ideas_warning(self, capsys):
        """2+ user ideas without counterfactual language triggers warning."""
        state = MagicMock()
        state.ai_evaluations = ["ok"]
        state.user_ideas = [
            "Invest in tech stocks",
            "Buy gold as hedge",
        ]
        run_bias_check(state)
        captured = capsys.readouterr()
        assert "反向情景" in captured.out

    def test_no_counterfactual_only_one_idea_no_warning(self, capsys):
        """Only 1 user idea without counterfactual — not enough to trigger."""
        state = MagicMock()
        state.ai_evaluations = ["ok"]
        state.user_ideas = ["Buy AAPL"]
        run_bias_check(state)
        captured = capsys.readouterr()
        assert "反向情景" not in captured.out

    def test_counterfactual_chinese_wanyiyi(self, capsys):
        """'万一' should count as counterfactual."""
        state = MagicMock()
        state.ai_evaluations = ["ok"]
        state.user_ideas = [
            "做多黄金",
            "万一美元走强怎么办",
        ]
        run_bias_check(state)
        captured = capsys.readouterr()
        assert "反向情景" not in captured.out  # has counterfactual, so should NOT warn

    def test_counterfactual_xiangfan(self, capsys):
        """'相反' should count as counterfactual."""
        state = MagicMock()
        state.ai_evaluations = ["ok"]
        state.user_ideas = [
            "长期看涨油",
            "相反的情况是什么",
        ]
        run_bias_check(state)
        captured = capsys.readouterr()
        assert "反向情景" not in captured.out

    def test_counterfactual_what_if(self, capsys):
        """'what if' should count as counterfactual (case-sensitive: must be lowercase)."""
        state = MagicMock()
        state.ai_evaluations = ["ok"]
        state.user_ideas = [
            "Long bonds",
            "what if rates rise again?",
        ]
        run_bias_check(state)
        captured = capsys.readouterr()
        assert "反向情景" not in captured.out

    def test_both_warnings_triggered(self, capsys):
        """Both sycophancy AND counterfactual warnings fire simultaneously."""
        state = MagicMock()
        state.ai_evaluations = [
            "同意，非常好的分析",
            "很有道理，支持",
            "这个分析是valid的",  # contains "valid" → counts as agree
        ]
        state.user_ideas = [
            "Invest in AI stocks",
            "Buy more crypto",
        ]
        run_bias_check(state)
        captured = capsys.readouterr()
        assert "阿谀偏差" in captured.out
        assert "反向情景" in captured.out

    def test_empty_ideas_with_high_agreement(self, capsys):
        """High agreement but no user ideas — only sycophancy warning."""
        state = MagicMock()
        state.ai_evaluations = [
            "同意",
            "有道理，支持这个观点",
        ]
        state.user_ideas = []
        run_bias_check(state)
        captured = capsys.readouterr()
        assert "阿谀偏差" in captured.out
        assert "反向情景" not in captured.out
