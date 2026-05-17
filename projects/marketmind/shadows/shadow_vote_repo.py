"""Vote and ranking persistence for shadow ecosystem (INTERNAL-ONLY).

These functions support the shadow competition ecosystem — ranked analyst shadows
that compete internally for signal quality. Vote persistence exists for
BACKTEST validation (backtest_runner.py) and crystallization hypothesis testing.
It is NOT used as input to the live decision pipeline (app.py:110 sets
shadow_votes = None by design).

Extracted from shadow_state.py per modular architecture rules (§3.1).
All functions accept sqlite3.Connection — no dependency on ShadowStateDB.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger("marketmind.shadows.shadow_vote_repo")


# ── Rankings ────────────────────────────────────────────────────────────────

def save_rankings(
    conn: sqlite3.Connection, date: str,
    rankings: list[tuple[str, float, float, dict]]
) -> None:
    """Persist shadow rankings for a given date."""
    for rank, (shadow_id, composite, deflated, components) in enumerate(rankings, 1):
        conn.execute(
            """INSERT OR REPLACE INTO ranking_history
               (date, shadow_id, rank, composite_score, deflated_score, component_scores)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (date, shadow_id, rank, composite, deflated,
             json.dumps(components))
        )
    conn.commit()


def get_ranking_history(
    conn: sqlite3.Connection, shadow_id: str, days: int = 90
) -> list[dict]:
    """Get ranking history for a shadow, most recent first."""
    rows = conn.execute(
        """SELECT * FROM ranking_history
           WHERE shadow_id = ?
           ORDER BY date DESC
           LIMIT ?""",
        (shadow_id, days)
    ).fetchall()
    results = []
    for r in rows:
        try:
            comp = json.loads(r["component_scores"])
        except json.JSONDecodeError:
            logger.warning("Corrupted component_scores for shadow=%s on %s",
                           r["shadow_id"], r["date"])
            comp = {}
        results.append({
            "date": r["date"], "shadow_id": r["shadow_id"],
            "rank": r["rank"], "composite_score": r["composite_score"],
            "deflated_score": r["deflated_score"],
            "component_scores": comp,
        })
    return results


# ── Vote lookup / persistence ──────────────────────────────────────────────

def get_all_active_votes(
    conn: sqlite3.Connection, date: str, ticker: str
) -> list[dict]:
    """Get a list of active non-eliminated, non-challenger shadows with vote metadata."""
    rows = conn.execute(
        """SELECT s.id, s.shadow_type, s.display_name
           FROM shadows s
           WHERE s.status != 'eliminated' AND s.shadow_type != 'challenger'
           ORDER BY s.id"""
    ).fetchall()
    return [{"shadow_id": r["id"], "shadow_type": r["shadow_type"],
             "display_name": r["display_name"],
             "date": date, "ticker": ticker} for r in rows]


def get_next_day_return_sign(
    conn: sqlite3.Connection, ticker_or_shadow: str, date: str
) -> int | None:
    """Get return sign for a ticker/shadow on a date. 1=positive, -1=negative, None=no data."""
    row = conn.execute(
        """SELECT pnl_pct FROM virtual_trades
           WHERE ticker = ? AND exit_date = ? AND pnl_pct IS NOT NULL
           LIMIT 1""",
        (ticker_or_shadow, date)
    ).fetchone()
    if row and row["pnl_pct"] is not None:
        return 1 if row["pnl_pct"] > 0 else -1
    snap_row = conn.execute(
        """SELECT daily_return_pct FROM daily_snapshots
           WHERE shadow_id = ? AND date = ? AND daily_return_pct IS NOT NULL
           LIMIT 1""",
        (ticker_or_shadow, date)
    ).fetchone()
    if snap_row and snap_row["daily_return_pct"] is not None:
        return 1 if snap_row["daily_return_pct"] > 0 else -1
    return None


def save_votes(
    conn: sqlite3.Connection, shadow_id: str, date: str, votes: list
) -> None:
    """Persist shadow votes for backtest/audit. Uses executemany for batch insert."""
    if not votes:
        return
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        (shadow_id, date, v.ticker, v.direction, v.confidence,
         getattr(v, 'thesis', '') or '', getattr(v, 'risk_note', '') or '', now)
        for v in votes
    ]
    conn.executemany(
        """INSERT INTO shadow_votes (shadow_id, date, ticker, direction,
           confidence, thesis, risk_note, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        rows
    )
    conn.commit()


def get_votes_by_date_range(
    conn: sqlite3.Connection, start_date: str, end_date: str
) -> list[dict]:
    """Get all votes within a date range, ordered by date DESC."""
    rows = conn.execute(
        """SELECT * FROM shadow_votes
           WHERE date >= ? AND date <= ?
           ORDER BY date DESC""",
        (start_date, end_date)
    ).fetchall()
    return [dict(r) for r in rows]


def get_pnl_by_domain(
    conn: sqlite3.Connection, domain: str
) -> list[float]:
    """Get PnL values from virtual_trades for shadows in a given domain."""
    rows = conn.execute(
        """SELECT vt.pnl_pct FROM virtual_trades vt
           JOIN shadows s ON vt.shadow_id = s.id
           WHERE vt.pnl_pct IS NOT NULL
             AND s.status != 'eliminated'
             AND json_extract(s.config_json, '$.domain') = ?""",
        (domain,)
    ).fetchall()
    return [r["pnl_pct"] for r in rows]
