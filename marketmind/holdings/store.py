"""Owner's real holdings (docs/S6_DESIGN.md), kept in data/holdings.json.

`data/` is git-ignored and the repository is public: real positions must never
be written anywhere else. Every `add` also writes an `owner` record to the
unified ledger (SPEC §7, "human decision mirror").
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from marketmind.ledger.store import LedgerEntry, LedgerStore

OWNER_HOLD_BARS = 60
_OPTION_RE = re.compile(r"\s|\d{6}[CP]\d{8}$")   # spaces or OCC option symbols


@dataclass
class Holding:
    ticker: str
    quantity: float
    cost_basis: float                 # per unit, USD
    opened: str                       # YYYY-MM-DD
    stop: float | None = None         # owner's own stop, optional
    note: str = ""
    ledger_ids: list[str] = field(default_factory=list)


def holdings_path() -> Path:
    return Path(os.getenv("MARKETMIND_DATA_DIR", "data")) / "holdings.json"


def load(path: Path | None = None) -> list[Holding]:
    path = path or holdings_path()
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding="utf-8")).get("holdings", [])
    return [Holding(**r) for r in rows]


def save(holdings: list[Holding], path: Path | None = None) -> None:
    path = path or holdings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "holdings": [asdict(h) for h in sorted(holdings, key=lambda h: h.ticker)]}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def validate_ticker(ticker: str) -> str:
    t = (ticker or "").strip().upper()
    if not t:
        raise ValueError("ticker is required")
    if _OPTION_RE.search(t):
        raise ValueError(f"{ticker!r} looks like an option; real trading excludes options")
    if t.startswith("^"):
        raise ValueError(f"{ticker!r} is an index, not a holding")
    return t


def add(ticker: str, quantity: float, cost_basis: float, *, opened: str | None = None,
        stop: float | None = None, note: str = "", ledger: LedgerStore | None = None,
        path: Path | None = None) -> Holding:
    t = validate_ticker(ticker)
    if quantity <= 0 or cost_basis <= 0:
        raise ValueError("quantity and cost_basis must be positive")
    if stop is not None and stop <= 0:
        raise ValueError("stop must be positive")
    opened = opened or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    holdings = load(path)
    existing = next((h for h in holdings if h.ticker == t), None)
    entry_id = _mirror(ledger, t, quantity, cost_basis, opened, stop, note)
    if existing:
        total = existing.quantity + quantity
        existing.cost_basis = round((existing.quantity * existing.cost_basis
                                     + quantity * cost_basis) / total, 6)
        existing.quantity = total
        existing.opened = min(existing.opened, opened)
        existing.stop = stop if stop is not None else existing.stop
        existing.note = note or existing.note
        h = existing
    else:
        h = Holding(t, quantity, cost_basis, opened, stop, note)
        holdings.append(h)
    if entry_id:
        h.ledger_ids.append(entry_id)
    save(holdings, path)
    return h


def remove(ticker: str, path: Path | None = None) -> bool:
    t = validate_ticker(ticker)
    holdings = load(path)
    kept = [h for h in holdings if h.ticker != t]
    if len(kept) == len(holdings):
        return False
    save(kept, path)
    return True


def _mirror(ledger: LedgerStore | None, ticker, quantity, cost, opened, stop, note) -> str | None:
    if ledger is None:
        return None
    from marketmind.ledger.recorder import classify_ticker
    layer, asset_type = classify_ticker(ticker)
    falsifier = f"跌破所有人止损 {stop}" if stop else "所有人未设止损"
    return ledger.add(LedgerEntry(
        source_type="owner", source_id="owner:robinhood", ticker=ticker, direction="long",
        hold_bars=OWNER_HOLD_BARS, confidence=0.5, confidence_is_default=True,
        position_usd=round(quantity * cost, 2), falsifier=falsifier,
        falsifier_rule={"type": "close_below", "price": float(stop)} if stop else None,
        thesis=note or "所有人实盘持仓（手动录入）", layer=layer, asset_type=asset_type,
        entry_rule="next_open",
        meta={"quantity": quantity, "cost_basis": cost, "opened": opened,
              "mirror": "owner holding recorded on entry; settles on its own horizon"},
    ))
