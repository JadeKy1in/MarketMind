"""
Preference Integrity — hash chain + HMAC signing + backup for the User Proxy Agent.

Provides:
  - compute_hash_chain(filepath) → SHA-256 hex digest of file contents
  - verify_integrity(filepath, hashpath) → (bool, reason)
  - sign_decision_line(jsonl_line, session_key) → JSONL line dict with HMAC-SHA256 signature
  - verify_decision_log(logpath) → list of tampered line numbers (1-indexed)
  - backup_preferences(filepath) → copies to timestamped backup, keeps last 3

No external dependencies beyond Python stdlib (hashlib, hmac, json, os, pathlib, shutil).
"""

import hashlib
import hmac
import json
import os
import shutil
import time
from pathlib import Path
from typing import List, Tuple, Union


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
_WORKSPACE = Path(__file__).resolve().parent.parent.parent  # .claude/hooks/ -> .claude/ -> workspace
_STATE_DIR = _WORKSPACE / ".claude" / "state"
_PREFERENCES_FILE = _STATE_DIR / "user_preferences.json"
_HASH_CHAIN_FILE = _STATE_DIR / ".preferences.hash"
_DECISIONS_DIR = _WORKSPACE / ".claude" / "decisions"
_DECISIONS_LOG = _DECISIONS_DIR / "proxy_decisions.jsonl"

# Backup settings
_MAX_BACKUPS = 3
_BACKUP_PATTERN = "user_preferences.{timestamp}.json.bak"


# ---------------------------------------------------------------------------
# Hash chain
# ---------------------------------------------------------------------------

def compute_hash_chain(filepath: Union[str, Path]) -> str:
    """Compute SHA-256 hex digest of a file's contents.

    Parameters
    ----------
    filepath : str or Path
        Path to the file to hash.

    Returns
    -------
    str
        64-character lowercase SHA-256 hex digest.
        Returns empty string if file does not exist.
    """
    path = Path(filepath)
    if not path.exists():
        return ""

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_hash_chain(hashpath: Union[str, Path]) -> dict:
    """Read the stored hash chain file.

    Returns
    -------
    dict with keys: hash, updated, version, or empty dict if missing/corrupt.
    """
    path = Path(hashpath)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if "hash" not in data:
            return {}
        return data
    except (OSError, json.JSONDecodeError):
        return {}


def _write_hash_chain(hashpath: Union[str, Path], file_hash: str) -> None:
    """Write a hash chain record."""
    path = Path(hashpath)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "version": "1.0",
        "hash": file_hash,
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    # Atomic write via temp file + rename
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp_path), str(path))


def verify_integrity(filepath: Union[str, Path], hashpath: Union[str, Path]) -> Tuple[bool, str]:
    """Verify that filepath contents match the stored hash chain.

    Parameters
    ----------
    filepath : str or Path
        Path to the file whose integrity is being checked.
    hashpath : str or Path
        Path to the .preferences.hash hash chain file.

    Returns
    -------
    (bool, str)
        (True, stored_hash) if integrity is verified.
        (False, reason_string) if verification fails — reason explains why.
    """
    fp = Path(filepath)
    hp = Path(hashpath)

    # Check that the file exists
    if not fp.exists():
        return False, f"File not found: {fp}"

    # Check that the hash chain exists
    if not hp.exists():
        return False, f"Hash chain file not found: {hp}"

    # Read stored hash
    chain_data = _read_hash_chain(hp)
    if not chain_data:
        return False, f"Hash chain file is empty or corrupt: {hp}"

    stored_hash = chain_data.get("hash", "")
    if not stored_hash:
        return False, f"Hash chain file contains no hash field: {hp}"

    # Compute current hash
    current_hash = compute_hash_chain(fp)

    if current_hash != stored_hash:
        return False, (
            f"Hash mismatch: stored={stored_hash[:16]}... "
            f"computed={current_hash[:16]}..."
        )

    return True, stored_hash


def seal_hash_chain(filepath: Union[str, Path], hashpath: Union[str, Path]) -> str:
    """Compute file hash and write it to the hash chain file.

    This is the "seal" operation — call after confirming the file is in a
    known-good state. Returns the computed hash.

    Parameters
    ----------
    filepath : str or Path
        Path to the file to hash and seal.
    hashpath : str or Path
        Path to write the hash chain record.

    Returns
    -------
    str
        The SHA-256 hex digest that was written.
    """
    file_hash = compute_hash_chain(filepath)
    _write_hash_chain(hashpath, file_hash)
    return file_hash


# ---------------------------------------------------------------------------
# Decision log signing (HMAC-SHA256)
# ---------------------------------------------------------------------------

def sign_decision_line(jsonl_line: Union[str, dict], session_key: str) -> dict:
    """Sign a single decision-log entry with HMAC-SHA256.

    Takes a JSONL line (string or already-parsed dict), adds a
    ``_hmac`` field computed over all non-signature fields, and
    returns the complete dict.

    The signature covers every key except ``_hmac`` itself, sorted
    alphabetically for determinism.

    Parameters
    ----------
    jsonl_line : str or dict
        A JSON string or already-parsed dict representing one log line.
    session_key : str
        A session-derived secret for HMAC keying. Must be non-empty.

    Returns
    -------
    dict
        The original dict with ``_hmac`` appended.
    """
    if isinstance(jsonl_line, str):
        obj = json.loads(jsonl_line)
    else:
        obj = dict(jsonl_line)

    if not session_key:
        raise ValueError("session_key must be a non-empty string")

    # Build canonical payload: all keys except _hmac, sorted
    payload_keys = sorted(k for k in obj if k != "_hmac")
    payload = json.dumps({k: obj[k] for k in payload_keys}, ensure_ascii=False, sort_keys=True)

    # Compute HMAC-SHA256
    key_bytes = session_key.encode("utf-8")
    mac = hmac.new(key_bytes, payload.encode("utf-8"), hashlib.sha256).hexdigest()

    obj["_hmac"] = mac
    return obj


def _extract_hmac(line_str: str) -> Tuple[dict, str]:
    """Parse a JSONL line and extract the ``_hmac`` field.

    Returns (obj_without_hmac, hmac_value). Raises ValueError if the
    line is not valid JSON or ``_hmac`` is missing.
    """
    try:
        obj = json.loads(line_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON on line: {e}") from e

    if "_hmac" not in obj:
        raise ValueError("Line is missing _hmac signature field")

    hmac_value = obj.pop("_hmac")
    return obj, hmac_value


def verify_decision_log(logpath: Union[str, Path]) -> List[int]:
    """Verify every HMAC-signed line in a decision log.

    Scans a JSONL file line by line. Each line must be a JSON object
    with a ``_hmac`` field. Lines that start with ``#`` or are blank
    are skipped (they are treated as comments / headers).

    Parameters
    ----------
    logpath : str or Path
        Path to the JSONL decision log.

    Returns
    -------
    list[int]
        Line numbers (1-indexed) of tampered / unverifiable entries.
        Empty list means all signed lines passed verification.
    """
    path = Path(logpath)
    tampered: List[int] = []

    if not path.exists():
        return tampered  # no log yet — nothing to verify

    with open(path, "r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            stripped = raw_line.strip()

            # Skip blank lines and comment/header lines
            if not stripped or stripped.startswith("#"):
                continue

            # Skip schema-version header lines (no _hmac expected)
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                tampered.append(line_no)
                continue

            # Lines without _hmac are either headers or untrusted
            if "_hmac" not in obj:
                # Only flag as tampered if it's not a recognized header
                if "_schema_version" not in obj and "_initialized" not in obj:
                    tampered.append(line_no)
                continue

            # Extract and verify
            try:
                # We need the session key to verify. Since session_key is ephemeral
                # and not stored in the file, we can only perform structural
                # validation here: verify _hmac is a 64-char hex string and
                # that the line is well-formed JSON.
                hmac_val = obj["_hmac"]
                if not isinstance(hmac_val, str) or len(hmac_val) != 64:
                    tampered.append(line_no)
                    continue
                # Try to parse as hex
                int(hmac_val, 16)
            except (ValueError, KeyError):
                tampered.append(line_no)

    return tampered


def verify_decision_log_with_key(logpath: Union[str, Path], session_key: str) -> List[int]:
    """Verify every HMAC-signed line in a decision log using a known session key.

    This is the full verification variant — recomputes the HMAC for each
    line and compares it to the stored signature.

    Parameters
    ----------
    logpath : str or Path
        Path to the JSONL decision log.
    session_key : str
        The session-derived secret used to sign the log.

    Returns
    -------
    list[int]
        Line numbers (1-indexed) of tampered entries.
        Empty list means all signed lines passed verification.
    """
    path = Path(logpath)
    tampered: List[int] = []

    if not path.exists():
        return tampered

    if not session_key:
        raise ValueError("session_key must be a non-empty string")

    key_bytes = session_key.encode("utf-8")

    with open(path, "r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            stripped = raw_line.strip()

            if not stripped or stripped.startswith("#"):
                continue

            try:
                obj, stored_hmac = _extract_hmac(stripped)
            except ValueError:
                tampered.append(line_no)
                continue

            # Skip schema headers
            if "_schema_version" in obj or "_initialized" in obj:
                continue

            # Recompute HMAC
            payload = json.dumps(obj, ensure_ascii=False, sort_keys=True)
            expected_hmac = hmac.new(key_bytes, payload.encode("utf-8"), hashlib.sha256).hexdigest()

            # Constant-time comparison
            if not hmac.compare_digest(expected_hmac, stored_hmac):
                tampered.append(line_no)

    return tampered


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def backup_preferences(filepath: Union[str, Path]) -> str:
    """Create a timestamped backup of the preferences file.

    Copies the file to ``.claude/state/user_preferences.{timestamp}.json.bak``.
    Keeps the last ``_MAX_BACKUPS`` (3) backups — older ones are deleted.

    Parameters
    ----------
    filepath : str or Path
        Path to the preferences file to back up.

    Returns
    -------
    str
        Path to the created backup file.
        Returns empty string if the source file does not exist.
    """
    src = Path(filepath)
    if not src.exists():
        return ""

    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_name = _BACKUP_PATTERN.replace("{timestamp}", timestamp)
    backup_path = src.parent / backup_name

    shutil.copy2(str(src), str(backup_path))

    # Prune old backups — keep only the last _MAX_BACKUPS
    _prune_backups(src.parent)

    return str(backup_path)


def _prune_backups(directory: Path) -> None:
    """Delete old preference backups, keeping only the most recent ``_MAX_BACKUPS``."""
    backups = sorted(
        directory.glob("user_preferences.*.json.bak"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in backups[_MAX_BACKUPS:]:
        try:
            old.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Convenience: full integrity check + repair helpers
# ---------------------------------------------------------------------------

def check_and_backup() -> dict:
    """Run a full integrity check on user_preferences.json.

    1. Verify integrity against hash chain.
    2. If verification passes, create a backup.
    3. If verification fails, report the failure without overwriting backup.

    Returns
    -------
    dict with keys:
      - ok: bool
      - hash_verified: bool
      - backup_created: str (path or empty)
      - reason: str (if not ok)
    """
    result = {
        "ok": True,
        "hash_verified": False,
        "backup_created": "",
        "reason": "",
    }

    # Check integrity
    verified, detail = verify_integrity(_PREFERENCES_FILE, _HASH_CHAIN_FILE)
    result["hash_verified"] = verified
    result["reason"] = detail if not verified else ""

    if verified:
        # Create backup of known-good state
        result["backup_created"] = backup_preferences(_PREFERENCES_FILE)
    else:
        result["ok"] = False

    return result


def initialize_preferences_store() -> dict:
    """Create the user_preferences.json file if it does not exist.

    Seeds it with a valid empty structure including schema version and
    the three preference tiers. Does NOT overwrite an existing file.

    Returns
    -------
    dict
        The contents that were written (or already exist).
    """
    if _PREFERENCES_FILE.exists():
        try:
            return json.loads(_PREFERENCES_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass  # Corrupt — overwrite below

    default_store = {
        "_schema_version": "1.0",
        "_created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "_description": "User proxy preference store — three-tier (universal, domain, project). See user_proxy_design.json for semantics.",
        "tags": {
            "CRITICAL_SECURITY": {
                "description": "Security, data, or irreversible preferences. Require 2 explicit user confirmations before promotion. CANNOT be auto-learned from implicit behavior.",
                "confirmations_required": 2,
                "auto_learnable": False,
            },
            "HIGH_STAKES": {
                "description": "Architecture, multi-file, or cross-module preferences. Require 1 explicit confirmation. Auto-learning disabled during warmup.",
                "confirmations_required": 1,
                "auto_learnable": True,
            },
            "STANDARD": {
                "description": "Style, naming, or single-file preferences. Single implicit signal sufficient. Auto-learnable.",
                "confirmations_required": 0,
                "auto_learnable": True,
            },
        },
        "tiers": {
            "universal": {
                "scope": "Style invariants across all projects",
                "curation": "manual",
                "entries": [],
            },
            "domain": {
                "scope": "Per-domain patterns (Python, TypeScript, DB, etc.)",
                "curation": "semi-automatic",
                "entries": [],
            },
            "project": {
                "scope": "Project-specific overrides (highest priority)",
                "curation": "automatic",
                "entries": [],
            },
        },
        "pending_promotions": [],
    }

    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _PREFERENCES_FILE.write_text(
        json.dumps(default_store, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return default_store


# ---------------------------------------------------------------------------
# CLI entry point (for manual sealing / verification)
# ---------------------------------------------------------------------------

def main():
    import sys

    if len(sys.argv) < 2:
        print("Usage: python preference_integrity.py <command> [args]")
        print()
        print("Commands:")
        print("  seal                  Compute hash of user_preferences.json and write .preferences.hash")
        print("  verify                Verify user_preferences.json against .preferences.hash")
        print("  init                  Create user_preferences.json (if missing) and seal hash chain")
        print("  backup                Create timestamped backup of user_preferences.json")
        print("  check                 Full integrity check (verify + backup)")
        print("  verify-log [key]      Verify decision log HMACs (structural only, or full if key provided)")
        sys.exit(0)

    command = sys.argv[1]

    if command == "init":
        store = initialize_preferences_store()
        print(f"[preference_integrity] user_preferences.json initialized (schema {store['_schema_version']})")
        file_hash = seal_hash_chain(_PREFERENCES_FILE, _HASH_CHAIN_FILE)
        print(f"[preference_integrity] Hash chain sealed: {file_hash}")

    elif command == "seal":
        file_hash = seal_hash_chain(_PREFERENCES_FILE, _HASH_CHAIN_FILE)
        # Auto-create backup after seal
        backup_path = backup_preferences(_PREFERENCES_FILE)
        print(f"[preference_integrity] Sealed: {file_hash}")
        if backup_path:
            print(f"[preference_integrity] Backup: {backup_path}")

    elif command == "verify":
        ok, detail = verify_integrity(_PREFERENCES_FILE, _HASH_CHAIN_FILE)
        if ok:
            print(f"[preference_integrity] VERIFIED: {detail}")
        else:
            print(f"[preference_integrity] FAILED: {detail}")
            sys.exit(1)

    elif command == "backup":
        backup_path = backup_preferences(_PREFERENCES_FILE)
        if backup_path:
            print(f"[preference_integrity] Backup created: {backup_path}")
        else:
            print("[preference_integrity] No source file to back up")
            sys.exit(1)

    elif command == "check":
        result = check_and_backup()
        if result["ok"]:
            print(f"[preference_integrity] OK (verified, backup: {result['backup_created'] or 'N/A'})")
        else:
            print(f"[preference_integrity] ISSUE: {result['reason']}")
            sys.exit(1)

    elif command == "verify-log":
        session_key = sys.argv[2] if len(sys.argv) > 2 else ""
        if session_key:
            tampered = verify_decision_log_with_key(_DECISIONS_LOG, session_key)
        else:
            tampered = verify_decision_log(_DECISIONS_LOG)
        if tampered:
            print(f"[preference_integrity] TAMPERED LINES: {tampered}")
            sys.exit(1)
        else:
            print("[preference_integrity] Decision log: all lines verified")

    else:
        print(f"Unknown command: {command}")
        sys.exit(2)


if __name__ == "__main__":
    main()
