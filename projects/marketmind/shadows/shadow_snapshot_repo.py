"""Daily snapshot persistence — save, query, and update shadow performance data.

Extracted from shadow_state.py per modular architecture rules (§3.1).
All functions accept sqlite3.Connection — no dependency on ShadowStateDB.
"""
from __future__ import annotations

import sqlite3

from marketmind.shadows.shadow_data_types import DailySnapshot


def save_snapshot(
    conn: sqlite3.Connection, shadow_id: str, snapshot: DailySnapshot
) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO daily_snapshots
           (shadow_id, date, virtual_capital, daily_return_pct,
            cumulative_return_pct, max_drawdown_pct, win_rate_pct,
            sharpe_ratio, calmar_ratio, omega_ratio, mppm_score,
            composite_score, deflated_score, percentile_rank,
            achievement_tier, flash_quota_used, pro_quota_used,
            emergency_quotas_used, insights_generated, votes_produced,
            discount_rate)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (shadow_id, snapshot.date, snapshot.virtual_capital,
         snapshot.daily_return_pct, snapshot.cumulative_return_pct,
         snapshot.max_drawdown_pct, snapshot.win_rate_pct,
         snapshot.sharpe_ratio, snapshot.calmar_ratio, snapshot.omega_ratio,
         snapshot.mppm_score, snapshot.composite_score, snapshot.deflated_score,
         snapshot.percentile_rank, snapshot.achievement_tier,
         snapshot.flash_quota_used, snapshot.pro_quota_used,
         snapshot.emergency_quotas_used, snapshot.insights_generated,
         snapshot.votes_produced, snapshot.discount_rate)
    )
    conn.commit()


def get_snapshot_history(
    conn: sqlite3.Connection, shadow_id: str, days: int = 90
) -> list[DailySnapshot]:
    rows = conn.execute(
        """SELECT * FROM daily_snapshots
           WHERE shadow_id = ?
           ORDER BY date DESC
           LIMIT ?""",
        (shadow_id, days)
    ).fetchall()
    return [_row_to_snapshot(r) for r in rows]


def get_latest_snapshot(
    conn: sqlite3.Connection, shadow_id: str
) -> DailySnapshot | None:
    row = conn.execute(
        "SELECT * FROM daily_snapshots WHERE shadow_id = ? ORDER BY date DESC LIMIT 1",
        (shadow_id,)
    ).fetchone()
    if row is None:
        return None
    return _row_to_snapshot(row)


def get_tier_history(
    conn: sqlite3.Connection, shadow_id: str, days: int = 120
) -> list[tuple[str, str]]:
    rows = conn.execute(
        """SELECT date, achievement_tier FROM daily_snapshots
           WHERE shadow_id = ? AND achievement_tier IS NOT NULL
           ORDER BY date DESC LIMIT ?""",
        (shadow_id, days)
    ).fetchall()
    return [(r["date"], r["achievement_tier"]) for r in rows]


def get_wr_history(
    conn: sqlite3.Connection, shadow_id: str, days: int = 120
) -> list[tuple[str, float]]:
    rows = conn.execute(
        """SELECT date, win_rate_pct FROM daily_snapshots
           WHERE shadow_id = ? AND win_rate_pct IS NOT NULL
           ORDER BY date DESC LIMIT ?""",
        (shadow_id, days)
    ).fetchall()
    return [(r["date"], r["win_rate_pct"] / 100.0) for r in rows]


def get_insight_dates(
    conn: sqlite3.Connection, shadow_id: str, days: int = 120
) -> list[str]:
    rows = conn.execute(
        """SELECT date FROM daily_snapshots
           WHERE shadow_id = ? AND insights_generated > 0
           ORDER BY date DESC LIMIT ?""",
        (shadow_id, days)
    ).fetchall()
    return [r["date"] for r in rows]


def get_abstention_days(
    conn: sqlite3.Connection, shadow_id: str, days: int = 180
) -> int:
    row = conn.execute(
        """SELECT COUNT(*) as cnt FROM daily_snapshots
           WHERE shadow_id = ? AND votes_produced = 0
           AND date >= date('now', ? || ' days')""",
        (shadow_id, f'-{days}')
    ).fetchone()
    return row["cnt"] if row else 0


def save_raw_output(
    conn: sqlite3.Connection, shadow_id: str, date: str, raw_output: str,
    token_count: int = 0, model: str = "pro"
) -> None:
    _ensure_votes_produced_column(conn)
    conn.execute(
        """INSERT OR REPLACE INTO shadow_outputs
           (shadow_id, date, raw_output, token_count, model)
           VALUES (?, ?, ?, ?, ?)""",
        (shadow_id, date, raw_output, token_count, model)
    )
    conn.commit()


def _ensure_votes_produced_column(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("SELECT votes_produced FROM daily_snapshots LIMIT 0")
    except Exception:
        conn.execute(
            "ALTER TABLE daily_snapshots ADD COLUMN votes_produced INTEGER DEFAULT 0"
        )


def count_consecutive_zero_insights(
    conn: sqlite3.Connection, shadow_id: str, max_days: int = 8
) -> int:
    rows = conn.execute(
        """SELECT date, insights_generated FROM daily_snapshots
           WHERE shadow_id = ? ORDER BY date DESC LIMIT ?""",
        (shadow_id, max_days)
    ).fetchall()
    count = 0
    for row in rows:
        if (row["insights_generated"] or 0) == 0:
            count += 1
        else:
            break
    return count


def get_raw_output(
    conn: sqlite3.Connection, shadow_id: str, date: str
) -> str | None:
    row = conn.execute(
        "SELECT raw_output FROM shadow_outputs WHERE shadow_id = ? AND date = ?",
        (shadow_id, date)
    ).fetchone()
    return row["raw_output"] if row else None


def get_token_history(
    conn: sqlite3.Connection, shadow_id: str, days: int = 30
) -> list[int]:
    rows = conn.execute(
        """SELECT token_count FROM shadow_outputs
           WHERE shadow_id = ? ORDER BY date ASC LIMIT ?""",
        (shadow_id, days)
    ).fetchall()
    return [r["token_count"] for r in rows if r["token_count"]]


def update_snapshot_fields(
    conn: sqlite3.Connection, shadow_id: str, date: str, **fields
) -> None:
    allowed = {"insights_generated", "votes_produced", "flash_quota_used",
               "pro_quota_used", "emergency_quotas_used"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [shadow_id, date]
    conn.execute(
        f"UPDATE daily_snapshots SET {set_clause} WHERE shadow_id = ? AND date = ?",
        values
    )
    conn.commit()


def _row_to_snapshot(row: sqlite3.Row) -> DailySnapshot:
    return DailySnapshot(
        shadow_id=row["shadow_id"],
        date=row["date"],
        virtual_capital=row["virtual_capital"],
        daily_return_pct=row["daily_return_pct"],
        cumulative_return_pct=row["cumulative_return_pct"],
        max_drawdown_pct=row["max_drawdown_pct"],
        win_rate_pct=row["win_rate_pct"],
        sharpe_ratio=row["sharpe_ratio"],
        calmar_ratio=row["calmar_ratio"],
        omega_ratio=row["omega_ratio"],
        mppm_score=row["mppm_score"],
        composite_score=row["composite_score"],
        deflated_score=row["deflated_score"],
        percentile_rank=row["percentile_rank"],
        achievement_tier=row["achievement_tier"],
        flash_quota_used=row["flash_quota_used"]
        if row["flash_quota_used"] is not None else 0,
        pro_quota_used=row["pro_quota_used"]
        if row["pro_quota_used"] is not None else 0,
        emergency_quotas_used=row["emergency_quotas_used"]
        if row["emergency_quotas_used"] is not None else 0,
        insights_generated=row["insights_generated"]
        if row["insights_generated"] is not None else 0,
        votes_produced=row["votes_produced"]
        if row["votes_produced"] is not None else 0,
        discount_rate=row["discount_rate"]
        if "discount_rate" in row.keys() and row["discount_rate"] is not None else None,
    )
