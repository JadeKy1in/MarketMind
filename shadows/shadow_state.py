"""Shadow state persistence -- SQLite schema, thin delegation layer to repo modules."""
from __future__ import annotations

import importlib
import logging
import sqlite3
from pathlib import Path

from marketmind.shadows.shadow_data_types import (  # noqa: F401 — re-export for backward compat
    ShadowConfig,
    VirtualTradeOpen,
    VirtualTrade,
    DailySnapshot,
    IntegrityEvent,
    EmergencyQuotaRequest,
    CollusionFlag,
)
from marketmind.shadows.shadow_schema import (  # noqa: F401 — re-export
    CODE_VERSION,
    _SCHEMA_SQL,
    _MIGRATIONS,
    init_shadow_db_schema,
)

logger = logging.getLogger("marketmind.shadows.shadow_state")

# Schema version + DDL + migrations imported from shadow_schema
_ = _SCHEMA_SQL  # reference to suppress unused-import warning

_REPO_BASE = "marketmind.shadows"

class ShadowStateDB:
    """SQLite-backed shadow state persistence -- thin delegation to repo modules."""

    def __init__(self, db_path: str = "data/shadows/shadows.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _delegate(self, module_path: str, func_name: str, *args, **kwargs):
        """Generic delegation: import repo function, connect, call, close."""
        mod = importlib.import_module(module_path)
        func = getattr(mod, func_name)
        conn = self._connect()
        try:
            return func(conn, *args, **kwargs)
        finally:
            conn.close()

    def init_schema(self) -> None:
        conn = self._connect()
        try:
            init_shadow_db_schema(conn)
            conn.commit()
        finally:
            conn.close()

    def close(self) -> None:
        pass  # SQLite connections are closed per-operation

    # ── Shadow CRUD ──────────────────────────────────────────────────────────

    def create_shadow(self, config: ShadowConfig) -> str:
        return self._delegate(f"{_REPO_BASE}.shadow_config_repo", "create_shadow", config)

    def get_shadow(self, shadow_id: str) -> ShadowConfig | None:
        return self._delegate(f"{_REPO_BASE}.shadow_config_repo", "get_shadow", shadow_id)

    def get_active_shadows(self, shadow_type: str | None = None) -> list[ShadowConfig]:
        return self._delegate(f"{_REPO_BASE}.shadow_config_repo", "get_active_shadows", shadow_type)

    def get_visible_shadows(self) -> list[ShadowConfig]:
        return self._delegate(f"{_REPO_BASE}.shadow_config_repo", "get_visible_shadows")

    def get_ranking_eligible_shadows(self) -> list[ShadowConfig]:
        return self._delegate(f"{_REPO_BASE}.shadow_config_repo", "get_ranking_eligible_shadows")

    def update_shadow_status(self, shadow_id: str, status: str) -> None:
        self._delegate(f"{_REPO_BASE}.shadow_config_repo", "update_shadow_status", shadow_id, status)

    def retire_shadow(self, shadow_id: str, reason: str) -> None:
        self._delegate(f"{_REPO_BASE}.shadow_config_repo", "retire_shadow", shadow_id, reason)

    def eliminate_shadow(self, shadow_id: str, reason: str) -> None:
        self._delegate(f"{_REPO_BASE}.shadow_config_repo", "eliminate_shadow", shadow_id, reason)

    def update_shadow_type(self, shadow_id: str, new_type: str) -> bool:
        return self._delegate(f"{_REPO_BASE}.shadow_config_repo", "update_shadow_type", shadow_id, new_type)

    # ── Methodology ──────────────────────────────────────────────────────────

    def update_methodology_prompt(self, shadow_id: str, new_prompt: str,
                                    reason: str = "") -> bool:
        return self._delegate(f"{_REPO_BASE}.shadow_config_repo", "update_methodology_prompt",
                            shadow_id, new_prompt, reason)

    def get_methodology_history(self, shadow_id: str,
                                 limit: int = 20) -> list[dict]:
        return self._delegate(f"{_REPO_BASE}.shadow_config_repo", "get_methodology_history",
                            shadow_id, limit)

    def get_original_methodology(self, shadow_id: str) -> str | None:
        return self._delegate(f"{_REPO_BASE}.shadow_config_repo", "get_original_methodology", shadow_id)

    def get_failure_patterns(self, shadow_id: str, days: int = 90) -> list[str]:
        return self._delegate(f"{_REPO_BASE}.shadow_config_repo", "get_failure_patterns",
                            shadow_id, days)

    def get_retired_insights(self, shadow_id: str, days: int = 90) -> list[str]:
        return self._delegate(f"{_REPO_BASE}.shadow_config_repo", "get_retired_insights",
                            shadow_id, days)

    # ── Virtual trades ──────────────────────────────────────────────────────

    def record_trade_open(self, shadow_id: str, trade: VirtualTradeOpen) -> int:
        return self._delegate(f"{_REPO_BASE}.shadow_trade_repo", "record_trade_open", shadow_id, trade)

    def record_trade_close(self, trade_id: int, exit_price: float,
                           exit_reason: str, pnl_pct: float) -> None:
        self._delegate(f"{_REPO_BASE}.shadow_trade_repo", "record_trade_close",
                      trade_id, exit_price, exit_reason, pnl_pct)

    def get_open_trades(self, shadow_id: str) -> list[VirtualTrade]:
        return self._delegate(f"{_REPO_BASE}.shadow_trade_repo", "get_open_trades", shadow_id)

    def get_all_open_trades(self) -> list[dict]:
        """Aggregate open trades across all visible shadows. Returns list of dicts."""
        trades: list[dict] = []
        for s in self.get_visible_shadows():
            for t in self.get_open_trades(s.shadow_id):
                trades.append({
                    "ticker": t.ticker,
                    "entry_price": t.entry_price,
                    "direction": t.direction,
                    "shadow_id": t.shadow_id,
                    "market_value": getattr(t, "market_value", t.entry_price),
                })
        return trades

    def get_trade_history(self, shadow_id: str, limit: int = 90) -> list[VirtualTrade]:
        return self._delegate(f"{_REPO_BASE}.shadow_trade_repo", "get_trade_history", shadow_id, limit)

    # ── Daily snapshots ─────────────────────────────────────────────────────

    def save_snapshot(self, shadow_id: str, snapshot: DailySnapshot) -> None:
        self._delegate(f"{_REPO_BASE}.shadow_snapshot_repo", "save_snapshot", shadow_id, snapshot)

    def get_snapshot_history(self, shadow_id: str, days: int = 90) -> list[DailySnapshot]:
        return self._delegate(f"{_REPO_BASE}.shadow_snapshot_repo", "get_snapshot_history", shadow_id, days)

    def get_latest_snapshot(self, shadow_id: str) -> DailySnapshot | None:
        return self._delegate(f"{_REPO_BASE}.shadow_snapshot_repo", "get_latest_snapshot", shadow_id)

    def get_tier_history(self, shadow_id: str, days: int = 120) -> list[tuple[str, str]]:
        return self._delegate(f"{_REPO_BASE}.shadow_snapshot_repo", "get_tier_history", shadow_id, days)

    def get_wr_history(self, shadow_id: str, days: int = 120) -> list[tuple[str, float]]:
        return self._delegate(f"{_REPO_BASE}.shadow_snapshot_repo", "get_wr_history", shadow_id, days)

    def get_insight_dates(self, shadow_id: str, days: int = 120) -> list[str]:
        return self._delegate(f"{_REPO_BASE}.shadow_snapshot_repo", "get_insight_dates", shadow_id, days)

    def get_abstention_days(self, shadow_id: str, days: int = 180) -> int:
        return self._delegate(f"{_REPO_BASE}.shadow_snapshot_repo", "get_abstention_days", shadow_id, days)

    def save_raw_output(self, shadow_id: str, date: str, raw_output: str,
                         token_count: int = 0, model: str = "pro") -> None:
        self._delegate(f"{_REPO_BASE}.shadow_snapshot_repo", "save_raw_output",
                      shadow_id, date, raw_output, token_count, model)

    def count_consecutive_zero_insights(self, shadow_id: str,
                                         max_days: int = 8) -> int:
        return self._delegate(f"{_REPO_BASE}.shadow_snapshot_repo", "count_consecutive_zero_insights",
                            shadow_id, max_days)

    def get_raw_output(self, shadow_id: str, date: str) -> str | None:
        return self._delegate(f"{_REPO_BASE}.shadow_snapshot_repo", "get_raw_output", shadow_id, date)

    def get_token_history(self, shadow_id: str, days: int = 30) -> list[int]:
        return self._delegate(f"{_REPO_BASE}.shadow_snapshot_repo", "get_token_history", shadow_id, days)

    def update_snapshot_fields(self, shadow_id: str, date: str, **fields) -> None:
        self._delegate(f"{_REPO_BASE}.shadow_snapshot_repo", "update_snapshot_fields",
                      shadow_id, date, **fields)

    def get_all_daily_snapshots(self, date: str) -> list[DailySnapshot]:
        return self._delegate(f"{_REPO_BASE}.shadow_snapshot_repo", "get_all_daily_snapshots", date)

    # ── Rankings ────────────────────────────────────────────────────────────

    def save_rankings(self, date: str, rankings: list[tuple[str, float, float, dict]]) -> None:
        self._delegate(f"{_REPO_BASE}.shadow_analysis_repo", "save_rankings", date, rankings)

    def get_ranking_history(self, shadow_id: str, days: int = 90) -> list[dict]:
        return self._delegate(f"{_REPO_BASE}.shadow_analysis_repo", "get_ranking_history", shadow_id, days)

    # ── Integrity / Emergency / Collusion ────────────────────────────────────

    def record_integrity_event(self, shadow_id: str, event: IntegrityEvent) -> bool:
        return self._delegate(f"{_REPO_BASE}.shadow_integrity_repo", "record_integrity_event",
                            shadow_id, event)

    def get_integrity_score(self, shadow_id: str) -> int:
        return self._delegate(f"{_REPO_BASE}.shadow_integrity_repo", "get_integrity_score", shadow_id)

    def get_integrity_history(self, shadow_id: str, days: int = 90) -> list[IntegrityEvent]:
        return self._delegate(f"{_REPO_BASE}.shadow_integrity_repo", "get_integrity_history",
                            shadow_id, days)

    def record_emergency_quota(self, shadow_id: str, quota: EmergencyQuotaRequest) -> int:
        return self._delegate(f"{_REPO_BASE}.shadow_integrity_repo", "record_emergency_quota",
                            shadow_id, quota)

    def update_emergency_result(self, quota_id: int, result: str,
                                pnl_impact: float, penalty: str) -> None:
        self._delegate(f"{_REPO_BASE}.shadow_integrity_repo", "update_emergency_result",
                      quota_id, result, pnl_impact, penalty)

    def get_pending_emergency_audits(self) -> list[EmergencyQuotaRequest]:
        return self._delegate(f"{_REPO_BASE}.shadow_integrity_repo", "get_pending_emergency_audits")

    def record_collusion_flag(self, flag: CollusionFlag) -> None:
        self._delegate(f"{_REPO_BASE}.shadow_integrity_repo", "record_collusion_flag", flag)

    def get_recent_collusion_flags(self, days: int = 30) -> list[CollusionFlag]:
        return self._delegate(f"{_REPO_BASE}.shadow_integrity_repo", "get_recent_collusion_flags", days)

    def save_emergency_quota_state(self, shadow_id: str, state_json: str) -> None:
        self._delegate(f"{_REPO_BASE}.shadow_integrity_repo", "save_emergency_quota_state",
                      shadow_id, state_json)

    def load_emergency_quota_state(self, shadow_id: str) -> str | None:
        return self._delegate(f"{_REPO_BASE}.shadow_integrity_repo", "load_emergency_quota_state", shadow_id)

    def save_paper_live_gap_state(self, shadow_id: str, state_json: str) -> None:
        self._delegate(f"{_REPO_BASE}.shadow_integrity_repo", "save_paper_live_gap_state",
                      shadow_id, state_json)

    def load_paper_live_gap_state(self, shadow_id: str) -> str | None:
        return self._delegate(f"{_REPO_BASE}.shadow_integrity_repo", "load_paper_live_gap_state", shadow_id)

    # ── Cycle checkpoints ────────────────────────────────────────────────────

    def save_checkpoint(self, date: str, shadow_id: str, status: str,
                        step: int, analysis_json: str | None = None,
                        error_message: str | None = None) -> None:
        self._delegate(f"{_REPO_BASE}.shadow_checkpoint_repo", "save_checkpoint",
                      date, shadow_id, status, step, analysis_json, error_message)

    def get_checkpoint(self, date: str, shadow_id: str) -> dict | None:
        return self._delegate(f"{_REPO_BASE}.shadow_checkpoint_repo", "get_checkpoint", date, shadow_id)

    def get_incomplete_shadows(self, date: str) -> list[str]:
        return self._delegate(f"{_REPO_BASE}.shadow_checkpoint_repo", "get_incomplete_shadows", date)

    def clear_date_checkpoints(self, date: str) -> None:
        self._delegate(f"{_REPO_BASE}.shadow_checkpoint_repo", "clear_date_checkpoints", date)

    # ── Analysis / PnL ──────────────────────────────────────────────────────

    def get_all_active_analyses(self, date: str, ticker: str) -> list[dict]:
        return self._delegate(f"{_REPO_BASE}.shadow_analysis_repo", "get_all_active_analyses",
                            date, ticker)

    def get_next_day_return_sign(self, ticker_or_shadow: str, date: str) -> int | None:
        return self._delegate(f"{_REPO_BASE}.shadow_analysis_repo", "get_next_day_return_sign",
                            ticker_or_shadow, date)

    def save_analyses(self, shadow_id: str, date: str, analyses: list) -> None:
        if not analyses:
            return
        self._delegate(f"{_REPO_BASE}.shadow_analysis_repo", "save_analyses",
                      shadow_id, date, analyses)

    def save_beta_analyses(self, shadow_id: str, date: str, analyses: list,
                           methodology_variant: str | None = None) -> None:
        if not analyses:
            return
        self._delegate(f"{_REPO_BASE}.shadow_analysis_repo", "save_beta_analyses",
                      shadow_id, date, analyses, methodology_variant)

    def get_analyses_by_date_range(self, start_date: str, end_date: str) -> list[dict]:
        return self._delegate(f"{_REPO_BASE}.shadow_analysis_repo", "get_analyses_by_date_range",
                            start_date, end_date)

    def get_analyses_with_direction(self, shadow_id: str,
                                     days: int = 90) -> list[dict]:
        return self._delegate(f"{_REPO_BASE}.shadow_analysis_repo", "get_analyses_with_direction",
                            shadow_id, days)

    def get_pnl_by_domain(self, domain: str) -> list[float]:
        return self._delegate(f"{_REPO_BASE}.shadow_analysis_repo", "get_pnl_by_domain", domain)

    # ── Market prices ───────────────────────────────────────────────────────

    def insert_market_price(self, ticker: str, date: str, open_price: float,
                            high: float, low: float, close: float, volume: int,
                            next_day_return: float | None = None) -> None:
        self._delegate(f"{_REPO_BASE}.shadow_market_repo", "insert_market_price",
                      ticker, date, open_price, high, low, close, volume, next_day_return)

    def get_market_prices(self, ticker: str, start_date: str | None = None,
                          end_date: str | None = None) -> list[dict]:
        return self._delegate(f"{_REPO_BASE}.shadow_market_repo", "get_market_prices",
                            ticker, start_date, end_date)

    def get_next_day_return(self, ticker: str, date: str) -> float | None:
        return self._delegate(f"{_REPO_BASE}.shadow_market_repo", "get_next_day_return", ticker, date)
