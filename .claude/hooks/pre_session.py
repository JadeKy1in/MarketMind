"""Pre-Session Validator — run BEFORE launching Claude Code.

Validates settings.json integrity, plugin installation state, and sandbox queue.
This must run BEFORE the Claude Code process starts because SessionStart hooks
fire too late — the skill scanner has already completed by then.

Usage (manual or via launch script):
    python "E:/AI_Studio_Workspace/.claude/hooks/pre_session.py"

Exit codes:
    0 = all good, launch Claude Code
    1 = errors found, fix before launching
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
GOOD_BACKUP = Path.home() / ".claude" / "settings.json.good_backup"
INSTALLED_PLUGINS_PATH = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
PLUGINS_CACHE = Path.home() / ".claude" / "plugins" / "cache"
WORKSPACE = Path("E:/AI_Studio_Workspace")
SANDBOX_INCOMING = WORKSPACE / ".claude" / "sandbox" / "incoming"


def log(msg: str, level: str = "INFO") -> None:
    tag = {"INFO": "OK", "WARN": "WARN", "FAIL": "FAIL"}.get(level, "?")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None
    print(f"  [{tag}] {msg}")


# ── 1. Settings.json integrity ───────────────────────────────────────────────

def validate_settings() -> dict | None:
    """Load and validate settings.json. Return dict or None if unrecoverable."""
    settings = None

    if SETTINGS_PATH.exists():
        try:
            settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            log("settings.json exists and is valid JSON", "INFO")
        except (OSError, json.JSONDecodeError) as e:
            log(f"settings.json corrupted: {e}", "FAIL")

    if settings is None and GOOD_BACKUP.exists():
        try:
            settings = json.loads(GOOD_BACKUP.read_text(encoding="utf-8"))
            log("Restored from good_backup", "WARN")
        except (OSError, json.JSONDecodeError):
            pass

    if settings is None:
        log("No valid settings.json or backup — starting from scratch", "FAIL")
        settings = {}

    return settings


# ── 2. Plugin sync ───────────────────────────────────────────────────────────

def sync_plugins(settings: dict) -> bool:
    """Sync enabledPlugins from installed_plugins.json. Returns True if changed."""
    if "enabledPlugins" not in settings:
        settings["enabledPlugins"] = {}

    if not INSTALLED_PLUGINS_PATH.exists():
        log("No installed_plugins.json — cannot sync", "WARN")
        return False

    try:
        installed = json.loads(INSTALLED_PLUGINS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log("installed_plugins.json corrupted", "FAIL")
        return False

    changed = False
    for plugin_id in installed.get("plugins", {}):
        if not settings["enabledPlugins"].get(plugin_id):
            settings["enabledPlugins"][plugin_id] = True
            log(f"Enabled: {plugin_id}", "INFO")
            changed = True

    return changed


# ── 3. Plugin file verification ─────────────────────────────────────────────

def verify_plugin_files(settings: dict) -> list[str]:
    """Verify all enabled plugins have their files on disk.

    Skills-type plugins must have cache/<marketplace>/<plugin>/<version>/skills/ with content.
    Non-skills plugins (e.g., claude-hud) are verified by plugin.json presence.
    """
    # Plugins that are NOT skills and don't need a skills/ directory
    NON_SKILLS_PLUGINS = {"claude-hud@claude-hud"}

    missing = []
    if not PLUGINS_CACHE.exists():
        return missing

    for plugin_id, enabled in settings.get("enabledPlugins", {}).items():
        if not enabled:
            continue
        parts = plugin_id.split("@")
        if len(parts) != 2:
            continue
        plugin_name, marketplace = parts[0], parts[1]
        marketplace_dir = PLUGINS_CACHE / marketplace
        if not marketplace_dir.exists():
            missing.append(plugin_id)
            log(f"Plugin marketplace missing: {marketplace_dir}", "FAIL")
            continue

        # Non-skills plugins: just check plugin.json exists
        if plugin_id in NON_SKILLS_PLUGINS:
            found_any = False
            for plugin_dir in marketplace_dir.iterdir():
                if plugin_dir.name.startswith(plugin_name):
                    for version_dir in plugin_dir.iterdir():
                        if (version_dir / ".claude-plugin" / "plugin.json").exists():
                            found_any = True
                            break
            if not found_any:
                missing.append(plugin_id)
                log(f"Plugin descriptor missing for: {plugin_id}", "FAIL")
            continue

        # Skills plugins: must have skills/ directory with content
        found = False
        for plugin_dir in marketplace_dir.iterdir():
            if not plugin_dir.name.startswith(plugin_name):
                continue
            for version_dir in plugin_dir.iterdir():
                if not version_dir.is_dir():
                    continue
                skills_dir = version_dir / "skills"
                if skills_dir.exists() and any(skills_dir.iterdir()):
                    found = True
                    break
            if found:
                break
        if not found:
            missing.append(plugin_id)
            log(f"Skill files missing for: {plugin_id}", "FAIL")

    return missing


# ── 4. Sandbox incoming check ────────────────────────────────────────────────

def check_sandbox() -> list[Path]:
    """Check for unprocessed files in sandbox incoming. Returns list of pending."""
    if not SANDBOX_INCOMING.exists():
        return []
    pending = list(SANDBOX_INCOMING.iterdir())
    if pending:
        log(f"{len(pending)} file(s) in sandbox incoming — needs review before install", "WARN")
        for p in pending:
            print(f"      {p.relative_to(SANDBOX_INCOMING)}")
    return pending


# ── 5. Save and backup ───────────────────────────────────────────────────────

def atomic_write(path: Path, data: dict) -> None:
    """Write JSON atomically: temp file → rename."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def save_settings(settings: dict) -> None:
    """Save settings.json and good_backup."""
    atomic_write(SETTINGS_PATH, settings)
    atomic_write(GOOD_BACKUP, settings)
    log("settings.json + good_backup saved", "INFO")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 60)
    print("Pre-Session Validator")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    errors = 0

    # 1. Validate settings
    settings = validate_settings()
    if settings is None:
        print("\nFATAL: Cannot recover settings. Run recover_config.py first.")
        return 1

    # 2. Sync plugins
    if sync_plugins(settings):
        errors += 0  # just a sync, not an error

    # 3. Verify plugin files
    missing = verify_plugin_files(settings)
    if missing:
        errors += 1
        print(f"\n  {len(missing)} plugin(s) have files missing. Re-install them.")

    # 4. Sandbox check
    pending = check_sandbox()
    if pending:
        print("\n  Review sandbox/incoming/ before installing.")

    # 5. Save
    save_settings(settings)

    # 6. Summary
    print("=" * 60)
    plugins_count = sum(1 for v in settings.get("enabledPlugins", {}).values() if v)
    print(f"Plugins enabled: {plugins_count}")
    print(f"Plugin files OK: {plugins_count - len(missing)}/{plugins_count}")
    print(f"Sandbox pending: {len(pending)}")
    print(f"Errors: {errors}")

    if errors > 0:
        print("\nFix errors above before launching Claude Code.")
        return 1
    else:
        print("\nReady to launch Claude Code.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
