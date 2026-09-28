"""Watch items and their SQLite store (docs/S10_DESIGN.md §3).

SQLite at `<data_dir>/watchlist.db`, separate from the ledger: a watch item is
not a prediction until it triggers. What IS a prediction is written to the
ledger by `marketmind.watchlist.runner` (the "enter now" counterfactual when
the item is created, and the real entry when it triggers).

Lifecycle: watching -> triggered | expired | invalidated (terminal).
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

from marketmind.watchlist.conditions import validate_conditions

SOURCES = ("main_pipeline", "anomaly")
STATUSES = ("watching", "triggered", "expired", "invalidated")
DIRECTIONS = ("long", "short")
# S10 §4 origin kinds
ORIGIN_KINDS = ("anomaly", "evidence", "news", "watch", "scanner", "shadow")
DEFAULT_EXPIRY_BARS = 20
DEFAULT_HOLD_BARS = 20
MAX_EXPIRY_BARS = 250
DEFAULT_ANOMALY_CONDITIONS = [{"type": "breakout_20d"}]


@dataclass
class WatchItem:
    ticker: str
    direction: str                      # long | short
    source: str                         # main_pipeline | anomaly
    thesis: str
    conditions: list[dict] = field(default_factory=list)   # all must hold on one bar (AND);
    #                                   empty is allowed only for anomaly items (-> breakout_20d)
    invalidation: list[dict] = field(default_factory=list)   # any one holding invalidates (OR)
    expiry_bars: int = DEFAULT_EXPIRY_BARS   # complete bars of the ticker's market after creation
    hold_bars: int = DEFAULT_HOLD_BARS       # holding period of the ledger entries it writes
    confidence: float | None = None     # P(profitable) if the source stated one
    origin: dict = field(default_factory=dict)
    # Assigned / maintained by the store and runner
    id: str = ""
    created_at: str = ""
    status: str = "watching"
    counterfactual_entry_id: str | None = None
    triggered_entry_id: str | None = None
    last_bar_date: str | None = None    # last complete bar already evaluated
    bars_seen: int = 0                  # complete bars evaluated since creation
    closed_at: str | None = None        # when it left `watching`
    close_bar_date: str | None = None
    close_detail: dict = field(default_factory=dict)   # conditions that fired / expiry note
    refreshed_at: str | None = None
    history: list[dict] = field(default_factory=list)

    def validate(self) -> None:
        self.ticker = (self.ticker or "").strip().upper()
        if not self.ticker:
            raise ValueError("ticker is required")
        if self.direction not in DIRECTIONS:
            raise ValueError(f"direction must be long|short, got {self.direction!r}")
        if self.source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}, got {self.source!r}")
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}")
        self.thesis = (self.thesis or "").strip()
        if not self.thesis:
            raise ValueError("thesis is required")
        if self.source == "anomaly" and not self.conditions:
            self.conditions = [dict(c) for c in DEFAULT_ANOMALY_CONDITIONS]
        self.conditions = validate_conditions(self.conditions)
        self.invalidation = validate_conditions(self.invalidation, allow_empty=True)
        for name in ("expiry_bars", "hold_bars"):
            v = getattr(self, name)
            if isinstance(v, float) and v.is_integer():
                v = int(v)
                setattr(self, name, v)
            if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= MAX_EXPIRY_BARS:
                raise ValueError(f"{name} must be an integer 1-{MAX_EXPIRY_BARS}, got {v!r}")
        if self.confidence is not None:
            try:
                c = float(self.confidence)
            except (TypeError, ValueError):
                raise ValueError(f"confidence must be 0-1, got {self.confidence!r}") from None
            if c > 1.0 and c <= 100.0:          # a percentage slipped through
                c /= 100.0
            if not 0.0 <= c <= 1.0:
                raise ValueError(f"confidence must be 0-1, got {self.confidence}")
            self.confidence = c
        if not isinstance(self.origin, dict):
            raise ValueError("origin must be an object")
        kind = self.origin.get("kind")
        if kind is None:
            self.origin = {"kind": "anomaly" if self.source == "anomaly" else "watch",
                           **self.origin}
        elif kind not in ORIGIN_KINDS:
            raise ValueError(f"origin.kind must be one of {ORIGIN_KINDS}, got {kind!r}")


_JSON_FIELDS = {"conditions", "invalidation", "origin", "close_detail", "history"}
_COLUMNS = [f.name for f in fields(WatchItem)]
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS watch_items (
    {", ".join(("id TEXT PRIMARY KEY" if c == "id" else c) for c in _COLUMNS)}
);
CREATE INDEX IF NOT EXISTS ix_watch_status ON watch_items(status);
CREATE INDEX IF NOT EXISTS ix_watch_key ON watch_items(ticker, direction, source);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class WatchlistStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def add(self, item: WatchItem) -> str:
        item.validate()
        item.id = item.id or uuid.uuid4().hex[:16]
        item.created_at = item.created_at or now_iso()
        row = self._to_row(item)
        with self._connect() as conn:
            conn.execute(f"INSERT INTO watch_items ({', '.join(row)}) "
                         f"VALUES ({', '.join('?' for _ in row)})", list(row.values()))
        return item.id

    def update(self, item: WatchItem) -> None:
        row = self._to_row(item)
        row.pop("id")
        with self._connect() as conn:
            conn.execute(f"UPDATE watch_items SET {', '.join(f'{c} = ?' for c in row)} WHERE id = ?",
                         [*row.values(), item.id])

    def get(self, item_id: str) -> WatchItem | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM watch_items WHERE id = ?", (item_id,)).fetchone()
        return self._from_row(row) if row else None

    def list(self, status: str | tuple[str, ...] | None = None) -> list[WatchItem]:
        sql, args = "SELECT * FROM watch_items", []
        if status:
            statuses = (status,) if isinstance(status, str) else tuple(status)
            sql += f" WHERE status IN ({', '.join('?' for _ in statuses)})"
            args.extend(statuses)
        sql += " ORDER BY created_at, id"
        with self._connect() as conn:
            return [self._from_row(r) for r in conn.execute(sql, args).fetchall()]

    def watching(self) -> list[WatchItem]:
        return self.list(status="watching")

    def find_watching(self, ticker: str, direction: str, source: str) -> WatchItem | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM watch_items WHERE status = 'watching' AND ticker = ? "
                "AND direction = ? AND source = ? ORDER BY created_at LIMIT 1",
                (ticker.upper(), direction, source)).fetchone()
        return self._from_row(row) if row else None

    @staticmethod
    def _to_row(item: WatchItem) -> dict:
        row = asdict(item)
        for k in _JSON_FIELDS:
            row[k] = json.dumps(row[k], ensure_ascii=False)
        return row

    @staticmethod
    def _from_row(row: sqlite3.Row) -> WatchItem:
        data = dict(row)
        for k in _JSON_FIELDS:
            data[k] = json.loads(data[k]) if data[k] else ({} if k in ("origin", "close_detail") else [])
        return WatchItem(**{k: data[k] for k in _COLUMNS if k in data})


def default_watchlist_path() -> Path:
    return Path(os.getenv("MARKETMIND_DATA_DIR", "data")) / "watchlist.db"
