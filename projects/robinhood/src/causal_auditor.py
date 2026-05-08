"""
Causal Auditor - 因果检验与逻辑失效引擎 (Phase 5: The Scout)
职责:
  1. 为每个投资论点 (thesis) 注册 InvalidationTrigger 集
  2. 定期检查 trigger 是否已被市场数据或宏观事件触发 (market_fetcher + macro_calendar)
  3. 如果触发, 标记 Thesis 为 invalidated, 并记录触发理由
  4. 为 48 小时后的自动回测打分提供结构化数据
"""

import logging
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Tuple
from uuid import uuid4

from src.scout_types import (
    InvalidationTrigger,
    AuditorCheckpoint,
    MacroTag,
)
from src.market_fetcher import MarketFetcher, Quote
from src.macro_calendar import MacroCalendar

logger = logging.getLogger(__name__)


# =========================================================================
# 触发器分类常量
# =========================================================================

class TriggerType:
    """触发器类型枚举 (字符串常量, 避免引入额外 Enum 依赖)"""
    MACRO = "macro"              # 宏观数据触发 (NFP > 25万, CPI 超预期, etc.)
    PRICE = "price"              # 价格触发 (跌破/突破价位)
    TECHNICAL = "technical"      # 技术指标触发 (RSI > 70, MACD 死叉, etc.)
    NEWS = "news"                # 新闻情绪触发 (地缘事件升级, etc.)
    TIME_DECAY = "time_decay"    # 时间衰减 (48h 后自动回归中性)


# =========================================================================
# Thesis 生命周期状态机
# =========================================================================

class ThesisStatus:
    ACTIVE = "active"            # 论点有效, 未被触发
    INVALIDATED = "invalidated"  # 至少一个 trigger 被触发
    EXPIRED = "expired"          # 超过 time_horizon, 自动过期(不扣分)
    COMPLETED = "completed"      # 论点被完全验证(手动或48h后自动)


# =========================================================================
# CausalAuditor 主类
# =========================================================================

class CausalAuditor:
    """
    因果检验引擎。

    用法:
        auditor = CausalAuditor(market_fetcher, macro_calendar)
        checkpoint = auditor.create_checkpoint(
            narrative="Fed rate cut expected",
            recommendation="buy GLD",
            triggers=[InvalidationTrigger(...), ...]
        )
        # 之后检查
        auditor.check_all_active()  # 遍历所有 active checkpoint
    """

    def __init__(
        self,
        market_fetcher: Optional[MarketFetcher] = None,
        macro_calendar: Optional[MacroCalendar] = None,
        ttl_hours: int = 48,
    ):
        self._fetcher = market_fetcher
        self._calendar = macro_calendar
        self._ttl_seconds = ttl_hours * 3600

        # 活跃的检查点池: checkpoint_id -> AuditorCheckpoint
        self._active_checkpoints: Dict[str, AuditorCheckpoint] = {}
        # 历史归档: checkpoint_id -> AuditorCheckpoint
        self._archived_checkpoints: Dict[str, AuditorCheckpoint] = {}

    # ------------------------------------------------------------------
    # Checkpoint 生命周期
    # ------------------------------------------------------------------

    def create_checkpoint(
        self,
        narrative: str,
        recommendation: str,
        triggers: Optional[List[InvalidationTrigger]] = None,
        source_tags: Optional[List[MacroTag]] = None,
    ) -> AuditorCheckpoint:
        """
        创建一个新的因果检验检查点。

        自动生成唯一 checkpoint_id, 初始 status = "active"。
        """
        cid = self._gen_id(narrative)

        # 如果 narrative 是价格相关的, 自动添加价格失效触发器
        triggers = list(triggers) if triggers else []
        triggers.extend(self._auto_generate_triggers(narrative, recommendation))

        cp = AuditorCheckpoint(
            checkpoint_id=cid,
            narrative=narrative,
            recommendation=recommendation,
            invalidation_triggers=triggers,
            status=ThesisStatus.ACTIVE,
        )

        self._active_checkpoints[cid] = cp
        logger.info(
            "Checkpoint created [%s]: %s -> %s (%d trigger(s))",
            cid, narrative, recommendation, len(triggers),
        )
        return cp

    def get_checkpoint(self, checkpoint_id: str) -> Optional[AuditorCheckpoint]:
        """获取指定检查点 (先从 active 查, 再从 archive 查)。"""
        cp = self._active_checkpoints.get(checkpoint_id)
        if cp:
            return cp
        return self._archived_checkpoints.get(checkpoint_id)

    def get_active_checkpoints(self) -> List[AuditorCheckpoint]:
        """返回所有活跃检查点快照。"""
        return list(self._active_checkpoints.values())

    def get_archived_checkpoints(self) -> List[AuditorCheckpoint]:
        """返回所有已归档检查点快照。"""
        return list(self._archived_checkpoints.values())

    def count_active(self) -> int:
        """活跃检查点数量。"""
        return len(self._active_checkpoints)

    # ------------------------------------------------------------------
    # 失效检查 (核心逻辑)
    # ------------------------------------------------------------------

    def check_all_active(self) -> List[AuditorCheckpoint]:
        """
        遍历检查所有活跃 checkpoints 的 invalidation triggers。
        对触发的 trigger, 标记对应 checkpoint 为 invalidated。

        Returns:
            被 invalidated 的 checkpoints 列表
        """
        now = datetime.now(timezone.utc)
        invalidated: List[AuditorCheckpoint] = []

        check_ids = list(self._active_checkpoints.keys())

        for cid in check_ids:
            cp = self._active_checkpoints[cid]

            # 1. 检查 TTL 过期
            if self._is_expired(cp, now):
                cp.status = ThesisStatus.EXPIRED
                self._archive(cid)
                logger.info("Checkpoint expired [%s]: past %d hour TTL", cid, self._ttl_seconds // 3600)
                continue

            # 2. 检查每个 trigger
            for trigger in cp.invalidation_triggers:
                if trigger.is_triggered:
                    continue  # 已触发过

                triggered = self._evaluate_trigger(trigger, now)
                if triggered:
                    trigger.is_triggered = True
                    reason = self._build_invalidation_reason(trigger)
                    cp.mark_invalidated(reason)
                    invalidated.append(cp)
                    self._archive(cid)
                    logger.warning(
                        "Checkpoint INVALIDATED [%s]: %s (trigger: %s)",
                        cid, reason, trigger.condition,
                    )
                    break  # 一旦触发, 不再检查后续 trigger

        return invalidated

    def check_single(self, checkpoint_id: str) -> Optional[str]:
        """
        检查单个指定 checkpoints 的 triggers。

        Returns:
            invalidation_reason 或 None (未被触发)
        """
        cp = self.get_checkpoint(checkpoint_id)
        if not cp:
            logger.warning("Checkpoint not found: %s", checkpoint_id)
            return None

        if cp.status != ThesisStatus.ACTIVE:
            return None

        now = datetime.now(timezone.utc)

        # 检查 TTL 过期
        if self._is_expired(cp, now):
            cp.status = ThesisStatus.EXPIRED
            self._archive(cp.checkpoint_id)
            return None

        for trigger in cp.invalidation_triggers:
            if trigger.is_triggered:
                continue
            triggered = self._evaluate_trigger(trigger, now)
            if triggered:
                trigger.is_triggered = True
                reason = self._build_invalidation_reason(trigger)
                cp.mark_invalidated(reason)
                self._archive(cp.checkpoint_id)
                return reason

        return None

    def manual_invalidate(self, checkpoint_id: str, reason: str) -> bool:
        """手动强制失效 (供 PM 人工干预)。"""
        cp = self._active_checkpoints.get(checkpoint_id)
        if not cp:
            return False
        cp.mark_invalidated(f"[MANUAL] {reason}")
        self._archive(checkpoint_id)
        logger.info("Manual invalidation [%s]: %s", checkpoint_id, reason)
        return True

    # ------------------------------------------------------------------
    # 48 小时后自动回测打分
    # ------------------------------------------------------------------

    def score_checkpoint(self, checkpoint_id: str) -> Optional[float]:
        """
        对已归档检查点进行自动回测打分。

        评分规则:
          - 如果 thesis 被 invalidated 且 market 走势与预期相反: 0 分 (正确失效)
          - 如果 thesis 被 invalidated 但 market 走势与预期一致: -1 分 (误触发)
          - 如果 thesis expired 且 market 走势与预期一致: +1 分 (正确判断)
          - 如果 thesis expired 且市场走势与预期相反: 0 分 (中性)
          - 如果 thesis expired 且无明显走势: 0 分 (中性)

        Returns:
            score: -1.0 ~ 1.0 或 None (无法获取实时行情)
        """
        cp = self._archived_checkpoints.get(checkpoint_id)
        if not cp:
            logger.warning("Cannot score unknown checkpoint: %s", checkpoint_id)
            return None

        if cp.score is not None:
            return cp.score  # 已打分

        if not self._fetcher:
            logger.warning("No MarketFetcher available for scoring")
            return None

        # 从 recommendation 中提取 ticker
        tickers = self._extract_tickers(cp.recommendation)
        if not tickers:
            logger.info("No ticker in recommendation, skipping price scoring")
            cp.score = 0.0
            return 0.0

        # 获取当前价格
        quotes = self._fetcher.get_bulk_quotes(tickers)

        # 判断预期方向
        expected_bullish = self._is_bullish(cp.recommendation)

        # 对每个可报价的 ticker 打分
        scores: List[float] = []
        for sym, q in quotes.items():
            if q is None:
                continue
            price_score = self._price_to_score(q, expected_bullish)
            scores.append(price_score)

        if not scores:
            logger.warning("No price data for scoring %s", checkpoint_id)
            return 0.0

        # 综合评分: 信号一致性加权
        final_score = round(sum(scores) / len(scores), 2)

        # 根据 status 校准
        if cp.status == ThesisStatus.INVALIDATED:
            # 失效状态下, 预期信号应该弱才表示正确失效
            if expected_bullish:
                # 做多预期 -> 价格下跌才算正确失效
                final_score = 1.0 if final_score < 0 else -1.0
            else:
                # 做空预期 -> 价格上涨才算正确失效
                final_score = 1.0 if final_score > 0 else -1.0

        cp.score = final_score
        logger.info(
            "Checkpoint scored [%s]: %.2f (status=%s, tickers=%s)",
            checkpoint_id, final_score, cp.status, tickers,
        )

        return final_score

    # ------------------------------------------------------------------
    # 私有辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _gen_id(narrative: str) -> str:
        """生成唯一检查点 ID。"""
        raw = hashlib.md5(narrative.encode("utf-8")).hexdigest()[:8]
        short = str(uuid4())[:4]
        return f"CP-{raw}-{short}"

    def _is_expired(self, cp: AuditorCheckpoint, now: datetime) -> bool:
        """检查 TTL 是否过期。"""
        if not cp.created_at:
            return False
        elapsed = (now - cp.created_at).total_seconds()
        return elapsed > self._ttl_seconds

    def _archive(self, checkpoint_id: str) -> None:
        """将活跃 checkpoint 移至归档。"""
        cp = self._active_checkpoints.pop(checkpoint_id, None)
        if cp:
            self._archived_checkpoints[checkpoint_id] = cp
            logger.debug("Archived checkpoint: %s", checkpoint_id)

    def _evaluate_trigger(
        self, trigger: InvalidationTrigger, now: datetime
    ) -> bool:
        """
        评估单个 InvalidationTrigger 是否已被市场条件触发。

        根据 trigger.type 分发到不同的评估逻辑:
          - macro:   通过 macro_calendar 检查宏观数据对比
          - price:   通过 market_fetcher 检查价格突破
          - technical:  (预留) 技术指标检查
          - news:     (预留) 新闻情绪检查
          - time_decay: 检查创建时间+time_horizon<now
        """
        if trigger.type == TriggerType.TIME_DECAY:
            return self._eval_time_decay(trigger, now)

        if trigger.type == TriggerType.MACRO:
            return self._eval_macro(trigger)

        if trigger.type == TriggerType.PRICE:
            return self._eval_price(trigger)

        return False

    def _eval_time_decay(
        self, trigger: InvalidationTrigger, now: datetime
    ) -> bool:
        """时间衰减触发器: 如果当前时间 > trigger.created_at + time_horizon, 触发。"""
        horizon = trigger.time_horizon or timedelta(hours=48)
        created = trigger.created_at or now
        return now > created + horizon

    def _eval_macro(self, trigger: InvalidationTrigger) -> bool:
        """宏观数据对比触发器。"""
        if not self._calendar:
            return False

        event = self._calendar.get_event_by_id(trigger.source_event_id or "")
        if not event or event.actual is None:
            return False

        try:
            actual_val = float(event.actual)
        except (ValueError, TypeError):
            return False

        condition = trigger.condition
        for op in [">=", "<=", ">", "<", "==", "!="]:
            if op in condition:
                parts = condition.split(op, 1)
                if len(parts) == 2:
                    try:
                        threshold = float(parts[1].strip().replace(",", ""))
                        if op == ">=":
                            return actual_val >= threshold
                        if op == "<=":
                            return actual_val <= threshold
                        if op == ">":
                            return actual_val > threshold
                        if op == "<":
                            return actual_val < threshold
                        if op == "==":
                            return abs(actual_val - threshold) < 0.001
                        if op == "!=":
                            return abs(actual_val - threshold) >= 0.001
                    except (ValueError, IndexError):
                        continue
        return False

    def _eval_price(self, trigger: InvalidationTrigger) -> bool:
        """价格触发器: 检查 ticker 当前价格是否突破阈值价位。"""
        if not self._fetcher:
            return False

        condition = trigger.condition
        for op in [">=", "<=", ">", "<"]:
            if op in condition:
                parts = condition.split(op, 1)
                if len(parts) == 2:
                    ticker = parts[0].strip()
                    threshold_str = parts[1].strip()
                    if not ticker or not threshold_str:
                        continue
                    try:
                        threshold = float(threshold_str)
                    except ValueError:
                        continue

                    quote = self._fetcher.get_quote(ticker)
                    if quote is None:
                        return False

                    price = quote.current_price
                    if op == ">=":
                        return price >= threshold
                    if op == "<=":
                        return price <= threshold
                    if op == ">":
                        return price > threshold
                    if op == "<":
                        return price < threshold
        return False

    @staticmethod
    def _build_invalidation_reason(trigger: InvalidationTrigger) -> str:
        """构建失效原因字符串。"""
        return (
            f"TRIGGERED: {trigger.type.upper()} | "
            f"condition={trigger.condition} | "
            f"source_event_id={trigger.source_event_id or 'N/A'}"
        )

    @staticmethod
    def _auto_generate_triggers(
        narrative: str, recommendation: str
    ) -> List[InvalidationTrigger]:
        """
        根据 narrative 和 recommendation 自动推断可能的失效触发器。
        """
        triggers: List[InvalidationTrigger] = []
        text = f"{narrative} {recommendation}".lower()
        tickers = []

        for word in recommendation.split():
            w = word.strip().upper()
            if len(w) <= 5 and w.isalpha():
                tickers.append(w)

        for ticker in tickers:
            if "buy" in recommendation.lower() and ticker in recommendation.upper():
                triggers.append(
                    InvalidationTrigger(
                        type=TriggerType.PRICE,
                        condition=f"{ticker} < {ticker}_entry * 0.95",
                        source_event_id=f"PRICE_{ticker}",
                        time_horizon=timedelta(hours=48),
                    )
                )

        macro_keywords = {
            "rate_cut": ("FED_INTEREST_RATE", "FED rate cut", "macro"),
            "nfp": ("NFP_MONTHLY", "NFP", "macro"),
            "cpi": ("CPI_MONTHLY", "CPI", "macro"),
            "gdp": ("GDP_QUARTERLY", "GDP", "macro"),
            "geopolitical": ("GEOPOLITICAL_EVENT", "Geopolitical", "macro"),
            "inflation": ("CPI_MONTHLY", "Inflation data", "macro"),
        }

        for keyword, (evt_id, evt_name, evt_type) in macro_keywords.items():
            if keyword in text:
                triggers.append(
                    InvalidationTrigger(
                        type=TriggerType.MACRO,
                        condition=f"{evt_name} triggers invalidation",
                        source_event_id=evt_id,
                        time_horizon=timedelta(hours=48),
                    )
                )

        return triggers

    @staticmethod
    def _extract_tickers(recommendation: str) -> List[str]:
        """从推荐文本中提取可能 ticker (2-5个大写字母)。"""
        import re
        pattern = r'\b[A-Z]{2,5}\b'
        return list(set(re.findall(pattern, recommendation)))

    @staticmethod
    def _is_bullish(recommendation: str) -> bool:
        """判断推荐方向是做多还是做空。"""
        text = recommendation.lower()
        bull_signals = ["buy", "long", "bullish", "overweight"]
        bear_signals = ["sell", "short", "bearish", "underweight", "reduce"]

        bull_count = sum(1 for w in bull_signals if w in text)
        bear_count = sum(1 for w in bear_signals if w in text)

        return bull_count > bear_count

    @staticmethod
    def _price_to_score(quote: Quote, expected_bullish: bool) -> float:
        """将价格变化转换为评分 (-1.0 ~ 1.0)。"""
        change = quote.change_pct or 0.0

        if expected_bullish:
            score = max(-1.0, min(1.0, change / 5.0))
        else:
            score = max(-1.0, min(1.0, -change / 5.0))

        return round(score, 2)