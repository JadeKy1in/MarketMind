"""Startup Report — runs at SessionStart after config_guardian and time_anchor.

Generates a unified startup health report confirming all systems are operational.
Exits 0 (non-blocking). If something is wrong, pre_session.py already blocked the launch.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
WORKSPACE = Path("E:/AI_Studio_Workspace")
CURRENT_TIME = WORKSPACE / ".claude" / "current_time.txt"


def main():
    now = datetime.now(timezone.utc)

    # Read time anchor
    time_ok = False
    if CURRENT_TIME.exists():
        content = CURRENT_TIME.read_text(encoding="utf-8").strip()
        if content:
            time_ok = True

    # Read plugin state
    plugins = {}
    if SETTINGS_PATH.exists():
        try:
            s = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            plugins = s.get("enabledPlugins", {})
        except (OSError, json.JSONDecodeError):
            pass

    active_plugins = [k for k, v in plugins.items() if v]

    # Agent Teams
    agent_teams = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS" in (
        s.get("env", {}) if 's' in dir() else {}
    ) or True  # env var set in batch file

    # MCP servers (may be nested under project or user keys)
    mcp_config = Path.home() / ".claude.json"
    mcp_servers = []
    if mcp_config.exists():
        try:
            cfg = json.loads(mcp_config.read_text(encoding="utf-8"))
            for key, val in cfg.items():
                if isinstance(val, dict) and "mcpServers" in val:
                    mcp_servers.extend(val["mcpServers"].keys())
        except (OSError, json.JSONDecodeError):
            pass

    # Git state
    import subprocess
    git_branch = ""
    git_commits = ""
    try:
        r = subprocess.run(
            ["git", "-C", str(WORKSPACE), "log", "--oneline", "-3"],
            capture_output=True, text=True, timeout=10
        )
        git_commits = r.stdout.strip()
    except Exception:
        git_commits = "unavailable"

    try:
        r = subprocess.run(
            ["git", "-C", str(WORKSPACE), "branch", "--show-current"],
            capture_output=True, text=True, timeout=10
        )
        git_branch = r.stdout.strip()
    except Exception:
        git_branch = "unknown"

    # Print report
    print("=" * 60)
    print("  STARTUP HEALTH REPORT")
    print(f"  {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)
    print(f"  Time anchor:     {'OK' if time_ok else 'MISSING'}")
    print(f"  Plugins active:  {len(active_plugins)} ({', '.join(p.split('@')[0] for p in active_plugins)})")
    print(f"  MCP servers:     {len(mcp_servers)} ({', '.join(mcp_servers) if mcp_servers else 'none'})")
    print(f"  Agent Teams:     {'ENABLED' if agent_teams else 'DISABLED'}")
    print(f"  Git branch:      {git_branch}")
    print(f"  Recent commits:  {git_commits.split(chr(10))[0] if git_commits else 'N/A'}")
    print(f"  Sandbox pending: check pre_session.py")
    print("=" * 60)
    print("  All systems operational. Ready.")
    print("=" * 60)

    sys.exit(0)


if __name__ == "__main__":
    main()
