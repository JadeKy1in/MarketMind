"""Per-day step markers: a re-attempted scheduled run skips the steps an earlier
attempt of the same day already finished (docs/AUTOMATION.md, "断点续跑").

2026-10-02: the laptop is sometimes restarted by hand mid-run; the retry (a later
trigger, or the watchdog catch-up) then redid everything, ~10 minutes and the LLM
tokens again. scheduled_run passes the day key (e.g. "2026-10-02-weekday") and the
marker file in MARKETMIND_RUN_KEY / MARKETMIND_STEPS_FILE, and clears the day's
markers on its first attempt. Without them (manual, mock and test runs) nothing is
skipped and nothing is recorded.

A marker is written only after a step finished without recording its own failure;
an unreadable file means nothing is skipped. Correctness never depends on it: the
ledger rejects a second submission for the same trading session anyway.
Stdlib only: scheduled_run imports this before it starts the run.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ENV_KEY = "MARKETMIND_RUN_KEY"
ENV_FILE = "MARKETMIND_STEPS_FILE"
KEEP_DAYS = 14                     # day keys kept in the file


class RunSteps:
    """Markers of one day key in a JSON file {day key: {step: {"t": ..., ...}}}."""

    def __init__(self, path: str | Path | None = None, key: str | None = None):
        self.path = Path(path) if path else None
        self.key = key or None

    @classmethod
    def from_env(cls) -> "RunSteps":
        return cls(os.getenv(ENV_FILE) or None, os.getenv(ENV_KEY) or None)

    @property
    def enabled(self) -> bool:
        return self.path is not None and self.key is not None

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            logger.warning("step markers %s unreadable; no step is skipped", self.path)
            return {}
        return data if isinstance(data, dict) else {}

    def done(self, step: str) -> dict | None:
        """The marker of `step` for this day key, or None."""
        if not self.enabled:
            return None
        day = self._load().get(self.key)
        rec = day.get(step) if isinstance(day, dict) else None
        return rec if isinstance(rec, dict) else None

    def mark(self, step: str, **extra) -> None:
        """Record `step` as finished. A failed write only costs a rerun of the step."""
        if not self.enabled:
            return
        data = self._load()
        day = data.get(self.key)
        if not isinstance(day, dict):
            day = data[self.key] = {}
        day[step] = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), **extra}
        self._write(dict(sorted(data.items())[-KEEP_DAYS:]))

    def reset(self) -> None:
        """Forget this day key's markers (a first attempt starts from scratch)."""
        if not self.enabled:
            return
        data = self._load()
        if data.pop(self.key, None) is not None:
            self._write(data)

    def _write(self, data: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str),
                           encoding="utf-8")
            for attempt in range(10):          # a reader holding the file blocks os.replace
                try:
                    os.replace(tmp, self.path)
                    return
                except PermissionError:
                    if attempt == 9:
                        raise
                    time.sleep(0.1)
        except OSError:
            logger.warning("step markers not written to %s; a retry reruns the step",
                           self.path, exc_info=True)
