"""Config Recover — standalone recovery script (NOT a hook — no stdin needed).

Use when settings.json has been completely wiped and the guardian hook is missing.
Git-tracked at E:/AI_Studio_Workspace/.claude/hooks/recover_config.py

@external-callers: start.bat:17 (error recovery path)
@never-delete: Standalone config recovery tool — essential when settings.json is corrupted

Usage:
    python "E:/AI_Studio_Workspace/.claude/hooks/recover_config.py"
"""

import json
import os
import sys
from pathlib import Path

# Bootstrap: add the hooks directory to path so we can import config_guardian
_HOOKS_DIR = Path(__file__).resolve().parent
if str(_HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(_HOOKS_DIR))

import config_guardian as cg


def main():
    """Recover settings.json from backup or scratch, then run all 4 guards."""
    settings_path = Path.home() / ".claude" / "settings.json"
    good_backup = Path.home() / ".claude" / "settings.json.good_backup"

    print("=" * 60)
    print("Config Recover — standalone recovery")
    print(f"Target: {settings_path}")
    print("=" * 60)

    settings = None

    # Step 1: Check if settings.json exists and is valid JSON
    if settings_path.exists():
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
            print("[OK] settings.json exists and is valid JSON")
        except (OSError, json.JSONDecodeError) as e:
            print(f"[WARN] settings.json exists but is invalid: {e}")
    else:
        print("[WARN] settings.json does not exist")

    # Step 2: If missing/invalid, try good_backup
    if settings is None:
        if good_backup.exists():
            try:
                with open(good_backup, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                print("[OK] Restored from good_backup")
            except (OSError, json.JSONDecodeError) as e:
                print(f"[WARN] good_backup invalid: {e}")

    # Step 3: Start from scratch
    if settings is None or not isinstance(settings, dict):
        print("[WARN] Starting from empty {}")
        settings = {}

    # Step 4: Run all 4 guards
    needs_write = False

    if cg.guard1_enabled_plugins(settings):
        needs_write = True

    if cg.guard2_statusline(settings):
        needs_write = True

    if cg.guard3_hooks(settings):
        needs_write = True

    if cg.guard4_env_and_prefs(settings):
        needs_write = True

    # Step 5: Write recovered settings
    if needs_write:
        try:
            cg.atomic_write(settings_path, settings)
            print(f"[OK] settings.json written ({len(json.dumps(settings))} bytes)")
        except OSError as e:
            print(f"[FAIL] Cannot write settings.json: {e}")
            sys.exit(1)
    else:
        print("[OK] No changes needed")

    # Step 6: Save new good_backup
    try:
        cg.atomic_write(good_backup, settings)
        print(f"[OK] good_backup saved -> {good_backup}")
    except OSError as e:
        print(f"[WARN] Cannot save good_backup: {e}")

    print("=" * 60)
    print("Recovery complete.")
    sys.exit(0)


if __name__ == "__main__":
    main()
