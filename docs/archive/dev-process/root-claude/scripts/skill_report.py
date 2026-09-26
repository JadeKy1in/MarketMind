"""Skill Usage Report — analyze skill_usage.jsonl for dead-weight identification.

Reads .claude/logs/skill_usage.jsonl and prints aggregated statistics:
  - Total invocations
  - Count per skill (sorted by usage, most-used first)
  - Count per plugin (sorted by usage)
  - Unused skills (known inventory minus observed usage)

Usage:
  python .claude/scripts/skill_report.py
  python .claude/scripts/skill_report.py --days 7   # filter to last N days
"""

import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

WORKSPACE = Path("E:/AI_Studio_Workspace")
LOG_PATH = WORKSPACE / ".claude" / "logs" / "skill_usage.jsonl"

# Known skill inventory for dead-weight detection.
# Update this list when skills are added or removed.
KNOWN_SKILLS = {
    # Superpowers plugin (13)
    "superpowers:dispatching-parallel-agents",
    "superpowers:finishing-a-development-branch",
    "superpowers:brainstorming",
    "superpowers:receiving-code-review",
    "superpowers:requesting-code-review",
    "superpowers:executing-plans",
    "superpowers:verification-before-completion",
    "superpowers:subagent-driven-development",
    "superpowers:writing-plans",
    "superpowers:using-superpowers",
    "superpowers:test-driven-development",
    "superpowers:systematic-debugging",
    "superpowers:using-git-worktrees",
    "superpowers:writing-skills",
    # Mattpocock skills — unprefixed (15)
    "find-skills",
    "frontend-design",
    "harness-assess",
    "harness-install",
    "parallel-feature-development",
    "vercel-react-best-practices",
    "update-config",
    "keybindings-help",
    "simplify",
    "fewer-permission-prompts",
    "loop",
    "claude-api",
    "init",
    "review",
    "security-review",
    # Karpathy (1)
    "andrej-karpathy-skills:karpathy-guidelines",
    # feature-dev (1)
    "feature-dev:feature-dev",
    # Claude HUD (2)
    "claude-hud:setup",
    "claude-hud:configure",
}


def parse_args():
    """Minimal arg parsing: support --days N."""
    days = None
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--days" and i + 1 < len(args):
            try:
                days = int(args[i + 1])
            except ValueError:
                print(f"ERROR: --days must be an integer, got '{args[i + 1]}'", file=sys.stderr)
                sys.exit(1)
    return days


def main():
    days_filter = parse_args()

    if not LOG_PATH.exists():
        print("No skill usage data yet. File does not exist:")
        print(f"  {LOG_PATH}")
        print("\nThis is expected if the skill_profiler hook has not been triggered yet.")
        print("Invoke any skill (e.g. /find-skills) and re-run this report.")
        sys.exit(0)

    entries = []
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass  # skip corrupt lines
    except OSError as e:
        print(f"ERROR: Could not read log file: {e}", file=sys.stderr)
        sys.exit(1)

    if not entries:
        print("No skill usage entries found. File is empty.")
        print(f"  {LOG_PATH}")
        sys.exit(0)

    # Apply days filter
    if days_filter is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_filter)
        filtered = []
        for entry in entries:
            try:
                ts = datetime.fromisoformat(entry["timestamp"])
                if ts >= cutoff:
                    filtered.append(entry)
            except (ValueError, KeyError):
                filtered.append(entry)  # keep entries with unparseable timestamps
        entries = filtered

    # Count per skill
    skill_counts = Counter(entry["skill_name"] for entry in entries)

    # Count per plugin
    plugin_counts = Counter(entry.get("plugin", "unknown") for entry in entries)

    # Find unused skills
    used_skills = set(skill_counts.keys())
    unused = KNOWN_SKILLS - used_skills

    # Print report
    header = "SKILL USAGE REPORT"
    if days_filter:
        header += f" (last {days_filter} days)"
    print("=" * 60)
    print(header)
    print("=" * 60)

    print(f"\nTotal invocations: {len(entries)}")
    print(f"Unique skills used: {len(skill_counts)}")
    print(f"Known skills in inventory: {len(KNOWN_SKILLS)}")

    print(f"\n{'─' * 60}")
    print("Usage by Skill")
    print(f"{'─' * 60}")
    if skill_counts:
        for skill, count in skill_counts.most_common():
            bar = "█" * min(count, 40)
            print(f"  {skill:<50} {count:>4}  {bar}")
    else:
        print("  (none)")

    print(f"\n{'─' * 60}")
    print("Usage by Plugin")
    print(f"{'─' * 60}")
    if plugin_counts:
        for plugin, count in plugin_counts.most_common():
            bar = "█" * min(count, 40)
            print(f"  {plugin:<30} {count:>4}  {bar}")
    else:
        print("  (none)")

    print(f"\n{'─' * 60}")
    print("Unused Skills (in inventory, never invoked)")
    print(f"{'─' * 60}")
    if unused:
        for skill in sorted(unused):
            plugin_tag = ""
            if ":" in skill:
                plugin_tag = f" [{skill.split(':', 1)[0]}]"
            else:
                plugin_tag = " [builtin]"
            print(f"  {skill}{plugin_tag}")
        print(f"\n  Total unused: {len(unused)} / {len(KNOWN_SKILLS)} ({100 * len(unused) // len(KNOWN_SKILLS)}%)")
    else:
        print("  All known skills have been used at least once.")

    # Session summary
    sessions = set(entry.get("session_id", "?") for entry in entries)
    print(f"\nUnique sessions: {len(sessions)}")

    print()


if __name__ == "__main__":
    main()
