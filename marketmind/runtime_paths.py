"""Where MarketMind keeps runtime files that live next to the package (briefs,
calibration, metrics, state under marketmind/.claude).

MARKETMIND_CLAUDE_DIR overrides the location. The test suite points it at a temporary
directory, so tests never write into the real files (2026-09-29: test runs had written
fake rule evolutions into metrics/evolutions.jsonl, which the calibration context reads
into L1 / decision prompts, and ~2,500 alerts into data/alerts.db).
"""
from __future__ import annotations

import os
from pathlib import Path


def claude_dir() -> Path:
    env = os.getenv("MARKETMIND_CLAUDE_DIR")
    return Path(env) if env else Path(__file__).resolve().parent / ".claude"
