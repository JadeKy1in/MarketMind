"""Market price persistence — CRUD for market_prices table.

Extracted from shadow_state.py per modular architecture rules (§3.1).
All functions accept sqlite3.Connection — no dependency on ShadowStateDB.
"""
from __future__ import annotations

import sqlite3


def insert_market_price(
    conn: sqlite3.Connection, ticker: str, date: str, open_price: float,
    high: float, low: float, close: float, volume: int,
    next_day_return: float | None = None
) -> None:
    """Insert or replace a market price row (P2-4)."""
    conn.execute(
        """INSERT OR REPLACE INTO market_prices
           (ticker, date, open, high, low, close, volume, next_day_return)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (ticker, date, open_price, high, low, close, volume, next_day_return))
    conn.commit()


def get_market_prices(
    conn: sqlite3.Connection, ticker: str, start_date: str | None = None,
    end_date: str | None = None
) -> list[dict]:
    """Get market prices for a ticker, optionally filtered by date range.

    Returns rows ordered by date ascending. Each row is a dict with keys
    matching the market_prices table columns.
    """
    if start_date and end_date:
        rows = conn.execute(
            """SELECT * FROM market_prices WHERE ticker = ? AND date >= ? AND date <= ?
               ORDER BY date ASC""",
            (ticker, start_date, end_date)).fetchall()
    elif start_date:
        rows = conn.execute(
            """SELECT * FROM market_prices WHERE ticker = ? AND date >= ?
               ORDER BY date ASC""",
            (ticker, start_date)).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM market_prices WHERE ticker = ? ORDER BY date ASC""",
            (ticker,)).fetchall()
    return [dict(r) for r in rows]


def get_next_day_return(
    conn: sqlite3.Connection, ticker: str, date: str
) -> float | None:
    """Get next_day_return for a ticker on a given date.

    Returns None if no price row exists for the ticker+date pair.
    """
    row = conn.execute(
        "SELECT next_day_return FROM market_prices WHERE ticker = ? AND date = ?",
        (ticker, date)).fetchone()
    return row["next_day_return"] if row else None
