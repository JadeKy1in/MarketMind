"""Virtual trade persistence — record, query, and close trades.

Extracted from shadow_state.py per modular architecture rules (§3.1).
All functions accept sqlite3.Connection — no dependency on ShadowStateDB.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from marketmind.shadows.shadow_data_types import VirtualTradeOpen, VirtualTrade


def record_trade_open(
    conn: sqlite3.Connection, shadow_id: str, trade: VirtualTradeOpen
) -> int:
    """Insert a new virtual trade and return its row ID."""
    cur = conn.execute(
        """INSERT INTO virtual_trades (shadow_id, ticker, direction,
           entry_price, position_size_pct, entry_date)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (shadow_id, trade.ticker, trade.direction,
         trade.entry_price, trade.position_size_pct, trade.entry_date)
    )
    conn.commit()
    return cur.lastrowid


def record_trade_close(
    conn: sqlite3.Connection, trade_id: int, exit_price: float,
    exit_reason: str, pnl_pct: float
) -> None:
    """Close a virtual trade with exit price and PnL."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn.execute(
        """UPDATE virtual_trades SET exit_price = ?, exit_date = ?,
           exit_reason = ?, pnl_pct = ? WHERE id = ?""",
        (exit_price, now, exit_reason, pnl_pct, trade_id)
    )
    conn.commit()


def get_open_trades(
    conn: sqlite3.Connection, shadow_id: str
) -> list[VirtualTrade]:
    """Return all open trades (exit_price IS NULL) for a shadow."""
    rows = conn.execute(
        "SELECT * FROM virtual_trades WHERE shadow_id = ? AND exit_price IS NULL",
        (shadow_id,)
    ).fetchall()
    return [_row_to_trade(r) for r in rows]


def get_trade_history(
    conn: sqlite3.Connection, shadow_id: str, limit: int = 90
) -> list[VirtualTrade]:
    """Return closed trades for a shadow, most recent first."""
    rows = conn.execute(
        """SELECT * FROM virtual_trades
           WHERE shadow_id = ? AND exit_price IS NOT NULL
           ORDER BY exit_date DESC
           LIMIT ?""",
        (shadow_id, limit)
    ).fetchall()
    return [_row_to_trade(r) for r in rows]


def _row_to_trade(row: sqlite3.Row) -> VirtualTrade:
    """Convert a virtual_trades row to a VirtualTrade dataclass."""
    return VirtualTrade(
        trade_id=row["id"],
        shadow_id=row["shadow_id"],
        ticker=row["ticker"],
        direction=row["direction"],
        entry_price=row["entry_price"],
        exit_price=row["exit_price"],
        position_size_pct=row["position_size_pct"],
        entry_date=row["entry_date"],
        exit_date=row["exit_date"],
        exit_reason=row["exit_reason"],
        pnl_pct=row["pnl_pct"],
        virtual_slippage_applied=row["virtual_slippage_applied"]
        if row["virtual_slippage_applied"] is not None else 0.0,
        confidence_discount_applied=row["confidence_discount_applied"]
        if row["confidence_discount_applied"] is not None else 0.0,
        paper_live_gap_ratio=row["paper_live_gap_ratio"]
        if row["paper_live_gap_ratio"] is not None else 0.0,
    )
