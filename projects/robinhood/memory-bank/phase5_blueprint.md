# Phase 5 — The Scout: 全球宏观雷达与主动发现层 架构蓝图

**文档版本**: v1.0  
**日期**: 2026-05-05  
**状态**: APPROVED  
**设计原则**: 借鉴桥水全天候框架 + 鲁宾斯坦反身性理论，全部自研，零新增第三方依赖

---

## 目录

1. [形象定位：从 Sniper 到 Scout 的认知升维](#1-形象定位从-sniper-到-scout-的认知升维)
2. [模块交互总图](#2-模块交互总图)
3. [模块一：资产映射矩阵 (asset_mapper.py)](#3-模块一资产映射矩阵-asset_mapperpy)
4. [模块二：因果检验与逻辑失效机制 (causal_auditor.py)](#4-模块二因果检验与逻辑失效机制-causal_auditorpy)
5. [模块三：激进数据挖掘与信源治理 (source_governor.py)](#5-模块三激进数据挖掘与信源治理-source_governorpy)
6. [模块四：深度推演协议 (continuation_protocol.py)](#6-模块四深度推演协议-continuation_protocolpy)
7. [核心数据结构定义 (Data Schema)](#7-核心数据结构定义-data-schema)
8. [Phase 5 分步开发计划](#8-phase-5-分步开发计划)
9. [风险与降级预案](#9-风险与降级预案)

---

## 1. 形象定位：从 Sniper 到 Scout 的认知升维

```
Phase 1-4 (The Sniper):          Phase 5 (The Scout):

  "等待已知事件发生"    ---->     "主动扫描未知奇点"
  被动管道 (Pipeline)            主动雷达 (Radar)
  单资产分析                     多资产矩阵映射
  线性推理链                     因果检验 + 反向证伪
  单轮 API 调用                  多轮递归续写协议
  信任单一信源                   三角形信源校验 (SAR)
```

**The Scout 不替代 The Sniper，而是在其之上构建第二层认知引擎。**  
Sniper 的数据输出（market_fetcher, sentiment_collector, macro_calendar）成为 Scout 的**结构化输入**，Scout 在此基础上执行跨资产、跨信源的主动发现。

---

## 2. 模块交互总图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        The Scout Orchestrator                         │
│                        scout_orchestrator.py                          │
│  (定时触发 或 事件驱动 — 每 4 小时或检测到宏异动时)                    │
└────┬──────────┬──────────┬──────────┬──────────────────────────────┘
     │          │          │          │
     ▼          ▼          ▼          ▼
┌─────────┐ ┌─────────┐ ┌─────────┐ ┌──────────────────────┐
│  Layer 0│ │  Layer 1│ │  Layer 2│ │     Layer 3          │
│  source │ │  asset  │ │ causal  │ │  continuation        │
│ _gover  │ │ _mapper │ │_auditor │ │  _protocol           │
│ nor.py  │ │  .py    │ │  .py    │ │  .py                 │
└────┬────┘ └────┬────┘ └────┬────┘ └──────────┬───────────┘
     │          │          │                   │
     │          │          │                   │
     ▼          ▼          ▼                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    Phase 1-4 现有管道 (复用)                           │
│  market_fetcher.py  │  sentiment_collector.py  │  macro_calendar.py  │
│  deepseek_client.py │  output_formatter.py     │  account_reader.py  │
└──────────────────────────────────────────────────────────────────────┘
```

**数据流方向：**

```
外部 RSS/API 信源
    │
    ▼
[source_governor.py] ──三角形校验──▶ 可靠叙事 (Narrative) 或 不可靠标记
    │                                      │
    │  (可靠叙事)                           │  (不可靠)
    ▼                                      ▼
[asset_mapper.py]                     标注为 "unverified"
    │  宏观 Tag → 三维配置篮子            仅记录日志
    ▼
[deepseek_client.py] ◀── 注入 三维篮子 + 叙事 JSON
    │
    ▼
[causal_auditor.py]
    │  生成 Logic Chain + Invalidation Triggers
    ▼
[continuation_protocol.py] (如需要长文)
    │  多轮 API 递归调用 + JSON 合并
    ▼
[output_formatter.py]
    │  渲染最终 Markdown 研报
    ▼
[memory-bank/] 存档
```

---

## 3. 模块一：资产映射矩阵 (asset_mapper.py)

### 3.1 核心职责

将抽象的宏观叙事 (Macro Narrative) 映射为可在 Robinhood 交易的**三维配置篮子**，输出为 DeepSeek 推理时可直接引用的 JSON 上下文。

### 3.2 映射逻辑

采用**桥水全天候框架四象限**作为底层分类引擎，叠加静态映射表和动态过滤器：

```
宏观叙事输入 (例: "Fed暗示提前降息 + 地缘冲突升级")
         │
         ▼
┌────────────────────────────────────┐
│  Step 1: 四象限分类               │
│  - 经济增长 ↑/↓                   │
│  - 通胀 ↑/↓                       │
│  当前定位: 经济增长↓ + 通胀↓       │
│  (衰退象限 -> 避险资产偏好)        │
└────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────┐
│  Step 2: Tag → Asset 静态路由     │
│  "rate_cut" -> GLD, IAU, TLT      │
│  "geopolitical_risk" -> GDX, XLE  │
│  "safe_haven" -> BTC, GLD, USFR   │
└────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────┐
│  Step 3: 三维篮子拆分             │
│  - 高流动性: GLD, SPY, QQQ        │
│  - 低费率: IAU (0.25%), VOO (0.03%)│
│  - 高弹性/杠杆: GDX, UPRO, BITO   │
└────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────┐
│  Step 4: 动态过滤器               │
│  - 检查 Robinhood 可交易性 (白名单)│
│  - 检查流动性阈值 (日均成交量)     │
│  - 检查与现有持仓相关性           │
└────────────────────────────────────┘
         │
         ▼
     输出: AssetBasket (三维配置)
```

### 3.3 核心数据结构

```python
# config/asset_universe.py — 静态资产白名单 (编译时常量)

ASSET_UNIVERSE = {
    # ===== 宏观 Tag → 相关资产组 =====
    "rate_cut": {
        "description": "央行降息周期",
        "beneficiaries": {
            "high_liquidity":  ["GLD", "TLT", "SPY"],
            "low_expense":     ["IAU", "VGLT", "VOO"],
            "high_beta":       ["GDX", "TMF", "UPRO"],
        },
        "victims": {
            "high_liquidity":  ["USFR", "SHV"],
            "low_expense":     ["BIL"],
            "high_beta":       ["SQQQ", "SPXU"],
        },
        "quadrant": "disinflation_growth_down",
    },
    "geopolitical_risk": {
        "description": "地缘冲突升级 / 军事紧张",
        "beneficiaries": {
            "high_liquidity":  ["GLD", "XLE", "USO"],
            "low_expense":     ["IAU", "VDE", "USL"],
            "high_beta":       ["GDX", "ERX", "BITO"],
        },
        "victims": {
            "high_liquidity":  ["EEM", "EWJ", "EWG"],
            "low_expense":     ["IEMG", "EFA"],
            "high_beta":       ["YINN", "TUR"],
        },
        "quadrant": "stagflation",
    },
    "inflation_surprise": {
        "description": "通胀超预期上行",
        "beneficiaries": {
            "high_liquidity":  ["GLD", "XLE", "DBC"],
            "low_expense":     ["IAU", "VDE", "PDBC"],
            "high_beta":       ["GDX", "ERX", "UCO"],
        },
        "victims": {
            "high_liquidity":  ["TLT", "QQQ", "ARKK"],
            "low_expense":     ["VGLT", "VUG"],
            "high_beta":       ["TMF", "TQQQ"],
        },
        "quadrant": "inflation_growth_up",
    },
    "credit_crunch": {
        "description": "信贷收缩 / 银行危机",
        "beneficiaries": {
            "high_liquidity":  ["GLD", "USFR", "SHY"],
            "low_expense":     ["IAU", "BIL", "VGIT"],
            "high_beta":       ["TMF", "GDX"],
        },
        "victims": {
            "high_liquidity":  ["XLF", "KRE", "IWM"],
            "low_expense":     ["VFH", "IWN"],
            "high_beta":       ["FAS", "TNA"],
        },
        "quadrant": "deflation_growth_down",
    },
    "commodity_supercycle": {
        "description": "大宗商品超级周期",
        "beneficiaries": {
            "high_liquidity":  ["DBC", "XLE", "GLD"],
            "low_expense":     ["PDBC", "VDE", "IAU"],
            "high_beta":       ["ERX", "UCO", "GDXJ"],
        },
        "victims": {
            "high_liquidity":  ["TLT", "QQQ"],
            "low_expense":     ["VGLT", "VUG"],
            "high_beta":       ["TMF"],
        },
        "quadrant": "inflation_growth_up",
    },
    "safe_haven_rush": {
        "description": "全面避险情绪 (VIX 飙升)",
        "beneficiaries": {
            "high_liquidity":  ["GLD", "USFR", "SHY"],
            "low_expense":     ["IAU", "BIL", "VGIT"],
            "high_beta":       ["TMF", "VXX"],
        },
        "victims": {
            "high_liquidity":  ["SPY", "QQQ", "IWM"],
            "low_expense":     ["VOO", "VTI", "VXUS"],
            "high_beta":       ["TQQQ", "UPRO", "TNA"],
        },
        "quadrant": "deflation_growth_down",
    },
}

# Robinhood 可交易性白名单 (Phase 6 前手动维护)
ROBINHOOD_TRADABLE_WHITELIST = {
    "GLD", "IAU", "TLT", "SPY", "QQQ", "IWM", "DBC", "USO",
    "XLE", "XLF", "KRE", "EEM", "GDX", "GDXJ", "USFR", "SHV",
    "BIL", "SHY", "VGIT", "VGLT", "VOO", "VTI", "VXUS", "VWO",
    "IEMG", "EFA", "EWJ", "EWG", "BITO", "VXX",
    "TMF", "UPRO", "TQQQ", "SQQQ", "SPXU", "TNA", "FAS",
    "UCO", "ERX", "YINN", "TUR", "PDBC", "VDE", "VUG", "VFH",
    "IWN", "USL", "ARKK",
}
```

---

## 4. 模块二：因果检验与逻辑失效机制 (causal_auditor.py)

### 4.1 核心职责

为每一条 AI 投资建议注入**可被系统自动回测的失效条件**。这是一套轻量级状态机——48 小时后 market_fetcher 自动拉取数据、与 trigger 条件比对、输出 `VALID` / `INVALIDATED` / `STALE` 判定。

### 4.2 状态机定义

```
                      ┌─────────────────┐
         生成建议     │   ACTIVE (活跃)  │
     ───────────────▶ │                  │
                      └────────┬────────┘
                               │
               ┌───────────────┼───────────────┐
               │               │               │
         条件满足          条件触发       超过有效期限
               │               │               │
               ▼               ▼               ▼
        ┌──────────┐   ┌──────────────┐  ┌──────────┐
        │  VALID   │   │ INVALIDATED  │  │  STALE   │
        │ (持续有效)│   │ (逻辑失效)   │  │ (过期)   │
        └──────────┘   └──────┬───────┘  └──────────┘
                              │
                        自动生成反向信号
                       (如: 原建议 BUY GLD →
                        失效后 SELL GLD)
```

### 4.3 InvalidationTrigger 数据结构

```python
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class InvalidationTrigger:
    """单个失效触发器"""
    trigger_id: str                    # 唯一标识
    trigger_type: str                  # "macro" | "technical" | "sentiment"
    description: str                   # 人类可读描述
    check_source: str                  # 数据来源 ("finnhub", "fred", "yahoo")
    check_endpoint: str                # API 端点或字段名
    check_operator: str                # "gt" | "lt" | "gte" | "lte" | "eq" | "cross_above" | "cross_below"
    check_threshold: float             # 阈值
    check_period_hours: int = 48       # 几小时后开始检查

@dataclass
class AuditState:
    """因果审计状态"""
    audit_id: str                      # 唯一审计 ID
    thesis_id: str                     # 对应的投资论据 ID
    created_at: str                    # ISO 时间戳
    status: str                        # "ACTIVE" | "VALID" | "INVALIDATED" | "STALE"
    invalidation_triggers: List[InvalidationTrigger]
    triggered_by: Optional[str] = None # 哪个 trigger 导致了失效
    invalidated_at: Optional[str] = None
    auto_signal: Optional[str] = None  # 自动生成的反向信号

@dataclass
class AuditReport:
    """一次审计运行的输出"""
    date: str
    audits_checked: int
    active_count: int
    invalidated_count: int
    details: List[AuditState]
```

---

## 5. 模块三：激进数据挖掘与信源治理 (source_governor.py)

### 5.1 核心职责

扫描 24 小时新闻流，识别"奇点事件"，通过**信源权重系统 (SAR — Source Authority Rating)** 和**三角形校验法则**过滤不可靠叙事。

### 5.2 信源权重系统 (SAR)

```python
# config/source_authority.py — 静态信源权重表

SOURCE_AUTHORITY_RATING = {
    # Tier 1: 官方一手数据 (权重 1.0) — 必须至少 1 个
    "federal_reserve":    {"weight": 1.0, "type": "official_data"},
    "bls_gov":            {"weight": 1.0, "type": "official_data"},
    "eia_gov":            {"weight": 1.0, "type": "official_data"},
    "ecb_europa":         {"weight": 1.0, "type": "official_data"},
    "pboe_uk":            {"weight": 1.0, "type": "official_data"},
    "opec_org":           {"weight": 0.95, "type": "official_data"},

    # Tier 2: 权威财经终端
    "reuters":            {"weight": 0.85, "type": "wire_service"},
    "bloomberg":          {"weight": 0.85, "type": "wire_service"},
    "wsj":                {"weight": 0.80, "type": "financial_press"},
    "financial_times":    {"weight": 0.80, "type": "financial_press"},

    # Tier 3: 专业分析/数据商
    "finnhub":            {"weight": 0.70, "type": "data_aggregator"},
    "fred_stlouisfed":    {"weight": 0.75, "type": "official_data"},
    "trading_economics":  {"weight": 0.65, "type": "data_aggregator"},

    # Tier 4: 社交媒体
    "twitter_finance":    {"weight": 0.30, "type": "social_media"},
    "reddit_wallstreet":  {"weight": 0.20, "type": "social_media"},
    "stocktwits":         {"weight": 0.20, "type": "social_media"},

    # Tier 0: 未知来源
    "unknown":            {"weight": 0.0, "type": "untrusted"},
}
```

### 5.3 三角形校验法则 (Triangulation Rule)

**核心原则**: 一个宏观叙事必须在以下三个维度中至少两个维度得到独立信源的交叉验证，否则标记为 `unreliable`。

```
                    维度 A: 官方数据
                   (Tier 1 信源)
                       /\
                      /  \
                     /    \
                    / 叙事 \
                   /  通过? \
                  /__________\
    维度 B: 权威媒体             维度 C: 物理流量数据
    (Tier 2 信源)               (港口/卫星/运费等)
```

**校验逻辑:**

```
def triangulate(narrative: Narrative) -> TriangulationResult:
    evidence = {
        "official_data": 0,   # Tier 1 信源命中数
        "authoritative": 0,   # Tier 2 信源命中数
        "physical_flow": 0,   # 物理流量数据命中数
    }

    for source in narrative.sources:
        tier = SOURCE_AUTHORITY_RATING[source]["type"]
        if tier == "official_data":
            evidence["official_data"] += 1
        elif tier in ("wire_service", "financial_press"):
            evidence["authoritative"] += 1
        elif tier == "physical_flow":
            evidence["physical_flow"] += 1

    # 必须至少有 1 个 Tier 1 官方数据源
    if evidence["official_data"] == 0:
        return TriangulationResult.UNRELIABLE("缺少官方数据支撑")

    # 三个维度中至少两个有命中
    dimensions_with_hits = sum(1 for v in evidence.values() if v > 0)
    if dimensions_with_hits >= 2:
        return TriangulationResult.RELIABLE

    return TriangulationResult.UNRELIABLE("信源维度不足")
```

---

## 6. 模块四：深度推演协议 (continuation_protocol.py)

### 6.1 问题陈述

DeepSeek API 有 `max_tokens` 上限（默认 8192）。当触发一个复杂宏观叙事时，单次 API 调用可能无法完整覆盖所有维度的深度分析。

### 6.2 解决方案：JSON 块续写协议

不依赖 API 的流式特性，而是通过**结构化续写指令**实现多轮递归调用。

### 6.3 协议流程

```
┌─────────────────────────────────────────────────────────────┐
│  continuation_protocol.py                                   │
│                                                             │
│  输入: FullAnalysisRequest                                  │
│  {                                                          │
│    "narrative": "...",                                      │
│    "asset_basket": {...},                                   │
│    "required_sections": [                                   │
│      "macro_analysis",                                      │
│      "fundamental_deep_dive",                               │
│      "technical_context",                                   │
│      "sentiment_landscape",                                 │
│      "event_risk_calendar",                                 │
│      "scenario_analysis",                                   │
│      "final_reasoning",                                     │
│      "causal_audit_triggers",                               │
│    ],                                                       │
│    "max_tokens_per_call": 4096,                             │
│    "total_max_calls": 5,                                    │
│  }                                                          │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Round 1: dispatch_prompt()                                 │
│  System: "你是宏观分析师。逐节展开分析..."                    │
│  User: {"narrative": "...", "section": "macro_analysis"}    │
│                                                             │
│  Response JSON:                                             │
│  {                                                          │
│    "section": "macro_analysis",                             │
│    "content": "...(分析内容)...",                            │
│    "continuation": {                                        │
│      "more_sections_remaining": true,                       │
│      "next_section": "fundamental_deep_dive",               │
│      "cumulative_token_estimate": 3200                      │
│    }                                                        │
│  }                                                          │
└─────────────────────────┬───────────────────────────────────┘
                          │ continuation.more_sections_remaining == true
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Round 2: dispatch_prompt()                                 │
│  User: {"narrative": "...",                                 │
│         "section": "fundamental_deep_dive",                 │
│         "previous_sections": {"macro_analysis": "..."}}     │
│                                                             │
│  ... (继续直到所有 section 完成 或 达到 max_calls 熔断)      │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  中转层 (ContinuationMerger):                               │
│                                                             │
│  1. 收集所有 Round 的 JSON 响应                              │
│  2. 按 section 字段合并 → 完整的 DeepResearch JSON           │
│  3. 校验: 所有 required_sections 是否都已产出?               │
│  4. 如果某些 section 缺失 (熔断触发):                        │
│     → 在缺失位置插入 {section: "xxx", content:               │
│        "[SYSTEM NOTE: Section truncated — max_calls reached.]│
│          Please re-run with narrower scope."}                │
│  5. 通过 clean_ascii_only() 净化                             │
│  6. 输出完整 JSON → 交给 output_formatter.py 渲染            │
└─────────────────────────────────────────────────────────────┘
```

---

## 7. 核心数据结构定义 (Data Schema)

### 7.1 Narrative (宏观叙事)

```python
@dataclass
class NarrativeSource:
    """信源记录"""
    source_name: str          # 信源名称 (对应 SAR 表 key)
    source_type: str          # "official_data" | "wire_service" | ...
    source_weight: float      # SAR 权重
    article_title: str
    article_url: str
    publish_time: str
    extracted_keywords: List[str]

@dataclass
class Narrative:
    """一个宏观叙事"""
    narrative_id: str
    title: str
    narrative_type: str       # 对应 ASSET_UNIVERSE 的 tag
    description: str
    sources: List[NarrativeSource]
    quadrant: str
    reliability: str          # "RELIABLE" | "UNRELIABLE" | "PENDING"
    triangulation_score: float
    created_at: str
```

### 7.2 AssetBasket (三维配置篮子)

```python
@dataclass
class AssetGroup:
    """单个维度的资产组"""
    dimension: str            # "high_liquidity" | "low_expense" | "high_beta"
    tickers: List[str]
    rationale: str

@dataclass
class AssetBasket:
    """完整三维篮子"""
    basket_id: str
    narrative_ref: str
    high_liquidity: AssetGroup
    low_expense: AssetGroup
    high_beta: AssetGroup
    filtered_out: List[str]
    filter_reasons: dict
```

### 7.3 ScoutReport (最终输出 — 喂给 output_formatter 的完整 JSON)

```python
SCOUT_REPORT_SCHEMA = {
    "executive_summary": {
        "signal": "BUY / SELL / HOLD / OBSERVE",
        "weighted_score": float (0-100),
        "conviction_level": "HIGH / MEDIUM / LOW",
        "one_liner": str,
        "override_available": bool,
    },
    "trading_decision": {
        "action": str,
        "max_shares": int,
        "max_notional": float,
        "cash_reserve_kept": float,
        "price_target_suggestion": str,
    },
    "deep_research": {
        "macro_analysis": str,
        "fundamental_deep_dive": str,
        "technical_context": str,
        "sentiment_landscape": str,
        "event_risk_calendar": str,
        "scenario_analysis": str,
        "final_reasoning": str,
    },
    "risk_assessment": {
        "max_loss_scenario": str,
        "stop_loss_level": str,
        "correlation_risk": str,
        "liquidity_concern": str,
        "overall_risk_rating": str,
    },
    "action_plan": {
        "immediate_steps": List[str],
        "contingency_triggers": List[str],
        "review_timeline": str,
    },
    # ===== Phase 5 新增字段 =====
    "scout_metadata": {
        "scan_timestamp": str,
        "narratives_detected": List[Narrative],
        "triangulation_summary": {
            "total_scanned": int,
            "reliable_count": int,
            "unreliable_count": int,
        },
    },
    "asset_basket": AssetBasket,
    "causal_audit": {
        "thesis_id": str,
        "audit_id": str,
        "invalidation_triggers": List[InvalidationTrigger],
        "auto_review_scheduled": str,
    },
}
```

---

## 8. Phase 5 分步开发计划

| Step | 模块 | 预估人天 | 测试数 (预估) |
|------|------|----------|---------------|
| 1 | scout_types + 配置表 | 1 | 15 |
| 2 | asset_mapper.py | 2 | 20 |
| 3 | source_governor.py | 2 | 25 |
| 4 | causal_auditor.py | 2 | 20 |
| 5 | continuation_protocol.py | 1.5 | 15 |
| 6 | output_formatter 扩展 | 1 | 20 |
| 7 | orchestrator + 集成测试 | 1.5 | 15 |
| **总计** | | **11 天** | **~130 tests** |

---

## 9. 风险与降级预案

| 风险点 | 概率 | 影响 | 降级方案 |
|--------|------|------|----------|
| DeepSeek API 多轮调用成本过高 | 中 | 中 | 单轮模式 (continuation_protocol 降级为单次调用, max_calls=1) |
| EIA/FRED API 限流导致三角形校验缺失 | 高 | 低 | 降级为二维校验 (仅官方数据 + 权威媒体), 标注 decreased confidence |
| ASSET_UNIVERSE 未覆盖新 Tag | 中 | 中 | 新增 fallback_assets 通用篮子配置 + 日志告警提示手动扩展 |
| 48 小时失效检查误触发 (数据延迟) | 低 | 中 | 增加 check_grace_period_hours 容错窗口参数 |
| Robinhood 白名单变动 (股票下架) | 低 | 高 | Phase 6 实现动态白名单同步 API, Phase 5 使用手动维护静态表 |

---

*Blueprint approved by PM on 2026-05-05.*