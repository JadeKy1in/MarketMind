"""Unified ledger store (SPEC_v3 §7): every prediction and paper trade, one table.

SQLite at `<data_dir>/ledger.db`. Records are written once at decision time;
settlement fields are filled in later by `marketmind.ledger.settlement`, which
recomputes from price bars on every run (idempotent), so a record can move
pending -> open -> settled (or void) without any hand edits.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

logger = logging.getLogger("marketmind.ledger.store")

SOURCE_TYPES = ("main", "main_forced", "shadow", "temp_shadow", "playground", "benchmark", "owner",
                "evidence", "alert", "watch", "watch_counterfactual")
ENTRY_RULES = ("next_open", "zone")
# pending: waiting for the entry fill; open: filled, not yet exited;
# settled: exited and scored; void: never filled within the window.
STATUSES = ("pending", "open", "settled", "void")
UNSETTLED = ("pending", "open")
# A record's target session is at most a few days after its creation (weekends,
# holidays), so only this recent a window can hold a same-session record.
SESSION_LOOKBACK_DAYS = 10


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
    exit_reason: str | None = None     # stop | target | falsifier | expiry | unfilled | gap_target (gap_stop: legacy)
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
    review: dict | None = None         # code-computed post-mortem facts (docs/S9_DESIGN.md §3)

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


_JSON_FIELDS = {"falsifier_rule", "meta", "review"}
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


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


class LedgerStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            # WAL: readers never block the writer (settlement, shadows and the main
            # pipeline may run in separate processes)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            # a ledger created before a column was added gets it (NULL for old rows)
            existing = {r[1] for r in conn.execute("PRAGMA table_info(ledger)")}
            for col in _COLUMNS:
                if col not in existing:
                    try:
                        conn.execute(f"ALTER TABLE ledger ADD COLUMN {col}")
                    except sqlite3.OperationalError as exc:
                        # another process added it between our check and the ALTER
                        if "duplicate column name" not in str(exc).lower():
                            raise

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)   # wait for a concurrent writer
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

    def update_if_status(self, entry: LedgerEntry, expected: tuple[str, ...]) -> bool:
        """Write `entry` only while the stored row still has one of the `expected`
        statuses; False if another process changed it meanwhile (e.g. voided it)."""
        row = self._to_row(entry)
        row.pop("entry_id")
        sets = ", ".join(f"{c} = ?" for c in row)
        marks = ", ".join("?" for _ in expected)
        with self._connect() as conn:
            cur = conn.execute(
                f"UPDATE ledger SET {sets} WHERE entry_id = ? AND status IN ({marks})",
                [*row.values(), entry.entry_id, *expected])
            return cur.rowcount == 1

    def add_submission(self, entries: list[LedgerEntry],
                       session_of: Callable[[LedgerEntry], str | None],
                       created_at: str | None = None,
                       companions: list[LedgerEntry] = ()) -> list[str] | None:
        """Insert one submission atomically, unless it repeats a target session.

        The submission is rejected (None, nothing written) when a record from the same
        (source_type, source_id) already exists for the target session of any of
        `entries` (`session_of`: the first bar date a record could trade on).
        `companions` (e.g. its random benchmark) are written only with the submission.
        Check and insert run in one BEGIN IMMEDIATE transaction, so two processes
        cannot both pass the check. Returns the ids of `entries`, then `companions`.
        """
        batch = list(entries) + list(companions)
        now = _now()
        for e in batch:
            e.validate()
            e.entry_id = e.entry_id or uuid.uuid4().hex[:16]
            e.created_at = created_at or e.created_at or now
        wanted: dict[tuple[str, str], tuple[set[str], str]] = {}
        for e in entries:
            session = session_of(e)
            if session:
                sessions, first = wanted.get((e.source_type, e.source_id), (set(), e.created_at))
                sessions.add(session)
                wanted[(e.source_type, e.source_id)] = (sessions, min(first, e.created_at))
        conn = self._connect()
        conn.isolation_level = None                  # explicit transaction below
        try:
            conn.execute("BEGIN IMMEDIATE")
            for (stype, sid), (sessions, first) in wanted.items():
                existing = {s for e in self.recent(stype, sid, first, conn)
                            if (s := session_of(e))}
                if clash := sessions & existing:
                    conn.execute("ROLLBACK")
                    logger.warning("Ledger: %s %s already has a record for session %s; "
                                   "duplicate submission not recorded",
                                   stype, sid, ", ".join(sorted(clash)))
                    return None
            for e in batch:
                row = self._to_row(e)
                conn.execute(f"INSERT INTO ledger ({', '.join(row)}) "
                             f"VALUES ({', '.join('?' for _ in row)})", list(row.values()))
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
        return [e.entry_id for e in batch]

    def recent(self, source_type: str, source_id: str, created_at: str | None = None,
               conn: sqlite3.Connection | None = None) -> list[LedgerEntry]:
        """Records of one source created at most SESSION_LOOKBACK_DAYS before
        `created_at` (default: now), void ones included."""
        ref = _parse(created_at) or datetime.now(timezone.utc)
        since = (ref - timedelta(days=SESSION_LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        sql = ("SELECT * FROM ledger WHERE source_type = ? AND source_id = ? "
               "AND created_at >= ? ORDER BY created_at, entry_id")
        if conn is not None:
            rows = conn.execute(sql, (source_type, source_id, since)).fetchall()
        else:
            with self._connect() as c:
                rows = c.execute(sql, (source_type, source_id, since)).fetchall()
        return [self._from_row(r) for r in rows]

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
        return self.list(status=UNSETTLED)

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
