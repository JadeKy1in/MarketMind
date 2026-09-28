"""Unified ledger store (SPEC_v3 §7): every prediction and paper trade, one table.

SQLite at `<data_dir>/ledger.db`. Records are written once at decision time;
settlement fields are filled in later by `marketmind.ledger.settlement`, which
recomputes from price bars on every run (idempotent), so a record can move
pending -> open -> settled (or void) without any hand edits.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

SOURCE_TYPES = ("main", "main_forced", "shadow", "temp_shadow", "playground", "benchmark", "owner",
                "evidence", "alert", "watch", "watch_counterfactual")
ENTRY_RULES = ("next_open", "zone")
# pending: waiting for the entry fill; open: filled, not yet exited;
# settled: exited and scored; void: never filled within the window.
STATUSES = ("pending", "open", "settled", "void")


@dataclass
class LedgerEntry:
    source_type: str
    source_id: str
    ticker: str
    direction: str                     # long | short
    hold_bars: int                     # holding period in daily bars (trading days; calendar days for crypto)
    confidence: float                  # P(profitable), 0-1
    position_usd: float
    falsifier: str                     # human-readable "I am wrong if ..."
    thesis: str = ""
    layer: str = "tradable"            # tradable | linkage
    asset_type: str = "stock"          # stock | etf | crypto | ...
    entry_rule: str = "next_open"
    entry_low: float | None = None
    entry_high: float | None = None
    stop_loss: float | None = None
    target_price: float | None = None
    falsifier_rule: dict | None = None  # e.g. {"type": "close_below", "price": 54.5}
    domain_benchmark: str | None = None
    confidence_is_default: bool = False
    snapshot_id: str | None = None
    meta: dict = field(default_factory=dict)
    # Assigned by the store
    entry_id: str = ""
    created_at: str = ""
    # Settlement (filled by settlement.py)
    status: str = "pending"
    entry_date: str | None = None
    entry_price: float | None = None
    exit_date: str | None = None
    exit_price: float | None = None
    exit_reason: str | None = None     # stop | target | falsifier | expiry | unfilled
    gross_return: float | None = None
    cost_return: float | None = None
    net_return: float | None = None
    pnl_usd: float | None = None
    market_benchmark: str | None = None
    market_return: float | None = None
    excess_market: float | None = None
    domain_return: float | None = None
    excess_domain: float | None = None
    brier: float | None = None
    falsifier_triggered: bool | None = None
    price_source: str | None = None
    settle_note: str = ""
    settled_at: str | None = None

    def validate(self) -> None:
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"unknown source_type {self.source_type!r}")
        if self.direction not in ("long", "short"):
            raise ValueError(f"direction must be long|short, got {self.direction!r}")
        if self.entry_rule not in ENTRY_RULES:
            raise ValueError(f"unknown entry_rule {self.entry_rule!r}")
        if self.entry_rule == "zone" and (self.entry_low is None or self.entry_high is None
                                          or self.entry_low > self.entry_high):
            raise ValueError("zone entry needs entry_low <= entry_high")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be 0-1, got {self.confidence}")
        if self.hold_bars < 1:
            raise ValueError("hold_bars must be >= 1")
        if not self.ticker:
            raise ValueError("ticker is required")
        if not self.falsifier.strip():
            raise ValueError("falsifier is required (SPEC_v3 L5)")
        if self.falsifier_rule is not None:
            if self.falsifier_rule.get("type") not in ("close_below", "close_above"):
                raise ValueError(f"unknown falsifier_rule type {self.falsifier_rule.get('type')!r}")
            try:
                self.falsifier_rule["price"] = float(self.falsifier_rule["price"])
            except (KeyError, TypeError, ValueError):
                raise ValueError("falsifier_rule needs a numeric price") from None


_JSON_FIELDS = {"falsifier_rule", "meta"}
_BOOL_FIELDS = {"confidence_is_default", "falsifier_triggered"}
_COLUMNS = [f.name for f in fields(LedgerEntry)]

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS ledger (
    {", ".join(("entry_id TEXT PRIMARY KEY" if c == "entry_id" else c) for c in _COLUMNS)}
);
CREATE INDEX IF NOT EXISTS ix_ledger_status ON ledger(status);
CREATE INDEX IF NOT EXISTS ix_ledger_source ON ledger(source_type, source_id);
CREATE TABLE IF NOT EXISTS quote_snapshots (
    snapshot_id TEXT NOT NULL,
    taken_at TEXT NOT NULL,
    ticker TEXT NOT NULL,
    price REAL,
    price_date TEXT,
    source TEXT,
    PRIMARY KEY (snapshot_id, ticker)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class LedgerStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    # ── writes ──────────────────────────────────────────────────────────

    def add(self, entry: LedgerEntry, created_at: str | None = None) -> str:
        entry.validate()
        entry.entry_id = entry.entry_id or uuid.uuid4().hex[:16]
        entry.created_at = created_at or entry.created_at or _now()
        row = self._to_row(entry)
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with self._connect() as conn:
            conn.execute(f"INSERT INTO ledger ({cols}) VALUES ({marks})", list(row.values()))
        return entry.entry_id

    def update(self, entry: LedgerEntry) -> None:
        row = self._to_row(entry)
        row.pop("entry_id")
        sets = ", ".join(f"{c} = ?" for c in row)
        with self._connect() as conn:
            conn.execute(f"UPDATE ledger SET {sets} WHERE entry_id = ?",
                         [*row.values(), entry.entry_id])

    def save_snapshot(self, quotes: dict[str, tuple[float | None, str | None, str | None]],
                      taken_at: str | None = None) -> str:
        """quotes: ticker -> (price, price_date, source). Returns the snapshot id."""
        snapshot_id = uuid.uuid4().hex[:16]
        taken_at = taken_at or _now()
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO quote_snapshots VALUES (?, ?, ?, ?, ?, ?)",
                [(snapshot_id, taken_at, t, p, d, s) for t, (p, d, s) in quotes.items()],
            )
        return snapshot_id

    # ── reads ───────────────────────────────────────────────────────────

    def get(self, entry_id: str) -> LedgerEntry | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM ledger WHERE entry_id = ?", (entry_id,)).fetchone()
        return self._from_row(row) if row else None

    def list(self, status: str | tuple[str, ...] | None = None,
             source_type: str | None = None) -> list[LedgerEntry]:
        sql, args = "SELECT * FROM ledger WHERE 1=1", []
        if status:
            statuses = (status,) if isinstance(status, str) else tuple(status)
            sql += f" AND status IN ({', '.join('?' for _ in statuses)})"
            args.extend(statuses)
        if source_type:
            sql += " AND source_type = ?"
            args.append(source_type)
        sql += " ORDER BY created_at, entry_id"
        with self._connect() as conn:
            return [self._from_row(r) for r in conn.execute(sql, args).fetchall()]

    def unsettled(self) -> list[LedgerEntry]:
        return self.list(status=("pending", "open"))

    def snapshot(self, snapshot_id: str) -> dict[str, dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM quote_snapshots WHERE snapshot_id = ?",
                                (snapshot_id,)).fetchall()
        return {r["ticker"]: dict(r) for r in rows}

    # ── mapping ─────────────────────────────────────────────────────────

    @staticmethod
    def _to_row(entry: LedgerEntry) -> dict:
        row = asdict(entry)
        for k in _JSON_FIELDS:
            row[k] = json.dumps(row[k], ensure_ascii=False) if row[k] is not None else None
        for k in _BOOL_FIELDS:
            row[k] = None if row[k] is None else int(bool(row[k]))
        return row

    @staticmethod
    def _from_row(row: sqlite3.Row) -> LedgerEntry:
        data = dict(row)
        for k in _JSON_FIELDS:
            data[k] = json.loads(data[k]) if data[k] else ({} if k == "meta" else None)
        for k in _BOOL_FIELDS:
            data[k] = None if data[k] is None else bool(data[k])
        return LedgerEntry(**{k: data[k] for k in _COLUMNS if k in data})


def default_ledger_path() -> Path:
    import os
    return Path(os.getenv("MARKETMIND_DATA_DIR", "data")) / "ledger.db"
