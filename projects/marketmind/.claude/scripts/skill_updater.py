"""Skill/Plugin Update Checker with Sandbox Review.

Checks installed plugins for available updates, downloads updates to sandbox,
scans for malicious patterns, and on approval installs and regenerates integrity manifest.

Usage:
  python skill_updater.py --check          # Check for updates only
  python skill_updater.py --update-all     # Download all updates to sandbox, scan, prompt
  python skill_updater.py --update <name>  # Update specific plugin
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path("E:/AI_Studio_Workspace")
SANDBOX_INCOMING = WORKSPACE / ".claude" / "sandbox" / "incoming"
BACKUPS_HOOKS = WORKSPACE / ".claude" / "backups" / "hooks"
INSTALLED_PLUGINS_PATH = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
PLUGINS_CACHE = Path.home() / ".claude" / "plugins" / "cache"

# Malicious patterns to scan for in downloaded files
MALICIOUS_PATTERNS = [
    (r'\beval\s*\(', "eval() call"),
    (r'\bexec\s*\(', "exec() call"),
    (r'\bcompile\s*\(', "compile() with dynamic input"),
    (r'\b__import__\s*\(', "__import__() with dynamic module"),
    (r'\bsubprocess\b', "subprocess call"),
    (r'\bos\.system\b', "os.system() call"),
    (r'\bos\.popen\b', "os.popen() call"),
    (r'\bbase64\.b64decode\b', "base64 decode (obfuscation)"),
    (r'\bzlib\.decompress\b', "zlib decompress (obfuscation)"),
    (r'\bcodecs\.decode\b', "codecs.decode (obfuscation)"),
    (r'\bsocket\.', "socket connection"),
    (r'\brequests\.(get|post|put|delete|patch)\b', "HTTP request"),
    (r'\bhttpx\.(get|post|put|delete)\b', "HTTPX request"),
    (r'\burllib\.', "urllib call"),
    (r'~/.ssh', "SSH key path access"),
    (r'~/.aws', "AWS credential path access"),
    (r'\.env\b', ".env file access"),
    (r'/etc/(passwd|shadow|hosts)', "System file access"),
    (r'rm\s+-rf\s+/', "Recursive delete root"),
    (r'>\s*/dev/[hs]d[a-z]', "Raw disk write"),
]

SKIP_PATTERNS = [
    r'\.git/',
    r'__pycache__/',
    r'\.pyc$',
    r'node_modules/',
    r'\.test\.',
    r'test_',
    r'tests/',
]


def log(msg):
    print(f"  {msg}")


def get_installed_plugins():
    """Read installed_plugins.json."""
    if not INSTALLED_PLUGINS_PATH.exists():
        return {}
    try:
        with open(INSTALLED_PLUGINS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "plugins" in data:
            return data["plugins"]
        if isinstance(data, list):
            return {p.get("name", f"unknown-{i}"): p for i, p in enumerate(data)}
        return data
    except (OSError, json.JSONDecodeError) as e:
        log(f"ERROR reading installed_plugins.json: {e}")
        return {}


def get_cached_versions():
    """Check cached plugin versions."""
    versions = {}
    if not PLUGINS_CACHE.exists():
        return versions
    for marketplace in PLUGINS_CACHE.iterdir():
        if marketplace.is_dir():
            for plugin in marketplace.iterdir():
                if plugin.is_dir():
                    plugin_json = plugin / ".claude-plugin" / "plugin.json"
                    if not plugin_json.exists():
                        plugin_json = plugin / "package.json"
                    if plugin_json.exists():
                        try:
                            with open(plugin_json, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            name = data.get("name", plugin.name)
                            ver = data.get("version", "0.0.0")
                            versions[name] = {"version": ver, "path": str(plugin)}
                        except (OSError, json.JSONDecodeError):
                            pass
    return versions


def check_npm_updates(plugin_name):
    """Check if a plugin has a newer version on npm.
    Plugin names are like 'superpowers@claude-plugins-official'.
    The npm package is the first part before '@'.
    """
    npm_name = plugin_name.split("@")[0]
    try:
        result = subprocess.run(
            ["npm", "view", npm_name, "version", "--json"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return result.stdout.strip().strip('"')
    except Exception:
        pass

    # Try full name as scoped package
    try:
        scoped = f"@{plugin_name.replace('@', '/')}"
        result = subprocess.run(
            ["npm", "view", scoped, "version", "--json"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return result.stdout.strip().strip('"')
    except Exception:
        pass

    return None


def check_for_updates():
    """Compare installed vs latest versions."""
    installed = get_installed_plugins()
    cached = get_cached_versions()

    updates = []
    for name, info in installed.items():
        current_ver = info.get("version", "0.0.0") if isinstance(info, dict) else "0.0.0"
        npm_ver = check_npm_updates(name)
        if npm_ver and npm_ver != current_ver:
            updates.append({
                "name": name,
                "current": current_ver,
                "latest": npm_ver,
            })

    return updates


def scan_file(filepath):
    """Scan a file for malicious patterns. Returns list of findings."""
    findings = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return [("UNREADABLE", "Cannot read file")]

    for pattern, description in MALICIOUS_PATTERNS:
        matches = re.findall(pattern, content, re.IGNORECASE)
        if matches:
            findings.append((description, f"{len(matches)} matches"))

    return findings


def scan_directory(dirpath):
    """Recursively scan a directory for malicious patterns."""
    all_findings = {}
    for root, dirs, files in os.walk(dirpath):
        # Skip ignored patterns
        dirs[:] = [d for d in dirs if not any(re.search(p, d) for p in SKIP_PATTERNS)]
        for f in files:
            if any(re.search(p, f) for p in SKIP_PATTERNS):
                continue
            filepath = os.path.join(root, f)
            if not os.path.isfile(filepath):
                continue
            # Only scan code files
            if not any(f.endswith(ext) for ext in (".py", ".js", ".ts", ".sh", ".json", ".yaml", ".yml", ".md")):
                continue
            findings = scan_file(filepath)
            if findings:
                rel_path = os.path.relpath(filepath, dirpath)
                all_findings[rel_path] = findings

    return all_findings


def download_to_sandbox(plugin_name, version):
    """Download plugin to sandbox incoming directory."""
    sandbox_dir = SANDBOX_INCOMING / f"{plugin_name}-{version}"
    if sandbox_dir.exists():
        shutil.rmtree(str(sandbox_dir))
    sandbox_dir.mkdir(parents=True, exist_ok=True)

    npm_name = plugin_name.split("@")[0]
    try:
        # Use npm pack to download
        result = subprocess.run(
            ["npm", "pack", f"{npm_name}@{version}", "--pack-destination", str(sandbox_dir)],
            capture_output=True, text=True, timeout=30,
            cwd=str(sandbox_dir)
        )
        if result.returncode != 0:
            log(f"npm pack failed for {npm_name}: {result.stderr[:200]}")
            return None

        # Extract the .tgz
        tgz_files = list(sandbox_dir.glob("*.tgz"))
        if tgz_files:
            import tarfile
            with tarfile.open(tgz_files[0]) as tar:
                tar.extractall(path=str(sandbox_dir))
            tgz_files[0].unlink()
            log(f"Downloaded {plugin_name} v{version} to sandbox")
            return str(sandbox_dir)
    except Exception as e:
        log(f"Download failed: {e}")
        return None

    return None


def show_diff_summary(old_dir, new_dir):
    """Show a diff summary between old and new versions."""
    if not old_dir or not os.path.exists(old_dir):
        return "No previous version to compare"

    # Simple file count comparison
    old_files = set()
    for root, _, files in os.walk(old_dir):
        for f in files:
            old_files.add(os.path.relpath(os.path.join(root, f), old_dir))

    new_files = set()
    for root, _, files in os.walk(new_dir):
        for f in files:
            new_files.add(os.path.relpath(os.path.join(root, f), new_dir))

    added = new_files - old_files
    removed = old_files - new_files
    changed = []
    for f in old_files & new_files:
        try:
            old_hash = hashlib.sha256(open(os.path.join(old_dir, f), "rb").read()).hexdigest()
            new_hash = hashlib.sha256(open(os.path.join(new_dir, f), "rb").read()).hexdigest()
            if old_hash != new_hash:
                changed.append(f)
        except Exception:
            changed.append(f)

    lines = []
    if added:
        lines.append(f"  +{len(added)} new files")
    if removed:
        lines.append(f"  -{len(removed)} removed files")
    if changed:
        lines.append(f"  ~{len(changed)} changed files")
    return "\n".join(lines) if lines else "  No changes detected"


def regenerate_manifest():
    """Regenerate the hook manifest after plugin update."""
    hooks_dir = WORKSPACE / ".claude" / "hooks"
    manifest_path = BACKUPS_HOOKS / "hook_manifest.json"

    hashes = {}
    for f in sorted(hooks_dir.glob("*.py")):
        h = hashlib.sha256()
        with open(f, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        hashes[f.name] = h.hexdigest()

    manifest = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hooks": hashes,
    }
    BACKUPS_HOOKS.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    log(f"Manifest regenerated: {len(hashes)} hooks")


def cmd_check():
    """Check for available updates."""
    print("Checking for plugin updates...")
    updates = check_for_updates()

    if not updates:
        print("All plugins up to date.")
        return

    print(f"\n{len(updates)} update(s) available:\n")
    for u in updates:
        print(f"  {u['name']}: {u['current']} → {u['latest']}")
    print("\nRun with --update-all to download and scan updates in sandbox.")


def cmd_update_all():
    """Download all updates to sandbox, scan, and prompt for approval."""
    updates = check_for_updates()
    if not updates:
        print("All plugins up to date.")
        return

    print(f"{len(updates)} update(s) to process.\n")

    for u in updates:
        print(f"\n{'='*50}")
        print(f"Plugin: {u['name']}")
        print(f"Version: {u['current']} → {u['latest']}")
        print(f"{'='*50}")

        # Step 1: Download to sandbox
        print("\n[1/4] Downloading to sandbox...")
        sandbox_dir = download_to_sandbox(u["name"], u["latest"])
        if not sandbox_dir:
            print("  FAILED: Could not download. Skipping.")
            continue

        # Step 2: Scan
        print("\n[2/4] Scanning for malicious patterns...")
        findings = scan_directory(sandbox_dir)
        if findings:
            print(f"  WARNING: {len(findings)} file(s) with suspicious patterns:")
            for fpath, issues in list(findings.items())[:10]:
                print(f"    {fpath}:")
                for desc, count in issues[:3]:
                    print(f"      - {desc} ({count})")
            if len(findings) > 10:
                print(f"    ... and {len(findings) - 10} more files")
            print("\n  Review required before installation.")
        else:
            print("  Clean: No malicious patterns detected.")

        # Step 3: Diff
        print("\n[3/4] Comparing with installed version...")
        cached = get_cached_versions()
        old_dir = None
        for name, info in cached.items():
            if u["name"] in name or name in u["name"]:
                old_dir = info.get("path")
                break
        diff = show_diff_summary(old_dir, sandbox_dir)
        print(diff)

        # Step 4: Approval
        print("\n[4/4] Ready to install.")
        response = input(f"  Install {u['name']} v{u['latest']}? [y/N]: ").strip().lower()
        if response == "y":
            # Install: copy from sandbox to cache
            if old_dir:
                # Backup old version
                backup_dir = Path(old_dir).parent / f"{Path(old_dir).name}.bak.{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
                shutil.move(old_dir, str(backup_dir))
                log(f"  Backed up old version to {backup_dir.name}")

            # Copy new version to cache
            plugin_name_simple = u["name"].split("@")[0]
            target_parent = Path(old_dir).parent if old_dir else PLUGINS_CACHE
            target = target_parent / plugin_name_simple
            if target.exists():
                shutil.rmtree(str(target))
            shutil.copytree(sandbox_dir, str(target))
            log(f"  Installed {u['name']} v{u['latest']}")

            # Update installed_plugins.json
            update_installed_plugins(u["name"], u["latest"])
        else:
            print("  Skipped.")

    # Final: regenerate manifest
    print("\nRegenerating integrity manifest...")
    regenerate_manifest()
    print("Done.")


def update_installed_plugins(name, version):
    """Update the version in installed_plugins.json."""
    try:
        with open(INSTALLED_PLUGINS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict) and "plugins" in data:
            if name in data["plugins"]:
                data["plugins"][name]["version"] = version
        elif isinstance(data, list):
            for p in data:
                if p.get("name") == name:
                    p["version"] = version

        # Atomic write
        tmpfd, tmpname = tempfile.mkstemp(dir=str(INSTALLED_PLUGINS_PATH.parent), suffix=".tmp")
        with os.fdopen(tmpfd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmpname, str(INSTALLED_PLUGINS_PATH))
    except Exception as e:
        log(f"WARNING: Could not update installed_plugins.json: {e}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "--check":
        cmd_check()
    elif cmd == "--update-all":
        cmd_update_all()
    elif cmd == "--update" and len(sys.argv) > 2:
        # Single plugin update — same flow but scoped
        print("Single plugin update not yet implemented. Use --update-all.")
        sys.exit(1)
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
