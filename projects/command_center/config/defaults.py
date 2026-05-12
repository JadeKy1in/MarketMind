"""defaults.py — 所有设置项的默认值字典。

定义 DEFAULT_SETTINGS 作为 config.json 的 schema 与初始值。
config.json 缺失时，以此字典填充首次运行数据。
"""

from typing import Dict, Any


DEFAULT_SETTINGS: Dict[str, Any] = {
    "version": "1.0",
    "last_modified": "",

    # ── 外观 ──
    "appearance": {
        "font_family": "Microsoft YaHei",       # Windows 默认中文字体
        "font_size_base": 14,
        "appearance_mode": "dark",
        "color_theme": "blue",
    },

    # ── API ──
    "api": {
        "deepseek_api_key_encoded": "",         # XOR + base64 混淆
        "deepseek_pro_model": "deepseek-v4-pro",
        "deepseek_flash_model": "deepseek-v4-flash",
    },

    # ── 调仓优化器 ──
    "optimizer": {
        "drift_threshold": 0.03,
        "max_suggestions": 10,
        "min_belief_weight": 0.1,
        "default_target_weight": 0.1,
        "max_single_position_weight": 0.3,
        "volatility_buffer": 0.02,
        "cash_weight_floor": 0.05,
    },

    # ── 影子对比 ──
    "shadow_comparator": {
        "n_simulations": 10000,
        "n_days": 30,
        "annual_return": 0.08,
        "annual_volatility": 0.18,
        "risk_free_rate": 0.03,
        "confidence_level": 0.95,
        "transaction_cost_pct": 0.001,
    },

    # ── 聊天 ──
    "chat": {
        "temperature_pro": 0.7,
        "temperature_flash": 0.3,
        "max_tokens": 4096,
        "context_window_size": 20,
    },

    # ── 情报管线 ──
    "intelligence": {
        "scraper_request_timeout": 15,
        "scraper_max_raw_chars": 50000,
        "checker_max_claims_per_pass": 10,
        "modifier_min_report_score": 20.0,
        "modifier_auto_high_urgency_threshold": 70.0,
    },

    # ── 信念系统 ──
    "belief": {
        "decay_rate_threshold": 0.85,
        "resolution_batch_size": 50,
        "reflection_interval_hours": 24,
    },
}


def get_nested(settings: Dict[str, Any], dot_path: str, default: Any = None) -> Any:
    """通过点号路径获取嵌套值。

    示例:
        get_nested(settings, "appearance.font_family")  # → "Microsoft YaHei"
        get_nested(settings, "api.foo.bar", "fallback")  # → "fallback"
    """
    keys = dot_path.split(".")
    val: Any = settings
    for key in keys:
        if isinstance(val, dict):
            val = val.get(key)
            if val is None:
                return default
        else:
            return default
    return val if val is not None else default


def set_nested(settings: Dict[str, Any], dot_path: str, value: Any) -> None:
    """通过点号路径设置嵌套值。"""
    keys = dot_path.split(".")
    target = settings
    for key in keys[:-1]:
        if key not in target or not isinstance(target[key], dict):
            target[key] = {}
        target = target[key]
    target[keys[-1]] = value