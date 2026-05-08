"""
semantic_translator.py — Sprint 4: "人话翻译器"

核心职责：将底层数学统计数据转换为人类可读（面试级专业）的中文自然语言描述。
绝对禁止在最终输出中暴露 α, β, Var, E[θ] 等数学符号。

转换链路：
  1. 信心等级映射 — 数值评分 → 中文信心等级
  2. 不确定性描述 — 标准差/VaR/CVaR → 自然语言风险描述
  3. 影子对比解读 — Monte Carlo 对比结果 → 调仓预期收益/风险自然语言分析
  4. 信念叙事 — 信念命题 → 投资逻辑的一句话叙事

SPARC:
  Specification: V2.0 Sprint 4 — 语义翻译引擎
  Pseudocode: scores + stats + comparison → structured natural language
  Architecture: 纯函数式变换，无 I/O，无外部依赖
  Refinement: 中文输出，零数学符号泄漏
  Completion: 测试覆盖率 ≥ 85%
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# 信心等级
# ============================================================

@dataclass(frozen=True)
class ConfidenceLevel:
    """信心等级映射结果。

    Attributes:
        score: 原始数值评分 [0, 1]
        level_name: 中文等级名称
        description: 一句话描述
        color: 颜色编码（绿/黄/红）
    """
    score: float = 0.5
    level_name: str = "一般"
    description: str = "信号模糊，需更多证据确认"
    color: str = "#fbbc04"  # 黄色


# ============================================================
# 不确定性描述
# ============================================================

@dataclass(frozen=True)
class UncertaintyDescription:
    """不确定性分析结果。

    Attributes:
        risk_level: 风险等级（低/中/高/极高）
        volatility_desc: 波动性自然语言描述
        tail_risk_desc: 尾部风险自然语言描述
        max_loss_desc: 最大可能损失描述
        confidence_text: 置信区间的一句话描述
    """
    risk_level: str = "中等"
    volatility_desc: str = ""
    tail_risk_desc: str = ""
    max_loss_desc: str = ""
    confidence_text: str = ""


# ============================================================
# 影子对比解读
# ============================================================

@dataclass
class ShadowComparisonInterpretation:
    """Monte Carlo 影子对比的自然语言解读。

    Attributes:
        verdict: 综合判断（建议 vs 保持）
        improvement_desc: 预期收益改善描述
        risk_desc: 风险变化描述
        win_rate_desc: 胜率变化描述
        convergence_desc: 收敛性描述
        summary_paragraph: 完整的一段总结建议
        recommended_action: 推荐操作的一句话
    """
    verdict: str = "当前方案与建议方案差异不大"
    improvement_desc: str = ""
    risk_desc: str = ""
    win_rate_desc: str = ""
    convergence_desc: str = ""
    summary_paragraph: str = ""
    recommended_action: str = "建议保持当前仓位配置"


# ============================================================
# 完整翻译结果
# ============================================================

@dataclass
class TranslationResult:
    """单条建议的完整语义翻译结果。

    Attributes:
        ticker: 标的代码
        asset_name: 资产名称
        confidence: 信心等级
        uncertainty: 不确定性描述
        shadow_interpretation: 影子对比解读
        belief_narrative: 信念叙事
        action_narrative: 操作建议叙事
    """
    ticker: str = ""
    asset_name: str = ""
    confidence: ConfidenceLevel = field(default_factory=ConfidenceLevel)
    uncertainty: UncertaintyDescription = field(default_factory=UncertaintyDescription)
    shadow_interpretation: ShadowComparisonInterpretation = field(
        default_factory=ShadowComparisonInterpretation
    )
    belief_narrative: str = ""
    action_narrative: str = ""


# ============================================================
# 信心等级映射表
# ============================================================

_CONFIDENCE_MAP: List[Tuple[float, str, str, str]] = [
    (0.90, "极强", "几乎确信，证据链完整", "#1a7a34"),
    (0.75, "很强", "证据充分，置信度高", "#34a853"),
    (0.60, "较强", "有明确信号支持", "#7cb342"),
    (0.45, "一般", "信号模糊，需更多证据确认", "#fbbc04"),
    (0.25, "较弱", "证据不足，参考价值有限", "#ea7a35"),
    (0.00, "极弱", "主要依赖猜测，风险极高", "#ea4335"),
]

# 紧急程度 → 中文映射
_URGENCY_MAP = {
    "HIGH": "紧急",
    "MEDIUM": "中等",
    "LOW": "可选",
}

# 信念命题 → 中文叙事映射
_DEFAULT_BELIEF_NARRATIVES: Dict[str, str] = {
    "macro_us_recession_risk": "美国经济衰退风险上升，防御性配置需求增加",
    "macro_fed_rate_path": "美联储利率路径不确定，久期管理需谨慎",
    "macro_inflation_trend": "通胀趋势变化影响实际购买力与资产定价",
    "sentiment_market_greed": "市场情绪偏向贪婪，需警惕短期回调风险",
    "sector_tech_outperform": "科技板块相对优势明显，成长型配置具备吸引力",
    "sector_financial_stress": "金融板块承压，信贷环境收紧传导至估值",
    "sector_energy_weakness": "能源板块动能减弱，大宗商品周期面临拐点",
}


# ============================================================
# SemanticTranslator — 核心翻译器
# ============================================================


class SemanticTranslator:
    """"人话翻译器" — 将数学统计翻译为中文自然语言。

    用法:
        translator = SemanticTranslator()
        result = translator.translate_suggestion(
            ticker="SPY", asset_name="SPDR S&P 500 ETF",
            belief_score=0.75, urgency="MEDIUM",
            from_weight=0.34, to_weight=0.30,
            delta_shares=-5.0,
            belief_proposition="macro_us_recession_risk",
        )
        print(result.action_narrative)
    """

    def __init__(
        self,
        belief_narratives: Optional[Dict[str, str]] = None,
    ) -> None:
        """初始化翻译器。

        Args:
            belief_narratives: 自定义信念命题 → 中文叙事映射
        """
        self._narratives = {
            **_DEFAULT_BELIEF_NARRATIVES,
            **(belief_narratives or {}),
        }
        logger.info("SemanticTranslator initialized with %d narratives", len(self._narratives))

    # ============================================================
    # 公共 API
    # ============================================================

    def translate_suggestion(
        self,
        ticker: str,
        asset_name: str,
        belief_score: float,
        urgency: str,
        from_weight: float,
        to_weight: float,
        delta_shares: float,
        belief_proposition: str = "",
        current_stats: Optional[Dict[str, float]] = None,
        suggested_stats: Optional[Dict[str, float]] = None,
        comparison: Optional[Dict[str, float]] = None,
    ) -> TranslationResult:
        """翻译单条调仓建议为完整的自然语言描述。

        Args:
            ticker: 标的代码
            asset_name: 资产名称
            belief_score: 信念评分 [0, 1]
            urgency: 紧急程度 (HIGH/MEDIUM/LOW)
            from_weight: 当前权重
            to_weight: 建议权重
            delta_shares: 调仓股数
            belief_proposition: 信念命题 ID
            current_stats: 当前组合统计量 dict
            suggested_stats: 建议组合统计量 dict
            comparison: 对比结果 dict

        Returns:
            TranslationResult: 完整语义翻译
        """
        # 1. 信心等级
        confidence = self._map_confidence(belief_score)

        # 2. 不确定性描述（基于当前组合统计量）
        uncertainty = self._describe_uncertainty(current_stats)

        # 3. 影子对比解读
        shadow_interp = self._interpret_shadow_comparison(
            comparison, current_stats, suggested_stats,
        )

        # 4. 信念叙事
        belief_narrative = self._build_belief_narrative(
            belief_proposition, belief_score,
        )

        # 5. 操作建议叙事
        action_narrative = self._build_action_narrative(
            ticker, asset_name, from_weight, to_weight,
            delta_shares, urgency, confidence, belief_narrative,
        )

        return TranslationResult(
            ticker=ticker,
            asset_name=asset_name,
            confidence=confidence,
            uncertainty=uncertainty,
            shadow_interpretation=shadow_interp,
            belief_narrative=belief_narrative,
            action_narrative=action_narrative,
        )

    def translate_full_comparison(
        self,
        comparison: Any,  # ComparisonResult 或 dict
        optimizer_result: Any = None,  # OptimizerResult 或 dict
    ) -> ShadowComparisonInterpretation:
        """翻译完整的影子对比结果为自然语言。

        Args:
            comparison: ComparisonResult 或 dict
            optimizer_result: 可选的 OptimizerResult（用于获取总市值等信息）

        Returns:
            ShadowComparisonInterpretation
        """
        comp = comparison
        if not isinstance(comp, dict):
            comp = {
                "improvement": getattr(comparison, "improvement", 0.0),
                "risk_reduction": getattr(comparison, "risk_reduction", 0.0),
                "win_probability": getattr(comparison, "win_probability", 0.0),
                "convergence_score": getattr(comparison, "convergence_score", 0.5),
                "suggested_is_preferred": getattr(comparison, "suggested_is_preferred", False),
                "n_simulations": getattr(comparison, "n_simulations", 0),
            }

        # 解析当前和建议统计量
        if not isinstance(comparison, dict):
            cs = getattr(comparison, "current_stats", None)
            ss = getattr(comparison, "suggested_stats", None)
        else:
            cs = comparison.get("current_stats")
            ss = comparison.get("suggested_stats")

        current_stats_dict = (
            {"mean": cs.mean, "std": cs.std, "var": cs.var, "cvar": cs.cvar}
            if cs and hasattr(cs, "mean")
            else {}
        )
        suggested_stats_dict = (
            {"mean": ss.mean, "std": ss.std, "var": ss.var, "cvar": ss.cvar}
            if ss and hasattr(ss, "mean")
            else {}
        )

        return self._interpret_shadow_comparison(
            comp, current_stats_dict, suggested_stats_dict,
        )

    # ============================================================
    # 内部方法
    # ============================================================

    def _map_confidence(self, score: float) -> ConfidenceLevel:
        """将数值评分映射为中文信心等级。"""
        score = max(0.0, min(1.0, score))
        for threshold, level_name, desc, color in _CONFIDENCE_MAP:
            if score >= threshold:
                return ConfidenceLevel(
                    score=score,
                    level_name=level_name,
                    description=desc,
                    color=color,
                )
        return ConfidenceLevel()

    def _describe_uncertainty(
        self,
        stats: Optional[Dict[str, float]],
    ) -> UncertaintyDescription:
        """基于统计量生成不确定性自然语言描述。"""
        if not stats:
            return UncertaintyDescription(
                risk_level="未知",
                volatility_desc="暂无波动率数据",
                tail_risk_desc="无法评估尾部风险",
                max_loss_desc="无法评估最大损失",
                confidence_text="当前缺乏足够数据评估不确定性",
            )

        std = stats.get("std", 0.0)
        var = stats.get("var", 0.0)
        cvar = stats.get("cvar", 0.0)
        mean = stats.get("mean", 0.0)

        # 波动性描述
        if std < 0.02:
            volatility_desc = "波动性较低，走势相对平稳"
            risk_level = "低"
        elif std < 0.05:
            volatility_desc = "波动性适中，短期波动在可控范围内"
            risk_level = "中等"
        elif std < 0.10:
            volatility_desc = "波动性较高，价格震荡幅度较大"
            risk_level = "高"
        else:
            volatility_desc = "波动性极高，市场情绪剧烈波动"
            risk_level = "极高"

        # 尾部风险
        if cvar < -0.10:
            tail_risk_desc = "极端行情下可能面临显著亏损，需设置止损保护"
        elif cvar < -0.05:
            tail_risk_desc = "尾部风险可控，但极端行情仍需留意"
        elif cvar < 0:
            tail_risk_desc = "尾部风险较低，极端不利情景影响有限"
        else:
            tail_risk_desc = "极端情景下仍保持正收益，抗压能力较强"

        # 最大损失
        if var < -0.08:
            max_loss_desc = "在最不利情景下可能承受较大回撤"
        elif var < -0.04:
            max_loss_desc = "最不利情景的回撤幅度在可接受范围"
        elif var < 0:
            max_loss_desc = "即使最不利情景，损失也相对有限"
        else:
            max_loss_desc = "在几乎所有情景下均可保持正收益"

        # 置信区间描述
        if mean > 0:
            confidence_text = f"预期收益为正，但实际结果可能在 {abs(var)*100:.1f}% 亏损到 {mean*100:.1f}% 盈利之间波动"
        else:
            confidence_text = f"预期收益为负，{abs(var)*100:.1f}% 以内的亏损属于正常波动范围"

        return UncertaintyDescription(
            risk_level=risk_level,
            volatility_desc=volatility_desc,
            tail_risk_desc=tail_risk_desc,
            max_loss_desc=max_loss_desc,
            confidence_text=confidence_text,
        )

    def _interpret_shadow_comparison(
        self,
        comparison: Optional[Dict[str, Any]],
        current_stats: Optional[Dict[str, float]],
        suggested_stats: Optional[Dict[str, float]],
    ) -> ShadowComparisonInterpretation:
        """将影子对比结果翻译为自然语言。"""
        if not comparison:
            return ShadowComparisonInterpretation()

        improvement = float(comparison.get("improvement", 0.0))
        risk_reduction = float(comparison.get("risk_reduction", 0.0))
        win_prob = float(comparison.get("win_probability", 0.0))
        convergence = float(comparison.get("convergence_score", 0.5))
        preferred = bool(comparison.get("suggested_is_preferred", False))
        n_sims = int(comparison.get("n_simulations", 0))

        # — 预期收益改善描述 —
        if improvement > 0.02:
            improvement_desc = (
                f"调仓后预期收益显著提升 {improvement*100:.1f} 个百分点，"
                f"表明新配置在收益端具备明显优势"
            )
        elif improvement > 0.005:
            improvement_desc = (
                f"调仓后预期收益小幅改善 {improvement*100:.2f} 个百分点，"
                f"收益端呈正面贡献"
            )
        elif improvement > -0.005:
            improvement_desc = (
                f"调仓前后预期收益差异不足 {abs(improvement)*100:.2f} 个百分点，"
                f"收益端基本持平"
            )
        else:
            improvement_desc = (
                f"调仓后预期收益下降 {abs(improvement)*100:.2f} 个百分点，"
                f"但可能通过风险降低来补偿"
            )

        # — 风险描述 —
        if risk_reduction > 0.02:
            risk_desc = (
                f"风险水平显著降低 {risk_reduction*100:.1f} 个百分点，"
                f"新配置的组合稳定性明显提升"
            )
        elif risk_reduction > 0.005:
            risk_desc = (
                f"风险水平小幅降低 {risk_reduction*100:.2f} 个百分点，"
                f"组合波动性略有改善"
            )
        elif risk_reduction > -0.005:
            risk_desc = "调仓前后风险水平基本一致，未引入额外波动"
        else:
            risk_desc = (
                f"风险水平上升 {abs(risk_reduction)*100:.2f} 个百分点，"
                f"新配置的波动性有所增加，需确认是否匹配风险承受能力"
            )

        # — 胜率描述 —
        if win_prob > 0.02:
            win_rate_desc = (
                f"盈利概率提升 {win_prob*100:.1f} 个百分点，"
                f"新配置在更多市场情景下具备盈利潜力"
            )
        elif win_prob > 0.005:
            win_rate_desc = (
                f"盈利概率小幅改善 {win_prob*100:.2f} 个百分点"
            )
        elif win_prob > -0.005:
            win_rate_desc = "盈利概率基本不变"
        else:
            win_rate_desc = (
                f"盈利概率下降 {abs(win_prob)*100:.2f} 个百分点，"
                f"需关注是否被其他维度的改善所抵消"
            )

        # — 收敛性 —
        if convergence > 0.7:
            convergence_desc = (
                f"建议方案的结果一致性很好，{convergence*100:.0f}% 的模拟路径"
                f"显示出相似的改善趋势"
            )
        elif convergence > 0.4:
            convergence_desc = (
                f"建议方案的结果一致性中等，约 {convergence*100:.0f}% 的模拟路径"
                f"支持该配置方向"
            )
        else:
            convergence_desc = (
                f"建议方案的结果分歧较大，仅约 {convergence*100:.0f}% 的模拟路径"
                f"方向一致，需谨慎执行"
            )

        # — 裁决 —
        if preferred:
            if improvement > 0.02 and risk_reduction > 0:
                verdict = f"建议方案在收益和风险两个维度均优于当前方案"
            elif improvement > 0.02:
                verdict = f"建议方案的收益改善显著，可考虑执行调仓"
            else:
                verdict = f"建议方案总体略优，风控维度有正面贡献"
            recommended_action = "建议执行调仓，按建议比例调整仓位配置"
        else:
            if risk_reduction > 0.02:
                verdict = f"当前方案收益略好，但建议方案风险控制更优"
                recommended_action = "建议保持观望，或仅执行小幅调整"
            elif improvement < -0.02:
                verdict = f"当前方案在收益端优势明显，建议暂不调仓"
                recommended_action = "建议保持当前仓位配置，等待更明确的信号"
            else:
                verdict = f"两个方案差异不大，均可接受"
                recommended_action = "建议保持当前仓位配置"

        # — 综合段落 —
        summary_parts = [
            f"基于 {n_sims:,} 条 Monte Carlo 模拟路径的综合分析：",
        ]
        if improvement_desc:
            summary_parts.append(improvement_desc + "。")
        if risk_desc:
            summary_parts.append(risk_desc + "。")
        if convergence_desc:
            summary_parts.append(convergence_desc + "。")

        summary_paragraph = "".join(summary_parts)

        return ShadowComparisonInterpretation(
            verdict=verdict,
            improvement_desc=improvement_desc,
            risk_desc=risk_desc,
            win_rate_desc=win_rate_desc,
            convergence_desc=convergence_desc,
            summary_paragraph=summary_paragraph,
            recommended_action=recommended_action,
        )

    def _build_belief_narrative(
        self,
        proposition_id: str,
        score: float,
    ) -> str:
        """根据信念命题 ID 构建中文叙事。"""
        if not proposition_id:
            return "无特定信念支撑此决策"

        narrative = self._narratives.get(
            proposition_id,
            f"信念命题「{proposition_id}」评分 {score:.2f}",
        )

        # 根据评分调整语气
        if score >= 0.75:
            return f"核心驱动：{narrative}（信心极强）"
        elif score >= 0.5:
            return f"重要参考：{narrative}（信心较强）"
        else:
            return f"辅助参考：{narrative}（信心一般，需交叉验证）"

    def _build_action_narrative(
        self,
        ticker: str,
        asset_name: str,
        from_weight: float,
        to_weight: float,
        delta_shares: float,
        urgency: str,
        confidence: ConfidenceLevel,
        belief_narrative: str,
    ) -> str:
        """构建完整的操作建议叙事。"""
        direction = "加仓" if delta_shares > 0 else "减仓"
        urgency_cn = _URGENCY_MAP.get(urgency, urgency)

        # 构建叙事段落
        parts: List[str] = []

        # 第一句：操作概览
        parts.append(
            f"{ticker}（{asset_name}）：{direction}操作建议（{urgency_cn}）。"
        )

        # 第二句：权重变化
        if abs(delta_shares) >= 0.01:
            parts.append(
                f"建议将仓位权重从 {from_weight*100:.1f}% 调整至 {to_weight*100:.1f}%，"
                f"涉及 {abs(delta_shares):.1f} 股。"
            )
        else:
            parts.append(
                f"建议将仓位权重从 {from_weight*100:.1f}% 微调至 {to_weight*100:.1f}%。"
            )

        # 第三句：信念支撑
        if belief_narrative:
            parts.append(belief_narrative + "。")

        # 第四句：信心评估
        parts.append(
            f"当前对该判断的信心等级为「{confidence.level_name}」，"
            f"{confidence.description}。"
        )

        return "".join(parts)