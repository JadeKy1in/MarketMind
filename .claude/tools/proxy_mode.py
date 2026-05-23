#!/usr/bin/env python3
"""
User Proxy Agent — Mode Management & Escalation Logic

Core decision engine for the User Proxy Agent. Manages Advisor/Delegate mode
state and implements should_escalate() — the single function that replaces
the ambiguous confidence-tier design from the original spec.

RED TEAM FIXES (2026-05-23):
  - Issue #1: Mode indicator now baked into this module. get_mode_indicator()
    returns "[Advisor]" or "[Delegate]" for prompt display. set_mode() also
    updates the workspace CLAUDE.md so the indicator is visible at session start.
  - Issue #2: 0.85+ gap closed. When user IS present in advisor mode and
    confidence > 0.85, the old design had no trigger — advisor triggered at
    <0.85, delegate triggered only when user was absent. Now: advisor mode
    with user present ALWAYS returns AUTO_EXECUTE_NOTIFY at every confidence
    tier (present recommendation, user decides). Advisor NEVER auto-executes.

Usage:
    from .claude.tools.proxy_mode import get_mode, set_mode, get_mode_indicator, should_escalate

    # Read current mode
    mode = get_mode()                         # "advisor" | "delegate"

    # Switch modes (also updates CLAUDE.md indicator)
    set_mode("delegate", "User granted autonomous control for this session")

    # Prompt indicator
    indicator = get_mode_indicator()          # "[Advisor]" | "[Delegate]"

    # Decision routing
    action = should_escalate(
        confidence=0.92,
        consequence="moderate",
        user_present=True,
    )  # → "AUTO_EXECUTE_NOTIFY"  (advisor mode, user present, high conf)

Architecture:
    .claude/state/proxy_mode.json          — current mode + thresholds (read/write)
    .claude/state/proxy_mode_changes.jsonl — append-only audit log of transitions
    .CLAUDE.md                             — mode indicator line updated on mode change
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

# ── Paths (computed relative to this file) ────────────────────────────────────
_TOOLS_DIR = Path(__file__).resolve().parent                     # .claude/tools/
_CLAUDE_DIR = _TOOLS_DIR.parent                                   # .claude/
_WORKSPACE_ROOT = _CLAUDE_DIR.parent                              # workspace root
_STATE_DIR = _CLAUDE_DIR / "state"
_MODE_FILE = _STATE_DIR / "proxy_mode.json"
_MODE_LOG = _STATE_DIR / "proxy_mode_changes.jsonl"
_CLAUDEMD = _WORKSPACE_ROOT / "CLAUDE.md"

# ── Type Aliases ──────────────────────────────────────────────────────────────
Mode = Literal["advisor", "delegate"]
Consequence = Literal["cosmetic", "moderate", "significant", "critical"]
Action = Literal[
    "AUTO_EXECUTE_SILENT",
    "AUTO_EXECUTE_NOTIFY",
    "REQUEST_CLARIFICATION",
    "QUEUE_FOR_USER",
    "ESCALATE",
]

# ── Sentinel for the CLAUDE.md mode-indicator line ───────────────────────────
# The line in CLAUDE.md looks like:
#   ## Proxy Mode: [Advisor]
# It is located immediately after the H1 title. On set_mode() we locate and
# replace it. Use this prefix to find the line; the full line is reconstructed
# with the current indicator bracketed.
_MODE_INDICATOR_PREFIX = "## Proxy Mode:"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _ensure_state_dir() -> None:
    """Create .claude/state/ directory tree if needed."""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)


def _init_mode_file() -> dict:
    """Create a fresh proxy_mode.json with safe defaults (advisor)."""
    default = {
        "mode": "advisor",
        "changed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "changed_by": "initialization",
        "delegate_confidence_floor": 0.50,
        "auto_notify_threshold": 0.85,
    }
    _ensure_state_dir()
    with open(_MODE_FILE, "w", encoding="utf-8") as f:
        json.dump(default, f, indent=2, ensure_ascii=False)
    return default


def _read_mode_data() -> dict:
    """Read proxy_mode.json, initializing if absent or corrupt."""
    if not _MODE_FILE.exists():
        return _init_mode_file()
    try:
        with open(_MODE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        # Corrupt or missing — overwrite with safe defaults
        return _init_mode_file()


def _update_claude_md_indicator(indicator: str) -> None:
    """Update the mode-indicator line in workspace CLAUDE.md.

    Looks for a line starting with '## Proxy Mode:' and replaces it.
    If the marker line is not found, inserts it after the H1 (line starting with '# ').
    """
    if not _CLAUDEMD.exists():
        return  # No CLAUDE.md to update — nothing to do

    new_line = f"{_MODE_INDICATOR_PREFIX} {indicator}"

    with open(_CLAUDEMD, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Try to find and replace an existing indicator line
    replaced = False
    for i, line in enumerate(lines):
        stripped = line.rstrip("\n").rstrip("\r")
        if stripped.startswith(_MODE_INDICATOR_PREFIX):
            # Preserve trailing whitespace/newline from the original
            lines[i] = f"{new_line}\n"
            replaced = True
            break

    if not replaced:
        # Insert after the first H1 line (the title line starting with "# ")
        inserted = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("# ") and not stripped.startswith("## "):
                lines.insert(i + 1, f"{new_line}\n")
                inserted = True
                break
        if not inserted:
            # No H1 found — prepend to the file
            lines.insert(0, f"{new_line}\n")

    with open(_CLAUDEMD, "w", encoding="utf-8") as f:
        f.writelines(lines)


# ── Public API ────────────────────────────────────────────────────────────────

def get_mode() -> Mode:
    """Return the current proxy mode: "advisor" or "delegate".

    Always returns "advisor" if the state file is missing, corrupt, or contains
    an unrecognised mode string — safe-by-default.
    """
    data = _read_mode_data()
    mode = data.get("mode", "advisor")
    if mode not in ("advisor", "delegate"):
        return "advisor"
    return mode


def set_mode(mode: Mode, reason: str, changed_by: str = "user") -> None:
    """Transition the proxy to a new mode.

    Writes the updated state to proxy_mode.json, appends an entry to the
    append-only change log (proxy_mode_changes.jsonl), and updates the
    mode-indicator line in the workspace CLAUDE.md so the new mode is
    visible at the next session start.

    Args:
        mode:          "advisor" or "delegate"
        reason:        Human-readable explanation (logged)
        changed_by:    Actor — "user", "system", "session_start", "safety_override"
    """
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Preserve existing thresholds, only update mode + metadata
    existing = {}
    if _MODE_FILE.exists():
        try:
            with open(_MODE_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            pass

    old_mode = existing.get("mode", "unknown")

    data = {
        "mode": mode,
        "changed_at": now_iso,
        "changed_by": changed_by,
        "delegate_confidence_floor": existing.get("delegate_confidence_floor", 0.50),
        "auto_notify_threshold": existing.get("auto_notify_threshold", 0.85),
    }

    _ensure_state_dir()
    with open(_MODE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # Append-only log
    log_entry = {
        "timestamp": now_iso,
        "from_mode": old_mode,
        "to_mode": mode,
        "reason": reason,
        "changed_by": changed_by,
    }
    with open(_MODE_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    # Update the visible indicator in CLAUDE.md
    indicator = "[Advisor]" if mode == "advisor" else "[Delegate]"
    _update_claude_md_indicator(indicator)


def get_mode_indicator() -> str:
    """Return "[Advisor]" or "[Delegate]" for display in the session prompt.

    Call this at session start to generate the mode-indicator line.
    """
    return "[Advisor]" if get_mode() == "advisor" else "[Delegate]"


def get_thresholds() -> dict:
    """Return the current confidence ceilings from proxy_mode.json.

    Returns:
        {
            "delegate_confidence_floor": 0.50,
            "auto_notify_threshold": 0.85,
        }
    """
    data = _read_mode_data()
    return {
        "delegate_confidence_floor": data.get("delegate_confidence_floor", 0.50),
        "auto_notify_threshold": data.get("auto_notify_threshold", 0.85),
    }


def should_escalate(
    confidence: float,
    consequence: Consequence,
    user_present: bool,
) -> Action:
    """Route a proxy decision to the correct action.

    This is the single decision function that replaces the ambiguous confidence
    tiers in the original design. All four mode/user combinations (advisor+present,
    advisor+absent, delegate+present, delegate+absent) have explicit behavior
    defined — no gaps, no silent fallthroughs.

    ── RED TEAM FIX (Issue #2 — 0.85+ gap) ──
    The original design had a gap: when user IS present AND confidence > 0.85
    in advisor mode, neither the advisor trigger (requires <0.85) nor the
    delegate trigger (requires user absent) would fire. The proxy would
    silently auto-execute while the user watched.

    Fix: In advisor mode, EVERY confidence tier with user present returns a
    notification action. Advisor mode NEVER auto-executes silently. The 0.85+
    tier now explicitly maps to AUTO_EXECUTE_NOTIFY (present recommendation,
    user decides).

    ── Decision Matrix ──

    ADVISOR MODE (user present):
      confidence >= 0.85  → AUTO_EXECUTE_NOTIFY  (present analysis; user decides)
      confidence 0.70-0.85 → AUTO_EXECUTE_NOTIFY  (show recommendation; user decides)
      confidence 0.50-0.70 → REQUEST_CLARIFICATION (ask user for clarification)
      confidence < 0.50    → ESCALATE              (user must decide)

    ADVISOR MODE (user absent):
      any confidence → QUEUE_FOR_USER  (cannot act without user consent)

    DELEGATE MODE (user present):
      confidence >= 0.85 + consequence ≤ moderate → AUTO_EXECUTE_SILENT
      confidence >= 0.85 + consequence > moderate → AUTO_EXECUTE_NOTIFY
      confidence 0.70-0.85 → AUTO_EXECUTE_NOTIFY
      confidence 0.50-0.70 → REQUEST_CLARIFICATION  (user is present; just ask)
      confidence < 0.50    → ESCALATE

    DELEGATE MODE (user absent):
      confidence >= 0.85 + consequence ≤ moderate → AUTO_EXECUTE_SILENT
      confidence >= 0.85 + consequence > moderate → AUTO_EXECUTE_NOTIFY
      confidence 0.70-0.85 → AUTO_EXECUTE_NOTIFY
      confidence 0.50-0.70 → QUEUE_FOR_USER
      confidence < 0.50    → QUEUE_FOR_USER

    Args:
        confidence:   Platt-calibrated confidence score in [0.0, 1.0].
        consequence:  Impact level — "cosmetic" | "moderate" | "significant"
                       | "critical".
        user_present: Whether the user is actively monitoring this session.

    Returns:
        One of:
          - "AUTO_EXECUTE_SILENT"   Execute immediately, log only.
          - "AUTO_EXECUTE_NOTIFY"   Execute (delegate) or present (advisor)
                                     and notify user.
          - "REQUEST_CLARIFICATION" Ask user before proceeding.
          - "QUEUE_FOR_USER"        Add to pending review queue; user absent.
          - "ESCALATE"              User must decide; cannot proceed without them.

    Raises:
        ValueError: If confidence is outside [0.0, 1.0].
    """
    # ── Validation ────────────────────────────────────────────────────────────
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(
            f"confidence must be in [0.0, 1.0], got {confidence!r}"
        )

    valid_consequences = frozenset({"cosmetic", "moderate", "significant", "critical"})
    if consequence not in valid_consequences:
        raise ValueError(
            f"consequence must be one of {sorted(valid_consequences)}, "
            f"got {consequence!r}"
        )

    mode = get_mode()

    # ── Advisor Mode ──────────────────────────────────────────────────────────
    # Advisor NEVER auto-executes silently. Every decision is routed to the user
    # for awareness or explicit approval.
    if mode == "advisor":
        if not user_present:
            # Cannot act without user consent in advisor mode — queue everything.
            return "QUEUE_FOR_USER"

        # User IS present — ALL paths notify or escalate to the user.
        # This is the fix for Red Team Issue #2: confidence >= 0.85 now has
        # an explicit action (NOTIFY) instead of falling into a silent gap.
        if confidence >= 0.85:
            # High confidence → present analysis + recommendation; user confirms
            return "AUTO_EXECUTE_NOTIFY"
        elif confidence >= 0.70:
            # Medium-high → show recommendation; user decides
            return "AUTO_EXECUTE_NOTIFY"
        elif confidence >= 0.50:
            # Medium-low → need user clarification before proceeding
            return "REQUEST_CLARIFICATION"
        else:
            # Low confidence → user must make the decision
            return "ESCALATE"

    # ── Delegate Mode ─────────────────────────────────────────────────────────
    # Delegate acts autonomously on behalf of the user. High-confidence,
    # low-stakes decisions auto-execute silently. Borderline cases and
    # high-stakes decisions trigger notifications or escalations.
    if mode == "delegate":
        if user_present:
            if confidence >= 0.85:
                if consequence in ("cosmetic", "moderate"):
                    # High confidence + low/medium stakes = safe to execute silently.
                    # The user is present and can interrupt if needed.
                    return "AUTO_EXECUTE_SILENT"
                else:
                    # High confidence + significant/critical stakes = execute
                    # but notify user so they're aware.
                    return "AUTO_EXECUTE_NOTIFY"
            elif confidence >= 0.70:
                # Moderate confidence → execute but flag for review
                return "AUTO_EXECUTE_NOTIFY"
            elif confidence >= 0.50:
                # Borderline confidence, user IS present → just ask
                return "REQUEST_CLARIFICATION"
            else:
                # Low confidence, user present → escalate
                return "ESCALATE"
        else:
            # User NOT present
            if confidence >= 0.85:
                if consequence in ("cosmetic", "moderate"):
                    return "AUTO_EXECUTE_SILENT"
                else:
                    return "AUTO_EXECUTE_NOTIFY"
            elif confidence >= 0.70:
                return "AUTO_EXECUTE_NOTIFY"
            elif confidence >= 0.50:
                # User absent + borderline = queue; don't auto-execute
                return "QUEUE_FOR_USER"
            else:
                # Low confidence + user absent = queue with escalation note
                return "QUEUE_FOR_USER"

    # Fallback — should be unreachable (mode is validated in get_mode)
    return "ESCALATE"


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli_status() -> None:
    """Print current mode and thresholds to stdout."""
    mode = get_mode()
    indicator = get_mode_indicator()
    thresholds = get_thresholds()
    print(f"  Mode:       {mode}  {indicator}")
    print(f"  Thresholds: delegate_floor={thresholds['delegate_confidence_floor']}  "
          f"auto_notify={thresholds['auto_notify_threshold']}")


def _cli_set(mode_str: str, reason: str) -> None:
    """Set mode via CLI with interactive confirmation."""
    mode = mode_str.lower()
    if mode not in ("advisor", "delegate"):
        print(f"Error: mode must be 'advisor' or 'delegate', got '{mode_str}'")
        raise SystemExit(1)

    print(f"Transitioning to {mode} mode...")
    print(f"  Reason: {reason}")
    print(f"  Indicator will show: {'[Advisor]' if mode == 'advisor' else '[Delegate]'}")

    confirm = input("Proceed? [y/N] ").strip().lower()
    if confirm not in ("y", "yes"):
        print("Aborted.")
        return

    set_mode(mode, reason, changed_by="user_cli")
    print(f"Mode changed to {mode}. CLAUDE.md indicator updated.")


def _cli_test_matrix() -> None:
    """Run a diagnostic: print the full decision matrix for all combinations."""
    modes: list[Mode] = ["advisor", "delegate"]
    consequences: list[Consequence] = ["cosmetic", "moderate", "significant", "critical"]
    confidence_levels = [
        (0.95, ">= 0.85"),
        (0.80, "0.70-0.85"),
        (0.60, "0.50-0.70"),
        (0.30, "< 0.50"),
    ]
    presence = [(True, "present"), (False, "absent")]

    width = 68
    print("=" * width)
    print(f"{'Proxy Mode Decision Matrix':^{width}}")
    print("=" * width)

    for mode in modes:
        indicator = "[Advisor]" if mode == "advisor" else "[Delegate]"
        print(f"\n  {'─' * (width - 2)}")
        print(f"  {indicator}  mode={mode}")
        print(f"  {'─' * (width - 2)}")

        for user_present, pres_label in presence:
            print(f"\n    User {pres_label}:")
            for conf, conf_label in confidence_levels:
                for cons in consequences:
                    action = should_escalate(
                        confidence=conf,
                        consequence=cons,
                        user_present=user_present,
                    )
                    print(
                        f"      conf={conf_label:<12}  consequence={cons:<12}  "
                        f"→ {action}"
                    )

    print(f"\n{'=' * width}")
    print("All 64 combinations (2 modes × 2 presence × 4 tiers × 4 consequences)")
    print(f"{'=' * width}")


def main() -> None:
    """CLI entry point for proxy mode management.

    Usage:
        python proxy_mode.py status           Show current mode
        python proxy_mode.py set advisor      Switch to advisor mode
        python proxy_mode.py set delegate     Switch to delegate mode
        python proxy_mode.py matrix           Print full decision matrix
        python proxy_mode.py indicator        Print just the mode indicator string
    """
    import sys

    if len(sys.argv) < 2:
        print("Usage: proxy_mode.py <status|set|matrix|indicator> [args...]")
        raise SystemExit(1)

    cmd = sys.argv[1].lower()

    if cmd == "status":
        _cli_status()
    elif cmd == "set":
        if len(sys.argv) < 3:
            print("Usage: proxy_mode.py set <advisor|delegate> [reason]")
            raise SystemExit(1)
        mode_str = sys.argv[2]
        reason = sys.argv[3] if len(sys.argv) > 3 else "Manual mode change via CLI"
        _cli_set(mode_str, reason)
    elif cmd == "matrix":
        _cli_test_matrix()
    elif cmd == "indicator":
        print(get_mode_indicator())
    else:
        print(f"Unknown command: {cmd}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
