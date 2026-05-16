"""Shadow state persistence -- CRUD operations for the shadow ecosystem.

Data Classification Scheme (Resolution 6-B, Phase 4 Red Team):
--------------------------------------------------------------------
20 persistent tables are classified into three tiers:

L1 (Public / Non-Sensitive):
    - archive_fts              (full-text search index, derived from public data)
    - collusion_flags          (aggregate agreement stats, no PII)
    - ranking_history          (composite/deflated scores, no raw methodology)
    - cycle_checkpoints        (step-completion markers, no position data)
    - access_audit_log         (operation metadata, no payload content)
    - shadow_rankings_fts      (tier/rank search index)

L2 (Internal / Shadow Ecosystem — Business Logic):
    - shadows                  (shadow configs + methodology prompts)
    - virtual_trades           (entry/exit/pnl — virtual only, no real capital)
    - daily_snapshots          (performance metrics: sharpe, calmar, drawdown)
    - shadow_outputs           (raw LLM outputs — contains proprietary analysis)
    - integrity_events         (claim verification history)
    - emergency_quotas         (confidence + opportunity descriptions)
    - emergency_quota_state    (runtime quota tracking)
    - paper_live_gap_state     (slippage calibration data)
    - shadow_votes             (ticker/direction/confidence/thesis — core IP)
    - methodology_changes      (prompt evolution history)
    - shadow_analyses_fts      (vote thesis/risk_note search index)
    - shadow_trades_fts        (exit_reason search index)
    - belief_nodes             (propositions + alpha/beta state)
    - forecast_scenarios        (scenario predictions + belief state)

L3 (Restricted / Real-Money Sensitive — None Currently):
    (No L3 tables exist at this time. If real brokerage integration or
     actual account balances are stored, they must be classified L3
     with access limited to system-only callers.)

The DB-level access control matrix in ShadowStateDB._ACCESS_MATRIX
enforces read isolation: shadows can only read their own L2 data;
main_ai cannot read any shadow data; collusion_detector/backtest_runner
can read all shadows; system has full access.

Config data types are in shadow_config.py; schema/migrations are in shadow_db.py.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from marketmind.shadows.shadow_config import (
    ShadowConfig, VirtualTradeOpen, VirtualTrade, DailySnapshot,
    IntegrityEvent, EmergencyQuotaRequest, CollusionFlag,
)
from marketmind.shadows.shadow_db import CODE_VERSION, init_schema as _init_schema_db

logger = logging.getLogger("marketmind.shadows.shadow_state")


class ShadowStateDB:
    """SQLite-backed shadow state persistence."""

    def __init__(self, db_path: str = "data/shadows/shadows.db"):
        self.db_path = db_path
        self._access_audit_enabled = True
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _execute_with_retry(self, operation, max_retries: int = 3, retry_delay: float = 0.5):
        """Execute a DB operation with retry on database locked errors.

        Intended for write operations in high-contention paths (e.g. shadow_mother
        orchestration) where multiple concurrent connections may contend for the
        same SQLite database.
        """
        last_error = None
        for attempt in range(max_retries):
            try:
                return operation()
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
                    last_error = e
                    continue
                raise
        raise last_error

    # Access matrix: who can read what
    _ACCESS_MATRIX = {
        "main_ai": {"self_only": False, "other_shadows": False, "all_shadows": False, "system": False},
        "system": {"self_only": True, "other_shadows": True, "all_shadows": True, "system": True},
        "collusion_detector": {"self_only": False, "other_shadows": False, "all_shadows": True, "system": False},
        "backtest_runner": {"self_only": False, "other_shadows": False, "all_shadows": True, "system": False},
    }

    def _check_access(self, caller_id: str, target_shadow_id: str, operation: str) -> bool:
        """Check if caller_id is authorized to access target_shadow_id.

        Rules:
        - "shadow:{id}" can only read its own data (caller_id == "shadow:{target_shadow_id}")
        - "main_ai" cannot read any shadow data
        - "collusion_detector" and "backtest_runner" can read all shadows
        - "system" can read everything
        """
        if caller_id.startswith("shadow:"):
            caller_shadow = caller_id.split(":", 1)[1]
            return caller_shadow == target_shadow_id
        if caller_id in ("collusion_detector", "backtest_runner", "system"):
            return True
        if caller_id == "main_ai":
            return False  # Main AI must not read shadow data (permanent isolation)
        return False

    def _log_access(self, caller_id: str, target_shadow_id: str, operation: str, detail: str = "") -> None:
        """Log access attempt to audit log (best-effort, non-blocking)."""
        if not self._access_audit_enabled:
            return
        try:
            conn = self._connect()
            try:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """INSERT INTO access_audit_log
                       (caller_id, target_shadow_id, operation, detail, accessed_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (caller_id, target_shadow_id, operation, detail, now)
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass  # Audit logging must never block primary operation

    def init_schema(self) -> None:
        conn = self._connect()
        try:
            _init_schema_db(conn)
            conn.commit()
        finally:
            conn.close()

    def close(self) -> None:
        pass  # SQLite connections are closed per-operation

    # ── Shadow CRUD ──────────────────────────────────────────────────────

    def create_shadow(self, config: ShadowConfig) -> str:
        conn = self._connect()
        try:
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
        finally:
            conn.close()

    def get_shadow(self, shadow_id: str, caller_id: str) -> ShadowConfig | None:
        if not self._check_access(caller_id, shadow_id, "get_shadow"):
            logger.warning("Access denied: caller=%s target=%s op=get_shadow", caller_id, shadow_id)
            return None
        self._log_access(caller_id, shadow_id, "get_shadow")
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM shadows WHERE id = ?", (shadow_id,)
            ).fetchone()
            if row is None:
                return None
            return self._row_to_config(row)
        finally:
            conn.close()

    def get_active_shadows(self, shadow_type: str | None = None) -> list[ShadowConfig]:
        conn = self._connect()
        try:
            if shadow_type:
                rows = conn.execute(
                    "SELECT * FROM shadows WHERE status != 'eliminated' AND shadow_type = ?",
                    (shadow_type,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM shadows WHERE status != 'eliminated'"
                ).fetchall()
            return [self._row_to_config(r) for r in rows]
        finally:
            conn.close()

    def get_visible_shadows(self) -> list[ShadowConfig]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM shadows WHERE status != 'eliminated' AND shadow_type != 'challenger'"
            ).fetchall()
            return [self._row_to_config(r) for r in rows]
        finally:
            conn.close()

    def update_shadow_status(self, shadow_id: str, status: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE shadows SET status = ? WHERE id = ?",
                (status, shadow_id)
            )
            conn.commit()
        finally:
            conn.close()

    def eliminate_shadow(self, shadow_id: str, reason: str) -> None:
        conn = self._connect()
        try:
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
        finally:
            conn.close()

    def update_shadow_type(self, shadow_id: str, new_type: str) -> bool:
        """Change a shadow's type (e.g., challenger → expert on promotion)."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE shadows SET shadow_type = ? WHERE id = ?",
                (new_type, shadow_id)
            )
            conn.commit()
            return conn.total_changes > 0
        finally:
            conn.close()

    def update_methodology_prompt(self, shadow_id: str, new_prompt: str,
                                    reason: str = "") -> bool:
        """Update a shadow's methodology prompt and log the change (P1-1).

        Returns True if the shadow was found and updated.
        """
        conn = self._connect()
        try:
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
        finally:
            conn.close()

    def get_methodology_history(self, shadow_id: str,
                                 caller_id: str, limit: int = 20) -> list[dict]:
        """Get methodology change history for a shadow (P1-1)."""
        if not self._check_access(caller_id, shadow_id, "get_methodology_history"):
            logger.warning("Access denied: caller=%s target=%s op=get_methodology_history", caller_id, shadow_id)
            return []
        self._log_access(caller_id, shadow_id, "get_methodology_history")
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT change_type, reason, changed_at FROM methodology_changes
                   WHERE shadow_id = ? ORDER BY changed_at DESC LIMIT ?""",
                (shadow_id, limit)
            ).fetchall()
            return [{"change_type": r["change_type"], "reason": r["reason"],
                     "changed_at": r["changed_at"]} for r in rows]
        finally:
            conn.close()

    def get_original_methodology(self, shadow_id: str, caller_id: str) -> str | None:
        """Get the first recorded methodology prompt (baseline) for a shadow."""
        if not self._check_access(caller_id, shadow_id, "get_original_methodology"):
            logger.warning("Access denied: caller=%s target=%s op=get_original_methodology", caller_id, shadow_id)
            return None
        self._log_access(caller_id, shadow_id, "get_original_methodology")
        conn = self._connect()
        try:
            row = conn.execute(
                """SELECT old_prompt FROM methodology_changes
                   WHERE shadow_id = ? ORDER BY changed_at ASC LIMIT 1""",
                (shadow_id,)
            ).fetchone()
            return row["old_prompt"] if row else None
        finally:
            conn.close()

    @staticmethod
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
            created_at=row["created_at"],
        )

    # ── Virtual trades ────────────────────────────────────────────────────

    def record_trade_open(self, shadow_id: str, trade: VirtualTradeOpen) -> int:
        conn = self._connect()
        try:
            cur = conn.execute(
                """INSERT INTO virtual_trades (shadow_id, ticker, direction,
                   entry_price, position_size_pct, entry_date)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (shadow_id, trade.ticker, trade.direction,
                 trade.entry_price, trade.position_size_pct, trade.entry_date)
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def record_trade_close(self, trade_id: int, exit_price: float,
                           exit_reason: str, pnl_pct: float) -> None:
        conn = self._connect()
        try:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            conn.execute(
                """UPDATE virtual_trades SET exit_price = ?, exit_date = ?,
                   exit_reason = ?, pnl_pct = ? WHERE id = ?""",
                (exit_price, now, exit_reason, pnl_pct, trade_id)
            )
            conn.commit()
        finally:
            conn.close()

    def get_open_trades(self, shadow_id: str) -> list[VirtualTrade]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM virtual_trades WHERE shadow_id = ? AND exit_price IS NULL",
                (shadow_id,)
            ).fetchall()
            return [self._row_to_trade(r) for r in rows]
        finally:
            conn.close()

    def get_trade_history(self, shadow_id: str, caller_id: str, limit: int = 90) -> list[VirtualTrade]:
        if not self._check_access(caller_id, shadow_id, "get_trade_history"):
            logger.warning("Access denied: caller=%s target=%s op=get_trade_history", caller_id, shadow_id)
            return []
        self._log_access(caller_id, shadow_id, "get_trade_history")
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT * FROM virtual_trades
                   WHERE shadow_id = ? AND exit_price IS NOT NULL
                   ORDER BY exit_date DESC
                   LIMIT ?""",
                (shadow_id, limit)
            ).fetchall()
            return [self._row_to_trade(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def _row_to_trade(row: sqlite3.Row) -> VirtualTrade:
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

    # ── Daily snapshots ───────────────────────────────────────────────────

    def save_snapshot(self, shadow_id: str, snapshot: DailySnapshot) -> None:
        conn = self._connect()
        try:
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
        finally:
            conn.close()

    def get_snapshot_history(self, shadow_id: str, caller_id: str, days: int = 90) -> list[DailySnapshot]:
        if not self._check_access(caller_id, shadow_id, "get_snapshot_history"):
            logger.warning("Access denied: caller=%s target=%s op=get_snapshot_history", caller_id, shadow_id)
            return []
        self._log_access(caller_id, shadow_id, "get_snapshot_history")
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT * FROM daily_snapshots
                   WHERE shadow_id = ?
                   ORDER BY date DESC
                   LIMIT ?""",
                (shadow_id, days)
            ).fetchall()
            return [self._row_to_snapshot(r) for r in rows]
        finally:
            conn.close()

    def get_latest_snapshot(self, shadow_id: str, caller_id: str) -> DailySnapshot | None:
        if not self._check_access(caller_id, shadow_id, "get_latest_snapshot"):
            logger.warning("Access denied: caller=%s target=%s op=get_latest_snapshot", caller_id, shadow_id)
            return None
        self._log_access(caller_id, shadow_id, "get_latest_snapshot")
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM daily_snapshots WHERE shadow_id = ? ORDER BY date DESC LIMIT 1",
                (shadow_id,)
            ).fetchone()
            if row is None:
                return None
            return self._row_to_snapshot(row)
        finally:
            conn.close()

    def get_tier_history(self, shadow_id: str, days: int = 120) -> list[tuple[str, str]]:
        """Get (date, achievement_tier) history for plateau/reset detection."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT date, achievement_tier FROM daily_snapshots
                   WHERE shadow_id = ? AND achievement_tier IS NOT NULL
                   ORDER BY date DESC LIMIT ?""",
                (shadow_id, days)
            ).fetchall()
            return [(r["date"], r["achievement_tier"]) for r in rows]
        finally:
            conn.close()

    def get_wr_history(self, shadow_id: str, days: int = 120) -> list[tuple[str, float]]:
        """Get (date, win_rate_pct) history for plateau/reset detection."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT date, win_rate_pct FROM daily_snapshots
                   WHERE shadow_id = ? AND win_rate_pct IS NOT NULL
                   ORDER BY date DESC LIMIT ?""",
                (shadow_id, days)
            ).fetchall()
            return [(r["date"], r["win_rate_pct"] / 100.0) for r in rows]
        finally:
            conn.close()

    def get_insight_dates(self, shadow_id: str, days: int = 120) -> list[str]:
        """Get dates where shadow produced insights. Derives from snapshots
        where insights_generated > 0."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT date FROM daily_snapshots
                   WHERE shadow_id = ? AND insights_generated > 0
                   ORDER BY date DESC LIMIT ?""",
                (shadow_id, days)
            ).fetchall()
            return [r["date"] for r in rows]
        finally:
            conn.close()

    def get_abstention_days(self, shadow_id: str, days: int = 180) -> int:
        """Count days where shadow produced zero votes (abstained)."""
        conn = self._connect()
        try:
            row = conn.execute(
                """SELECT COUNT(*) as cnt FROM daily_snapshots
                   WHERE shadow_id = ? AND votes_produced = 0
                   AND date >= date('now', ? || ' days')""",
                (shadow_id, f'-{days}')
            ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    def save_raw_output(self, shadow_id: str, date: str, raw_output: str,
                         token_count: int = 0, model: str = "pro") -> None:
        """Persist raw LLM output for health monitoring (Phase 3)."""
        conn = self._connect()
        try:
            # Ensure votes_produced column exists (migration safety)
            self._ensure_votes_produced_column(conn)
            conn.execute(
                """INSERT OR REPLACE INTO shadow_outputs
                   (shadow_id, date, raw_output, token_count, model)
                   VALUES (?, ?, ?, ?, ?)""",
                (shadow_id, date, raw_output, token_count, model)
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _ensure_votes_produced_column(conn) -> None:
        """Add votes_produced column if missing (lazy migration)."""
        try:
            conn.execute("SELECT votes_produced FROM daily_snapshots LIMIT 0")
        except Exception:
            conn.execute(
                "ALTER TABLE daily_snapshots ADD COLUMN votes_produced INTEGER DEFAULT 0"
            )

    def count_consecutive_zero_insights(self, shadow_id: str,
                                         max_days: int = 8) -> int:
        """Count consecutive recent days with zero insights (Phase 3)."""
        conn = self._connect()
        try:
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
        finally:
            conn.close()

    def get_raw_output(self, shadow_id: str, date: str, caller_id: str) -> str | None:
        """Retrieve raw LLM output for a shadow on a given date."""
        if not self._check_access(caller_id, shadow_id, "get_raw_output"):
            logger.warning("Access denied: caller=%s target=%s op=get_raw_output", caller_id, shadow_id)
            return None
        self._log_access(caller_id, shadow_id, "get_raw_output")
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT raw_output FROM shadow_outputs WHERE shadow_id = ? AND date = ?",
                (shadow_id, date)
            ).fetchone()
            return row["raw_output"] if row else None
        finally:
            conn.close()

    def get_token_history(self, shadow_id: str, days: int = 30) -> list[int]:
        """Get token count history for trend analysis (Phase 3).
        Returns oldest-first for Mann-Kendall computation."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT token_count FROM shadow_outputs
                   WHERE shadow_id = ? ORDER BY date ASC LIMIT ?""",
                (shadow_id, days)
            ).fetchall()
            return [r["token_count"] for r in rows if r["token_count"]]
        finally:
            conn.close()

    def update_snapshot_fields(self, shadow_id: str, date: str, **fields) -> None:
        """Update select fields on a snapshot after analysis (Phase 2)."""
        allowed = {"insights_generated", "votes_produced", "flash_quota_used",
                   "pro_quota_used", "emergency_quotas_used"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [shadow_id, date]
        conn = self._connect()
        try:
            conn.execute(
                f"UPDATE daily_snapshots SET {set_clause} WHERE shadow_id = ? AND date = ?",
                values
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
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

    # ── Rankings ──────────────────────────────────────────────────────────

    def save_rankings(self, date: str, rankings: list[tuple[str, float, float, dict]]) -> None:
        conn = self._connect()
        try:
            for rank, (shadow_id, composite, deflated, components) in enumerate(rankings, 1):
                conn.execute(
                    """INSERT OR REPLACE INTO ranking_history
                       (date, shadow_id, rank, composite_score, deflated_score, component_scores)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (date, shadow_id, rank, composite, deflated,
                     json.dumps(components))
                )
            conn.commit()
        finally:
            conn.close()

    def get_ranking_history(self, shadow_id: str, days: int = 90) -> list[dict]:
        conn = self._connect()
        try:
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
        finally:
            conn.close()

    # ── Integrity ─────────────────────────────────────────────────────────

    def record_integrity_event(self, shadow_id: str, event: IntegrityEvent) -> bool:
        conn = self._connect()
        try:
            cur = conn.execute(
                """INSERT OR IGNORE INTO integrity_events
                   (shadow_id, date, event_type, claim_detail, score_change, new_score)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (shadow_id, event.date, event.event_type, event.claim_detail,
                 event.score_change, event.new_score)
            )
            recorded = cur.rowcount > 0
            if not recorded:
                logger.debug("Duplicate integrity event ignored: shadow=%s date=%s type=%s",
                             shadow_id, event.date, event.event_type)
            conn.commit()
            return recorded
        finally:
            conn.close()

    def get_integrity_score(self, shadow_id: str) -> int:
        conn = self._connect()
        try:
            row = conn.execute(
                """SELECT new_score FROM integrity_events
                   WHERE shadow_id = ?
                   ORDER BY date DESC LIMIT 1""",
                (shadow_id,)
            ).fetchone()
            return row["new_score"] if row else 100
        finally:
            conn.close()

    def get_integrity_history(self, shadow_id: str, days: int = 90) -> list[IntegrityEvent]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT * FROM integrity_events
                   WHERE shadow_id = ?
                   ORDER BY date DESC
                   LIMIT ?""",
                (shadow_id, days)
            ).fetchall()
            return [IntegrityEvent(
                shadow_id=r["shadow_id"], date=r["date"],
                event_type=r["event_type"], claim_detail=r["claim_detail"],
                score_change=r["score_change"], new_score=r["new_score"],
            ) for r in rows]
        finally:
            conn.close()

    # ── Emergency quotas ──────────────────────────────────────────────────

    def record_emergency_quota(self, shadow_id: str, quota: EmergencyQuotaRequest) -> int:
        conn = self._connect()
        try:
            cur = conn.execute(
                """INSERT INTO emergency_quotas
                   (shadow_id, requested_at, confidence_self_report, opportunity_description)
                   VALUES (?, ?, ?, ?)""",
                (shadow_id, quota.requested_at, quota.confidence_self_report,
                 quota.opportunity_description)
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def update_emergency_result(self, quota_id: int, result: str,
                                pnl_impact: float, penalty: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """UPDATE emergency_quotas
                   SET result = ?, pnl_impact_pct = ?, quota_penalty_applied = ?
                   WHERE id = ?""",
                (result, pnl_impact, penalty, quota_id)
            )
            conn.commit()
        finally:
            conn.close()

    def get_pending_emergency_audits(self) -> list[EmergencyQuotaRequest]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM emergency_quotas WHERE result = 'pending'"
            ).fetchall()
            return [EmergencyQuotaRequest(
                id=r["id"],
                shadow_id=r["shadow_id"],
                requested_at=r["requested_at"],
                confidence_self_report=r["confidence_self_report"],
                opportunity_description=r["opportunity_description"],
                result=r["result"],
                pnl_impact_pct=r["pnl_impact_pct"],
                quota_penalty_applied=r["quota_penalty_applied"],
            ) for r in rows]
        finally:
            conn.close()

    # ── Collusion ─────────────────────────────────────────────────────────

    def record_collusion_flag(self, flag: CollusionFlag) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO collusion_flags
                   (date, agreement_pct, consecutive_days, market_signal_strength,
                    verdict, user_action)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (flag.date, flag.agreement_pct, flag.consecutive_days,
                 flag.market_signal_strength, flag.verdict, flag.user_action)
            )
            conn.commit()
        finally:
            conn.close()

    def get_recent_collusion_flags(self, days: int = 30) -> list[CollusionFlag]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT * FROM collusion_flags
                   ORDER BY date DESC
                   LIMIT ?""",
                (days,)
            ).fetchall()
            return [CollusionFlag(
                date=r["date"],
                agreement_pct=r["agreement_pct"],
                consecutive_days=r["consecutive_days"],
                market_signal_strength=r["market_signal_strength"],
                verdict=r["verdict"],
                user_action=r["user_action"],
            ) for r in rows]
        finally:
            conn.close()

    # ── Emergency quota runtime state ──────────────────────────────────────

    def save_emergency_quota_state(self, shadow_id: str, state_json: str) -> None:
        """Save emergency quota state for a shadow (dedicated table, no read-merge-write)."""
        conn = self._connect()
        try:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """INSERT OR REPLACE INTO emergency_quota_state
                   (shadow_id, state_json, updated_at)
                   VALUES (?, ?, ?)""",
                (shadow_id, state_json, now)
            )
            conn.commit()
        finally:
            conn.close()

    def load_emergency_quota_state(self, shadow_id: str) -> str | None:
        """Load emergency quota state JSON for a shadow, or None if no state exists."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT state_json FROM emergency_quota_state WHERE shadow_id = ?",
                (shadow_id,)
            ).fetchone()
            return row["state_json"] if row else None
        finally:
            conn.close()

    # ── Paper/live gap runtime state ───────────────────────────────────────

    def save_paper_live_gap_state(self, shadow_id: str, state_json: str) -> None:
        """Save paper/live gap state for a shadow (dedicated table, no read-merge-write)."""
        conn = self._connect()
        try:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """INSERT OR REPLACE INTO paper_live_gap_state
                   (shadow_id, state_json, updated_at)
                   VALUES (?, ?, ?)""",
                (shadow_id, state_json, now)
            )
            conn.commit()
        finally:
            conn.close()

    def load_paper_live_gap_state(self, shadow_id: str) -> str | None:
        """Load paper/live gap state JSON for a shadow, or None if no state exists."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT state_json FROM paper_live_gap_state WHERE shadow_id = ?",
                (shadow_id,)
            ).fetchone()
            return row["state_json"] if row else None
        finally:
            conn.close()

    # ── Bulk operations ───────────────────────────────────────────────────

    def get_all_daily_snapshots(self, date: str) -> list[DailySnapshot]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM daily_snapshots WHERE date = ?",
                (date,)
            ).fetchall()
            return [self._row_to_snapshot(r) for r in rows]
        finally:
            conn.close()

    def get_ready_count(self, today: str) -> tuple[int, int]:
        """R4: Count shadows that have completed today's analysis.

        Returns (completed, total) where:
          completed = shadows with a daily_snapshot for today's date
          total     = active visible shadows (not eliminated, not challenger)
        """
        conn = self._connect()
        try:
            completed_row = conn.execute(
                "SELECT COUNT(DISTINCT shadow_id) FROM daily_snapshots WHERE date = ?",
                (today,)
            ).fetchone()
            completed = completed_row[0] if completed_row else 0

            total_row = conn.execute(
                "SELECT COUNT(*) FROM shadows WHERE status != 'eliminated'"
                " AND shadow_type != 'challenger'"
            ).fetchone()
            total = total_row[0] if total_row else 0

            return (completed, total)
        finally:
            conn.close()

    def get_all_active_votes(self, date: str, ticker: str) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT s.id, s.shadow_type, s.display_name
                   FROM shadows s
                   WHERE s.status != 'eliminated' AND s.shadow_type != 'challenger'
                   ORDER BY s.id"""
            ).fetchall()
            return [{"shadow_id": r["id"], "shadow_type": r["shadow_type"],
                     "display_name": r["display_name"],
                     "date": date, "ticker": ticker} for r in rows]
        finally:
            conn.close()

    # ── Next-day return lookup ─────────────────────────────────────────────

    def get_next_day_return_sign(self, ticker_or_shadow: str, date: str) -> int | None:
        """Get return sign for a ticker/shadow on a given date. 1=positive, -1=negative, None=no data."""
        conn = self._connect()
        try:
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
        finally:
            conn.close()

    # ── Vote persistence ───────────────────────────────────────────────────

    def save_votes(self, shadow_id: str, date: str, votes: list) -> None:
        """Persist shadow votes for backtest/audit. Uses executemany for batch insert."""
        if not votes:
            return
        conn = self._connect()
        try:
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
        finally:
            conn.close()

    def label_vote_outcomes(self, ticker: str, date: str,
                            atr_mult: float = 2.0) -> int:
        """Label unlabeled votes for a ticker+date using next-day close vs ATR.

        Returns count of votes labeled. Uses market_prices for actual returns.
        Writes: outcome_label='upper_barrier'/'lower_barrier'/'time_expired',
                outcome_return_pct=actual next-day return.
        """
        conn = self._connect()
        try:
            # Get unlabeled votes for this ticker+date
            votes = conn.execute(
                """SELECT id FROM shadow_votes
                   WHERE ticker = ? AND date = ? AND outcome_label IS NULL""",
                (ticker, date)
            ).fetchall()
            if not votes:
                return 0

            # Get next-day close from market_prices
            price_row = conn.execute(
                """SELECT close, next_day_return FROM market_prices
                   WHERE ticker = ? AND date = ?""",
                (ticker, date)
            ).fetchone()

            if price_row and price_row["next_day_return"] is not None:
                ret = price_row["next_day_return"]
                # Simplified Triple-Barrier: positive ret = upper, negative = lower
                label = "upper_barrier" if ret > 0 else "lower_barrier"
                ids = [v["id"] for v in votes]
                conn.executemany(
                    """UPDATE shadow_votes SET outcome_label = ?, outcome_return_pct = ?
                       WHERE id = ?""",
                    [(label, ret, vid) for vid in ids]
                )
            else:
                # No market data available — mark as time_expired
                ids = [v["id"] for v in votes]
                conn.executemany(
                    """UPDATE shadow_votes SET outcome_label = 'time_expired'
                       WHERE id = ?""",
                    [(vid,) for vid in ids]
                )
            conn.commit()
            return len(votes)
        finally:
            conn.close()

    def get_votes_by_date_range(self, start_date: str, end_date: str, caller_id: str) -> list[dict]:
        """Get all votes within a date range, ordered by date DESC.
        Requires all_shadows access (collusion_detector, backtest_runner, system)."""
        if not self._check_access(caller_id, "_all_", "get_votes_by_date_range"):
            logger.warning("Access denied: caller=%s op=get_votes_by_date_range", caller_id)
            return []
        self._log_access(caller_id, "_all_", "get_votes_by_date_range")
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT * FROM shadow_votes
                   WHERE date >= ? AND date <= ?
                   ORDER BY date DESC""",
                (start_date, end_date)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── Market prices (P2-4) ─────────────────────────────────────────────

    def save_market_prices(self, ticker: str, prices: dict[str, dict[str, float]]) -> int:
        """Batch insert/replace OHLCV data. Returns rows inserted."""
        if not prices:
            return 0
        conn = self._connect()
        try:
            rows = [
                (ticker, date, p["open"], p["high"], p["low"], p["close"],
                 p.get("volume", 0), p.get("next_day_return"))
                for date, p in prices.items()
            ]
            conn.executemany(
                """INSERT OR REPLACE INTO market_prices
                   (ticker, date, open, high, low, close, volume, next_day_return)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                rows
            )
            conn.commit()
            return len(rows)
        finally:
            conn.close()

    def get_market_prices(self, ticker: str, start_date: str,
                          end_date: str | None = None) -> dict[str, dict[str, float]]:
        """Get OHLCV data for a ticker in date range. Returns {date: {open, high, low, close, volume}}."""
        conn = self._connect()
        try:
            if end_date:
                rows = conn.execute(
                    """SELECT * FROM market_prices
                       WHERE ticker = ? AND date >= ? AND date <= ?
                       ORDER BY date ASC""",
                    (ticker, start_date, end_date)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM market_prices
                       WHERE ticker = ? AND date >= ?
                       ORDER BY date ASC""",
                    (ticker, start_date)
                ).fetchall()
            return {
                r["date"]: {
                    "open": r["open"], "high": r["high"], "low": r["low"],
                    "close": r["close"], "volume": r["volume"],
                    "next_day_return": r["next_day_return"],
                }
                for r in rows
            }
        finally:
            conn.close()

    # ── Cycle checkpoints (P3-4: partial-state recovery) ────────────────

    def save_cycle_checkpoint(self, date: str, shadow_states: dict[str, str],
                              step_completed: int = 4,
                              status: str = "running") -> None:
        """Save or update a cycle checkpoint for crash recovery."""
        import json
        conn = self._connect()
        try:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """INSERT OR REPLACE INTO cycle_checkpoints
                   (date, status, step_completed, shadow_states, created_at, updated_at)
                   VALUES (?, ?, ?, ?, COALESCE(
                       (SELECT created_at FROM cycle_checkpoints WHERE date = ?), ?), ?)""",
                (date, status, step_completed, json.dumps(shadow_states),
                 date, now, now)
            )
            conn.commit()
        finally:
            conn.close()

    def get_cycle_checkpoint(self, date: str) -> dict | None:
        """Get checkpoint for a date. Returns None if no checkpoint exists."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM cycle_checkpoints WHERE date = ?",
                (date,)
            ).fetchone()
            if row is None:
                return None
            import json
            return {
                "date": row["date"],
                "status": row["status"],
                "step_completed": row["step_completed"],
                "shadow_states": json.loads(row["shadow_states"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        finally:
            conn.close()

    def get_incomplete_checkpoints(self) -> list[dict]:
        """Get all checkpoints with status != 'completed', oldest first."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT * FROM cycle_checkpoints
                   WHERE status != 'completed'
                   ORDER BY date ASC"""
            ).fetchall()
            import json
            return [{
                "date": r["date"],
                "status": r["status"],
                "step_completed": r["step_completed"],
                "shadow_states": json.loads(r["shadow_states"] or "{}"),
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            } for r in rows]
        finally:
            conn.close()

    def cleanup_old_checkpoints(self, keep_days: int = 30) -> int:
        """Remove checkpoints older than keep_days. Returns count deleted."""
        conn = self._connect()
        try:
            from datetime import timedelta
            cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)
                     ).strftime("%Y-%m-%d")
            cur = conn.execute(
                "DELETE FROM cycle_checkpoints WHERE date < ?",
                (cutoff,)
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    # ── PnL by domain ──────────────────────────────────────────────────────

    def get_pnl_by_domain(self, domain: str) -> list[float]:
        """Get PnL values from virtual_trades for shadows in a given domain.
        Domain is extracted from config_json JSON field."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT vt.pnl_pct FROM virtual_trades vt
                   JOIN shadows s ON vt.shadow_id = s.id
                   WHERE vt.pnl_pct IS NOT NULL
                     AND s.status != 'eliminated'
                     AND json_extract(s.config_json, '$.domain') = ?""",
                (domain,)
            ).fetchall()
            return [r["pnl_pct"] for r in rows]
        except Exception:
            logger.warning("json_extract failed for domain=%s — SQLite JSON1 may be missing", domain)
            return []

    def set_quarantine(self, shadow_id: str) -> None:
        """Mark a shadow as in post-collaboration quarantine for 7 days."""
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        conn = self._connect()
        try:
            conn.execute(
                """UPDATE daily_snapshots SET post_collaboration_quarantine = 1
                   WHERE shadow_id = ? AND date = ?""",
                (shadow_id, today)
            )
            conn.commit()
        finally:
            conn.close()

    def is_quarantined(self, shadow_id: str) -> bool:
        """Check if a shadow is in quarantine (flag=1 and within 7 days)."""
        conn = self._connect()
        try:
            row = conn.execute(
                """SELECT 1 FROM daily_snapshots
                   WHERE shadow_id = ? AND post_collaboration_quarantine = 1
                   AND date >= date('now', '-7 days') LIMIT 1""",
                (shadow_id,)
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def cleanup_expired_quarantines(self) -> int:
        """Clear quarantine flags older than 7 days. Returns count cleared."""
        conn = self._connect()
        try:
            cur = conn.execute(
                """UPDATE daily_snapshots SET post_collaboration_quarantine = 0
                   WHERE post_collaboration_quarantine = 1
                   AND date < date('now', '-7 days')"""
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()
