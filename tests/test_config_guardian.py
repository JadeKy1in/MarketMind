"""PICA-Unit tests for config_guardian.py — 6 tests covering all 4 guards + atomic write.

Each test has explicit Given/When/Then scenario descriptions.
Uses tmp_path fixtures — never modifies real settings files.
"""

import json
import os
import sys
from pathlib import Path

import pytest

# Ensure the hooks directory is in the import path
HOOKS_DIR = Path(__file__).resolve().parent.parent / ".claude" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import config_guardian as cg


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def base_settings():
    """Minimal valid settings dict — no plugins, no statusLine, no hooks, no env."""
    return {}


@pytest.fixture
def settings_with_session_start():
    """Settings that already have a hooks.SessionStart key (empty list)."""
    return {"hooks": {"SessionStart": []}}


# ---------------------------------------------------------------------------
# Test 1: Guard 1 — enabledPlugins missing, installed_plugins.json exists
# ---------------------------------------------------------------------------

def test_guard1_enabled_plugins_missing(tmp_path, monkeypatch):
    """Given settings.json has no enabledPlugins key and installed_plugins.json has 5 plugins
    When guard1 runs
    Then enabledPlugins is created with all 5 plugin IDs.
    """
    # Given: installed_plugins.json with 5 plugins
    ip_dir = tmp_path / "plugins"
    ip_dir.mkdir(parents=True)
    ip_path = ip_dir / "installed_plugins.json"
    ip_data = {
        "version": 2,
        "plugins": {
            "superpowers@claude-plugins-official": [],
            "claude-hud@claude-hud": [],
            "skill-creator@claude-plugins-official": [],
            "andrej-karpathy-skills@karpathy-skills": [],
            "mattpocock-skills@mattpocock-skills": [],
        },
    }
    ip_path.write_text(json.dumps(ip_data))

    monkeypatch.setattr(cg, "INSTALLED_PLUGINS_PATH", ip_path)

    settings = {}

    # When
    changed = cg.guard1_enabled_plugins(settings)

    # Then
    assert changed is True
    assert "enabledPlugins" in settings
    eps = settings["enabledPlugins"]
    assert len(eps) == 5
    for pid in ip_data["plugins"]:
        assert eps[pid] is True


# ---------------------------------------------------------------------------
# Test 2: Guard 1 — fallback to hardcoded when both sources are empty
# ---------------------------------------------------------------------------

def test_guard1_fallback_to_hardcoded(tmp_path, monkeypatch):
    """Given installed_plugins.json is missing AND good_backup has no enabledPlugins
    When guard1 runs
    Then it falls back to the hardcoded 5-plugin list.
    """
    # Given: no installed_plugins.json
    ip_path = tmp_path / "nonexistent_installed_plugins.json"
    monkeypatch.setattr(cg, "INSTALLED_PLUGINS_PATH", ip_path)

    # good_backup also empty
    backup_path = tmp_path / "good_backup.json"
    backup_path.write_text("{}")
    monkeypatch.setattr(cg, "GOOD_BACKUP_PATH", backup_path)

    settings = {}

    # When
    changed = cg.guard1_enabled_plugins(settings)

    # Then
    assert changed is True
    assert "enabledPlugins" in settings
    eps = settings["enabledPlugins"]
    assert len(eps) == 5
    for pid in cg.HARDCODED_PLUGINS:
        assert eps[pid] is True


# ---------------------------------------------------------------------------
# Test 3: Guard 2 — statusLine restored when missing
# ---------------------------------------------------------------------------

def test_guard2_statusline_restored():
    """Given settings.json has no statusLine key
    When guard2 runs
    Then statusLine is created with type='command' and the HUD command string.
    """
    # Given
    settings = {}

    # When
    changed = cg.guard2_statusline(settings)

    # Then
    assert changed is True
    sl = settings["statusLine"]
    assert sl["type"] == "command"
    assert len(sl["command"]) > 50
    assert "claude-hud" in sl["command"]
    assert "stty" in sl["command"]


def test_guard2_statusline_intact():
    """Given settings.json already has a valid statusLine
    When guard2 runs
    Then no changes are made.
    """
    # Given
    settings = {"statusLine": {"type": "command", "command": "echo hello"}}

    # When
    changed = cg.guard2_statusline(settings)

    # Then
    assert changed is False
    assert settings["statusLine"]["command"] == "echo hello"


# ---------------------------------------------------------------------------
# Test 4: Guard 3 — hook added when guardian absent
# ---------------------------------------------------------------------------

def test_guard3_hook_added_when_guardian_absent(monkeypatch, tmp_path):
    """Given hooks.SessionStart exists but lacks a config_guardian.py entry
    When guard3 runs
    Then the guardian self-entry is appended with correct nested format.
    """
    # Given: SessionStart with some other hooks but no guardian
    guardian_path = tmp_path / "config_guardian.py"
    guardian_path.write_text("# dummy")
    monkeypatch.setattr(cg, "THIS_FILE", guardian_path)

    settings = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "",
                    "hooks": [
                        {"type": "command", "command": "python other_hook.py"}
                    ],
                }
            ]
        }
    }

    # When
    changed = cg.guard3_hooks(settings)

    # Then
    assert changed is True
    session_hooks = settings["hooks"]["SessionStart"]
    assert len(session_hooks) >= 2

    # Find the guardian entry
    guardian_entry = None
    for entry in session_hooks:
        for h in entry.get("hooks", []):
            if "config_guardian.py" in h.get("command", ""):
                guardian_entry = entry
                break

    assert guardian_entry is not None, "Guardian entry was not added"
    assert guardian_entry["matcher"] == ""
    assert len(guardian_entry["hooks"]) == 1
    assert guardian_entry["hooks"][0]["type"] == "command"
    assert "config_guardian.py" in guardian_entry["hooks"][0]["command"]


def test_guard3_hook_already_exists(monkeypatch, tmp_path):
    """Given hooks.SessionStart already has config_guardian.py
    When guard3 runs
    Then no duplicate is added.
    """
    # Given
    guardian_path = tmp_path / "config_guardian.py"
    guardian_path.write_text("# dummy")
    monkeypatch.setattr(cg, "THIS_FILE", guardian_path)

    settings = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f'python "{guardian_path}"',
                        }
                    ],
                }
            ]
        }
    }

    # When
    changed = cg.guard3_hooks(settings)

    # Then
    assert changed is False
    assert len(settings["hooks"]["SessionStart"]) == 1


# ---------------------------------------------------------------------------
# Test 5: Guard 4 — env keys restored
# ---------------------------------------------------------------------------

def test_guard4_env_keys_restored():
    """Given settings.json is missing env.ANTHROPIC_BASE_URL and preferences
    When guard4 runs
    Then all 4 REQUIRED_ENV keys and 3 preference defaults are restored from hardcoded values.
    """
    # Given: no env key, no prefs
    settings = {}

    # When
    changed = cg.guard4_env_and_prefs(settings)

    # Then
    assert changed is True
    assert "env" in settings
    for key, value in cg.REQUIRED_ENV.items():
        assert settings["env"][key] == value, f"Missing REQUIRED_ENV key: {key}"
    for key, value in cg.PREFERENCE_DEFAULTS.items():
        assert settings[key] == value, f"Missing PREFERENCE_DEFAULTS key: {key}"


def test_guard4_env_keys_intact():
    """Given settings.json already has all required env and prefs
    When guard4 runs
    Then no changes are made.
    """
    # Given
    settings = {
        "env": dict(cg.REQUIRED_ENV),
        "effortLevel": "max",
        "theme": "dark",
        "includeCoAuthoredBy": False,
    }

    # When
    changed = cg.guard4_env_and_prefs(settings)

    # Then
    assert changed is False


# ---------------------------------------------------------------------------
# Test 6: atomic_write preserves data
# ---------------------------------------------------------------------------

def test_atomic_write_preserves_data(tmp_path):
    """Given a valid settings dict and a target path
    When atomic_write(path, data) is called
    Then the file contains correct JSON and no temp files are left behind.
    """
    # Given
    target = tmp_path / "settings.json"
    data = {
        "enabledPlugins": {"superpowers@claude-plugins-official": True},
        "statusLine": {"type": "command", "command": "echo test"},
        "env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:15721"},
    }

    # When
    cg.atomic_write(target, data)

    # Then: file exists with correct content
    assert target.exists()
    read_back = json.loads(target.read_text())
    assert read_back == data

    # Then: no .tmp files left behind
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0, f"Temp files left behind: {tmp_files}"


def test_atomic_write_overwrites_existing(tmp_path):
    """Given an existing file at the target path
    When atomic_write overwrites it
    Then the new content replaces the old atomically.
    """
    # Given
    target = tmp_path / "existing.json"
    target.write_text('{"old": "data"}')
    new_data = {"new": "data"}

    # When
    cg.atomic_write(target, new_data)

    # Then
    assert json.loads(target.read_text()) == new_data
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0
