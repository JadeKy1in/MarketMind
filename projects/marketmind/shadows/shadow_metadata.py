"""Shadow metadata — Chinese names, strategy/target descriptions."""
from __future__ import annotations

# shadow_id → {cn_name, strategy_desc}
SHADOW_META: dict[str, dict[str, str]] = {
    "shadow_expert_gold": {"cn_name": "黄金专家", "desc": "贵金属分析 · Gold & Precious Metals"},
    "shadow_expert_crypto": {"cn_name": "加密专家", "desc": "数字货币分析 · Crypto & Digital Assets"},
    "shadow_expert_energy": {"cn_name": "能源专家", "desc": "原油能源分析 · Oil & Energy"},
    "shadow_expert_bonds": {"cn_name": "债券专家", "desc": "固定收益分析 · Fixed Income & Bonds"},
    "shadow_expert_volatility": {"cn_name": "波动率专家", "desc": "波动率分析 · Volatility & VIX"},
    "shadow_expert_emerging": {"cn_name": "新兴市场专家", "desc": "新兴市场分析 · Emerging Markets"},
    "shadow_expert_tech": {"cn_name": "科技专家", "desc": "科技板块分析 · Tech & Semiconductors"},
    "shadow_expert_financials": {"cn_name": "金融专家", "desc": "金融板块分析 · Financials & Banking"},
    "shadow_expert_healthcare": {"cn_name": "医疗专家", "desc": "医疗板块分析 · Healthcare & Pharma"},
    "shadow_expert_consumer": {"cn_name": "消费专家", "desc": "消费板块分析 · Consumer & Retail"},
    "shadow_expert_industrials": {"cn_name": "工业专家", "desc": "工业板块分析 · Industrials & Manufacturing"},
    "shadow_expert_macro": {"cn_name": "宏观专家", "desc": "宏观经济分析 · Macro & SPY"},
    "shadow_expert_metals": {"cn_name": "金属专家", "desc": "工业金属分析 · Industrial Metals"},
    "shadow_expert_real_estate": {"cn_name": "地产专家", "desc": "房地产分析 · Real Estate & REITs"},
    "shadow_expert_fx": {"cn_name": "外汇专家", "desc": "外汇市场分析 · FX & Currency"},
    "shadow_expert_short": {"cn_name": "做空专家", "desc": "做空策略分析 · Short & Bearish"},
    "shadow_momentum_01": {"cn_name": "动量一号", "desc": "趋势跟踪策略 · Momentum Trend Following"},
    "shadow_momentum_02": {"cn_name": "动量二号", "desc": "突破交易策略 · Breakout Trading"},
    "shadow_momentum_03": {"cn_name": "动量三号", "desc": "均值回归策略 · Mean Reversion"},
    "shadow_daredevil_01": {"cn_name": "敢死一号", "desc": "逆向投资策略 · Contrarian Value"},
    "shadow_daredevil_02": {"cn_name": "敢死二号", "desc": "事件驱动策略 · Event-Driven"},
    "shadow_daredevil_03": {"cn_name": "敢死三号", "desc": "高波动策略 · High Volatility"},
    "shadow_beta_01": {"cn_name": "基准一号", "desc": "市场基准 · Market Beta Baseline"},
}


def get_shadow_meta(shadow_id: str) -> dict[str, str]:
    """Return {cn_name, desc} for a shadow, or defaults."""
    return SHADOW_META.get(shadow_id, {
        "cn_name": shadow_id,
        "desc": "策略分析 · Strategy Analysis",
    })
