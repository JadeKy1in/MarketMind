"""
position.py — V2.0 Position Data Models (Sprint 1)

Position 和 RebalanceSuggestion 是不可变数据模型，与 SQLite 表一一对映。
保持与 belief_types.py 一致的 frozen dataclass 风格。

SPARC:
  Specification: PM 批准的 V2.0 蓝图 §三-1
  Pseudocode: frozen dataclass + to_dict/from_dict
  Architecture: 与 gateway/task_queue.py 解耦 — position 是纯数据
  Refinement: mark_for_update() 模式用于批量更新
  Completion: Sprint 1 可测试
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ============================================================
# 时间戳 & ID 生成器（与 belief_types.py 风格一致）
# ============================================================

def _auto_iso() -> str:
    """Current UTC timestamp, ISO-8601 with 'Z' suffix."""
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    ) + "Z"


def _auto_uuid() -> str:
    """Random UUID4 string."""
    return str(uuid.uuid4())


# ============================================================
# Enums
# ============================================================

class AssetClass:
    EQUITY = "EQUITY"
    BOND = "BOND"
    COMMODITY = "COMMODITY"
    CASH = "CASH"
    CRYPTO = "CRYPTO"


class PositionStatus:
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    WATCHLIST = "WATCHLIST"


class UrgencyLevel:
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# ============================================================
# Data Models
# ============================================================

@dataclass(frozen=True)
class Position:
    """与 SQLite positions 表一一对应的不可变仓位数据模型。

    Invariants:
      I1 — shares >= 0（不支持做空，做空用负数表示）
      I2 — avg_cost >= 0
      I3 — target_weight in [0.0, 1.0]
      I4 — ticker 必须大写且非空

    Args:
        id: 唯一标识（UUID4）
        ticker: 标的代码（大写，如 'TSLA'）
        asset_name: 资产名称
        asset_class: 资产类别
        shares: 持仓股数（>=0）
        avg_cost: 平均成本价（>=0）
        current_price: 当前市价（0 表示未更新）
        target_weight: 目标配置权重 [0, 1]
        current_weight: 当前实际权重（计算字段，可缓存的）
        status: 状态 (ACTIVE/CLOSED/WATCHLIST)
        notes: PM 备注
        created_at: ISO-8601 UTC
        updated_at: ISO-8601 UTC
    """
    id: str = field(default_factory=_auto_uuid)
    ticker: str = ""
    asset_name: str = ""
    asset_class: str = AssetClass.EQUITY
    shares: float = 0.0
    avg_cost: float = 0.0
    current_price: float = 0.0
    target_weight: float = 0.0
    current_weight: float = 0.0
    status: str = PositionStatus.ACTIVE
    notes: str = ""
    created_at: str = field(default_factory=_auto_iso)
    updated_at: str = field(default_factory=_auto_iso)

    def __post_init__(self) -> None:
        if not self.ticker or not self.ticker.strip():
            raise ValueError("ticker must not be empty")
        if self.ticker != self.ticker.strip().upper():
            # Auto-uppercase ticker
            object.__setattr__(self, "ticker", self.ticker.strip().upper())
        if self.shares < 0:
            raise ValueError(f"shares must be >= 0; got {self.shares}")
        if self.avg_cost < 0:
            raise ValueError(f"avg_cost must be >= 0; got {self.avg_cost}")
        if not (0.0 <= self.target_weight <= 1.0):
            raise ValueError(
                f"target_weight must be in [0, 1]; got {self.target_weight}"
            )

    @property
    def market_value(self) -> float:
        """当前市值 = shares × current_price"""
        return self.shares * self.current_price

    @property
    def pnl(self) -> float:
        """未实现盈亏 = (current_price - avg_cost) × shares"""
        return (self.current_price - self.avg_cost) * self.shares

    @property
    def pnl_pct(self) -> float:
        """盈亏百分比。avg_cost=0 时返回 0。"""
        if self.avg_cost <= 0:
            return 0.0
        return (self.current_price - self.avg_cost) / self.avg_cost * 100.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Position":
        return cls(**data)

    def with_update(self, **kwargs) -> "Position":
        """返回一个更新了指定字段的新 Position（不可变模式）。

        用法:
            pos = pos.with_update(current_price=150.0, notes="财报超预期")
        """
        merged = self.to_dict()
        merged.update(kwargs)
        merged["updated_at"] = _auto_iso()
        return Position(**merged)


@dataclass(frozen=True)
class RebalanceSuggestion:
    """单条调仓建议数据模型。

    Args:
        ticker: 标的代码
        asset_name: 资产名称
        from_weight: 当前权重
        to_weight: 建议权重
        delta_shares: 需要买卖的股数（正=买入，负=卖出）
        belief_weight: 调仓时的信念权重 [0, 1]
        belief_proposition: 调仓依据的信念命题原文
        narrative: SemanticTranslator 生成的自然语言解释
        urgency: HIGH/MEDIUM/LOW
        reason_short: 一句话原因（用于表格展示）
    """
    ticker: str = ""
    asset_name: str = ""
    from_weight: float = 0.0
    to_weight: float = 0.0
    delta_shares: float = 0.0
    belief_weight: float = 0.0
    belief_proposition: str = ""
    narrative: str = ""
    urgency: str = UrgencyLevel.MEDIUM
    reason_short: str = ""

    def __post_init__(self) -> None:
        if not self.ticker:
            raise ValueError("ticker must not be empty")
        if not (0.0 <= self.belief_weight <= 1.0):
            raise ValueError(
                f"belief_weight must be in [0, 1]; got {self.belief_weight}"
            )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RebalanceSuggestion":
        return cls(**data)