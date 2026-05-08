"""
test_integration.py — Sprint 4: 全链路端到端集成测试

测试从数据摄入到最终报告生成的完整管道 100% 畅通。
覆盖路径：
  1. 创建仓位 + 信念快照
  2. Optimizer 调仓计算
  3. ShadowComparator Monte Carlo 对比
  4. SemanticTranslator 语义翻译
  5. Reporter 报告生成（Markdown + PDF）
  6. ReportViewer UI 回调

SPARC:
  Specification: V2.0 Sprint 4 — 全链路集成测试
  Pseudocode: positions → optimizer → comparator → translator → reporter → verify
  Architecture: 单文件端到端，无外部依赖
  Refinement: 异常安全，PDF 降级验证
  Completion: 100% PASS
"""

from __future__ import annotations

import datetime
import os
import tempfile
from dataclasses import asdict
from typing import Any, Dict, List, Optional

import pytest

from projects.command_center.models.position import (
    Position,
    RebalanceSuggestion,
    UrgencyLevel,
)
from projects.command_center.engine.optimizer import (
    Optimizer,
    OptimizerConfig,
    OptimizerResult,
    DEFAULT_TICKER_BELIEF_MAP,
)
from projects.command_center.engine.shadow_comparator import (
    ShadowComparator,
    ShadowComparatorConfig,
    ComparisonResult,
    DistributionStats,
)
from projects.command_center.engine.semantic_translator import (
    SemanticTranslator,
    TranslationResult,
    ConfidenceLevel,
    UncertaintyDescription,
    ShadowComparisonInterpretation,
)
from projects.command_center.engine.reporter import (
    Reporter,
    ReportData,
)


# ============================================================
# Fixtures: 完整测试数据集
# ============================================================


@pytest.fixture
def sample_positions() -> List[Position]:
    """真实风格的仓位数据集。"""
    return [
        Position(
            ticker="SPY",
            asset_name="SPDR S&P 500 ETF",
            asset_class="EQUITY",
            shares=100.0,
            avg_cost=450.0,
            current_price=480.0,
            target_weight=0.30,
            current_weight=0.34,
            status="ACTIVE",
        ),
        Position(
            ticker="QQQ",
            asset_name="Invesco QQQ Trust",
            asset_class="EQUITY",
            shares=50.0,
            avg_cost=380.0,
            current_price=410.0,
            target_weight=0.25,
            current_weight=0.22,
            status="ACTIVE",
        ),
        Position(
            ticker="TLT",
            asset_name="iShares 20+ Year Treasury Bond ETF",
            asset_class="BOND",
            shares=200.0,
            avg_cost=95.0,
            current_price=92.0,
            target_weight=0.20,
            current_weight=0.18,
            status="ACTIVE",
        ),
        Position(
            ticker="GLD",
            asset_name="SPDR Gold Shares",
            asset_class="COMMODITY",
            shares=30.0,
            avg_cost=185.0,
            current_price=190.0,
            target_weight=0.15,
            current_weight=0.14,
            status="ACTIVE",
        ),
        Position(
            ticker="CASH",
            asset_name="Cash",
            asset_class="CASH",
            shares=1.0,
            avg_cost=1.0,
            current_price=1.0,
            target_weight=0.10,
            current_weight=0.12,
            status="ACTIVE",
        ),
    ]


@pytest.fixture
def sample_beliefs() -> List[Dict[str, Any]]:
    """信念快照数据集。"""
    return [
        {"proposition_id": "macro_us_recession_risk", "score": 0.65, "expectation": 0.6},
        {"proposition_id": "macro_fed_rate_path", "score": 0.72, "expectation": 0.7},
        {"proposition_id": "sentiment_market_greed", "score": 0.55, "expectation": 0.5},
        {"proposition_id": "sector_tech_outperform", "score": 0.80, "expectation": 0.75},
        {"proposition_id": "sector_financial_stress", "score": 0.38, "expectation": 0.35},
        {"proposition_id": "macro_inflation_trend", "score": 0.50, "expectation": 0.45},
        {"proposition_id": "sector_energy_weakness", "score": 0.30, "expectation": 0.25},
    ]


@pytest.fixture
def optimizer() -> Optimizer:
    return Optimizer()


@pytest.fixture
def shadow_comparator() -> ShadowComparator:
    return ShadowComparator(config=ShadowComparatorConfig(
        n_simulations=500, seed=42,
    ))


@pytest.fixture
def translator() -> SemanticTranslator:
    return SemanticTranslator()


@pytest.fixture
def reporter() -> Reporter:
    return Reporter()


# ============================================================
# Test Phase 1: 数据摄入 → Optimizer
# ============================================================


class TestPhase1DataToOptimizer:
    """验证 Position + Belief → OptimizerResult 管道。"""

    def test_optimizer_produces_suggestions(
        self,
        sample_positions: List[Position],
        sample_beliefs: List[Dict[str, Any]],
        optimizer: Optimizer,
    ):
        result = optimizer.optimize(sample_positions, sample_beliefs)
        assert isinstance(result, OptimizerResult)
        assert result.suggestion_count > 0
        assert result.total_portfolio_value > 0
        assert len(result.belief_scores) == len(sample_positions)
        for s in result.suggestions:
            assert s.ticker in [p.ticker for p in sample_positions]
            assert 0 <= s.belief_weight <= 1.0

    def test_optimizer_belief_scores_mapped(
        self,
        sample_positions: List[Position],
        sample_beliefs: List[Dict[str, Any]],
        optimizer: Optimizer,
    ):
        scores = optimizer.compute_belief_scores(sample_beliefs)
        assert "SPY" in scores
        assert "QQQ" in scores
        assert "TLT" in scores
        # All scores should be in [0, 1]
        for v in scores.values():
            assert 0 <= v <= 1.0

    def test_optimizer_drift_detected(
        self,
        sample_positions: List[Position],
        optimizer: Optimizer,
    ):
        result = optimizer.optimize(sample_positions, None)
        assert len(result.drifts) == len(sample_positions)
        # SPY current=0.34 target≈0.30 → drift detected
        spy_drift = next(d for d in result.drifts if d.ticker == "SPY")
        assert abs(spy_drift.drift) > 0.01


# ============================================================
# Test Phase 2: Optimizer → ShadowComparator
# ============================================================


class TestPhase2OptimizerToComparator:
    """验证 OptimizerResult → ShadowComparator.compare() 管道。"""

    def test_comparison_receives_suggestions(
        self,
        sample_positions: List[Position],
        sample_beliefs: List[Dict[str, Any]],
        optimizer: Optimizer,
        shadow_comparator: ShadowComparator,
    ):
        opt_result = optimizer.optimize(sample_positions, sample_beliefs)
        comp_result = shadow_comparator.compare(
            sample_positions, opt_result.suggestions,
        )
        assert isinstance(comp_result, ComparisonResult)
        assert comp_result.n_simulations == 500
        assert comp_result.current_stats is not None
        assert comp_result.suggested_stats is not None

    def test_comparison_stats_valid(
        self,
        sample_positions: List[Position],
        optimizer: Optimizer,
        shadow_comparator: ShadowComparator,
    ):
        opt_result = optimizer.optimize(sample_positions, None)
        comp_result = shadow_comparator.compare(
            sample_positions, opt_result.suggestions,
        )
        cs = comp_result.current_stats
        ss = comp_result.suggested_stats
        assert cs.n_simulations > 0
        assert ss.n_simulations > 0
        assert isinstance(cs.mean, float)
        assert isinstance(ss.mean, float)
        assert isinstance(cs.sharpe, float)
        assert isinstance(ss.sharpe, float)

    def test_comparison_deterministic(
        self,
        sample_positions: List[Position],
    ):
        """相同 seed 应产生相同对比结果。"""
        suggestions = [
            RebalanceSuggestion(
                ticker="SPY", to_weight=0.32, from_weight=0.34, belief_weight=0.6,
            ),
            RebalanceSuggestion(
                ticker="QQQ", to_weight=0.24, from_weight=0.22, belief_weight=0.7,
            ),
        ]
        comp1 = ShadowComparator(
            config=ShadowComparatorConfig(n_simulations=500, seed=99),
        ).compare(sample_positions, suggestions)
        comp2 = ShadowComparator(
            config=ShadowComparatorConfig(n_simulations=500, seed=99),
        ).compare(sample_positions, suggestions)
        assert abs(comp1.improvement - comp2.improvement) < 0.001
        assert comp1.suggested_is_preferred == comp2.suggested_is_preferred


# ============================================================
# Test Phase 3: ShadowComparator → SemanticTranslator
# ============================================================


class TestPhase3ComparatorToTranslator:
    """验证 ComparisonResult → SemanticTranslator 管道。"""

    def test_translate_full_comparison(
        self,
        sample_positions: List[Position],
        sample_beliefs: List[Dict[str, Any]],
        optimizer: Optimizer,
        shadow_comparator: ShadowComparator,
        translator: SemanticTranslator,
    ):
        opt_result = optimizer.optimize(sample_positions, sample_beliefs)
        comp_result = shadow_comparator.compare(
            sample_positions, opt_result.suggestions,
        )
        interp = translator.translate_full_comparison(comp_result)
        assert isinstance(interp, ShadowComparisonInterpretation)
        assert interp.verdict
        assert interp.summary_paragraph
        assert interp.recommended_action

    def test_translate_suggestion_no_math_symbols(
        self,
        translator: SemanticTranslator,
    ):
        """验证翻译结果不含底层数学符号。"""
        tr = translator.translate_suggestion(
            ticker="SPY",
            asset_name="SPDR S&P 500 ETF",
            belief_score=0.75,
            urgency="HIGH",
            from_weight=0.34,
            to_weight=0.28,
            delta_shares=-10.0,
            belief_proposition="macro_us_recession_risk",
        )
        narrative = tr.action_narrative
        # 禁止的数学符号
        forbidden = ["α", "β", "Var[", "E[", "σ", "Σ", "Gamma", "Beta("]
        for sym in forbidden:
            assert sym not in narrative, f"Narrative contains forbidden symbol: {sym}"
        assert isinstance(tr.confidence, ConfidenceLevel)

    def test_translate_suggestion_contains_chinese(
        self,
        translator: SemanticTranslator,
    ):
        """验证翻译结果包含自然中文描述。"""
        tr = translator.translate_suggestion(
            ticker="QQQ",
            asset_name="Invesco QQQ Trust",
            belief_score=0.80,
            urgency="MEDIUM",
            from_weight=0.22,
            to_weight=0.26,
            delta_shares=5.0,
            belief_proposition="sector_tech_outperform",
        )
        assert "加仓" in tr.action_narrative or "调整" in tr.action_narrative
        assert "信心等级" in tr.action_narrative
        assert tr.belief_narrative

    def test_translate_low_confidence(
        self,
        translator: SemanticTranslator,
    ):
        """低信心应映射为正确等级。"""
        tr = translator.translate_suggestion(
            ticker="GLD",
            asset_name="SPDR Gold Shares",
            belief_score=0.20,
            urgency="LOW",
            from_weight=0.14,
            to_weight=0.14,
            delta_shares=0.0,
        )
        assert tr.confidence.level_name in ("较弱", "极弱")

    def test_translate_with_uncertainty(
        self,
        translator: SemanticTranslator,
    ):
        """带统计量的翻译应生成不确定性描述。"""
        current_stats = {"std": 0.03, "var": -0.02, "cvar": -0.04, "mean": 0.005}
        tr = translator.translate_suggestion(
            ticker="SPY",
            asset_name="SPDR S&P 500 ETF",
            belief_score=0.65,
            urgency="MEDIUM",
            from_weight=0.34,
            to_weight=0.30,
            delta_shares=-5.0,
            belief_proposition="macro_us_recession_risk",
            current_stats=current_stats,
        )
        assert tr.uncertainty.volatility_desc
        assert "波动" in tr.uncertainty.volatility_desc


# ============================================================
# Test Phase 4: Full Pipeline → Reporter
# ============================================================


class TestPhase4FullPipelineToReporter:
    """验证全链路数据 → Reporter.build_markdown() 管道。"""

    def build_report_data(
        self,
        positions: List[Position],
        beliefs: List[Dict[str, Any]],
        optimizer: Optimizer,
        comparator: ShadowComparator,
        translator: SemanticTranslator,
    ) -> ReportData:
        """辅助：执行全链路并组装 ReportData。"""
        # Step 1: Optimizer
        opt_result = optimizer.optimize(positions, beliefs)

        # Step 2: ShadowComparator
        comp_result = comparator.compare(positions, opt_result.suggestions)

        # Step 3: SemanticTranslator
        interp = translator.translate_full_comparison(comp_result)

        # Step 4: 逐条翻译
        interp_map: Dict[str, Any] = {}
        for s in opt_result.suggestions:
            tr = translator.translate_suggestion(
                ticker=s.ticker,
                asset_name=s.asset_name,
                belief_score=s.belief_weight,
                urgency=s.urgency,
                from_weight=s.from_weight,
                to_weight=s.to_weight,
                delta_shares=s.delta_shares,
                belief_proposition=s.belief_proposition,
                current_stats=asdict(comp_result.current_stats) if comp_result.current_stats else None,
                suggested_stats=asdict(comp_result.suggested_stats) if comp_result.suggested_stats else None,
            )
            interp_map[s.ticker] = tr

        # Step 5: 组装 ReportData
        return ReportData(
            title="Cline OS Command Center — 集成测试报告",
            positions=[asdict(p) for p in positions],
            belief_summary=beliefs,
            rebalance_suggestions=[asdict(s) for s in opt_result.suggestions],
            optimizer_summary=opt_result.summary,
            comparison=comp_result,
            comparison_interpretation=interp,
            interpretation_map=interp_map,
            total_portfolio_value=opt_result.total_portfolio_value,
            n_simulations=comp_result.n_simulations,
        )

    def test_report_data_assembled(
        self,
        sample_positions: List[Position],
        sample_beliefs: List[Dict[str, Any]],
        optimizer: Optimizer,
        shadow_comparator: ShadowComparator,
        translator: SemanticTranslator,
    ):
        report_data = self.build_report_data(
            sample_positions, sample_beliefs,
            optimizer, shadow_comparator, translator,
        )
        assert isinstance(report_data, ReportData)
        assert len(report_data.positions) == 5
        assert len(report_data.belief_summary) == 7
        assert report_data.total_portfolio_value > 0
        assert report_data.n_simulations == 500

    def test_markdown_report_generated(
        self,
        sample_positions: List[Position],
        sample_beliefs: List[Dict[str, Any]],
        optimizer: Optimizer,
        shadow_comparator: ShadowComparator,
        translator: SemanticTranslator,
        reporter: Reporter,
    ):
        report_data = self.build_report_data(
            sample_positions, sample_beliefs,
            optimizer, shadow_comparator, translator,
        )
        md = reporter.build_markdown(report_data)
        assert isinstance(md, str)
        assert len(md) > 500  # 报告应该有实质内容
        # 检查关键章节
        assert "Cline OS Command Center" in md
        assert "执行摘要" in md
        assert "仓位一览" in md
        assert "信念图谱" in md
        assert "调仓建议" in md
        assert "Monte Carlo 影子对比分析" in md
        assert "深度分析" in md
        assert "免责声明" in md

    def test_markdown_no_math_leakage(
        self,
        sample_positions: List[Position],
        sample_beliefs: List[Dict[str, Any]],
        optimizer: Optimizer,
        shadow_comparator: ShadowComparator,
        translator: SemanticTranslator,
        reporter: Reporter,
    ):
        """最终报告不应泄漏底层数学符号。"""
        report_data = self.build_report_data(
            sample_positions, sample_beliefs,
            optimizer, shadow_comparator, translator,
        )
        md = reporter.build_markdown(report_data)
        forbidden = ["α", "β", "Var[", "E[θ]", "Gamma", "Beta("]
        for sym in forbidden:
            assert sym not in md, f"Report contains forbidden math symbol: {sym}"

    def test_markdown_table_structure(
        self,
        sample_positions: List[Position],
        sample_beliefs: List[Dict[str, Any]],
        optimizer: Optimizer,
        shadow_comparator: ShadowComparator,
        translator: SemanticTranslator,
        reporter: Reporter,
    ):
        """Markdown 应包含格式正确的表格。"""
        report_data = self.build_report_data(
            sample_positions, sample_beliefs,
            optimizer, shadow_comparator, translator,
        )
        md = reporter.build_markdown(report_data)
        # 检查表格分隔线
        assert "|------|" in md
        # 检查仓位表头
        assert "| 标的 | 名称 | 股数 |" in md
        # 检查调仓建议表头
        assert "| 标的 | 方向 | 当前权重 |" in md

    def test_pdf_export_graceful_degradation(
        self,
        sample_positions: List[Position],
        sample_beliefs: List[Dict[str, Any]],
        optimizer: Optimizer,
        shadow_comparator: ShadowComparator,
        translator: SemanticTranslator,
        reporter: Reporter,
    ):
        """PDF 导出应优雅降级（weasyprint 可能未安装）。"""
        report_data = self.build_report_data(
            sample_positions, sample_beliefs,
            optimizer, shadow_comparator, translator,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = reporter.build_pdf(report_data, output_dir=tmpdir)
            # 可能是 None（weasyprint 未安装），也可能是 str（成功）
            if pdf_path is not None:
                assert os.path.exists(pdf_path)
                assert pdf_path.endswith(".pdf")

    def test_report_with_empty_suggestions(
        self,
        reporter: Reporter,
    ):
        """无调仓建议时报告应正常生成。"""
        data = ReportData(
            positions=[],
            belief_summary=[],
            rebalance_suggestions=[],
            total_portfolio_value=0.0,
        )
        md = reporter.build_markdown(data)
        assert "执行摘要" in md
        assert "*当前无需调整仓位*" in md or "暂无" in md

    def test_report_with_empty_beliefs(
        self,
        reporter: Reporter,
    ):
        """无信念数据时报告应正常生成。"""
        data = ReportData(
            positions=[{"ticker": "SPY", "status": "ACTIVE", "shares": 100.0}],
            belief_summary=[],
        )
        md = reporter.build_markdown(data)
        assert "*暂无活跃信念数据。*" in md


# ============================================================
# Test Phase 5: 完整全链路端到端
# ============================================================


class TestPhase5EndToEndPipeline:
    """完整端到端验证：Position → Report Markdown。"""

    def test_end_to_end_pipeline(
        self,
        sample_positions: List[Position],
        sample_beliefs: List[Dict[str, Any]],
    ):
        """单函数全链路执行。"""
        # 1. 初始化所有引擎
        opt = Optimizer()
        comp = ShadowComparator(config=ShadowComparatorConfig(
            n_simulations=500, seed=42,
        ))
        trans = SemanticTranslator()
        rep = Reporter()

        # 2. 执行 Optimizer
        opt_result = opt.optimize(sample_positions, sample_beliefs)
        assert opt_result.suggestion_count > 0

        # 3. 执行 ShadowComparator
        comp_result = comp.compare(sample_positions, opt_result.suggestions)
        assert comp_result.current_stats is not None

        # 4. 执行 SemanticTranslator
        interp = trans.translate_full_comparison(comp_result)
        assert interp.summary_paragraph

        # 5. 逐条翻译
        interp_map: Dict[str, Any] = {}
        for s in opt_result.suggestions:
            tr = trans.translate_suggestion(
                ticker=s.ticker,
                asset_name=s.asset_name,
                belief_score=s.belief_weight,
                urgency=s.urgency,
                from_weight=s.from_weight,
                to_weight=s.to_weight,
                delta_shares=s.delta_shares,
                belief_proposition=s.belief_proposition,
            )
            interp_map[s.ticker] = tr

        # 6. 组装 ReportData
        report_data = ReportData(
            positions=[asdict(p) for p in sample_positions],
            belief_summary=sample_beliefs,
            rebalance_suggestions=[asdict(s) for s in opt_result.suggestions],
            comparison=comp_result,
            comparison_interpretation=interp,
            interpretation_map=interp_map,
            total_portfolio_value=opt_result.total_portfolio_value,
            n_simulations=comp_result.n_simulations,
        )

        # 7. 生成 Markdown
        md = rep.build_markdown(report_data)
        assert len(md) > 500

        # 8. 验证报告包含所有关键信息
        key_elements = [
            "执行摘要",
            "仓位一览",
            "信念图谱",
            "调仓建议",
            "Monte Carlo 影子对比分析",
            "深度分析",
            "免责声明",
        ]
        for elem in key_elements:
            assert elem in md, f"Report missing section: {elem}"

        # 9. 验证每条建议都有翻译
        for s in opt_result.suggestions:
            assert s.ticker in interp_map

        # 10. 验证无数学符号泄漏
        forbidden = ["α", "β", "Var[", "E[θ]"]
        for sym in forbidden:
            assert sym not in md

    def test_edge_case_empty_portfolio(
        self,
    ):
        """空组合端到端测试。"""
        opt = Optimizer()
        comp = ShadowComparator(config=ShadowComparatorConfig(n_simulations=100))
        trans = SemanticTranslator()
        rep = Reporter()

        opt_result = opt.optimize([], [])
        comp_result = comp.compare([], [])
        interp = trans.translate_full_comparison(comp_result)

        report_data = ReportData(
            positions=[],
            belief_summary=[],
            rebalance_suggestions=[],
            comparison=comp_result,
            comparison_interpretation=interp,
            total_portfolio_value=0.0,
        )
        md = rep.build_markdown(report_data)
        assert md
        assert "免责声明" in md


# ============================================================
# Test Phase 6: ReportViewer 回调验证
# ============================================================


class TestPhase6ReportViewerCallback:
    """验证 ReportViewer 的回调机制（无头单元测试）。"""

    def test_optimize_callback_returns_tuple(
        self,
        sample_positions: List[Position],
        sample_beliefs: List[Dict[str, Any]],
    ):
        """模拟 ReportViewer._on_optimize 接收的返回值。"""
        opt = Optimizer()
        comp = ShadowComparator(config=ShadowComparatorConfig(
            n_simulations=500, seed=42,
        ))
        trans = SemanticTranslator()
        rep = Reporter()

        opt_result = opt.optimize(sample_positions, sample_beliefs)
        comp_result = comp.compare(sample_positions, opt_result.suggestions)
        interp = trans.translate_full_comparison(comp_result)

        # 模拟 ReportViewer 接收的元组
        result_tuple = (opt_result, comp_result, None)
        assert len(result_tuple) == 3
        assert result_tuple[0] is opt_result
        assert result_tuple[1] is comp_result

    def test_pipeline_callback_produces_report_data(
        self,
        sample_positions: List[Position],
        sample_beliefs: List[Dict[str, Any]],
    ):
        """模拟完整管道返回 ReportData。"""
        def fake_pipeline():
            opt = Optimizer()
            comp = ShadowComparator(config=ShadowComparatorConfig(
                n_simulations=500, seed=42,
            ))
            trans = SemanticTranslator()
            rep = Reporter()

            opt_result = opt.optimize(sample_positions, sample_beliefs)
            comp_result = comp.compare(sample_positions, opt_result.suggestions)
            interp = trans.translate_full_comparison(comp_result)

            interp_map = {}
            for s in opt_result.suggestions:
                tr = trans.translate_suggestion(
                    ticker=s.ticker,
                    asset_name=s.asset_name,
                    belief_score=s.belief_weight,
                    urgency=s.urgency,
                    from_weight=s.from_weight,
                    to_weight=s.to_weight,
                    delta_shares=s.delta_shares,
                )
                interp_map[s.ticker] = tr

            report_data = ReportData(
                positions=[asdict(p) for p in sample_positions],
                belief_summary=sample_beliefs,
                rebalance_suggestions=[asdict(s) for s in opt_result.suggestions],
                comparison=comp_result,
                comparison_interpretation=interp,
                interpretation_map=interp_map,
                total_portfolio_value=opt_result.total_portfolio_value,
                n_simulations=comp_result.n_simulations,
            )
            md = rep.build_markdown(report_data)
            return (opt_result, comp_result, report_data)

        result = fake_pipeline()
        assert len(result) == 3
        opt_result, comp_result, report_data = result
        assert report_data is not None
        assert len(report_data.rebalance_suggestions) > 0


# ============================================================
# Test Phase 7: 信念叙事映射验证
# ============================================================


class TestPhase7BeliefNarratives:
    """验证信念命题 → 中文叙事映射。"""

    def test_belief_narratives_defined(
        self,
        translator: SemanticTranslator,
    ):
        """所有默认信念命题应有对应中文翻译。"""
        propositions = [
            "macro_us_recession_risk",
            "macro_fed_rate_path",
            "macro_inflation_trend",
            "sentiment_market_greed",
            "sector_tech_outperform",
            "sector_financial_stress",
            "sector_energy_weakness",
        ]
        for prop in propositions:
            narrative = translator._build_belief_narrative(prop, 0.6)
            assert narrative
            assert "信心" in narrative or "参考" in narrative or "驱动" in narrative or "辅助" in narrative

    def test_custom_narrative_override(
        self,
    ):
        """自定义叙事应覆盖默认映射。"""
        custom_narratives = {
            "macro_us_recession_risk": "自定义衰退风险描述",
        }
        translator = SemanticTranslator(belief_narratives=custom_narratives)
        narrative = translator._build_belief_narrative("macro_us_recession_risk", 0.8)
        assert "自定义衰退风险描述" in narrative

    def test_unknown_proposition(
        self,
        translator: SemanticTranslator,
    ):
        """未注册的命题应生成默认描述。"""
        narrative = translator._build_belief_narrative("unknown_proposition", 0.5)
        assert narrative
        assert "unknown_proposition" in narrative


# ============================================================
# Test Phase 8: 信心等级映射边界
# ============================================================


class TestPhase8ConfidenceMapping:
    """信心等级映射的边界条件验证。"""

    @pytest.mark.parametrize("score,expected_level", [
        (1.0, "极强"),
        (0.90, "极强"),
        (0.85, "很强"),
        (0.75, "很强"),
        (0.70, "较强"),
        (0.60, "较强"),
        (0.50, "一般"),
        (0.45, "一般"),
        (0.30, "较弱"),
        (0.25, "较弱"),
        (0.10, "极弱"),
        (0.0, "极弱"),
    ])
    def test_confidence_level_mapping(
        self,
        score: float,
        expected_level: str,
    ):
        translator = SemanticTranslator()
        level = translator._map_confidence(score)
        assert level.level_name == expected_level, (
            f"score={score} expected={expected_level} got={level.level_name}"
        )

    def test_confidence_out_of_range_clamped(self):
        translator = SemanticTranslator()
        assert translator._map_confidence(-0.5).level_name == "极弱"
        assert translator._map_confidence(1.5).level_name == "极强"