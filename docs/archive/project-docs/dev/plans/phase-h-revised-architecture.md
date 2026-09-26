# MarketMind Phase H: 深度分析增强 — 修订架构方案

**日期**: 2026-05-18 | **版本**: v2 (修订) | **基于**: 3 份红方审计 + 资产类别路由设计 + 外网方案研究 + 原方案 v1 | **状态**: 待用户审批

---

## 零、v1 → v2 变更摘要

| 审计发现 | v1 问题 | v2 修正 |
|------|------|------|
| 逻辑 C1 | 因果分解对所有资产用同一资产负债框架 | 加资产类别路由 — 5 种资产类别各有自己的分解透镜 |
| 逻辑 C2 | 资金流实体模型只适用美债 | 实体模型按资产类别键控 — 日元用 BoJ/GPIF/散户，欧股用 ECB/机构/出口商 |
| 架构 C1 | investigation_loop 918 行超硬上限 | ✅ 已拆分为 5 模块，主文件 486 行 |
| 架构 C2 | HypothesisResult 不流向决策阶段 | ✅ 已接入 generate_decision() |
| 安全 H-SEC-1 | 外部数据无清洗入 LLM | ✅ input_guard 已接入 gateway |
| 安全 H-SEC-2 | API 成本无上限 | ✅ MAX_PRO_CALLS_PER_SESSION=30 |
| 安全 H-SEC-3 | 异常静默吞没 | ✅ macro_data 异常已加日志 |
| 逻辑 H3 | 体制映射 1985-2025 偏牛市 | 加预 1985 定性数据 + 变量加权（通胀期 CPI 权重翻倍）|
| 逻辑 H4 | 情景预测过滤掉尾部风险 | MONITOR 假设抽样 1 个做反向情景分析 |
| 逻辑 H5 | 脆弱性阈值无过期检测 | 每条阈值加 last_validated 字段 + 季度复核协议 |
| 逻辑 H6 | 术语库无"我不知道"逃生口 | 每条 LLM prompt 追加："如果遇到你不认识的机制，明确说'我不知道'，不要猜测" |
| 逻辑 H7 | 6 模块信号各自输出无合成 | Decision 阶段加信号冲突检测 + 加权合成步骤 |

---

## 一、架构原则（不变）

1. 管道单向流动：Stage N → Stage N+1
2. 所有 LLM 调用通过 gateway（chat_flash / chat_pro）
3. 新模块渐进增强，不替代现有代码
4. pipeline-manifest.yaml 为单源真理
5. 每个新模块单一入口 + 明确 dataclass 契约
6. PICA 全协议（Unit → Security → Integration → Regression）
7. 数据模块例外（常量/枚举/配置允许多导出）

---

## 二、资产类别路由层（新增）

v2 最关键的新增：所有分析模块在启动前必须经过路由分类。

### 2.1 资产类别分类

```python
# config/asset_class_routing.py — 数据模块
ASSET_CLASS_TAXONOMY = {
    "US_FIXED_INCOME": {
        "keywords": ["Treasury", "美债", "国债", "TIPS", "MBS", "agency", "SOFR", "Fed", "美联储"],
        "tickers": ["TLT", "IEF", "SHY", "AGG", "MBB"],
        "decomposition_lens": "balance_sheet",  # 资产负债端分解
        "entity_types": ["US_HOUSEHOLD", "US_INSTITUTIONAL", "FOREIGN_OFFICIAL", "FOREIGN_PRIVATE", "FED"],
        "net_directional_force": "net_liquidity_impact",  # -1 (抽水) to +1 (放水)
        "key_data_sources": ["FRED:WALCL", "FRED:RRPONTSYD", "FRED:WTREGEN", "FRED:WRBWFRBL"]
    },
    "US_EQUITIES": {
        "keywords": ["S&P", "Nasdaq", "美股", "标普", "科技股", "AI", "earnings", "估值"],
        "tickers": ["SPY", "QQQ", "IWM", "DIA"],
        "decomposition_lens": "earnings_discount_rate",  # 盈利/折现率/回购/资金流
        "entity_types": ["RETAIL", "INSTITUTIONAL", "CORPORATE_BUYBACK", "FOREIGN_INVESTOR", "HEDGE_FUND"],
        "net_directional_force": "net_flow_pressure",
        "key_data_sources": ["FRED:SP500", "market_data:SPY", "FRED:GS10", "FRED:T10Y2Y"]
    },
    "COMMODITIES": {
        "keywords": ["原油", "黄金", "铜", "大豆", "天然气", "crude", "gold", "copper"],
        "tickers": ["GLD", "USO", "UNG", "DBA", "CPER"],
        "decomposition_lens": "supply_demand_inventory",  # 供需/库存/地缘
        "entity_types": ["PRODUCER", "CONSUMER", "SPECULATOR", "EXCHANGE_INVENTORY", "SOVEREIGN_RESERVE"],
        "net_directional_force": "net_supply_demand_balance",
        "key_data_sources": ["EIA:inventory", "CFTC:COT", "LME:warehouse", "customs:import_export"]
    },
    "FX": {
        "keywords": ["EUR/USD", "USD/JPY", "美元指数", "DXY", "汇率", "yen", "euro"],
        "tickers": ["UUP", "FXY", "FXE"],
        "decomposition_lens": "dual_central_bank_carry",  # 双央行/利差/资本流
        "entity_types": ["CENTRAL_BANK_A", "CENTRAL_BANK_B", "CARRY_TRADER", "CORPORATE_HEDGER", "SOVEREIGN_FUND"],
        "net_directional_force": "net_carry_pressure",
        "key_data_sources": ["FRED:DEXJPUS", "FRED:DEXUSEU", "BIS:cross_currency_basis", "CFTC:COT_FX"]
    },
    "CRYPTO": {
        "keywords": ["BTC", "ETH", "比特币", "加密货币", "blockchain", "DeFi"],
        "tickers": ["BTC-USD", "ETH-USD"],
        "decomposition_lens": "onchain_offchain",  # 链上(交易所储备/哈希率) + 链下(ETF流/监管)
        "entity_types": ["EXCHANGE_RESERVE", "MINER", "ETF_ISSUER", "STABLECOIN_ISSUER", "RETAIL_HODLER"],
        "net_directional_force": "net_accumulation_pressure",
        "key_data_sources": ["crypto:exchange_reserves", "crypto:hash_rate", "market_data:BTC-USD", "ETF_flow:BITB"]
    }
}
```

### 2.2 路由逻辑

在 causal_decomposition 和 flow_decomposition 入口处调用 `route_asset_class(hypothesis_text, affected_tickers) -> AssetClass`。路由优先级：ticker 匹配 > 关键词密度 > LLM 分类（fallback）。

---

## 三、增强模块设计（修订）

### 模块 0：资产类别路由（优先级 0 — 先决条件）

**文件**: `config/asset_class_routing.py`（数据模块）

**内容**: 上述 ASSET_CLASS_TAXONOMY + `route_asset_class(text, tickers) -> AssetClass` 函数。

**零新代码** — 纯数据 + 一个关键词匹配函数。

### 模块 0.5：机制术语库（优先级 1）

**文件**: `config/mechanism_glossary.py`（数据模块）

**内容**: ~40 个机制术语映射。每个条目：机制名、描述、数据源、方向含义、相关机制。

**逃生口**: 所有 Pro prompt 追加："如果遇到你无法确认的机制或工具，明确说'我无法确认该机制的具体运作方式'，不要猜测或编造名称。"

### 模块 1：因果分解 `causal_decomposition.py`（优先级 2）

**与原方案相同，加上**：
- 入口处调用 `route_asset_class()` 确定分解透镜
- 按资产类别选择因子模板（资产负债表 vs 供需 vs 双央行 vs 链上）
- `net_liquidity_impact` 仅对 US_FIXED_INCOME 有效；其他类别用对应的 `net_directional_force`
- 若路由失败（无法分类）→ 返回 None，管道继续

### 模块 2：资金流分解 `flow_decomposition.py`（优先级 3）

**与原方案相同，加上**：
- 实体类型从 `ASSET_CLASS_TAXONOMY[class].entity_types` 动态获取
- 非美资产用当地主导实体（日元：BoJ、GPIF、日本散户、外国对冲基金、日本银行）
- TIC 数据仅用于美国资产；BIS 地域银行统计用于跨境流

### 模块 3：历史体制映射 `regime_mapper.py`（优先级 4）

**修正**：
- 预 1985 年定性数据层（1970s 滞胀、Volcker 时代、大萧条）作为手动标注的 regime 记录
- 变量加权：CPI 主导的 regime 中 CPI 权重 ×2，增长主导中 GDP 权重 ×2
- 每次输出声明："模型仅基于 1985-2025 数据训练。若当前体制与 1970s 滞胀类似，定量类似度可能被低估"
- 保留旧版关键词 fallback

### 模块 4：条件预测 `scenario_forecaster.py`（优先级 5）

**修正**：
- 对所有 ACTIONABLE 假设运行（不变）
- 额外从 MONITOR 的高 `bear_case_confidence` 假设中抽样 1 个做反向情景（"如果看空是对的"）
- 情景树输出标注："以下为条件预测，每个路径依赖假设条件成立。实际结果取决于条件变量的最终状态"

### 模块 5：脆弱性扫描 `fragility_scanner.py`（优先级 7）

**修正**：
- 每条阈值加 `last_validated: str`（ISO 日期）和 `source_document: str`（引用来源）
- 季度复核协议：`validate_thresholds()` 检查所有阈值的 last_validated，>90 天未验证的标记为 STALE
- 过期阈值不删除 — 降级为 "历史参考"，不再触发告警
- 阈值库版本号：`version: "2026-05-18"`，每次修改递增

### 模块 6：跨境资本流 `cross_border_analyzer.py`（优先级 8）

**不变** — 原方案已考虑。新增 TLS 验证要求（`verify=True`）、BIS API key 配置、TIC 匿名访问文档化。

---

## 四、跨模块冲突解决（新增）

**问题**: 6 个模块产出独立信号。因果说看空、资金流说看多 — 都存着，都不合成。

**解决**: 在 `decision.py` 的 `generate_decision()` 中加信号冲突检测：

```python
def _detect_signal_conflicts(hypotheses: list[HypothesisResult]) -> list[SignalConflict]:
    """Find where independent modules disagree on the same hypothesis."""
    # For each hypothesis, check:
    #  - causal.net_directional_force vs flow.flow_imbalance
    #  - scenario.base_case.probability vs fragility overall_score
    #  - regime.top_analogue forward return vs scenario expected return
    # Flag contradictions where one signal >0.6 and another <0.4
```

冲突不自动解决 — 标记为 "ANALYST_DISAGREEMENT" 并呈现给用户在 decision card 中作为风险提示。

---

## 五、实施阶段（修订）

### 前置（已完成 ✅）

| 步骤 | 内容 |
|:---:|------|
| ✅ | 安全修复（原子写入、安全反序列化、异常日志）|
| ✅ | 模块提取（investigation_loop 918→486、app.py 971→76）|
| ✅ | input_guard 接线 gateway |
| ✅ | HypothesisResult 接线 decision |
| ✅ | API 成本上限 |
| ✅ | PICA 全协议制品（35 个）|

### Phase H-0: 资产路由 + 术语库（零破坏）

| 步骤 | 内容 | 新文件 | 行数 |
|:---:|------|------|:---:|
| 0.1 | `asset_class_routing.py` | `config/` | ~100 |
| 0.2 | `mechanism_glossary.py` | `config/` | ~100 |
| 0.3 | 3 文件 prompt 更新（机制术语注入）| — | ~20 |

### Phase H-1: 因果分解 + 资金流（并行）

| 步骤 | 内容 | 行数 |
|:---:|------|:---:|
| 1.1 | `causal_decomposition.py` | ~250 |
| 1.2 | `flow_decomposition.py` | ~250 |
| 1.3 | 集成进 investigation_loop | ~30 |

### Phase H-2: 体制映射 + 条件预测（并行）

| 步骤 | 内容 | 行数 |
|:---:|------|:---:|
| 2.1 | `regime_library.py` (config) | ~80 |
| 2.2 | `regime_mapper.py` | ~300 |
| 2.3 | `scenario_forecaster.py` | ~250 |

### Phase H-3: 脆弱性 + 跨境（并行）

| 步骤 | 内容 | 行数 |
|:---:|------|:---:|
| 3.1 | `fragility_thresholds.py` (config) | ~80 |
| 3.2 | `fragility_scanner.py` | ~300 |
| 3.3 | `cross_border.py` (gateway) + analyzer | ~450 |

### Phase H-4: 合成 + 端到端

| 步骤 | 内容 |
|:---:|------|
| 4.1 | decision.py 信号冲突检测 |
| 4.2 | app.py Gate 1 接线（--mode gate1 / --mode full）|
| 4.3 | orchestration.py 拆分（run_stages_0_3 / run_gate1 / run_stages_4_10）|
| 4.4 | 端到端集成测试 |

---

## 六、兼容性

- 与影子生态不冲突（增强模块只在主 AI 管道运行）
- 与 L1/L2/L3 不冲突（增强在 Stage 2b 内部，L1 之前）
- 所有新模块 ≤ 500 行
- 每个模块单一入口 + 明确数据契约
- 向后兼容：新字段有默认值，旧管道路径不变

---

**方案状态**: 待用户审批
