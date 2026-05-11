"""Shadow state persistence -- SQLite schema, config models, CRUD operations."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class ShadowConfig:
    """JSON-serializable shadow configuration."""
    shadow_id: str
    shadow_type: str                 # "beta" | "expert" | "daredevil" | "temp_event" | "challenger" | "missed_path" | "catfish"
    display_name: str
    methodology_prompt: str          # the shadow's entire system prompt
    virtual_capital: float
    max_positions: int = 3
    model: str = "flash"             # "flash" | "pro"
    temperature: float = 0.3
    reasoning_effort: str = "max"
    domain: str | None = None
    max_drawdown_limit: float = 0.35
    min_trades_for_ranking: int = 5
    parent_shadow_id: str | None = None
    generation: int = 0
    status: str = "active"           # "active" | "paused" | "watch" | "endangered" | "eliminated"
    eliminated_at: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class VirtualTradeOpen:
    shadow_id: str
    ticker: str
    direction: str                  # "long" | "short"
    entry_price: float
    position_size_pct: float
    entry_date: str


@dataclass
class VirtualTrade:
    trade_id: int
    shadow_id: str
    ticker: str
    direction: str
    entry_price: float
    exit_price: float | None
    position_size_pct: float
    entry_date: str
    exit_date: str | None
    exit_reason: str | None
    pnl_pct: float | None
    virtual_slippage_applied: float
    confidence_discount_applied: float
    paper_live_gap_ratio: float


@dataclass
class DailySnapshot:
    shadow_id: str
    date: str
    virtual_capital: float
    daily_return_pct: float | None = None
    cumulative_return_pct: float | None = None
    max_drawdown_pct: float | None = None
    win_rate_pct: float | None = None
    sharpe_ratio: float | None = None
    calmar_ratio: float | None = None
    omega_ratio: float | None = None
    mppm_score: float | None = None
    composite_score: float | None = None
    deflated_score: float | None = None
    percentile_rank: float | None = None
    achievement_tier: str | None = None
    flash_quota_used: int = 0
    pro_quota_used: int = 0
    emergency_quotas_used: int = 0
    insights_generated: int = 0


@dataclass
class IntegrityEvent:
    shadow_id: str
    date: str
    event_type: str                # "unverifiable_claim" | "false_claim" | "missing_source" | "verified_true"
    claim_detail: str              # JSON string
    score_change: int
    new_score: int


@dataclass
class EmergencyQuotaRequest:
    shadow_id: str
    requested_at: str
    confidence_self_report: int    # 8-10
    opportunity_description: str
    result: str = "pending"
    pnl_impact_pct: float | None = None
    quota_penalty_applied: str | None = None


@dataclass
class CollusionFlag:
    date: str
    agreement_pct: float
    consecutive_days: int
    market_signal_strength: float  # 0-1
    verdict: str                   # "convergence" | "herding" | "pending_review"
    user_action: str | None = None


# ── SQLite database ──────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS shadows (
    id TEXT PRIMARY KEY,
    shadow_type TEXT NOT NULL,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    methodology_prompt TEXT,
    config_json TEXT,
    created_at TEXT NOT NULL,
    eliminated_at TEXT
);

CREATE TABLE IF NOT EXISTS virtual_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    position_size_pct REAL NOT NULL,
    entry_date TEXT NOT NULL,
    exit_date TEXT,
    exit_reason TEXT,
    pnl_pct REAL,
    virtual_slippage_applied REAL DEFAULT 0.0,
    confidence_discount_applied REAL DEFAULT 0.0,
    paper_live_gap_ratio REAL DEFAULT 0.0,
    FOREIGN KEY (shadow_id) REFERENCES shadows(id)
);

CREATE TABLE IF NOT EXISTS daily_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT NOT NULL,
    date TEXT NOT NULL,
    virtual_capital REAL NOT NULL,
    daily_return_pct REAL,
    cumulative_return_pct REAL,
    max_drawdown_pct REAL,
    win_rate_pct REAL,
    sharpe_ratio REAL,
    calmar_ratio REAL,
    omega_ratio REAL,
    mppm_score REAL,
    composite_score REAL,
    deflated_score REAL,
    percentile_rank REAL,
    achievement_tier TEXT,
    flash_quota_used INTEGER DEFAULT 0,
    pro_quota_used INTEGER DEFAULT 0,
    emergency_quotas_used INTEGER DEFAULT 0,
    insights_generated INTEGER DEFAULT 0,
    UNIQUE(shadow_id, date),
    FOREIGN KEY (shadow_id) REFERENCES shadows(id)
);

CREATE TABLE IF NOT EXISTS ranking_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    shadow_id TEXT NOT NULL,
    rank INTEGER NOT NULL,
    composite_score REAL NOT NULL,
    deflated_score REAL NOT NULL,
    component_scores TEXT NOT NULL,
    UNIQUE(date, shadow_id),
    FOREIGN KEY (shadow_id) REFERENCES shadows(id)
);

CREATE TABLE IF NOT EXISTS integrity_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT NOT NULL,
    date TEXT NOT NULL,
    event_type TEXT NOT NULL,
    claim_detail TEXT NOT NULL,
    score_change INTEGER NOT NULL,
    new_score INTEGER NOT NULL,
    UNIQUE(shadow_id, date, event_type, claim_detail),
    FOREIGN KEY (shadow_id) REFERENCES shadows(id)
);

CREATE TABLE IF NOT EXISTS emergency_quotas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    confidence_self_report INTEGER NOT NULL,
    opportunity_description TEXT NOT NULL,
    result TEXT DEFAULT 'pending',
    pnl_impact_pct REAL,
    quota_penalty_applied TEXT,
    FOREIGN KEY (shadow_id) REFERENCES shadows(id)
);

CREATE TABLE IF NOT EXISTS collusion_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    agreement_pct REAL NOT NULL,
    consecutive_days INTEGER NOT NULL,
    market_signal_strength REAL,
    verdict TEXT NOT NULL,
    user_action TEXT
);
"""


class ShadowStateDB:
    """SQLite-backed shadow state persistence."""

    def __init__(self, db_path: str = "data/shadows/shadows.db"):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA_SQL)
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

    def get_shadow(self, shadow_id: str) -> ShadowConfig | None:
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
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _row_to_config(row: sqlite3.Row) -> ShadowConfig:
        config_json = json.loads(row["config_json"] or "{}")
        return ShadowConfig(
            shadow_id=row["id"],
            shadow_type=row["shadow_type"],
            display_name=row["display_name"],
            methodology_prompt=row["methodology_prompt"] or "",
            virtual_capital=config_json.get("virtual_capital", 0),
            max_positions=config_json.get("max_positions", 3),
            model=config_json.get("model", "flash"),
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

    def get_trade_history(self, shadow_id: str, days: int = 90) -> list[VirtualTrade]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT * FROM virtual_trades
                   WHERE shadow_id = ? AND exit_price IS NOT NULL
                   ORDER BY exit_date DESC
                   LIMIT ?""",
                (shadow_id, days * 10)
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
            virtual_slippage_applied=row["virtual_slippage_applied"] or 0.0,
            confidence_discount_applied=row["confidence_discount_applied"] or 0.0,
            paper_live_gap_ratio=row["paper_live_gap_ratio"] or 0.0,
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
                    emergency_quotas_used, insights_generated)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (shadow_id, snapshot.date, snapshot.virtual_capital,
                 snapshot.daily_return_pct, snapshot.cumulative_return_pct,
                 snapshot.max_drawdown_pct, snapshot.win_rate_pct,
                 snapshot.sharpe_ratio, snapshot.calmar_ratio, snapshot.omega_ratio,
                 snapshot.mppm_score, snapshot.composite_score, snapshot.deflated_score,
                 snapshot.percentile_rank, snapshot.achievement_tier,
                 snapshot.flash_quota_used, snapshot.pro_quota_used,
                 snapshot.emergency_quotas_used, snapshot.insights_generated)
            )
            conn.commit()
        finally:
            conn.close()

    def get_snapshot_history(self, shadow_id: str, days: int = 90) -> list[DailySnapshot]:
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

    def get_latest_snapshot(self, shadow_id: str) -> DailySnapshot | None:
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
            flash_quota_used=row["flash_quota_used"] or 0,
            pro_quota_used=row["pro_quota_used"] or 0,
            emergency_quotas_used=row["emergency_quotas_used"] or 0,
            insights_generated=row["insights_generated"] or 0,
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
            return [{
                "date": r["date"], "shadow_id": r["shadow_id"],
                "rank": r["rank"], "composite_score": r["composite_score"],
                "deflated_score": r["deflated_score"],
                "component_scores": json.loads(r["component_scores"]),
            } for r in rows]
        finally:
            conn.close()

    # ── Integrity ─────────────────────────────────────────────────────────

    def record_integrity_event(self, shadow_id: str, event: IntegrityEvent) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO integrity_events
                   (shadow_id, date, event_type, claim_detail, score_change, new_score)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (shadow_id, event.date, event.event_type, event.claim_detail,
                 event.score_change, event.new_score)
            )
            conn.commit()
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
