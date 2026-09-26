"""Pipeline test fixture system — JSON only, no pickle, no YAML unsafe loaders.

Each fixture captures a pipeline stage's output for isolated per-stage testing.
Regeneration is a 2-step operation: write to temp → diff → require --force.

Security: loads only via json.load() from stdlib. Never deserialize pickle/YAML.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).resolve().parent
STALENESS_DAYS_WARN = 7
STALENESS_DAYS_FAIL = 14


class FixtureStaleError(RuntimeError):
    """Fixture is older than the fail threshold and must be regenerated."""


class FixtureHashMismatchError(RuntimeError):
    """Pipeline source hash in fixture metadata doesn't match current pipeline code."""


# ── Scrubbers ────────────────────────────────────────────────────────────────

_TIMESTAMP_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?\b")
_UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)
_WORKDIR_RE: re.Pattern | None = None


def _get_workdir_re() -> re.Pattern:
    global _WORKDIR_RE
    if _WORKDIR_RE is None:
        wd = re.escape(str(Path.cwd()).replace("\\", "/"))
        _WORKDIR_RE = re.compile(rf"{wd}|{re.escape(str(Path.cwd()))}", re.IGNORECASE)
    return _WORKDIR_RE


def scrub_output(data: Any) -> Any:
    """Normalize non-deterministic fields: timestamps → [TIMESTAMP], UUIDs → [UUID-N]."""
    if isinstance(data, str):
        data = _TIMESTAMP_RE.sub("[TIMESTAMP]", data)
        data = _UUID_RE.sub("[UUID]", data)
        data = _get_workdir_re().sub("[WORKDIR]", data)
        return data
    elif isinstance(data, dict):
        return {k: scrub_output(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [scrub_output(v) for v in data]
    return data


# ── Pipeline content hash ────────────────────────────────────────────────────

def compute_pipeline_hash() -> str:
    """SHA256 of all pipeline .py files — used to detect code-vs-fixture drift."""
    pipeline_dir = Path(__file__).resolve().parent.parent / "pipeline"
    if not pipeline_dir.is_dir():
        return ""
    hasher = hashlib.sha256()
    for pyfile in sorted(pipeline_dir.glob("*.py")):
        hasher.update(pyfile.read_bytes())
    return hasher.hexdigest()


# ── Metadata ─────────────────────────────────────────────────────────────────

def _metadata_path(stage: str, name: str) -> Path:
    return FIXTURES_DIR / f"{stage}_{name}_metadata.json"


def _fixture_path(stage: str, name: str) -> Path:
    return FIXTURES_DIR / f"{stage}_{name}.json"


def read_metadata(stage: str, name: str) -> dict:
    """Read fixture metadata, raise FixtureHashMismatchError if pipeline hash doesn't match."""
    path = _metadata_path(stage, name)
    if not path.exists():
        return {}
    meta = json.loads(path.read_text(encoding="utf-8"))
    current_hash = compute_pipeline_hash()
    stored_hash = meta.get("pipeline_content_hash", "")
    if current_hash and stored_hash and current_hash != stored_hash:
        raise FixtureHashMismatchError(
            f"Pipeline hash mismatch for {stage}/{name}: "
            f"fixture was generated from different pipeline code. "
            f"Run --regenerate-fixtures to update."
        )
    return meta


def check_staleness(stage: str, name: str) -> None:
    """Warn if fixture >7 days old. Raise FixtureStaleError if >14 days."""
    meta = read_metadata(stage, name)
    created = meta.get("created_at", "")
    if not created:
        return
    try:
        created_dt = datetime.fromisoformat(created)
        age_days = (datetime.now(timezone.utc) - created_dt).days
    except (ValueError, TypeError):
        return

    ci = os.environ.get("CI", "").lower() in ("1", "true", "yes")
    if age_days > STALENESS_DAYS_FAIL:
        raise FixtureStaleError(
            f"Fixture {stage}/{name} is {age_days} days old (limit: {STALENESS_DAYS_FAIL}). "
            f"Run --regenerate-fixtures to update."
        )
    if age_days > STALENESS_DAYS_WARN:
        msg = (
            f"WARNING: Fixture {stage}/{name} is {age_days} days old. "
            f"Consider running --regenerate-fixtures."
        )
        if ci:
            raise FixtureStaleError(msg)
        import logging
        logging.getLogger("marketmind.test_fixtures").warning(msg)


# ── Load / Save ──────────────────────────────────────────────────────────────

def load_fixture(stage: str, name: str = "normal") -> dict | list:
    """Load a scrubbed stage output fixture. Validates staleness and pipeline hash."""
    check_staleness(stage, name)
    read_metadata(stage, name)  # validates pipeline hash
    path = _fixture_path(stage, name)
    if not path.exists():
        raise FileNotFoundError(
            f"Fixture {stage}/{name} not found at {path}. "
            f"Run --regenerate-fixtures first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def save_fixture(stage: str, name: str, data: Any) -> None:
    """Save scrubbed data as a JSON fixture with metadata."""
    scrubbed = scrub_output(data)
    fixture_path = _fixture_path(stage, name)
    meta_path = _metadata_path(stage, name)

    fixture_path.write_text(
        json.dumps(scrubbed, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    meta_path.write_text(
        json.dumps({
            "stage": stage,
            "name": name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "pipeline_content_hash": compute_pipeline_hash(),
            "python_version": os.environ.get("PYTHON_VERSION", ""),
        }, indent=2),
        encoding="utf-8",
    )


# ── Regeneration ─────────────────────────────────────────────────────────────

def regenerate_all(config, force: bool = False) -> dict:
    """Run full pipeline once, capture every stage output. Writes to temp, requires --force."""
    import asyncio

    if not force:
        raise RuntimeError(
            "Fixture regeneration requires --force flag. "
            "This is a deliberate human-supervised operation. "
            "Run with --regenerate-fixtures --force to proceed."
        )

    # Will be implemented in Phase 2 — calls each stage with mock data
    return {"status": "not_implemented", "message": "Phase 2: stage-by-stage capture"}
