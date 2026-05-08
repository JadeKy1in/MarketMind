"""
scout_types.py - Phase 5 (The Scout) core data structures.

Defines all data types for the active discovery layer:
  - AssetMappingField / AssetBasket  (3-dimensional asset allocation)
  - MacroTag / NarrativeTag          (macro narrative tagging)
  - NewsSignal / TriangleValidation  (signal extraction & validation)
  - SourceRecord / source_weight     (source governance ledger)
  - InvalidationTrigger / AuditorCheckpoint (causal invalidation state)
  - ContinuationState                (multi-turn API merge protocol)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Union
from enum import Enum
from dataclasses import dataclass


# =========================================================================
# NewsItem (moved from sentiment_collector.py — cross-module dependency)
# =========================================================================


@dataclass
class NewsItem:
    """A single news article with sentiment score.

    Originally defined in sentiment_collector.py (Phase 1-4),
    moved to scout_types.py in Phase 5 for cross-module type sharing.
    """
    title: str
    source: str
    publish_time: str
    summary: str = ""
    sentiment_score: float = 0.0  # -1.0 to 1.0


@dataclass
class SentimentReport:
    """Aggregated sentiment report."""
    overall_sentiment: str  # bullish / bearish / neutral
    avg_score: float
    item_count: int
    items: List[NewsItem]


# =========================================================================
# Asset Mapping
# =========================================================================


class AssetMappingField(Enum):
    """Three dimensions of the asset allocation matrix."""
    HIGH_LIQUIDITY = "high_liquidity"
    LOW_EXPENSE_RATIO = "low_expense_ratio"
    HIGH_BETA = "high_beta"


class AssetBasket:
    """Three-dimensional asset allocation basket.

    Maps a macro narrative to concrete tradeable tickers across
    the three dimensions: high-liquidity, low-expense-ratio, high-beta.
    """

    def __init__(
        self,
        high_liquidity: Optional[List[str]] = None,
        low_expense_ratio: Optional[List[str]] = None,
        high_beta: Optional[List[str]] = None,
    ):
        self.high_liquidity = high_liquidity or []
        self.low_expense_ratio = low_expense_ratio or []
        self.high_beta = high_beta or []

    def dimension_count(self) -> int:
        """Number of non-empty dimensions."""
        return sum(
            1 for d in [self.high_liquidity, self.low_expense_ratio, self.high_beta] if d
        )

    def all_tickers(self) -> List[str]:
        """Return deduplicated union of all tickers across dimensions."""
        seen: set[str] = set()
        result: list[str] = []
        for ticker in self.high_liquidity + self.low_expense_ratio + self.high_beta:
            if ticker not in seen:
                seen.add(ticker)
                result.append(ticker)
        return result

    def get(self, key: str) -> List[str]:
        """Access a dimension by key name (e.g. 'high_liquidity')."""
        return getattr(self, key, [])


# =========================================================================
# Macro Tagging
# =========================================================================


class MacroTag:
    """A macro narrative tag discovered by the Scout radar."""

    def __init__(
        self,
        narrative: str,
        category: str,
        confidence: float,
        related_assets: Optional[List[str]] = None,
        source_ids: Optional[List[str]] = None,
        source_weights: Union[float, Dict[str, float], None] = None,
    ):
        self.narrative = narrative
        self.category = category
        self.confidence = confidence
        self.related_assets = related_assets or []
        self.source_ids = source_ids or []
        # source_weights: either a single float (aggregate authority level)
        # or a dict mapping source name -> weight
        self.source_weights = source_weights


class NarrativeTag(MacroTag):
    """Extended macro tag with optional subcategory for finer granularity."""

    def __init__(
        self,
        narrative: str,
        category: str,
        confidence: float,
        related_assets: Optional[List[str]] = None,
        source_ids: Optional[List[str]] = None,
        source_weights: Union[float, Dict[str, float], None] = None,
        subcategory: Optional[str] = None,
    ):
        super().__init__(
            narrative=narrative,
            category=category,
            confidence=confidence,
            related_assets=related_assets,
            source_ids=source_ids,
            source_weights=source_weights,
        )
        self.subcategory = subcategory


# =========================================================================
# Source Governance — Signal & Triangle Validation
# =========================================================================


class TriangleValidation:
    """Result of a triangle validation check on a news signal.

    A narrative is considered "triangulated" when at least
    min_proofs_required independent official data sources corroborate it.
    """

    def __init__(
        self,
        matched_proofs: Optional[List[str]] = None,
        missing_proofs: Optional[List[str]] = None,
        is_passed: bool = False,
    ):
        self.matched_proofs = matched_proofs or []
        self.missing_proofs = missing_proofs or []
        self.is_passed = is_passed


class NewsSignal:
    """A single news signal extracted and governed by the SourceGovernor.

    Represents a candidate "macro narrative" that has passed through
    SAR filtering and (optionally) triangle validation.

    The full lifecycle:
        1. Raw NewsItem arrives from SentimentCollector
        2. SAR filter assigns authority_level and initial confidence
        3. Triangle validation updates validation_status and adjusts confidence
        4. Deduplication merges identical narratives
        5. (Optional) signals_to_macro_tags converts to MacroTag for downstream
    """

    def __init__(
        self,
        narrative: str,
        authority_level: float = 0.0,
        sentiment_score: float = 0.0,
        confidence: float = 0.0,
        sources: Optional[List[str]] = None,
        original_titles: Optional[List[str]] = None,
        validation_status: Optional[str] = None,
        validation: Optional[TriangleValidation] = None,
    ):
        self.narrative = narrative
        self.authority_level = authority_level
        self.sentiment_score = sentiment_score
        self.confidence = confidence
        self.sources = sources or []
        self.original_titles = original_titles or []
        self.validation_status = validation_status  # e.g. "passed", "partial", "failed"
        self.validation = validation

    def append_sources(self, new_sources: List[str]) -> None:
        """Merge new source names into self.sources, deduplicating."""
        seen = set(self.sources)
        for s in new_sources:
            if s not in seen:
                self.sources.append(s)
                seen.add(s)

    def append_titles(self, new_titles: List[str]) -> None:
        """Merge new titles into self.original_titles, deduplicating."""
        seen = set(self.original_titles)
        for t in new_titles:
            if t not in seen:
                self.original_titles.append(t)
                seen.add(t)


# =========================================================================
# Source Governance — Authority Weights
# =========================================================================


_SOURCE_WEIGHTS: Dict[str, float] = {
    "fred": 0.95,
    "eia": 0.90,
    "reuters": 0.80,
    "bloomberg": 0.85,
    "opec": 0.75,
    "finnhub": 0.60,
    "twitter": 0.20,
    "social_media": 0.10,
}


def source_weight(source_name: str) -> float:
    """Return the authority weight for a given source name (case-insensitive)."""
    return _SOURCE_WEIGHTS.get(source_name.lower(), 0.05)


class SourceRecord:
    """A governed source record with content hash and verification chain."""

    def __init__(
        self,
        source_id: str,
        source_name: str,
        url: str,
        publish_time: Optional[datetime] = None,
        content_hash: Optional[str] = None,
        summary: Optional[str] = None,
        verified_by: Optional[List[str]] = None,
    ):
        self.source_id = source_id
        self.source_name = source_name
        self.url = url
        self.publish_time = publish_time or datetime.now(timezone.utc)
        self.content_hash = content_hash
        self.summary = summary or ""
        self.verified_by = verified_by or []


# =========================================================================
# Causal Audit (Invalidation Triggers)
# =========================================================================


class InvalidationTrigger:
    """A single condition that, if met, invalidates its parent thesis.

    Fields aligned with causal_auditor.py's usage:
      - type:          trigger type string (macro / price / technical / news / time_decay)
      - condition:     human-readable condition description (e.g. "NFP > 250000")
      - asset:         optional ticker this trigger applies to
      - source_event_id: optional macro_calendar event_id for macro triggers
      - time_horizon:  timedelta after which the trigger auto-decays (default 48h)
      - created_at:    timestamp when the trigger was created
      - is_triggered:  whether this trigger has already fired
    """

    def __init__(
        self,
        type: str,
        condition: str,
        asset: Optional[str] = None,
        source_event_id: Optional[str] = None,
        time_horizon: Optional[timedelta] = None,
        created_at: Optional[datetime] = None,
        is_triggered: bool = False,
    ):
        self.type = type
        self.condition = condition
        self.asset = asset
        self.source_event_id = source_event_id
        self.time_horizon = time_horizon or timedelta(hours=48)
        self.created_at = created_at or datetime.now(timezone.utc)
        self.is_triggered = is_triggered


class AuditorCheckpoint:
    """A checkpoint recording a thesis recommendation and its invalidation triggers."""

    def __init__(
        self,
        checkpoint_id: str,
        narrative: str,
        recommendation: str,
        invalidation_triggers: Optional[List[InvalidationTrigger]] = None,
        score: Optional[float] = None,
        status: str = "active",
        invalidation_reason: Optional[str] = None,
        created_at: Optional[datetime] = None,
    ):
        self.checkpoint_id = checkpoint_id
        self.narrative = narrative
        self.recommendation = recommendation
        self.invalidation_triggers = invalidation_triggers or []
        self.score = score
        self.status = status
        self.invalidation_reason = invalidation_reason
        self.created_at = created_at or datetime.now(timezone.utc)

    def mark_invalidated(self, reason: str) -> None:
        """Mark this checkpoint as invalidated with a reason."""
        self.status = "invalidated"
        self.invalidation_reason = reason


# =========================================================================
# Continuation Protocol (Multi-turn API Merge)
# =========================================================================


class ContinuationState:
    """Tracks multi-turn API continuation fragments for long report generation."""

    def __init__(
        self,
        session_id: str,
        fragments: Optional[List[Dict[str, Any]]] = None,
        turn_count: int = 0,
        is_complete: bool = False,
        merged_json: Optional[Dict[str, Any]] = None,
    ):
        self.session_id = session_id
        self.fragments = fragments or []
        self.turn_count = turn_count
        self.is_complete = is_complete
        self.merged_json = merged_json

    def add_fragment(self, turn: int, fragment: Dict[str, Any]) -> None:
        """Register a new fragment and increment the turn counter."""
        self.fragments.append({"turn": turn, "data": fragment})
        self.turn_count += 1

    def merge_strict(self) -> Dict[str, Any]:
        """Deep-merge all fragments: concatenate strings, deduplicate lists."""
        merged: Dict[str, Any] = {}
        for entry in self.fragments:
            data = entry["data"]
            for key, value in data.items():
                if key not in merged:
                    merged[key] = _deep_copy(value)
                else:
                    existing = merged[key]
                    if isinstance(value, str) and isinstance(existing, str):
                        merged[key] = existing + " " + value
                    elif isinstance(value, list) and isinstance(existing, list):
                        # Deduplicate while preserving order
                        seen = set(existing)
                        for item in value:
                            if item not in seen:
                                seen.add(item)
                                existing.append(item)
                    else:
                        merged[key] = _deep_copy(value)
        return merged


def _deep_copy(value: Any) -> Any:
    """Simple deep copy helper for basic types (lists, dicts, scalars)."""
    if isinstance(value, list):
        return list(value)
    if isinstance(value, dict):
        return dict(value)
    return value


# =========================================================================
# Phase 6: Risk Engine & Dual-Track Decision Engine Types
# =========================================================================


class SellTriggerSource(Enum):
    """卖出触发源类型 (Phase 6 — Sell/Liquidate Protocol)."""
    MACRO_INVALIDATION = "macro_invalidation"
    TECHNICAL_BREAKDOWN = "technical_breakdown"
    PORTFOLIO_REBALANCING = "portfolio_rebalancing"


class RiskProfileLabel(Enum):
    """机会整体方向画像标签 (Phase 6 — Risk-Reward Profiling)."""
    ASYMMETRIC = "asymmetric"            # 低风险/高回报
    SPECULATIVE = "speculative"          # 高风险/高回报
    TREND_FOLLOWING = "trend_following"  # 中等风险/中等回报


# =========================================================================
# 第一层剖析: 机会整体方向画像 (RiskProfile)
# =========================================================================


@dataclass
class RiskProfile:
    """第一层剖析输出: 机会整体方向画像.

    Fields:
        profile_id: 画像唯一标识符
        narrative_ref: 引用的 MacroTag.narrative
        label: 风险画像标签 (ASYMMETRIC / SPECULATIVE / TREND_FOLLOWING)
        risk_reward_ratio: 盈亏比 (e.g. 3.5 表示 3.5:1)
        expected_upside_pct: 预期上涨百分比
        expected_downside_pct: 预期下跌百分比
        safety_margin_pct: 安全边际百分比
        confidence_rating: "HIGH" | "MEDIUM" | "LOW"
        rationale: 人类可读的画像依据 (100-300 字)
        triggering_conditions: 触发此画像的具体条件列表
        risk_warnings: 风险警示列表
        time_horizon: 预期持仓周期 (e.g. "3-6 months")
    """
    profile_id: str
    narrative_ref: str
    label: RiskProfileLabel
    risk_reward_ratio: float
    expected_upside_pct: float
    expected_downside_pct: float
    safety_margin_pct: float
    confidence_rating: str
    rationale: str
    triggering_conditions: List[str]
    risk_warnings: List[str]
    time_horizon: str


# =========================================================================
# 第二层剖析: 配置标的穿透分析 (AssetPenetrationItem)
# =========================================================================


@dataclass
class AssetPenetrationItem:
    """单个标的的穿透分析条目 (Phase 6 — Asset Class Penetration).

    Fields:
        ticker: 标的 Ticker 代码
        direction: "BUY" | "SELL"
        layer: 分层归属 ("core" / "upstream_leverage" / "downstream_related")
        layer_rationale: 为何归入此层
        suggested_weight_pct: 建议仓位占比 (% of buying_power)
        current_price: 当前市价
        limit_price: 建议限价单价格
        stop_loss: 建议止损价
        take_profit: 建议止盈价
        expected_return_pct: 预期回报率
        beta: Beta 系数
        correlation_warning: 相关性警告
        risk_note: 特殊风险提示
    """
    ticker: str
    direction: str
    layer: str
    layer_rationale: str
    suggested_weight_pct: float
    current_price: Optional[float] = None
    limit_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    expected_return_pct: Optional[float] = None
    beta: Optional[float] = None
    correlation_warning: Optional[str] = None
    risk_note: Optional[str] = None


# =========================================================================
# 完整订单建议 (OrderSuggestion)
# =========================================================================


@dataclass
class OrderSuggestion:
    """轨道 B 的最终输出: 完整订单建议结构 (Phase 6).

    Fields:
        order_id: 订单唯一标识符
        created_at: ISO 时间戳
        decision_track: 固定为 "ACTION_AND_ADJUST"
        action_type: "BUY" | "SELL" | "MIXED"
        risk_profile: 第一层风险画像
        penetration_items: 第二层标的穿透分析
        total_notional_commitment: 建议总投入金额
        cash_reserve_after: 操作后预估现金余额
        cash_reserve_pct: 操作后现金占比
        account_state_ref: 引用的账户状态快照
        causal_audit_refs: 引用的 AuditorCheckpoint ID 列表
        execution_disclaimer: 物理隔离标记 — 固定文案:
            "THEORETICAL OUTPUT ONLY - NO BROKERAGE API CONNECTED"
    """
    order_id: str
    created_at: str
    decision_track: str
    action_type: str
    risk_profile: RiskProfile
    penetration_items: List[AssetPenetrationItem]
    total_notional_commitment: float
    cash_reserve_after: float
    cash_reserve_pct: float
    account_state_ref: str
    causal_audit_refs: List[str]
    execution_disclaimer: str = (
        "THEORETICAL OUTPUT ONLY - NO BROKERAGE API CONNECTED"
    )


# =========================================================================
# 轨道 A: 市场演变推演 (MarketEvolutionReport)
# =========================================================================


@dataclass
class WatchPoint:
    """一个观察点定义 (Phase 6 — Observe & Wait).

    Fields:
        direction: 关注方向 (e.g. "cpi_trend")
        description: 人类可读描述
        current_value: 当前指标值
        activation_threshold: 激活阈值
        activation_operator: "gt" | "lt" | "cross_above" | "cross_below"
        activated_action: 触发后的预设动作描述
        data_source: 数据来源 (e.g. "BLS CPI release")
    """
    direction: str
    description: str
    current_value: float
    activation_threshold: float
    activation_operator: str
    activated_action: str
    data_source: str


@dataclass
class NarrativeThread:
    """一条暗流趋势 (Phase 6 — Observe & Wait).

    Fields:
        narrative: 趋势描述
        evidence_chain: 支撑证据链
        confidence: 置信度 (0.0 ~ 1.0)
    """
    narrative: str
    evidence_chain: List[str]
    confidence: float


@dataclass
class MarketEvolutionReport:
    """轨道 A 输出: 市场演变推演报告 (Phase 6).

    Fields:
        report_id: 报告唯一标识符
        created_at: ISO 时间戳
        decision_track: 固定为 "OBSERVE_AND_WAIT"
        trigger_scenario: 触发场景代号
            (CONTRADICTION / WEAK_OPPORTUNITY / AMBIGUOUS /
             SIDEWAYS / CRISIS_MODE)
        reason_for_observe: 不行动理由 (200 字)
        dark_currents: 当前暗流趋势 (至少 1 条)
        watch_points: 观察点列表 (至少 2 个)
        review_timeline: 建议复审时间 (e.g. "2026-05-08 after CPI release")
    """
    report_id: str
    created_at: str
    decision_track: str
    trigger_scenario: str
    reason_for_observe: str
    dark_currents: List[NarrativeThread]
    watch_points: List[WatchPoint]
    review_timeline: str


# =========================================================================
# 定性判定引擎输出 (QualitativeJudgment)
# =========================================================================


@dataclass
class QualitativeJudgment:
    """定性判定引擎的输出 (Phase 6 — Dual-Track Router).

    Fields:
        judgment_id: 判定唯一标识符
        timestamp: ISO 时间戳
        signal_coherence_score: 宏观信号一致性 (0-100)
        reward_risk_ratio: 盈亏比
        market_regime: 市场状态
            ("trending" | "mean_reverting" | "choppy" | "crisis")
        decision_track: 最终轨道路由
            ("OBSERVE_AND_WAIT" | "ACTION_AND_ADJUST")
        track_confidence: 判定置信度 (0.0 ~ 1.0)
        decision_rationale: 判定依据 (引用判定规则表)
        suggested_subtrack: 如果是 ACTION_AND_ADJUST, 分支建议
            ("BUY" | "SELL" | "MIXED" | None)
        observe_scenario: 如果是 OBSERVE_AND_WAIT, 场景代号
            ("CONTRADICTION" | "WEAK_OPPORTUNITY" | 等 | None)
    """
    judgment_id: str
    timestamp: str
    signal_coherence_score: float
    reward_risk_ratio: float
    market_regime: str
    decision_track: str
    track_confidence: float
    decision_rationale: str
    suggested_subtrack: Optional[str] = None
    observe_scenario: Optional[str] = None


# =========================================================================
# 卖出清仓报告 (LiquidationReport)
# =========================================================================


@dataclass
class LiquidationReport:
    """轨道 B — 卖出清仓报告 (Phase 6 — Sell/Liquidate Protocol).

    Fields:
        action: 固定为 "SELL"
        position_to_close: 需要清仓/减仓的持仓 Ticker
        current_shares: 当前持有股数
        suggested_liquidation_ratio: 建议清仓比例 (0.0 ~ 1.0)
            (1.0 = 全部清仓, 0.5 = 减半)
        trigger_source: 触发源类型 (SellTriggerSource)
        macro_trigger: 宏观触发事件描述 (e.g. "NFP: 320K vs 180K")
        technical_trigger: 技术触发条件 (e.g. "周线收盘跌破 60MA @ $142.30")
        evidence_chain: 支撑证据链 (至少 2 条独立证据)
        protective_stop: 保护性止损限价 (若不全部清仓)
        reason_narrative: 人类可读的卖出理由 (100-300 字)
        causal_audit_ref: 引用的因果检验 checkpoint_id
    """
    action: str = "SELL"
    position_to_close: str = ""
    current_shares: int = 0
    suggested_liquidation_ratio: float = 0.0
    trigger_source: SellTriggerSource = SellTriggerSource.PORTFOLIO_REBALANCING
    macro_trigger: Optional[str] = None
    technical_trigger: Optional[str] = None
    evidence_chain: Optional[List[str]] = None
    protective_stop: Optional[float] = None
    reason_narrative: str = ""
    causal_audit_ref: str = ""
