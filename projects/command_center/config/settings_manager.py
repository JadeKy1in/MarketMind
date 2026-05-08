"""settings_manager.py — 全局设置中心 (SettingsManager)

核心职责:
  1. 以 config.json 为单一真实来源进行读写
  2. API Key XOR + base64 混淆存储
  3. 发布-订阅模式（Pub-Sub）实现热更新通知
  4. Nested get/set 通过点号路径（如 "appearance.font_family"）

设计模式:
  - 单例（Singleton）：全局唯一实例
  - 观察者（Observer）：subscribe() / notify() 解耦消费者

SPARC:
  Specification: V2.0 Sprint 5 — 全局设置中心
  Pseudocode: SettingsManager 单例 → load/save/get/set/subscribe/notify
  Architecture: 单例 + Pub-Sub + Nested dot-path access
  Refinement: Exception-safe I/O，XOR 作混淆而非加密
  Completion: 单元测试 15+ 项
"""

from __future__ import annotations

import base64
import copy
import json
import logging
import os
import platform
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict, List, Optional

from projects.command_center.config.defaults import (
    DEFAULT_SETTINGS,
    get_nested,
    set_nested,
)

logger = logging.getLogger(__name__)

# ── 回调类型 ──
SettingsCallback = Callable[[Dict[str, Any]], None]


def _machine_fingerprint() -> bytes:
    """生成机器指纹用于 XOR 混淆。

    组合系统 UUID 和主机名，取 SHA256 前 16 字节。
    同一台机器的此值在重启后保持稳定。
    """
    raw = f"{uuid.uuid1()}:{platform.node()}:{uuid.getnode()}"
    import hashlib
    return hashlib.sha256(raw.encode()).digest()[:16]


_MACHINE_KEY = _machine_fingerprint()


def _xor_obfuscate(data: str) -> str:
    """XOR + base64 混淆。

    警告: 这是混淆 (obfuscation)，不是加密 (encryption)。
    防止意外暴露（如截图分享），不防御针对性攻击。
    """
    raw = data.encode("utf-8")
    obfuscated = bytes(b ^ _MACHINE_KEY[i % len(_MACHINE_KEY)] for i, b in enumerate(raw))
    return base64.b64encode(obfuscated).decode("ascii")


def _xor_deobfuscate(encoded: str) -> str:
    """XOR + base64 反混淆。"""
    try:
        obfuscated = base64.b64decode(encoded)
        raw = bytes(b ^ _MACHINE_KEY[i % len(_MACHINE_KEY)] for i, b in enumerate(obfuscated))
        return raw.decode("utf-8")
    except Exception as exc:
        logger.warning("API key deobfuscation failed: %s", exc)
        return ""


def _config_path() -> Path:
    """返回 config.json 的绝对路径。"""
    # 与 requirements.txt 同级（command_center 根目录）
    return Path(__file__).resolve().parent.parent / "config.json"


class SettingsManager:
    """全局设置管理器（单例）。

    用法:
        sm = SettingsManager()          # 单例，第一次调用时加载
        sm.get("appearance.font_family")  # → "Microsoft YaHei"
        sm.set("appearance.font_family", "SimHei")
        sm.save()
        sm.subscribe(my_callback)       # 注册热更新
        sm.notify()                     # 通知所有订阅者
    """

    _instance: Optional["SettingsManager"] = None
    _lock: Lock = Lock()

    # ============================================================
    # 单例
    # ============================================================

    def __new__(cls, *args, **kwargs) -> "SettingsManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    # 避免 __init__ 被多次调用
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, auto_load: bool = True) -> None:
        """初始化设置管理器。

        Args:
            auto_load: 是否在创建时自动加载 config.json（默认 True）
        """
        if self._initialized:
            return
        self._initialized = True

        self._path: Path = _config_path()
        self._data: Dict[str, Any] = {}
        self._subscribers: List[SettingsCallback] = []
        self._rw_lock: Lock = Lock()

        if auto_load:
            self.load()

    # ============================================================
    # 加载 / 保存
    # ============================================================

    def load(self) -> Dict[str, Any]:
        """从 config.json 加载设置。文件不存在则返回默认值。

        Returns:
            当前设置字典
        """
        with self._rw_lock:
            if self._path.exists():
                try:
                    raw = self._path.read_text(encoding="utf-8")
                    self._data = json.loads(raw)
                    # 确保所有默认键存在（新增设置项兼容）
                    self._merge_defaults()
                    logger.info("Settings loaded from %s", self._path)
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning("Failed to load config.json: %s. Using defaults.", exc)
                    self._data = copy.deepcopy(DEFAULT_SETTINGS)
            else:
                logger.info("config.json not found. Using defaults.")
                self._data = copy.deepcopy(DEFAULT_SETTINGS)
            return dict(self._data)  # 返回副本

    def save(self) -> None:
        """将当前设置写入 config.json。"""
        with self._rw_lock:
            import datetime
            self._data["last_modified"] = (
                datetime.datetime.now(datetime.timezone.utc).isoformat()
            )
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._path.write_text(
                    json.dumps(self._data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                logger.info("Settings saved to %s", self._path)
            except OSError as exc:
                logger.error("Failed to save config.json: %s", exc)

    def reset_to_defaults(self) -> None:
        """重置所有设置为默认值。"""
        with self._rw_lock:
            self._data = copy.deepcopy(DEFAULT_SETTINGS)
        logger.info("Settings reset to defaults.")

    # ============================================================
    # 读取 / 写入
    # ============================================================

    def get(self, dot_path: str, default: Any = None) -> Any:
        """读取设置值（通过点号路径）。

        Args:
            dot_path: 如 "appearance.font_family"
            default: 路径不存在时的默认值

        Returns:
            设置值
        """
        with self._rw_lock:
            return get_nested(self._data, dot_path, default)

    def set(self, dot_path: str, value: Any) -> None:
        """写入设置值（通过点号路径）。

        Args:
            dot_path: 如 "appearance.font_family"
            value: 新的设置值
        """
        with self._rw_lock:
            set_nested(self._data, dot_path, value)
        logger.debug("Settings set: %s = %r", dot_path, value)

    def get_all(self) -> Dict[str, Any]:
        """返回完整设置字典的副本。"""
        with self._rw_lock:
            return dict(self._data)

    # ============================================================
    # API Key 混淆存取
    # ============================================================

    def get_api_key(self) -> str:
        """获取解密后的 DeepSeek API Key。"""
        encoded = self.get("api.deepseek_api_key_encoded", "")
        if not encoded:
            # fallback 到环境变量
            return os.environ.get("DEEPSEEK_API_KEY", "")
        return _xor_deobfuscate(encoded)

    def set_api_key(self, api_key: str) -> None:
        """设置并混淆存储 API Key。"""
        if not api_key:
            self.set("api.deepseek_api_key_encoded", "")
            return
        encoded = _xor_obfuscate(api_key)
        self.set("api.deepseek_api_key_encoded", encoded)

    # ============================================================
    # 发布-订阅 (Pub-Sub)
    # ============================================================

    def subscribe(self, callback: SettingsCallback) -> None:
        """注册设置变更回调。保存后通过 notify() 通知所有订阅者。

        Args:
            callback: 接收完整设置字典的回调函数
        """
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: SettingsCallback) -> None:
        """取消订阅。"""
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def notify(self) -> None:
        """通知所有订阅者设置已变更。

        通常在 save() 后调用。订阅者读取最新的设置并做热更新。
        """
        snapshot = self.get_all()
        for cb in self._subscribers:
            try:
                cb(snapshot)
            except Exception as exc:
                logger.error("Settings subscriber error: %s", exc)

    def save_and_notify(self) -> None:
        """保存到文件并通知所有订阅者。"""
        self.save()
        self.notify()

    # ============================================================
    # 内部
    # ============================================================

    def _merge_defaults(self) -> None:
        """确保现有设置中包含所有默认键（兼容新增设置项）。

        Source（从文件加载的数据）中的值会覆盖 target（默认值）中已有的
        非 dict 类型的值。只有 dict 类型的键会被递归合并。
        """
        merged = copy.deepcopy(DEFAULT_SETTINGS)

        def _deep_merge(target: Dict[str, Any], source: Dict[str, Any]) -> None:
            for key, val in source.items():
                if key in target and isinstance(target[key], dict) and isinstance(val, dict):
                    _deep_merge(target[key], val)
                elif key not in target:
                    target[key] = val
                else:
                    # 非 dict 键同时存在于 default 和 source 中 → source 覆盖 default
                    target[key] = val

        _deep_merge(merged, self._data)
        self._data = merged
