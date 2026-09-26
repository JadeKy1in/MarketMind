"""Shadow configuration CRUD -- create, query, update, and retire shadows.

Extracted from shadow_state.py per modular architecture rules (§3.1).
All functions accept sqlite3.Connection -- no dependency on ShadowStateDB.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone

from marketmind.shadows.shadow_data_types import ShadowConfig

logger = logging.getLogger("marketmind.shadows.shadow_config_repo")


# ── Row conversion ────────────────────────────────────────────────────────────

def _row_to_config(row: sqlite3.Row) -> ShadowConfig:
    try:
        config_json = json.loads(row["config_json"] or "{}")
    except json.JSONDecodeError:
        logger.warning("Corrupted config_json for shadow %s, using defaults", row["id"])
        config_json = {}
    return ShadowConfig(
        shadow_id=row["id"],
        shadow_type=row["shadow_type"],
        display_name=row["display_name"],
        methodology_prompt=row["methodology_prompt"] or "",
        virtual_capital=config_json.get("virtual_capital", 0),
        max_positions=config_json.get("max_positions", 3),
        model=config_json.get("model", "pro"),
        temperature=config_json.get("temperature", 0.3),
        reasoning_effort=config_json.get("reasoning_effort", "max"),
        domain=config_json.get("domain"),
        max_drawdown_limit=config_json.get("max_drawdown_limit", 0.35),
        min_trades_for_ranking=config_json.get("min_trades_for_ranking", 5),
        parent_shadow_id=config_json.get("parent_shadow_id"),
        generation=config_json.get("generation", 0),
        status=row["status"],
        eliminated_at=row["eliminated_at"],
        retired_at=row["retired_at"],
        retirement_reason=row["retirement_reason"],
        created_at=row["created_at"],
    )


# ── Create / Read ─────────────────────────────────────────────────────────────

def create_shadow(conn: sqlite3.Connection, config: ShadowConfig) -> str:
    existing = conn.execute(
        "SELECT id FROM shadows WHERE id = ?", (config.shadow_id,)
    ).fetchone()
    if existing:
        raise ValueError(f"Shadow '{config.shadow_id}' already exists")

    config_json = json.dumps({
        "virtual_capital": config.virtual_capital,
        "max_positions": config.max_positions,
        "model": config.model,
        "temperature": config.temperature,
        "reasoning_effort": config.reasoning_effort,
        "domain": config.domain,
        "max_drawdown_limit": config.max_drawdown_limit,
        "min_trades_for_ranking": config.min_trades_for_ranking,
        "parent_shadow_id": config.parent_shadow_id,
        "generation": config.generation,
    })
    conn.execute(
        """INSERT INTO shadows (id, shadow_type, display_name, status,
           methodology_prompt, config_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (config.shadow_id, config.shadow_type, config.display_name,
         config.status, config.methodology_prompt, config_json,
         config.created_at)
    )
    conn.commit()
    return config.shadow_id


def get_shadow(conn: sqlite3.Connection, shadow_id: str) -> ShadowConfig | None:
    row = conn.execute(
        "SELECT * FROM shadows WHERE id = ?", (shadow_id,)
    ).fetchone()
    if row is None:
        return None
    return _row_to_config(row)


def get_active_shadows(
    conn: sqlite3.Connection, shadow_type: str | None = None
) -> list[ShadowConfig]:
    if shadow_type:
        rows = conn.execute(
            "SELECT * FROM shadows WHERE status NOT IN ('eliminated','retired') AND shadow_type = ?",
            (shadow_type,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM shadows WHERE status NOT IN ('eliminated','retired')"
        ).fetchall()
    return [_row_to_config(r) for r in rows]


def get_visible_shadows(conn: sqlite3.Connection) -> list[ShadowConfig]:
    rows = conn.execute(
        "SELECT * FROM shadows WHERE status NOT IN ('eliminated','retired')"
        " AND shadow_type != 'challenger'"
    ).fetchall()
    return [_row_to_config(r) for r in rows]


def get_ranking_eligible_shadows(conn: sqlite3.Connection) -> list[ShadowConfig]:
    """Shadows eligible for ranking, collusion detection, and challenger engine.
    Excludes beta, retired, eliminated, and challenger shadows."""
    rows = conn.execute(
        "SELECT * FROM shadows WHERE status NOT IN ('eliminated','retired','beta')"
        " AND shadow_type != 'challenger'"
    ).fetchall()
    return [_row_to_config(r) for r in rows]


# ── Update / Retire / Eliminate ──────────────────────────────────────────────

def update_shadow_status(
    conn: sqlite3.Connection, shadow_id: str, status: str
) -> None:
    conn.execute(
        "UPDATE shadows SET status = ? WHERE id = ?",
        (status, shadow_id)
    )
    conn.commit()


def retire_shadow(conn: sqlite3.Connection, shadow_id: str, reason: str) -> None:
    """Mark shadow as retired. Preserves methodology and history as frozen benchmark."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE shadows SET status = 'retired', retired_at = ?, "
        "retirement_reason = ? WHERE id = ?",
        (now, reason, shadow_id)
    )
    conn.execute(
        """UPDATE virtual_trades SET exit_reason = 'shadow_retired',
           exit_date = ? WHERE shadow_id = ? AND exit_price IS NULL""",
        (now[:10], shadow_id)
    )
    conn.commit()


def eliminate_shadow(conn: sqlite3.Connection, shadow_id: str, reason: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE shadows SET status = 'eliminated', eliminated_at = ? WHERE id = ?",
        (now, shadow_id)
    )
    conn.execute(
        """UPDATE virtual_trades SET exit_reason = 'shadow_eliminated',
           exit_date = ? WHERE shadow_id = ? AND exit_price IS NULL""",
        (now[:10], shadow_id)
    )
    conn.commit()


def update_shadow_type(
    conn: sqlite3.Connection, shadow_id: str, new_type: str
) -> bool:
    """Change a shadow's type (e.g., challenger -> expert on promotion)."""
    conn.execute(
        "UPDATE shadows SET shadow_type = ? WHERE id = ?",
        (new_type, shadow_id)
    )
    conn.commit()
    return conn.total_changes > 0


# ── Methodology prompt management ────────────────────────────────────────────

def update_methodology_prompt(
    conn: sqlite3.Connection, shadow_id: str, new_prompt: str,
    reason: str = ""
) -> bool:
    """Update a shadow's methodology prompt and log the change (P1-1).

    Returns True if the shadow was found and updated.
    """
    old = conn.execute(
        "SELECT methodology_prompt FROM shadows WHERE id = ?",
        (shadow_id,)
    ).fetchone()
    if old is None:
        return False
    old_prompt = old["methodology_prompt"] or ""

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE shadows SET methodology_prompt = ? WHERE id = ?",
        (new_prompt, shadow_id)
    )
    conn.execute(
        """INSERT INTO methodology_changes
           (shadow_id, change_type, old_prompt, new_prompt, reason, changed_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (shadow_id, "update", old_prompt[:500], new_prompt[:500], reason, now)
    )
    conn.commit()
    logger.info("Methodology updated for %s: %s", shadow_id, reason)
    return True


def get_methodology_history(
    conn: sqlite3.Connection, shadow_id: str, limit: int = 20
) -> list[dict]:
    """Get methodology change history for a shadow (P1-1)."""
    rows = conn.execute(
        """SELECT change_type, reason, changed_at FROM methodology_changes
           WHERE shadow_id = ? ORDER BY changed_at DESC LIMIT ?""",
        (shadow_id, limit)
    ).fetchall()
    return [{"change_type": r["change_type"], "reason": r["reason"],
             "changed_at": r["changed_at"]} for r in rows]


def get_original_methodology(
    conn: sqlite3.Connection, shadow_id: str
) -> str | None:
    """Get the first recorded methodology prompt (baseline) for a shadow."""
    row = conn.execute(
        """SELECT old_prompt FROM methodology_changes
           WHERE shadow_id = ? ORDER BY changed_at ASC LIMIT 1""",
        (shadow_id,)
    ).fetchone()
    return row["old_prompt"] if row else None


def get_failure_patterns(
    conn: sqlite3.Connection, shadow_id: str, days: int = 90
) -> list[str]:
    """Get failure patterns from AEL debriefs (P3-1).

    Queries methodology_changes for debrief-type entries within the
    specified day window. Each row's reason field contains one failure
    pattern description.
    """
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT reason, new_prompt FROM methodology_changes
           WHERE shadow_id = ? AND change_type = 'debrief'
           AND changed_at >= ?
           ORDER BY changed_at DESC""",
        (shadow_id, cutoff)
    ).fetchall()

    patterns = []
    for row in rows:
        reason = (row["reason"] or "").strip()
        if reason:
            patterns.append(reason)

    # Also extract from [FAILURE PATTERNS TO AVOID] block in new_prompt
    for row in rows:
        new_prompt = row["new_prompt"] or ""
        if "[FAILURE PATTERNS TO AVOID" in new_prompt:
            section = new_prompt.split("[FAILURE PATTERNS TO AVOID")[1]
            section = section.split("\n\n")[0] if "\n\n" in section else section
            for line in section.split("\n"):
                line = line.strip().lstrip("-").strip()
                if line and not line.startswith("learned"):
                    patterns.append(line)

    return patterns


def get_retired_insights(
    conn: sqlite3.Connection, shadow_id: str, days: int = 90
) -> list[str]:
    """Get retired insights from crystallization (P3-1).

    Queries methodology_changes for crystallization_retire entries.
    Retired insights are previously-validated insights that have been
    invalidated by new evidence.
    """
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT reason, new_prompt FROM methodology_changes
           WHERE shadow_id = ? AND change_type = 'crystallization_retire'
           AND changed_at >= ?
           ORDER BY changed_at DESC""",
        (shadow_id, cutoff)
    ).fetchall()

    insights = []
    for row in rows:
        reason = (row["reason"] or "").strip()
        if reason:
            insights.append(reason)

    # Also extract from [RETIRED] block in new_prompt
    for row in rows:
        new_prompt = row["new_prompt"] or ""
        if "[RETIRED:" in new_prompt:
            section = new_prompt.split("[RETIRED:")[1]
            section = section.split("]")[0] if "]" in section else section
            section = section.strip()
            if section:
                insights.append(section)

    return insights
