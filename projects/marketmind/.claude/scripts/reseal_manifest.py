"""Reseal the hook integrity manifest with current file hashes.

Run after intentionally modifying any hook script.
Usage: python scripts/reseal_manifest.py
"""

import hashlib
import json
import shutil
import os
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path("E:/AI_Studio_Workspace")
HOOKS_DIR = WORKSPACE / ".claude" / "hooks"
BACKUPS_DIR = WORKSPACE / ".claude" / "backups" / "hooks"
MANIFEST_PATH = BACKUPS_DIR / "hook_manifest.json"
GLOBAL_HOOKS = Path.home() / ".claude" / "hooks"


def main():
    # 1. Compute hashes
    hashes = {}
    for f in sorted(HOOKS_DIR.glob("*.py")):
        h = hashlib.sha256()
        with open(f, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        hashes[f.name] = h.hexdigest()

    # 2. Update backups
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    for f in HOOKS_DIR.glob("*.py"):
        shutil.copy2(str(f), str(BACKUPS_DIR / f.name))

    # 3. Sync to global
    GLOBAL_HOOKS.mkdir(parents=True, exist_ok=True)
    for f in HOOKS_DIR.glob("*.py"):
        shutil.copy2(str(f), str(GLOBAL_HOOKS / f.name))

    # 4. Write manifest
    manifest = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hooks": hashes,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

    print(f"Manifest resealed: {len(hashes)} hooks")
    print(f"Backups updated: {BACKUPS_DIR}")
    print(f"Global sync: {GLOBAL_HOOKS}")


if __name__ == "__main__":
    main()
