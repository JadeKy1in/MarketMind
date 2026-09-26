#!/usr/bin/env python3
"""
User Proxy Agent Decision Audit CLI

A command-line audit interface for reviewing, approving, and overriding
User Proxy Agent decisions stored in .claude/decisions/proxy_decisions.jsonl.

Commands:
    review                 Display all decisions in a readable table
    review --pending       Show only flagged/unreviewed decisions
    approve <id>           Mark a decision as explicitly approved
    override <id> --reason "..."  Mark a decision as overridden
    digest                 Summary statistics

No external dependencies — Python stdlib only.
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Locate the decisions log relative to this script
SCRIPT_DIR = Path(__file__).resolve().parent
DECISIONS_LOG = SCRIPT_DIR.parent / "decisions" / "proxy_decisions.jsonl"

# Valid enum values from the User Proxy Agent design spec
VALID_DECISION_TYPES = {
    "naming", "architecture", "tool_choice", "code_style",
    "dependency", "testing", "deployment", "security",
}
VALID_CONSEQUENCES = {"cosmetic", "moderate", "significant", "critical"}
VALID_MODES = {"advisor", "delegate"}
VALID_STATUSES = {"auto_executed", "flagged", "queued", "escalated",
                   "reviewed", "overridden"}

# Display column widths
COL_ID = 5
COL_DATE = 10
COL_DECISION = 22
COL_FILE = 16
COL_CONF = 6
COL_STATUS = 8

TABLE_FMT = (
    f"{{:<{COL_ID}}}  {{:<{COL_DATE}}}  {{:<{COL_DECISION}}}  "
    f"{{:<{COL_FILE}}}  {{:>{COL_CONF}}}  {{:<{COL_STATUS}}}"
)
TABLE_SEP = (
    f"{{:-<{COL_ID}}}--{{:-<{COL_DATE}}}--{{:-<{COL_DECISION}}}--"
    f"{{:-<{COL_FILE}}}--{{:-<{COL_CONF}}}--{{:-<{COL_STATUS}}}"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_decisions():
    """Read the JSONL decisions file. Returns (header, entries).

    header: dict from the _schema_version line (first line)
    entries: list of decision dicts (metadata lines starting with '_' are skipped)

    Malformed lines are skipped with a warning to stderr.
    """
    header = None
    entries = []

    if not DECISIONS_LOG.exists():
        print(f"[warn] Decisions log not found: {DECISIONS_LOG}", file=sys.stderr)
        print("[warn] It will be created when the User Proxy Agent logs its first decision.",
              file=sys.stderr)
        return header, entries

    with open(DECISIONS_LOG, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                print(f"[warn] Line {lineno}: invalid JSON — {exc}", file=sys.stderr)
                continue

            # Schema version header (first line, or any line with _schema_version)
            if "_schema_version" in obj:
                if header is None:
                    header = obj
                # Don't treat schema lines as decisions
                if lineno != 1:
                    print(f"[warn] Line {lineno}: unexpected _schema_version after line 1",
                          file=sys.stderr)
                continue

            # Skip other metadata lines
            if list(obj.keys()) and list(obj.keys())[0].startswith("_"):
                continue

            entries.append(obj)

    return header, entries


def _write_decisions(header, entries):
    """Overwrite the decisions log with header + entries.

    The header line is always written first, followed by each entry as a
    single JSON line.  Every write creates a backup copy at
    proxy_decisions.jsonl.bak first.
    """
    # Backup
    if DECISIONS_LOG.exists():
        bak = DECISIONS_LOG.with_suffix(".jsonl.bak")
        try:
            bak.write_bytes(DECISIONS_LOG.read_bytes())
        except OSError as exc:
            print(f"[warn] Could not create backup: {exc}", file=sys.stderr)
            # Continue anyway — user has been warned

    with open(DECISIONS_LOG, "w", encoding="utf-8") as fh:
        # Header
        if header:
            fh.write(json.dumps(header, ensure_ascii=False) + "\n")
        else:
            # Fallback: write a fresh header
            fh.write(json.dumps({
                "_schema_version": "1.0",
                "_initialized": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "_description": "User Proxy Agent decisions log",
            }, ensure_ascii=False) + "\n")

        for entry in entries:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _short_id(decision_id):
    """Extract a short display ID from a full ID like 'proxy-2026-05-23-001'."""
    if not decision_id:
        return "?"
    parts = decision_id.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[1]  # "001"
    # Fallback: return the last 6 chars if it looks reasonable
    if len(decision_id) > 6:
        return decision_id[-6:]
    return decision_id


def _short_date(timestamp_str):
    """Convert ISO timestamp to 'MM-DD HH:MM' for display."""
    if not timestamp_str:
        return "?"
    try:
        # Handle 'Z' suffix and '+00:00' offsets
        ts = timestamp_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%m-%d %H:%M")
    except (ValueError, TypeError):
        # If it's already a short string, return as-is truncated
        return timestamp_str[:11] if len(timestamp_str) > 11 else timestamp_str


def _truncate(text, width):
    """Truncate text to width chars, adding a trailing marker if cut."""
    if not text:
        return ""
    text = str(text)
    if len(text) <= width:
        return text
    return text[:width - 3] + "..."


def _format_confidence(raw, calibrated):
    """Format confidence as a single number for display (prefer calibrated)."""
    if calibrated is not None:
        try:
            return f"{float(calibrated):.2f}"
        except (ValueError, TypeError):
            pass
    if raw is not None:
        try:
            return f"{float(raw):.2f}"
        except (ValueError, TypeError):
            pass
    return "?"


def _display_status(entry):
    """Derive a compact display status from the decision entry."""
    user_action = entry.get("user_action")
    status = entry.get("status", "unknown")

    if user_action == "approved":
        return "ok"
    if user_action == "overridden":
        return "OVERRIDE"

    # Map internal statuses to short display forms
    display_map = {
        "auto_executed": "auto",
        "flagged": "flagged",
        "queued": "queued",
        "escalated": "ESCALATE",
        "reviewed": "ok",
        "overridden": "OVERRIDE",
    }
    return display_map.get(status, status[:8])


def _is_pending(entry):
    """Return True if this entry needs user review.

    Pending means: status is one of {flagged, queued, escalated}
    OR user_action is null (never reviewed by user).
    """
    if entry.get("user_action") is not None:
        # User already acted on it — not pending
        return False
    status = entry.get("status", "")
    return status in {"flagged", "queued", "escalated"}


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_review(args):
    """Display decisions in a readable table."""
    _, entries = _read_decisions()

    if not entries:
        print("No decisions logged yet.")
        return

    # Filter if --pending
    if args.pending:
        entries = [e for e in entries if _is_pending(e)]
        if not entries:
            print("No pending decisions. All clear.")
            return
        print(f"\nShowing {len(entries)} pending decision(s):\n")
    else:
        print(f"\nShowing {len(entries)} decision(s):\n")

    # Print header
    sep = TABLE_SEP.format("-", "-", "-", "-", "-", "-")
    header_line = TABLE_FMT.format("ID", "Date", "Decision", "File", "Conf", "Status")
    print(header_line)
    print(sep)

    for entry in entries:
        sid = _short_id(entry.get("id", "?"))
        date = _short_date(entry.get("timestamp", ""))
        summary = _truncate(entry.get("summary", ""), COL_DECISION)
        file_path = _truncate(entry.get("file", ""), COL_FILE)
        conf = _format_confidence(
            entry.get("confidence_raw"),
            entry.get("confidence_calibrated"),
        )
        status = _display_status(entry)

        row = TABLE_FMT.format(sid, date, summary, file_path, conf, status)
        print(row)

    print(sep)
    print(f"\nUse 'proxy_cli.py approve <id>' or 'proxy_cli.py override <id> --reason ...' to act.\n")


def cmd_approve(args):
    """Mark a decision as explicitly approved."""
    header, entries = _read_decisions()

    target_id = args.id
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Search for matching entry
    updated = False
    for entry in entries:
        eid = entry.get("id", "")
        # Match full ID or short numeric suffix
        if eid == target_id or _short_id(eid) == target_id:
            if entry.get("user_action") == "approved":
                print(f"Decision '{eid}' is already approved.")
                return
            entry["user_action"] = "approved"
            entry["approved_at"] = now
            entry["status"] = "reviewed"
            updated = True
            print(f"Approved: {eid}")
            print(f"  Summary: {entry.get('summary', 'N/A')}")
            print(f"  This trains the User Proxy Agent preference model (weight 2.0).")
            break

    if not updated:
        print(f"Decision '{target_id}' not found. Use 'review' to see available IDs.",
              file=sys.stderr)
        sys.exit(1)

    _write_decisions(header, entries)


def cmd_override(args):
    """Mark a decision as overridden with a reason."""
    header, entries = _read_decisions()

    target_id = args.id
    reason = args.reason
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not reason or not reason.strip():
        print("Error: --reason is required for override.", file=sys.stderr)
        sys.exit(1)

    updated = False
    for entry in entries:
        eid = entry.get("id", "")
        if eid == target_id or _short_id(eid) == target_id:
            entry["user_action"] = "overridden"
            entry["overridden_at"] = now
            entry["override_reason"] = reason.strip()
            entry["status"] = "overridden"
            updated = True
            print(f"Overridden: {eid}")
            print(f"  Summary: {entry.get('summary', 'N/A')}")
            print(f"  Reason: {reason.strip()}")
            print(f"  This feeds back to the User Proxy Agent learning loop "
                  f"(correction weight -1.0).")
            break

    if not updated:
        print(f"Decision '{target_id}' not found. Use 'review' to see available IDs.",
              file=sys.stderr)
        sys.exit(1)

    _write_decisions(header, entries)


def cmd_digest(args):
    """Print summary statistics."""
    _, entries = _read_decisions()

    if not entries:
        print("No decisions logged yet. Nothing to summarize.")
        return

    total = len(entries)

    # Count by consequence tier
    tier_counts = Counter()
    for e in entries:
        tier = e.get("consequence", "unknown")
        tier_counts[tier] += 1

    # Count by decision type
    type_counts = Counter()
    for e in entries:
        dt = e.get("decision_type", "unknown")
        type_counts[dt] += 1

    # Count by status
    status_counts = Counter()
    for e in entries:
        st = e.get("status", "unknown")
        status_counts[st] += 1

    # User action counts
    approved = sum(1 for e in entries if e.get("user_action") == "approved")
    overridden = sum(1 for e in entries if e.get("user_action") == "overridden")
    unreviewed = sum(1 for e in entries if e.get("user_action") is None)
    correction_rate = (overridden / total * 100) if total > 0 else 0.0

    # Top-3 corrected types
    corrected_type_counts = Counter()
    for e in entries:
        if e.get("user_action") == "overridden":
            dt = e.get("decision_type", "unknown")
            corrected_type_counts[dt] += 1
    top3_corrected = corrected_type_counts.most_common(3)

    # Confidence stats
    raw_confs = []
    cal_confs = []
    for e in entries:
        rc = e.get("confidence_raw")
        cc = e.get("confidence_calibrated")
        if rc is not None:
            try:
                raw_confs.append(float(rc))
            except (ValueError, TypeError):
                pass
        if cc is not None:
            try:
                cal_confs.append(float(cc))
            except (ValueError, TypeError):
                pass

    # Mode distribution
    mode_counts = Counter()
    for e in entries:
        mode = e.get("mode", "unknown")
        mode_counts[mode] += 1

    # ── Output ──
    print()
    print("=" * 55)
    print("  User Proxy Agent -- Audit Digest")
    print("=" * 55)
    print(f"  Total decisions        : {total}")
    print()

    print(f"  By consequence tier:")
    for tier in ["cosmetic", "moderate", "significant", "critical"]:
        count = tier_counts.get(tier, 0)
        bar = "#" * min(count, 40) if count > 0 else ""
        print(f"    {tier:<14s}: {count:>4d}  {bar}")
    # Catch any unknown tiers
    for tier, count in tier_counts.items():
        if tier not in {"cosmetic", "moderate", "significant", "critical"}:
            print(f"    {tier:<14s}: {count:>4d}")

    print()
    print(f"  By decision type:")
    for dtype, count in type_counts.most_common():
        print(f"    {dtype:<14s}: {count:>4d}")

    print()
    print(f"  By mode:")
    for mode in ["advisor", "delegate"]:
        count = mode_counts.get(mode, 0)
        print(f"    {mode:<14s}: {count:>4d}")

    print()
    print(f"  User review status:")
    print(f"    Approved       : {approved}")
    print(f"    Overridden     : {overridden}")
    print(f"    Unreviewed     : {unreviewed}")
    print(f"    Correction rate: {correction_rate:.1f}%")

    if top3_corrected:
        print()
        print(f"  Top corrected types:")
        for dtype, count in top3_corrected:
            print(f"    {dtype:<14s}: {count:>4d} overrides")
    else:
        print()
        print(f"  Top corrected types : (none yet)")

    if raw_confs:
        avg_raw = sum(raw_confs) / len(raw_confs)
        print()
        print(f"  Avg raw confidence     : {avg_raw:.3f}  (n={len(raw_confs)})")
    if cal_confs:
        avg_cal = sum(cal_confs) / len(cal_confs)
        print(f"  Avg calibrated conf    : {avg_cal:.3f}  (n={len(cal_confs)})")

    print()
    print("=" * 55)
    print()


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="proxy_cli",
        description="User Proxy Agent Decision Audit CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python proxy_cli.py review              Show all decisions
  python proxy_cli.py review --pending    Show only flagged/unreviewed
  python proxy_cli.py approve proxy-2026-05-23-001
  python proxy_cli.py approve 001         Short ID works too
  python proxy_cli.py override 001 --reason "Should have been snake_case"
  python proxy_cli.py digest              Summary statistics
        """,
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # review
    p_review = sub.add_parser("review", help="Display decisions in table format")
    p_review.add_argument(
        "--pending", action="store_true",
        help="Only show flagged/unreviewed decisions",
    )

    # approve
    p_approve = sub.add_parser("approve", help="Mark a decision as explicitly approved")
    p_approve.add_argument("id", help="Decision ID (full or short form)")

    # override
    p_override = sub.add_parser("override", help="Mark a decision as overridden")
    p_override.add_argument("id", help="Decision ID (full or short form)")
    p_override.add_argument(
        "--reason", required=True,
        help="Explanation for why this decision was wrong",
    )

    # digest
    sub.add_parser("digest", help="Print summary statistics")

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    commands = {
        "review": cmd_review,
        "approve": cmd_approve,
        "override": cmd_override,
        "digest": cmd_digest,
    }

    cmd_func = commands.get(args.command)
    if cmd_func is None:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    cmd_func(args)


if __name__ == "__main__":
    main()
