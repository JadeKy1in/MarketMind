"""Config Guardian — 4-Guard configuration integrity daemon.

SessionStart hook that validates and auto-restores critical configuration keys
before each Claude Code session. Always exits 0 (non-blocking).

Guards:
  1. enabledPlugins — sync from installed_plugins.json, fallback to backup, then hardcoded
  2. statusLine    — restore Windows + Git Bash HUD command if missing
  3. hooks         — ensure guardian's own SessionStart entry exists (nested format)
  4. env           — restore REQUIRED_ENV and PREFERENCE_DEFAULTS from hardcoded values

Recovery logging: writes JSONL to .claude/logs/config_guardian.jsonl for root-cause analysis.
Recovery script path: E:/AI_Studio_Workspace/.claude/hooks/recover_config.py
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
GOOD_BACKUP_PATH = Path.home() / ".claude" / "settings.json.good_backup"
INSTALLED_PLUGINS_PATH = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
LOGS_DIR = Path.home() / ".claude" / "logs"
LOG_PATH = LOGS_DIR / "config_guardian.jsonl"

THIS_FILE = Path(__file__).resolve()
PROJECT_GUARDIAN_PATH = Path("E:/AI_Studio_Workspace/.claude/hooks/config_guardian.py")

RECOVER_SCRIPT_PATH = "E:/AI_Studio_Workspace/.claude/hooks/recover_config.py"

# Guard 1: hardcoded plugin fallback (R3)
HARDCODED_PLUGINS = [
    "superpowers@claude-plugins-official",
    "claude-hud@claude-hud",
    "feature-dev@claude-plugins-official",
    "andrej-karpathy-skills@karpathy-skills",
    "mattpocock-skills@mattpocock-skills",
]

# Guard 2: dynamic version-finding HUD command (Windows + Git Bash)
STATUSLINE_CMD = (
    "cols=$(stty size </dev/tty 2>/dev/null | awk '{print $2}'); "
    "export COLUMNS=$(( ${cols:-120} > 4 ? ${cols:-120} - 4 : 1 )); "
    'plugin_dir=$(ls -1d "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"'
    "/plugins/cache/*/claude-hud/*/ 2>/dev/null | sort -V | tail -1); "
    'exec node "${plugin_dir}dist/index.js"'
)

# Guard 4: hardcoded env keys (M3)
REQUIRED_ENV = {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:15721",
    "ANTHROPIC_AUTH_TOKEN": "PROXY_MANAGED",
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
    "ENABLE_TOOL_SEARCH": "true",
}

PREFERENCE_DEFAULTS = {
    "effortLevel": "max",
    "theme": "dark",
    "includeCoAuthoredBy": False,
}


# ---------------------------------------------------------------------------
# Atomic write — eliminates TOCTOU race (C3)
# ---------------------------------------------------------------------------

def atomic_write(path, data):
    """Write JSON to a temp file in the same directory, then atomically rename.

    Uses mkstemp (not NamedTemporaryFile) because on Windows, NamedTemporaryFile
    holds an open handle that blocks os.replace().
    """
    tmpfd, tmpname = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(tmpfd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
            f.flush()
        # File handle is now closed — safe for os.replace() on Windows
        os.replace(tmpname, str(path))
    finally:
        if os.path.exists(tmpname):
            os.unlink(tmpname)


# ---------------------------------------------------------------------------
# Recovery logging (R4)
# ---------------------------------------------------------------------------

def log_recovery(guard, action, detail):
    """Append a JSONL entry to the recovery log and print a human-readable line."""
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "guard": guard,
        "action": action,
        "detail": detail,
    }
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # logging failure must not block the hook
    print(f"- [config_guardian] {action} {guard}: {detail}")


def log_ok(guard):
    """Print an OK line for a guard that passed."""
    print(f"- [config_guardian] OK: {guard} intact")


# ---------------------------------------------------------------------------
# Guard 1: enabledPlugins
# ---------------------------------------------------------------------------

def guard1_enabled_plugins(settings):
    """Sync enabledPlugins from installed_plugins.json, with fallbacks.

    Strategy (R3):
      1. Read installed_plugins.json
      2. If empty/missing, fall back to good_backup's enabledPlugins
      3. If still empty, fall back to HARDCODED_PLUGINS
    Then ensure every expected plugin is in settings["enabledPlugins"].
    """
    expected_ids = set()

    # Step 1: installed_plugins.json
    try:
        if INSTALLED_PLUGINS_PATH.exists():
            with open(INSTALLED_PLUGINS_PATH, "r", encoding="utf-8") as f:
                ip_data = json.load(f)
            for plugin_id in ip_data.get("plugins", {}):
                expected_ids.add(plugin_id)
    except (OSError, json.JSONDecodeError):
        pass

    # Step 2: fallback to good_backup
    if not expected_ids:
        try:
            if GOOD_BACKUP_PATH.exists():
                with open(GOOD_BACKUP_PATH, "r", encoding="utf-8") as f:
                    backup = json.load(f)
                backup_eps = backup.get("enabledPlugins", {})
                if backup_eps:
                    expected_ids = set(backup_eps.keys())
        except (OSError, json.JSONDecodeError):
            pass

    # Step 3: hardcoded fallback
    if not expected_ids:
        expected_ids = set(HARDCODED_PLUGINS)

    # Ensure enabledPlugins key and apply
    if "enabledPlugins" not in settings:
        settings["enabledPlugins"] = {}

    restored = []
    for pid in expected_ids:
        if not settings["enabledPlugins"].get(pid):
            settings["enabledPlugins"][pid] = True
            restored.append(pid)

    if restored:
        log_recovery("enabledPlugins", "restored", f"added: {', '.join(restored)}")
        return True
    else:
        log_ok("enabledPlugins")
        return False


# ---------------------------------------------------------------------------
# Guard 2: statusLine
# ---------------------------------------------------------------------------

def guard2_statusline(settings):
    """Ensure statusLine.type == 'command' and statusLine.command is non-empty."""
    sl = settings.get("statusLine", {})
    needs_fix = False

    if not isinstance(sl, dict):
        needs_fix = True
    elif not sl.get("command") or sl.get("type") != "command":
        needs_fix = True

    if needs_fix:
        settings["statusLine"] = {"type": "command", "command": STATUSLINE_CMD}
        log_recovery("statusLine", "restored", "HUD command recreated")
        return True
    else:
        log_ok("statusLine")
        return False


# ---------------------------------------------------------------------------
# Guard 3: hooks — ensure guardian self-entry exists (nested format)
# ---------------------------------------------------------------------------

def _guardian_hook_entry(python_path):
    """Build the nested hook entry for the guardian."""
    return {
        "matcher": "",
        "hooks": [
            {"type": "command", "command": f'python "{python_path}"'}
        ],
    }


def _find_guardian_in_hooks(session_start_hooks):
    """Check if any hook entry in the SessionStart list references config_guardian.py."""
    for entry in session_start_hooks:
        if not isinstance(entry, dict):
            continue
        matcher = entry.get("matcher", "")
        # matcher must be "" for SessionStart (no tool filter)
        if matcher != "":
            continue
        sub_hooks = entry.get("hooks", [])
        for h in sub_hooks:
            if isinstance(h, dict) and "config_guardian.py" in h.get("command", ""):
                return True
    return False


def guard3_hooks(settings):
    """Ensure the guardian's own SessionStart hook entry exists (nested format).

    Only validates the guardian's own entry — never modifies other hooks (H1).
    """
    if "hooks" not in settings:
        settings["hooks"] = {}
    if "SessionStart" not in settings["hooks"]:
        settings["hooks"]["SessionStart"] = []

    session_hooks = settings["hooks"]["SessionStart"]
    if not isinstance(session_hooks, list):
        session_hooks = []
        settings["hooks"]["SessionStart"] = session_hooks

    # Check both the project path and the global path
    if _find_guardian_in_hooks(session_hooks):
        log_ok("hooks (guardian self-entry)")
        return False

    # Determine which python path to use
    # Prefer project path for project settings, global path for global settings
    # But the command itself must resolve. Use THIS_FILE first, fall back to project path.
    python_path = str(THIS_FILE).replace("\\", "/")
    if not Path(python_path).exists():
        python_path = str(PROJECT_GUARDIAN_PATH).replace("\\", "/")

    session_hooks.append(_guardian_hook_entry(python_path))
    log_recovery("hooks", "added", f"guardian self-entry -> {python_path}")
    return True


# ---------------------------------------------------------------------------
# Guard 4: env keys
# ---------------------------------------------------------------------------

def guard4_env_and_prefs(settings):
    """Restore required env keys and preference defaults from hardcoded values (M3)."""
    changed = False

    # Ensure env section
    if "env" not in settings:
        settings["env"] = {}

    for key, value in REQUIRED_ENV.items():
        if settings["env"].get(key) != value:
            settings["env"][key] = value
            log_recovery("env", "restored", f"{key}={value}")
            changed = True

    for key, value in PREFERENCE_DEFAULTS.items():
        current = settings.get(key)
        if current != value:
            settings[key] = value
            log_recovery("prefs", "restored", f"{key}={json.dumps(value)}")
            changed = True

    if not changed:
        log_ok("env & preferences")

    return changed


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    """Run all 4 guards. Always exits 0 (non-blocking SessionStart hook)."""
    # Accept stdin per Claude Code hook protocol, but work without it (for testing)
    try:
        stdin_data = sys.stdin.read()
        if stdin_data.strip():
            try:
                _ = json.loads(stdin_data)
            except json.JSONDecodeError:
                pass  # stdin present but not valid JSON — ignore and proceed
    except (OSError, EOFError):
        pass  # no stdin available — testing mode

    # Load settings
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except (OSError, json.JSONDecodeError):
        print("- [config_guardian] WARNING: settings.json missing or invalid; starting from empty")
        print(f"- [config_guardian] If guardian hook was lost, run: python {RECOVER_SCRIPT_PATH}")
        settings = {}

    needs_write = False

    # Run guards in order
    if guard1_enabled_plugins(settings):
        needs_write = True

    if guard2_statusline(settings):
        needs_write = True

    if guard3_hooks(settings):
        needs_write = True

    if guard4_env_and_prefs(settings):
        needs_write = True

    if needs_write:
        try:
            atomic_write(SETTINGS_PATH, settings)
            print(f"- [config_guardian] settings.json updated")
        except OSError as e:
            print(f"- [config_guardian] ERROR writing settings.json: {e}")
    else:
        print("- [config_guardian] all guards passed, no changes needed")

    sys.exit(0)


if __name__ == "__main__":
    main()
