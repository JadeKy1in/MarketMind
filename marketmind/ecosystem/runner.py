"""Daily shadow-ecosystem health run: ledger (read-only) -> data/ecosystem/<NY date>.json.

`run_ecosystem()` is the pipeline step; `read_report()` is the read function for the
dashboard and the daily report (docs/ECOSYSTEM_DESIGN.md §5). Monitoring only.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from marketmind.ecosystem import config as C
from marketmind.ecosystem.health import Facts, evaluate, summary_line
from marketmind.ledger.store import LedgerEntry, LedgerStore

log = logging.getLogger(__name__)

VERSION = 1


def data_dir(value: str | Path | None = None) -> Path:
    return Path(value if value is not None else os.getenv("MARKETMIND_DATA_DIR", "data"))


def report_dir(root: str | Path | None = None) -> Path:
    return data_dir(root) / "ecosystem"


def ny_today() -> str:
    from marketmind.trend.daily import ny_date
    return ny_date()


def load_entries(ledger_path: Path) -> list[LedgerEntry]:
    """Every ledger row, opened read-only (the monitor never writes the ledger)."""
    if not ledger_path.exists():
        return []
    conn = sqlite3.connect(f"file:{ledger_path.as_posix()}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM ledger ORDER BY created_at, entry_id").fetchall()
    finally:
        conn.close()
    return [LedgerStore._from_row(r) for r in rows]


def _trend_states(root: Path, days: set[str]) -> dict[str, dict[str, str]]:
    """{day: {ticker: state}} from data/trend/<day>.json (full universe) for `days`."""
    out = {}
    folder = root / "trend"
    for d in sorted(days):
        p = folder / f"{d}.json"
        if not p.exists():
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        full = doc.get("full") or {}
        out[d] = {t: (s or {}).get("state") for t, s in full.items() if isinstance(s, dict)}
    return out


def load_facts(root: Path, days: set[str]) -> tuple[Facts, list[str]]:
    """Roster, retirements, trials, Playground manifests and trend states. A source that
    cannot be read is left unknown (its check is skipped) and named in the notes."""
    from marketmind.shadows.v3 import roster
    notes: list[str] = []
    facts = Facts(active_ids={r.shadow_id for r in roster.active(root)},
                  roster_ids={r.shadow_id for r in roster.all_entries(root)})
    try:
        approved = roster._approved(root)
        facts.retired = {p["shadow_id"]: p.get("decided_at") or "" for p in approved if p.get("shadow_id")}
        facts.successor_start = {(p.get("successor") or {}).get("shadow_id"): p.get("decided_at") or ""
                                 for p in approved if (p.get("successor") or {}).get("shadow_id")}
    except Exception:                                    # noqa: BLE001 - monitoring must not fail
        notes.append("retirements unreadable: retired-submitting check skipped")
    try:
        from marketmind.shadows.v3 import trials
        facts.trial_parent = {f"trial:{t.trial_id}": t.parent_id for t in trials.load(root / "trials")}
    except Exception:                                    # noqa: BLE001
        notes.append("trials.json unreadable: trial orphan check skipped")
    try:
        from marketmind.playground.agent_manifest import discover_agents
        from marketmind.playground.playground_runner import DEFAULT_PLAYGROUND_DIR
        facts.playground_ids = {f"playground:{m.agent_id}" for m in discover_agents(DEFAULT_PLAYGROUND_DIR)}
    except Exception:                                    # noqa: BLE001
        notes.append("Playground manifests unreadable: playground orphan check skipped")
    facts.trend_by_day = _trend_states(root, days)
    if not facts.trend_by_day:
        notes.append("no trend files for the run days: herding flags stay 'unclassified'")
    return facts, notes


def _write_atomic(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for attempt in range(10):        # a reader holding the file open blocks os.replace on Windows
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.1)


def run_ecosystem(root: str | Path | None = None, today: str | None = None,
                  write: bool = True, ledger_path: str | Path | None = None) -> dict:
    """Evaluate the ecosystem as of `today` (default: New York date) and write
    <root>/ecosystem/<today>.json atomically unless `write` is False."""
    from marketmind.ecosystem.health import day_of
    root = data_dir(root)
    today = today or ny_today()
    entries = load_entries(Path(ledger_path) if ledger_path else root / "ledger.db")
    days = {day_of(e) for e in entries if e.source_type in C.SOURCE_TYPES}
    facts, notes = load_facts(root, {d for d in days if d <= today})
    doc = {"version": VERSION, "date": today,
           "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           **evaluate(entries, today, facts), "thresholds": C.thresholds(), "notes": notes}
    doc["summary"] = summary_line(doc)
    if write:
        _write_atomic(report_dir(root) / f"{today}.json", doc)
    return doc


def read_report(day: str | None = None, root: str | Path | None = None) -> dict | None:
    """The ecosystem report of `day` (YYYY-MM-DD), or the latest one when `day` is None;
    None when there is none. For the dashboard / daily report: `summary` is the one-line
    text, `herding.flags`, `diversity.pnl.n_eff`, `integrity.zombies` the headline facts."""
    folder = report_dir(root)
    if day:
        paths = [folder / f"{day}.json"]
    else:
        paths = sorted(folder.glob("????-??-??.json"), reverse=True) if folder.is_dir() else []
    for p in paths:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            if day:
                return None
            continue
    return None
