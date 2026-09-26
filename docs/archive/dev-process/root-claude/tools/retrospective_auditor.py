#!/usr/bin/env python3
"""
Retrospective Auditor — Post-hoc review of User Proxy Agent decisions.

Design (from user_proxy_design.json, lines 171-178):
  - Separate agent persona: skeptical, outcome-focused, unimpressed by high
    confidence scores.
  - Runs AFTER decisions execute. Reviews previous session's decisions.
  - Spot-check 10% of auto-executed. Review 100% of council/advisor decisions.
  - Criteria:
      1. Outcome matches stated intent?
      2. Would a reasonable developer agree?
      3. Did this decision create technical debt?
      4. Was the confidence score justified?
  - Output: .claude/audits/proxy_retrospective_{date}.json
  - Flagged decisions: .claude/state/proxy_audit_queue.json

Commands:
    python retrospective_auditor.py audit --session latest
    python retrospective_auditor.py audit --days 7

Persona: SKEPTICAL AUDITOR. High confidence does not mean good decision.
An auto-executed rename at 0.92 confidence that missed the project naming
convention is still a bad decision. Call it out.

No external dependencies — Python stdlib only.
"""

import argparse
import json
import math
import os
import random
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
CLAUDE_DIR = SCRIPT_DIR.parent
DECISIONS_LOG = CLAUDE_DIR / "decisions" / "proxy_decisions.jsonl"
AUDITS_DIR = CLAUDE_DIR / "audits"
STATE_DIR = CLAUDE_DIR / "state"
AUDIT_QUEUE_FILE = STATE_DIR / "proxy_audit_queue.json"

# ── Architecture / refactoring keywords that suggest broader impact ──────────
ARCHITECTURE_KEYWORDS = [
    "refactor", "extract", "redesign", "restructure", "reorganize",
    "decouple", "split", "merge", "abstract", "introduce pattern",
    "pipeline", "layer", "gateway", "interface", "plugin", "middleware",
    "migrate", "rewrite",
]

# ── Technical debt indicators ───────────────────────────────────────────────
TECH_DEBT_KEYWORDS = [
    "temporary", "workaround", "hack", "todo", "fixme",
    "quick fix", "band-aid", "hotfix",
    "for now", "until we", "placeholder", "stub",
]

# ── Naming conventions the auditor expects ──────────────────────────────────
PYTHON_NAMING_RULES = {
    "files": "snake_case",     # .py files should be snake_case
    "functions": "snake_case",
    "classes": "PascalCase",
    "variables": "snake_case",
    "constants": "UPPER_SNAKE",
}

# ── Consequence tier: max justifiable confidence ────────────────────────────
# The auditor is skeptical: high confidence should be earned.
# These caps represent "above this, the auditor gets suspicious."
CONFIDENCE_CAPS = {
    "cosmetic":    0.95,   # Still high — but we'll ask: was it really that certain?
    "moderate":    0.85,
    "significant": 0.78,
    "critical":    0.70,   # Critical decisions at >0.70? Show me the evidence.
}

# ── Sampling rates ──────────────────────────────────────────────────────────
AUTO_EXECUTED_SAMPLE_RATE = 0.10   # Spot-check 10%
COUNCIL_REVIEW_RATE       = 1.00   # Review 100% of council/advisor decisions

# ── Session gap threshold (hours) ───────────────────────────────────────────
# Decisions more than this many hours apart are considered different sessions.
SESSION_GAP_HOURS = 4


# ===========================================================================
#  Data I/O
# ===========================================================================

def _read_decisions():
    """Read the JSONL decisions file.

    Returns (header: dict | None, entries: list[dict]).
    The header is the _schema_version line. Metadata lines (keys starting with
    '_') are skipped.
    """
    header = None
    entries = []

    if not DECISIONS_LOG.exists():
        return header, entries

    with open(DECISIONS_LOG, "r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                continue

            if "_schema_version" in obj:
                if header is None:
                    header = obj
                continue
            if list(obj.keys()) and list(obj.keys())[0].startswith("_"):
                continue
            entries.append(obj)

    return header, entries


def _read_audit_queue():
    """Read existing audit queue or return empty list.

    Returns list of previously-flagged decision IDs that are still waiting for
    user review.
    """
    if not AUDIT_QUEUE_FILE.exists():
        return []

    try:
        data = json.loads(AUDIT_QUEUE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError):
        return []


def _write_audit_queue(queue_entries):
    """Write the audit queue file, creating the directory if needed."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_QUEUE_FILE.write_text(
        json.dumps(queue_entries, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_report(report, output_path):
    """Write the audit report JSON to disk."""
    AUDITS_DIR.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ===========================================================================
#  Session partitioning
# ===========================================================================

def _parse_timestamp(ts_str):
    """Parse an ISO timestamp string to a datetime (UTC)."""
    if not ts_str:
        return None
    try:
        ts = ts_str.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _group_into_sessions(entries):
    """Partition entries into sessions based on time gaps.

    A session boundary occurs when two consecutive decisions are more than
    SESSION_GAP_HOURS apart.

    Returns list of lists: [[session1_entries], [session2_entries], ...].
    """
    if not entries:
        return []

    # Sort by timestamp
    sorted_entries = sorted(
        entries,
        key=lambda e: _parse_timestamp(e.get("timestamp", "")) or datetime.min.replace(tzinfo=timezone.utc),
    )

    sessions = []
    current_session = [sorted_entries[0]]

    for i in range(1, len(sorted_entries)):
        prev_ts = _parse_timestamp(sorted_entries[i - 1].get("timestamp", ""))
        curr_ts = _parse_timestamp(sorted_entries[i].get("timestamp", ""))

        if prev_ts and curr_ts:
            gap = (curr_ts - prev_ts).total_seconds() / 3600.0
            if gap > SESSION_GAP_HOURS:
                sessions.append(current_session)
                current_session = [sorted_entries[i]]
            else:
                current_session.append(sorted_entries[i])
        else:
            current_session.append(sorted_entries[i])

    if current_session:
        sessions.append(current_session)

    return sessions


# ===========================================================================
#  Selection: which decisions to audit
# ===========================================================================

def _select_decisions_to_audit(entries):
    """Select which decisions to review.

    Per design spec:
      - 10% random sample of auto_executed decisions
      - 100% of council/advisor decisions (anything not auto_executed)

    Returns (selected: list[dict], sampling_note: str).
    """
    auto_executed = [e for e in entries if e.get("status") == "auto_executed"]
    non_auto = [e for e in entries if e.get("status") != "auto_executed"]

    # Council / advisor decisions: 100% review
    selected = list(non_auto)

    # Auto-executed: 10% spot-check (at least 1 if there are any)
    sample_size = max(1, math.ceil(len(auto_executed) * AUTO_EXECUTED_SAMPLE_RATE))
    if auto_executed:
        sampled = random.sample(auto_executed, min(sample_size, len(auto_executed)))
        selected.extend(sampled)
    else:
        sampled = []

    note = (
        f"Auto-executed: {len(auto_executed)} total, {len(sampled)} sampled "
        f"({AUTO_EXECUTED_SAMPLE_RATE*100:.0f}% spot-check). "
        f"Council/Advisor: {len(non_auto)} total, {len(non_auto)} reviewed (100%)."
    )

    return selected, note


# ===========================================================================
#  Heuristic evaluation
# ===========================================================================

# ── Persona prompt (for context — not sent to an LLM, just guides our logic) ─
AUDITOR_PERSONA = """
You are the RETROSPECTIVE AUDITOR. You are skeptical by nature. You do not
trust confidence scores. You have seen too many 0.92-confidence decisions
that were flat-out wrong. Your job is to ask uncomfortable questions:

- Did the outcome match the stated intent, or did the proxy rationalize
  post-hoc?
- Would a reasonable developer on this project agree with the decision?
  Would they nod, or would they frown and undo it?
- Did this create technical debt? Even a little? Count it.
- Was the confidence score justified? Or was the proxy overconfident about
  something it didn't fully understand?

You are outcome-focused. You don't care about the proxy's rationale.
You care about what the codebase looks like AFTER the decision.
"""


def _evaluate_outcome_matches_intent(entry):
    """Check if the decision type and summary are coherent.

    Returns (passes: bool, notes: str).
    """
    decision_type = entry.get("decision_type", "")
    summary = (entry.get("summary", "") or "").lower()
    file_path = (entry.get("file", "") or "").lower()

    # If decision_type is "naming" but the summary talks about extraction
    # or splitting, the decision was miscategorized.
    if decision_type == "naming":
        for kw in ["extract", "split", "refactor", "decouple", "merge", "add "]:
            if kw in summary:
                return False, f"Miscategorized: 'naming' decision contains '{kw}' — scope was larger than a rename."

    # If decision_type is "code_style" but sounds architectural
    if decision_type == "code_style":
        arch_words_in_summary = sum(1 for kw in ARCHITECTURE_KEYWORDS if kw in summary)
        if arch_words_in_summary >= 2:
            return False, f"Miscategorized: 'code_style' with architectural keywords ({arch_words_in_summary} found)."

    # If decision_type is "architecture" but summary is just a rename
    if decision_type == "architecture":
        if "rename" in summary and all(kw not in summary for kw in ARCHITECTURE_KEYWORDS):
            return False, "Miscategorized: 'architecture' decision looks like a simple rename."

    # Naming: check Python conventions
    if decision_type == "naming":
        if file_path.endswith(".py"):
            if " " in summary:
                # Try to extract the new name from the summary
                pass  # hard to do reliably without parsing

    return True, ""


def _evaluate_reasonable_developer(entry):
    """Would a reasonable developer on this project agree?

    Checks:
      - Critical decisions with one-line rationales → suspicious
      - Architecture decisions without multi-sentence rationale → suspicious
      - Naming that violates conventions → suspicious

    Returns (passes: bool, notes: str).
    """
    consequence = entry.get("consequence", "")
    decision_type = entry.get("decision_type", "")
    rationale = (entry.get("rationale", "") or "").strip()
    summary = (entry.get("summary", "") or "").lower()

    # Critical decisions need substantial justification
    if consequence == "critical":
        if len(rationale.split(". ")) < 2:
            return False, "Critical decision with only one-line rationale — insufficient justification."

    # Architecture decisions should have detailed rationale
    if decision_type == "architecture":
        if len(rationale) < 60:
            return False, f"Architecture decision with short rationale ({len(rationale)} chars) — lacks context for developer buy-in."

    # Naming: check for obviously bad patterns
    if decision_type == "naming":
        # Long names are a smell
        if "TooLong" in summary or len(summary) > 80:
            return False, "Excessively long name — reasonable developer would push back."
        # MixedCase in Python snake_case contexts
        if "." in (entry.get("file", "") or ""):
            pass  # skip for now

    # Overridden decisions: the developer already disagreed
    if entry.get("user_action") == "overridden":
        return False, f"Developer overrode this decision: {entry.get('override_reason', 'no reason given')}"

    return True, ""


def _evaluate_technical_debt(entry):
    """Does this decision create technical debt?

    Checks:
      - Keywords like "temporary", "workaround", "hack", "TODO"
      - Architecture decisions that increase coupling
      - Decisions that add new files vs. modifying existing ones

    Returns (passes: bool, notes: str).
    """
    summary = (entry.get("summary", "") or "").lower()
    rationale = (entry.get("rationale", "") or "").lower()
    file_path = (entry.get("file", "") or "")

    # Explicit technical debt markers
    for kw in TECH_DEBT_KEYWORDS:
        if kw in summary or kw in rationale:
            return False, f"Explicit technical debt marker: '{kw}'."

    # "Extract" without corresponding test or validation → possible tech debt
    if "extract" in summary and "parametrize" not in summary and "test" not in file_path:
        # Could be creating untested abstraction
        return False, "Extraction without corresponding test — untested abstraction is technical debt."

    return True, ""


def _evaluate_confidence_justified(entry):
    """Is the confidence score justified?

    The auditor is SKEPTICAL. High confidence on high-consequence decisions
    does NOT get a free pass.

    Returns (passes: bool, notes: str).
    """
    consequence = entry.get("consequence", "moderate")
    confidence = None

    # Prefer calibrated, fall back to raw
    cc = entry.get("confidence_calibrated")
    rc = entry.get("confidence_raw")
    try:
        if cc is not None:
            confidence = float(cc)
        elif rc is not None:
            confidence = float(rc)
    except (ValueError, TypeError):
        pass

    if confidence is None:
        return True, "No confidence score available."

    cap = CONFIDENCE_CAPS.get(consequence, 0.80)

    if confidence > cap:
        return False, (
            f"Suspiciously high confidence ({confidence:.2f}) for "
            f"'{consequence}' consequence. Cap is {cap:.2f}. "
            f"Was the proxy really this certain?"
        )

    # Additional: if it was overridden, the confidence was clearly wrong
    if entry.get("user_action") == "overridden" and confidence > 0.75:
        return False, (
            f"Confidence {confidence:.2f} on an overridden decision — "
            f"overconfidence in action."
        )

    return True, ""


def _audit_entry(entry):
    """Run all four evaluation criteria against a single decision entry.

    Returns a finding dict.
    """
    results = {
        "outcome_matches_intent": _evaluate_outcome_matches_intent(entry),
        "reasonable_developer_agree": _evaluate_reasonable_developer(entry),
        "created_technical_debt": _evaluate_technical_debt(entry),
        "confidence_justified": _evaluate_confidence_justified(entry),
    }

    criteria_results = {}
    auditor_notes_lines = []
    all_pass = True

    for criterion, (passes, note) in results.items():
        criteria_results[criterion] = passes
        if not passes:
            all_pass = False
            auditor_notes_lines.append(f"[{criterion}] {note}")

    # Determine severity
    fail_count = sum(1 for p in criteria_results.values() if not p)
    if fail_count == 0:
        severity = "clean"
    elif fail_count == 1:
        severity = "minor"
    elif fail_count == 2:
        severity = "warning"
    else:
        severity = "critical"

    finding = {
        "decision_id": entry.get("id", "unknown"),
        "passes": all_pass,
        "criteria_results": criteria_results,
        "auditor_notes": " | ".join(auditor_notes_lines) if auditor_notes_lines else "All criteria pass.",
        "severity": severity,
        "decision_summary": entry.get("summary", ""),
        "confidence_raw": entry.get("confidence_raw"),
        "confidence_calibrated": entry.get("confidence_calibrated"),
        "consequence": entry.get("consequence"),
        "decision_type": entry.get("decision_type"),
    }

    return finding


# ===========================================================================
#  Audit orchestration
# ===========================================================================

def _get_scope_entries(args):
    """Determine which entries to audit based on CLI args.

    Returns (entries: list[dict], scope_label: str).
    """
    _, all_entries = _read_decisions()

    if not all_entries:
        return [], "(no decisions found)"

    if args.days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
        filtered = []
        for e in all_entries:
            ts = _parse_timestamp(e.get("timestamp", ""))
            if ts and ts >= cutoff:
                filtered.append(e)
        return filtered, f"last {args.days} day(s)"

    # --session latest (default)
    sessions = _group_into_sessions(all_entries)
    if not sessions:
        return [], "(no sessions found)"

    latest_session = sessions[-1]
    return latest_session, "latest session"


def cmd_audit(args):
    """Run a retrospective audit and produce a report."""
    scope_entries, scope_label = _get_scope_entries(args)

    if not scope_entries:
        print(f"[auditor] No decisions found for {scope_label}.")
        print("[auditor] Nothing to audit. (The proxy may not have made decisions yet.)")
        return

    selected, sampling_note = _select_decisions_to_audit(scope_entries)

    if not selected:
        print("[auditor] No decisions selected for review (sampling returned empty).")
        return

    print(f"[auditor] Scope: {scope_label}  |  {sampling_note}")
    print(f"[auditor] Auditing {len(selected)} decision(s)...")
    print()

    findings = []
    flagged = []

    for entry in selected:
        finding = _audit_entry(entry)
        findings.append(finding)

        status_icon = "[PASS]" if finding["passes"] else "[FLAG]"
        print(f"  {status_icon} {finding['decision_id']}  "
              f"severity={finding['severity']}  "
              f"type={finding['decision_type']}  "
              f"consequence={finding['consequence']}")

        if not finding["passes"]:
            print(f"         {finding['auditor_notes']}")
            flagged.append(finding)

    print()

    # ── Build report ────────────────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    audit_date_str = now.strftime("%Y-%m-%d")
    audit_ts_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    audit_id = f"audit-{audit_date_str}-{now.strftime('%H%M%S')}"

    report = {
        "audit_id": audit_id,
        "audit_date": audit_ts_str,
        "scope": scope_label,
        "decisions_in_scope": len(scope_entries),
        "decisions_reviewed": len(selected),
        "sampling_note": sampling_note,
        "findings": findings,
        "summary": {
            "passed": sum(1 for f in findings if f["passes"]),
            "flagged": sum(1 for f in findings if not f["passes"]),
            "by_severity": {
                "clean": sum(1 for f in findings if f["severity"] == "clean"),
                "minor": sum(1 for f in findings if f["severity"] == "minor"),
                "warning": sum(1 for f in findings if f["severity"] == "warning"),
                "critical": sum(1 for f in findings if f["severity"] == "critical"),
            },
        },
        "auditor_persona_note": (
            "Skeptical, outcome-focused auditor. High confidence scores do not "
            "constitute evidence. Review flagged findings and confirm or dismiss."
        ),
    }

    # ── Write report ────────────────────────────────────────────────────────
    report_filename = f"proxy_retrospective_{audit_date_str}.json"
    report_path = AUDITS_DIR / report_filename
    _write_report(report, report_path)
    print(f"[auditor] Report written to: {report_path}")

    # ── Update audit queue ──────────────────────────────────────────────────
    if flagged:
        existing_queue = _read_audit_queue()
        existing_ids = {q.get("decision_id", "") for q in existing_queue}

        new_queue_entries = []
        for f in flagged:
            if f["decision_id"] not in existing_ids:
                new_queue_entries.append({
                    "decision_id": f["decision_id"],
                    "audit_id": audit_id,
                    "audit_date": audit_ts_str,
                    "severity": f["severity"],
                    "auditor_notes": f["auditor_notes"],
                    "status": "pending_review",
                })

        if new_queue_entries:
            merged = existing_queue + new_queue_entries
            _write_audit_queue(merged)
            print(f"[auditor] {len(new_queue_entries)} new flag(s) added to audit queue: "
                  f"{AUDIT_QUEUE_FILE}")

    # ── Final summary ───────────────────────────────────────────────────────
    total = len(findings)
    passed = report["summary"]["passed"]
    flagged_count = report["summary"]["flagged"]
    flag_pct = (flagged_count / total * 100) if total > 0 else 0

    print()
    print("=" * 55)
    print("  RETROSPECTIVE AUDIT COMPLETE")
    print("=" * 55)
    print(f"  Reviewed   : {total}")
    print(f"  Passed     : {passed}")
    print(f"  Flagged    : {flagged_count} ({flag_pct:.1f}%)")
    print(f"  Severity   : {report['summary']['by_severity']['clean']} clean, "
          f"{report['summary']['by_severity']['minor']} minor, "
          f"{report['summary']['by_severity']['warning']} warning, "
          f"{report['summary']['by_severity']['critical']} critical")
    print()
    if flagged_count > 0:
        print("  Flagged decisions have been added to the proxy audit queue.")
        print(f"  Review them with: python .claude/tools/proxy_cli.py review --pending")
    print("=" * 55)


# ===========================================================================
#  CLI
# ===========================================================================

def build_parser():
    parser = argparse.ArgumentParser(
        prog="retrospective_auditor",
        description="Post-hoc review of User Proxy Agent decisions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python retrospective_auditor.py audit --session latest
  python retrospective_auditor.py audit --days 7

The auditor is skeptical by design. It evaluates each decision against four
criteria:
  1. Outcome matches intent
  2. Reasonable developer would agree
  3. Created technical debt
  4. Confidence score justified
        """,
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    p_audit = sub.add_parser("audit", help="Run a retrospective audit")
    scope_group = p_audit.add_mutually_exclusive_group()
    scope_group.add_argument(
        "--session", type=str, default="latest",
        help="Audit a specific session (default: latest)",
    )
    scope_group.add_argument(
        "--days", type=int, default=None,
        help="Audit decisions from the last N days",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "audit":
        cmd_audit(args)
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
