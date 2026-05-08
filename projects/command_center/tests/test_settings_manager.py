"""test_settings_manager.py — SettingsManager 单元测试

覆盖范围:
  - 单例模式
  - 默认值加载
  - get/set 读写（含嵌套 dot-path）
  - API Key XOR 混淆 + 反混淆 roundtrip
  - 发布-订阅 (subscribe / notify)
  - save / load 持久化
  - 文件不存在时的优雅降级
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from projects.command_center.config.settings_manager import (
    SettingsManager,
    _xor_obfuscate,
    _xor_deobfuscate,
    _config_path,
)
from projects.command_center.config.defaults import DEFAULT_SETTINGS, get_nested


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(autouse=True)
def _reset_singleton() -> Generator:
    """在每个测试前重置 SettingsManager 单例。"""
    SettingsManager._instance = None
    yield
    SettingsManager._instance = None


@pytest.fixture
def temp_config(tmp_path: Path) -> Generator[Path, None, None]:
    """创建一个临时 config.json 目录，覆盖 _config_path。"""
    from projects.command_center.config import settings_manager as sm
    original_config = sm._config_path

    test_path = tmp_path / "command_center" / "config.json"
    test_path.parent.mkdir(parents=True, exist_ok=True)

    def fake_path():
        return test_path

    sm._config_path = fake_path
    yield test_path

    sm._config_path = original_config


# ============================================================
# Tests: 单例模式
# ============================================================

class TestSingleton:
    def test_singleton_returns_same_instance(self):
        sm1 = SettingsManager(auto_load=False)
        sm2 = SettingsManager(auto_load=False)
        assert sm1 is sm2

    def test_singleton_cross_file(self):
        sm1 = SettingsManager(auto_load=False)
        sm2 = SettingsManager(auto_load=False)
        assert id(sm1) == id(sm2)


# ============================================================
# Tests: 默认值加载
# ============================================================

class TestDefaults:
    def test_load_returns_defaults_when_no_file(self, temp_config):
        sm = SettingsManager(auto_load=False)
        data = sm.load()
        assert data["version"] == "1.0"
        assert data["appearance"]["font_family"] == "Microsoft YaHei"

    def test_default_appearance(self, temp_config):
        sm = SettingsManager()
        assert sm.get("appearance.font_family") == "Microsoft YaHei"
        assert sm.get("appearance.font_size_base") == 14
        assert sm.get("appearance.appearance_mode") == "dark"
        assert sm.get("appearance.color_theme") == "blue"

    def test_default_api_key_empty(self, temp_config):
        sm = SettingsManager()
        assert sm.get_api_key() == ""

    def test_default_optimizer_params(self, temp_config):
        sm = SettingsManager()
        assert sm.get("optimizer.drift_threshold") == 0.03
        assert sm.get("optimizer.max_single_position_weight") == 0.3

    def test_default_shadow_params(self, temp_config):
        sm = SettingsManager()
        assert sm.get("shadow_comparator.n_simulations") == 10000
        assert sm.get("shadow_comparator.confidence_level") == 0.95


# ============================================================
# Tests: get / set
# ============================================================

class TestGetSet:
    def test_get_set_nested(self, temp_config):
        sm = SettingsManager()
        sm.set("appearance.font_family", "SimHei")
        assert sm.get("appearance.font_family") == "SimHei"

    def test_set_overwrites(self, temp_config):
        sm = SettingsManager()
        sm.set("appearance.font_size_base", 18)
        assert sm.get("appearance.font_size_base") == 18

    def test_get_nonexistent_returns_default(self, temp_config):
        sm = SettingsManager()
        assert sm.get("nonexistent.path", 42) == 42

    def test_get_all_returns_copy(self, temp_config):
        sm = SettingsManager()
        data = sm.get_all()
        assert isinstance(data, dict)
        assert data["version"] == "1.0"

    def test_set_non_nested(self, temp_config):
        sm = SettingsManager()
        sm.set("version", "2.0")
        assert sm.get("version") == "2.0"


# ============================================================
# Tests: API Key XOR 混淆
# ============================================================

class TestApiKeyObfuscation:
    def test_xor_roundtrip(self):
        key = "sk-1234567890abcdef"
        encoded = _xor_obfuscate(key)
        decoded = _xor_deobfuscate(encoded)
        assert decoded == key

    def test_xor_empty_string(self):
        encoded = _xor_obfuscate("")
        decoded = _xor_deobfuscate(encoded)
        assert decoded == ""

    def test_xor_long_key(self):
        key = "sk-" + "a" * 100
        encoded = _xor_obfuscate(key)
        decoded = _xor_deobfuscate(encoded)
        assert decoded == key

    def test_set_api_key_roundtrip(self, temp_config):
        sm = SettingsManager()
        sm.set_api_key("sk-test-key-123")
        assert sm.get_api_key() == "sk-test-key-123"

    def test_set_api_key_empty_clears(self, temp_config):
        sm = SettingsManager()
        sm.set_api_key("sk-test")
        sm.set_api_key("")
        assert sm.get_api_key() == ""

    def test_api_key_not_stored_in_plaintext(self, temp_config):
        sm = SettingsManager()
        sm.set_api_key("sk-secret-123")
        sm.save()

        raw = temp_config.read_text(encoding="utf-8")
        data = json.loads(raw)
        stored = data["api"]["deepseek_api_key_encoded"]
        assert "sk-secret" not in stored
        assert len(stored) > 0
        assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=" for c in stored)

    def test_api_key_fallback_to_env(self, temp_config, monkeypatch):
        """config.json 中无 key 时回退到环境变量。"""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-key")
        SettingsManager._instance = None  # 强制重建单例，避免前序测试残留
        sm = SettingsManager()
        assert sm.get_api_key() == "sk-env-key"


# ============================================================
# Tests: 持久化 (save / load)
# ============================================================

class TestPersistence:
    def test_save_and_reload(self, temp_config):
        sm = SettingsManager()
        sm.set("appearance.font_family", "SimHei")
        sm.set("optimizer.drift_threshold", 0.05)
        sm.set_api_key("sk-persist-test")
        sm.save()

        SettingsManager._instance = None
        sm2 = SettingsManager()
        assert sm2.get("appearance.font_family") == "SimHei"
        assert sm2.get("optimizer.drift_threshold") == 0.05
        assert sm2.get_api_key() == "sk-persist-test"

    def test_save_creates_file(self, temp_config):
        assert not temp_config.exists()
        sm = SettingsManager()
        sm.save()
        assert temp_config.exists()

    def test_reset_to_defaults(self, temp_config):
        sm = SettingsManager()
        sm.set("appearance.font_family", "CustomFont")
        sm.reset_to_defaults()
        assert sm.get("appearance.font_family") == "Microsoft YaHei"

    def test_corrupted_file_uses_defaults(self, temp_config):
        temp_config.write_text("{corrupted json}", encoding="utf-8")
        sm = SettingsManager()
        data = sm.load()
        assert data["version"] == "1.0"

    def test_last_modified_updated_on_save(self, temp_config):
        sm = SettingsManager()
        sm.save()
        assert len(sm.get("last_modified", "")) > 0


# ============================================================
# Tests: 发布-订阅 (Pub-Sub)
# ============================================================

class TestPubSub:
    def test_subscribe_gets_notified(self, temp_config):
        sm = SettingsManager()
        received = []

        def callback(settings):
            # 注意：settings 是普通 dict（get_all() 的浅拷贝），
            # 需要通过字典键访问嵌套值，不能使用点号路径
            received.append(settings["appearance"]["font_family"])

        sm.subscribe(callback)
        sm.set("appearance.font_family", "CustomFont")
        sm.notify()

        assert len(received) == 1
        assert received[0] == "CustomFont"

    def test_multiple_subscribers(self, temp_config):
        sm = SettingsManager()
        count = [0, 0]

        def cb1(_):
            count[0] += 1

        def cb2(_):
            count[1] += 1

        sm.subscribe(cb1)
        sm.subscribe(cb2)
        sm.notify()

        assert count[0] == 1
        assert count[1] == 1

    def test_unsubscribe(self, temp_config):
        sm = SettingsManager()
        count = [0]

        def cb(_):
            count[0] += 1

        sm.subscribe(cb)
        sm.notify()
        assert count[0] == 1

        sm.unsubscribe(cb)
        sm.notify()
        assert count[0] == 1

    def test_subscriber_error_does_not_crash(self, temp_config):
        sm = SettingsManager()
        errors = []

        def bad_cb(_):
            raise ValueError("Boom")

        def good_cb(_):
            errors.append("ok")

        sm.subscribe(bad_cb)
        sm.subscribe(good_cb)
        sm.notify()
        assert errors == ["ok"]

    def test_save_and_notify(self, temp_config):
        sm = SettingsManager()
        notified = [False]

        def cb(_):
            notified[0] = True

        sm.subscribe(cb)
        sm.save_and_notify()
        assert notified[0] is True


# ============================================================
# Tests: Config Path
# ============================================================

class TestConfigPath:
    def test_config_path_is_json(self):
        path = _config_path()
        assert path.name == "config.json"
        assert str(path).endswith("config.json")

    def test_config_path_in_command_center(self):
        path = _config_path()
        assert "command_center" in str(path)