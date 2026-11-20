"""Daily push budget (docs/S8_DESIGN.md 推送优先级, 2026-11-20).

Server酱's free plan delivers 5 messages a day (notify.py docstring). Every message
Server酱 accepted is counted here (notify.send calls `record`), so a lower-priority push
can check what is left before it spends one. Only Server酱 is counted: the other
channels have no comparable daily cap.

The counter's day is the China calendar day (UTC+8): Server酱 is a China service and its
FAQ does not say when the daily count resets - an assumption, not a documented fact.
The count is best effort (a push sent from another machine, or a file write that failed,
is missing), so callers keep a reserve rather than spending down to zero.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("marketmind.alerts.quota")

DAILY_LIMIT = 5                        # Server酱 free plan, messages per day
REPORT_RESERVE = 1                     # kept for the daily report (sent last in the run)
KEEP_DAYS = 14
CHINA = timezone(timedelta(hours=8))   # China has no DST


def _path() -> Path:
    return Path(os.getenv("MARKETMIND_DATA_DIR", "data")) / "scheduler" / "push_count.json"


def day_key(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(CHINA).strftime("%Y-%m-%d")


def _load() -> dict[str, int]:
    try:
        doc = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: int(v) for k, v in doc.items() if isinstance(v, int)} if isinstance(doc, dict) else {}


def sent_today(now: datetime | None = None) -> int:
    return _load().get(day_key(now), 0)


def remaining(now: datetime | None = None) -> int:
    return max(0, DAILY_LIMIT - sent_today(now))


def record(now: datetime | None = None) -> None:
    """Count one delivered Server酱 message; never raises (a lost count is not a lost push)."""
    key = day_key(now)
    counts = _load()
    counts[key] = counts.get(key, 0) + 1
    counts = dict(sorted(counts.items())[-KEEP_DAYS:])
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(counts), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        logger.warning("push count not recorded: %s", type(e).__name__)
