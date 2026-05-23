#!/usr/bin/env python3
"""
User Proxy Agent — Decision Logger + Compounding Detection

Part 1: Decision atomization with mandatory one-line rationale.
         Every auto-executed decision is logged as a discrete, revertible entry.

Part 2: Compounding detection scans for architectural drift across
         consecutive decisions — chain alerts, file fragmentation, and
         abstraction sprawl.

Design reference: .claude/state/user_proxy_design.json
  — Reversibility / Decision Atomization  (line 166)
  — Compounding Detection                  (line 180)

No external dependencies — Python stdlib only.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Path resolution (relative to this file: .claude/tools/decision_logger.py)
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_CLAUDE_DIR = _SCRIPT_DIR.parent
_DECISIONS_LOG = _CLAUDE_DIR / "decisions" / "proxy_decisions.jsonl"
_BASELINES_FILE = _CLAUDE_DIR / "state" / "proxy_module_baselines.json"

# ---------------------------------------------------------------------------
# Enums from the User Proxy Agent design spec
# ---------------------------------------------------------------------------
VALID_DECISION_TYPES = frozenset({
    "naming", "architecture", "tool_choice", "code_style",
    "dependency", "testing", "deployment", "security",
})
VALID_CONSEQUENCES = frozenset({"cosmetic", "moderate", "significant", "critical"})
VALID_MODES = frozenset({"advisor", "delegate"})
VALID_STATUSES = frozenset({
    "auto_executed", "flagged", "queued", "escalated", "reviewed", "overridden",
})

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_dirs() -> None:
    """Create decisions and state directories if they do not exist."""
    _DECISIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
    _BASELINES_FILE.parent.mkdir(parents=True, exist_ok=True)


def _read_all() -> list:
    """Read every decision entry from the JSONL log.

    Returns:
        List of decision dicts (metadata lines starting with '_' are skipped).
        Returns an empty list if the log does not exist.
    """
    entries: list = []
    if not _DECISIONS_LOG.exists():
        return entries

    with open(_DECISIONS_LOG, "r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                # Corrupt line — skip with silent resilience
                continue

            # Schema-version header lines
            if "_schema_version" in obj:
                continue

            # Other metadata lines (keys prefixed with '_')
            if obj and list(obj.keys())[0].startswith("_"):
                continue

            entries.append(obj)

    return entries


def _next_sequence_number() -> int:
    """Return the next available sequence number for today's date.

    Scans existing entries for IDs matching ``proxy-YYYY-MM-DD-NNN``
    and returns max(NNN) + 1.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prefix = f"proxy-{today}-"

    max_seq = 0
    for entry in _read_all():
        eid = entry.get("id", "")
        if eid.startswith(prefix):
            try:
                seq = int(eid.rsplit("-", 1)[-1])
                max_seq = max(max_seq, seq)
            except (ValueError, IndexError):
                pass

    return max_seq + 1


def _write_header_if_missing() -> None:
    """Create the decisions log with a schema-version header if it does not exist."""
    _ensure_dirs()
    if _DECISIONS_LOG.exists():
        return
    header = {
        "_schema_version": "1.0",
        "_initialized": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "_description": (
            "User Proxy Agent decisions log — append-only, each line is a valid "
            "JSON object. Schema version header must be the first line. Do not edit "
            "lines in place; append correction entries for modifications."
        ),
    }
    with open(_DECISIONS_LOG, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(header, ensure_ascii=False) + "\n")


def _append_entry(entry: dict) -> None:
    """Append a single decision entry as a JSON line to the log (append-only)."""
    _write_header_if_missing()
    with open(_DECISIONS_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _backup_log() -> None:
    """Create a backup of the decisions log before an in-place rewrite."""
    if not _DECISIONS_LOG.exists():
        return
    bak = _DECISIONS_LOG.with_suffix(".jsonl.bak")
    try:
        bak.write_bytes(_DECISIONS_LOG.read_bytes())
    except OSError:
        pass  # non-fatal — backup is best-effort


def _rewrite_log(entries: list) -> None:
    """Rewrite the entire decisions log (header + entries).

    Used by ``mark_reviewed`` when updating an entry in place.
    Preserves the original ``_initialized`` timestamp from the existing header.
    Creates a .bak backup before overwriting.
    """
    _ensure_dirs()

    # Preserve the original initialization timestamp if available
    header: Dict[str, Any] = {
        "_schema_version": "1.0",
        "_initialized": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "_description": (
            "User Proxy Agent decisions log — append-only, each line is a valid "
            "JSON object. Schema version header must be the first line. Do not edit "
            "lines in place; append correction entries for modifications."
        ),
    }

    if _DECISIONS_LOG.exists():
        try:
            with open(_DECISIONS_LOG, "r", encoding="utf-8") as fh:
                first_line = fh.readline().strip()
                if first_line:
                    existing = json.loads(first_line)
                    if "_initialized" in existing:
                        header["_initialized"] = existing["_initialized"]
        except (json.JSONDecodeError, OSError):
            pass

    _backup_log()

    with open(_DECISIONS_LOG, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(header, ensure_ascii=False) + "\n")
        for entry in entries:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Part 1: Decision Atomization + Rationale
# ---------------------------------------------------------------------------

def log_decision(decision_data: dict) -> str:
    """Log a proxy decision to the append-only decisions log.

    Every decision **must** include a one-line human-readable rationale.
    This is the mandatory audit trail required by the design spec
    (section "mandatory_rationale", line 71 of user_proxy_design.json).

    Args:
        decision_data: Dict with the following mandatory keys:

            - **decision_type** (*str*): One of ``naming``, ``architecture``,
              ``tool_choice``, ``code_style``, ``dependency``, ``testing``,
              ``deployment``, ``security``.
            - **consequence** (*str*): One of ``cosmetic``, ``moderate``,
              ``significant``, ``critical``.
            - **file** (*str*): Affected file path (project-relative preferred).
            - **summary** (*str*): One-line description of the change.
            - **rationale** (*str*): **MANDATORY** one-line human-readable
              explanation.  Example: *"Matched 7 prior naming conventions in
              this project."*
            - **mode** (*str*): ``advisor`` or ``delegate``.
            - **confidence_raw** (*float*): Raw model confidence (0.0–1.0).
            - **confidence_calibrated** (*float*): Platt-calibrated confidence
              (0.0–1.0).

    Returns:
        The assigned decision ID (e.g. ``"proxy-2026-05-23-001"``).

    Raises:
        ValueError: If any mandatory field is missing or ``rationale`` is empty.
    """
    mandatory = [
        "decision_type", "consequence", "file", "summary",
        "rationale", "mode", "confidence_raw", "confidence_calibrated",
    ]
    missing = [f for f in mandatory if decision_data.get(f) in (None, "")]
    if missing:
        raise ValueError(
            f"Missing mandatory fields: {', '.join(missing)}. "
            f"All decisions require: {', '.join(mandatory)}"
        )

    rationale = str(decision_data.get("rationale", "")).strip()
    if not rationale:
        raise ValueError(
            "rationale is mandatory — every decision must include a "
            "one-line human-readable rationale. Example: "
            "'Matched 7 prior naming conventions in this project.'"
        )

    # ---- Build entry ----
    seq = _next_sequence_number()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    decision_id = f"proxy-{today}-{seq:03d}"

    entry: Dict[str, Any] = {
        "id": decision_id,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "decision_type": decision_data["decision_type"],
        "consequence": decision_data["consequence"],
        "file": decision_data["file"],
        "summary": str(decision_data["summary"]).strip(),
        "rationale": rationale,
        "mode": decision_data["mode"],
        "confidence_raw": float(decision_data["confidence_raw"]),
        "confidence_calibrated": float(decision_data["confidence_calibrated"]),
        "status": "auto_executed",
        "user_action": None,
    }

    _append_entry(entry)
    return decision_id


def get_pending_decisions() -> list:
    """Return all decisions awaiting user review.

    A decision is considered *pending* when:
        - ``user_action`` is ``null`` (never reviewed), **AND**
        - ``status`` is one of ``flagged``, ``queued``, ``escalated``.

    Decisions that were auto_executed but not yet flagged/queued/escalated
    are **not** returned — they are considered auto-cleared under the
    confidence-based triage rules.

    Returns:
        List of pending decision dicts, ordered as they appear in the log.
    """
    entries = _read_all()
    pending: list = []
    for e in entries:
        if e.get("user_action") is not None:
            continue
        if e.get("status") in {"flagged", "queued", "escalated"}:
            pending.append(e)
    return pending


def mark_reviewed(
    decision_id: str,
    action: str,
    reason: Optional[str] = None,
) -> Optional[dict]:
    """Mark a decision as reviewed by the user.

    Args:
        decision_id: Full ID (``"proxy-2026-05-23-001"``) or short numeric
            suffix (``"001"``).
        action: ``"approved"`` — explicit approval (trains with weight 2.0),
            or ``"overridden"`` — marked as incorrect (trains with weight -1.0).
        reason: Required when ``action="overridden"`` — explains why the
            decision was wrong.

    Returns:
        The updated decision dict, or ``None`` if the decision ID was not found.

    Raises:
        ValueError: If ``action`` is not ``"approved"`` or ``"overridden"``,
            or if ``reason`` is missing for an override.
    """
    if action not in ("approved", "overridden"):
        raise ValueError(
            f"action must be 'approved' or 'overridden', got '{action}'"
        )
    if action == "overridden" and (not reason or not str(reason).strip()):
        raise ValueError("reason is required when overriding a decision")

    entries = _read_all()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    updated: Optional[dict] = None

    for e in entries:
        eid = e.get("id", "")
        # Accept full ID (e.g. "proxy-2026-05-23-001") or short numeric suffix ("001")
        short = eid.rsplit("-", 1)[-1] if "-" in eid else eid
        if eid == decision_id or short == decision_id:
            if action == "approved":
                e["user_action"] = "approved"
                e["approved_at"] = now
                e["status"] = "reviewed"
            else:
                e["user_action"] = "overridden"
                e["overridden_at"] = now
                e["override_reason"] = str(reason).strip()
                e["status"] = "overridden"
            updated = e
            break

    if updated is None:
        return None

    _rewrite_log(entries)
    return updated


def generate_digest(days: int = 7) -> str:
    """Generate a summary statistics report for recent decisions.

    Args:
        days: Lookback window in days (default 7).

    Returns:
        A multi-line formatted digest string suitable for display or logging.
        Includes: total count, breakdown by consequence tier and decision type,
        user review status (approved / overridden / unreviewed), correction
        rate, top corrected types, and average confidence scores.
    """
    entries = _read_all()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Filter to the lookback window
    recent: list = []
    for e in entries:
        ts = e.get("timestamp", "")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt < cutoff:
                    continue
            except (ValueError, TypeError):
                pass  # unparseable timestamp — include anyway
        recent.append(e)

    if not recent:
        return f"No decisions logged in the last {days} day(s)."

    total = len(recent)

    # Aggregations
    tier_counts = Counter(e.get("consequence", "unknown") for e in recent)
    type_counts = Counter(e.get("decision_type", "unknown") for e in recent)
    status_counts = Counter(e.get("status", "unknown") for e in recent)

    approved = sum(1 for e in recent if e.get("user_action") == "approved")
    overridden = sum(1 for e in recent if e.get("user_action") == "overridden")
    unreviewed = sum(1 for e in recent if e.get("user_action") is None)
    correction_rate = (overridden / total * 100) if total > 0 else 0.0

    # Top corrected types
    corrected_types = Counter(
        e.get("decision_type", "unknown")
        for e in recent
        if e.get("user_action") == "overridden"
    )
    top3 = corrected_types.most_common(3)

    # Confidence stats
    raw_confs = []
    cal_confs = []
    for e in recent:
        for src, dst in [
            ("confidence_raw", raw_confs),
            ("confidence_calibrated", cal_confs),
        ]:
            try:
                val = e.get(src)
                if val is not None:
                    dst.append(float(val))
            except (ValueError, TypeError):
                pass

    # ---- Render ----
    lines: list = []
    lines.append("=" * 55)
    lines.append(f"  User Proxy Agent — {days}-Day Digest")
    lines.append("=" * 55)
    lines.append(f"  Total decisions        : {total}")
    lines.append("")

    lines.append("  By consequence tier:")
    for tier in ["cosmetic", "moderate", "significant", "critical"]:
        count = tier_counts.get(tier, 0)
        bar = "#" * min(count, 40) if count > 0 else ""
        lines.append(f"    {tier:<14s}: {count:>4d}  {bar}")
    # Surface any unrecognized tiers
    for tier, count in sorted(tier_counts.items()):
        if tier not in {"cosmetic", "moderate", "significant", "critical"}:
            lines.append(f"    {tier:<14s}: {count:>4d}")

    lines.append("")
    lines.append("  By decision type:")
    for dtype, count in type_counts.most_common():
        lines.append(f"    {dtype:<14s}: {count:>4d}")

    lines.append("")
    lines.append("  User review status:")
    lines.append(f"    Approved       : {approved}")
    lines.append(f"    Overridden     : {overridden}")
    lines.append(f"    Unreviewed     : {unreviewed}")
    lines.append(f"    Correction rate: {correction_rate:.1f}%")

    if top3:
        lines.append("")
        lines.append("  Top corrected types:")
        for dtype, count in top3:
            lines.append(f"    {dtype:<14s}: {count:>4d} overrides")
    else:
        lines.append("")
        lines.append("  Top corrected types : (none)")

    if raw_confs:
        avg_raw = sum(raw_confs) / len(raw_confs)
        lines.append("")
        lines.append(
            f"  Avg raw confidence     : {avg_raw:.3f}  (n={len(raw_confs)})"
        )
    if cal_confs:
        avg_cal = sum(cal_confs) / len(cal_confs)
        lines.append(
            f"  Avg calibrated conf    : {avg_cal:.3f}  (n={len(cal_confs)})"
        )

    lines.append("")
    lines.append("=" * 55)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Part 2: Compounding Detection
# ---------------------------------------------------------------------------

# -- Module baseline tracking (for fragmentation alert) --

def _load_baselines() -> dict:
    """Load persisted module baselines from disk."""
    if not _BASELINES_FILE.exists():
        return {}
    try:
        with open(_BASELINES_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_baselines(data: dict) -> None:
    """Persist module baselines to disk (with backup)."""
    _ensure_dirs()
    if _BASELINES_FILE.exists():
        try:
            bak = _BASELINES_FILE.with_suffix(".json.bak")
            bak.write_bytes(_BASELINES_FILE.read_bytes())
        except OSError:
            pass
    with open(_BASELINES_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def _module_key(module_path: str) -> str:
    """Stable hash-based key for a module path (16 hex chars)."""
    return hashlib.sha256(str(module_path).encode("utf-8")).hexdigest()[:16]


# -- Detection helpers --

def _count_files_in_module(module_path: Path) -> int:
    """Count non-hidden, non-bytecode files recursively under *module_path*."""
    if not module_path.exists() or not module_path.is_dir():
        return 0
    count = 0
    for entry in module_path.rglob("*"):
        if not entry.is_file():
            continue
        if entry.name.startswith("."):
            continue
        if "__pycache__" in entry.parts:
            continue
        count += 1
    return count


def _decisions_for_module(
    decisions: list, module_path: Path
) -> list:
    """Return decisions whose ``file`` field resolves under *module_path*."""
    result: list = []
    try:
        prefix = str(module_path.resolve())
    except (ValueError, OSError):
        return result

    for d in decisions:
        df = d.get("file", "")
        if not df:
            continue
        try:
            resolved = str(Path(df).resolve())
        except (ValueError, OSError):
            continue
        if resolved.startswith(prefix):
            result.append(d)
    return result


# -- Keyword sets for abstraction sprawl heuristics --

_EXTRACTION_KEYWORDS = (
    "extract", "refactor", "move to", "split", "separate",
    "decouple", "break out", "pull out", "hoist",
)

_CREATION_KEYWORDS = (
    "create", "add new", "implement", "introduce", "build",
    "new module", "new file", "scaffold",
)


def _classify_decision_intent(decision: dict) -> Optional[str]:
    """Heuristically classify a decision as 'extraction' or 'creation'.

    Scans the ``summary`` and ``rationale`` fields for keyword matches.
    Returns ``"extraction"``, ``"creation"``, or ``None`` if indeterminate.
    """
    text = (
        str(decision.get("summary", "")) + " " +
        str(decision.get("rationale", ""))
    ).lower()

    is_extraction = any(kw in text for kw in _EXTRACTION_KEYWORDS)
    is_creation = any(kw in text for kw in _CREATION_KEYWORDS)

    if is_extraction and not is_creation:
        return "extraction"
    if is_creation and not is_extraction:
        return "creation"
    # Both or neither — indeterminate
    return None


# -- Main entry point --

def detect_compounding(
    decisions: list,
    module_path: str,
) -> Optional[dict]:
    """Scan recent decisions for architectural drift and compounding risk.

    Runs three independent checks, each designed with conservative thresholds
    to minimize false positives:

    1. **chain_alert** — 3+ consecutive decisions of the same type within the
       same module.  Two-in-a-row is common; three signals a pattern worth
       reviewing.

    2. **fragmentation_alert** — Module file count has grown > 40% from the
       stored baseline.  The baseline is auto-recorded on first call and
       updated after each check, so the alert fires once per milestone crossing.

    3. **abstraction_sprawl_alert** — Extraction-to-creation ratio exceeds
       3:1 (at least 3 extractions required to trigger).  Extractions and
       creations are identified heuristically via keyword matching on the
       ``summary`` and ``rationale`` fields.

    Args:
        decisions: List of decision dicts (typically from ``_read_all()`` or
            filtered to a recent window).
        module_path: Filesystem path to the module directory being analyzed.
            Used for file-count baselining and scoping chain detection.

    Returns:
        A dict keyed by alert type (``chain_alert``, ``fragmentation_alert``,
        ``abstraction_sprawl_alert``), each value is either a sub-dict with
        ``message``, ``severity``, and type-specific detail fields, or
        ``None`` if that check did not fire.

        Returns ``None`` when **no** alerts fire at all (all three values are
        ``None``).
    """
    if not decisions:
        return None

    alerts: Dict[str, Optional[dict]] = {
        "chain_alert": None,
        "fragmentation_alert": None,
        "abstraction_sprawl_alert": None,
    }

    module_path_obj = Path(module_path).resolve()

    # ---- 1. Chain detection ----
    # 3+ consecutive same-type decisions scoped to this module.

    module_decisions = _decisions_for_module(decisions, module_path_obj)
    if module_decisions:
        # Sort by timestamp so "consecutive" is temporal, not insertion-order
        module_decisions.sort(key=lambda d: d.get("timestamp", ""))

        chain_details: list = []
        run_type: Optional[str] = None
        run_count = 0

        for d in module_decisions:
            dt = d.get("decision_type", "")
            if dt == run_type:
                run_count += 1
            else:
                if run_count >= 3:
                    chain_details.append({
                        "decision_type": run_type,
                        "count": run_count,
                        "module": str(module_path_obj),
                    })
                run_type = dt
                run_count = 1

        # Flush final run
        if run_count is not None and run_count >= 3 and run_type is not None:
            chain_details.append({
                "decision_type": run_type,
                "count": run_count,
                "module": str(module_path_obj),
            })

        if chain_details:
            types_seen = {c["decision_type"] for c in chain_details}
            alerts["chain_alert"] = {
                "message": (
                    f"Detected {len(chain_details)} chain(s) of 3+ consecutive "
                    f"same-type decisions in {module_path_obj.name}: "
                    f"{', '.join(sorted(types_seen))}"
                ),
                "chains": chain_details,
                "severity": "moderate",
            }

    # ---- 2. Fragmentation detection ----
    # File count growth > 40% from stored baseline.

    if module_path_obj.exists() and module_path_obj.is_dir():
        current_count = _count_files_in_module(module_path_obj)
        baselines = _load_baselines()
        key = _module_key(str(module_path_obj))

        if key in baselines and current_count > 0:
            baseline_count = baselines[key].get("file_count", current_count)
            baseline_time = baselines[key].get("recorded_at", "unknown")

            if baseline_count > 0:
                growth_pct = ((current_count - baseline_count) / baseline_count) * 100
                if growth_pct > 40:
                    alerts["fragmentation_alert"] = {
                        "message": (
                            f"Module file count grew {growth_pct:.1f}% "
                            f"(from {baseline_count} to {current_count} files) "
                            f"— exceeds 40% threshold"
                        ),
                        "baseline": baseline_count,
                        "current": current_count,
                        "growth_pct": round(growth_pct, 1),
                        "baseline_recorded_at": baseline_time,
                        "severity": "significant",
                    }

        # Update baseline after check (alert fires once per milestone crossing)
        baselines[key] = {
            "file_count": current_count,
            "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "module_path": str(module_path_obj),
        }
        _save_baselines(baselines)

    # ---- 3. Abstraction sprawl detection ----
    # Extraction-to-creation ratio > 3:1 (min 3 extractions to trigger).

    extraction_count = 0
    creation_count = 0

    for d in decisions:
        intent = _classify_decision_intent(d)
        if intent == "extraction":
            extraction_count += 1
        elif intent == "creation":
            creation_count += 1

    if extraction_count >= 3:
        denominator = max(creation_count, 1)
        ratio = extraction_count / denominator
        if ratio > 3.0:
            alerts["abstraction_sprawl_alert"] = {
                "message": (
                    f"Extraction-to-creation ratio is {ratio:.1f}:1 "
                    f"({extraction_count} extractions vs {creation_count} creations) "
                    f"— exceeds 3:1 threshold"
                ),
                "extraction_count": extraction_count,
                "creation_count": creation_count,
                "ratio": round(ratio, 1),
                "severity": "significant",
            }

    # Return None only when every check is clean
    if all(v is None for v in alerts.values()):
        return None

    return alerts
