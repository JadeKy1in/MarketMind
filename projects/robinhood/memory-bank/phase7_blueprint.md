# Phase 7 — 认知引擎升维：马赛克推理与红军对抗网络 架构蓝图

**文档版本**: v1.0  
**日期**: 2026-05-05  
**状态**: APPROVED  
**上层依赖**: Phase 6 (The Fund Manager) 双轨决策引擎  
**设计原则**: 零新增第三方依赖，继承 SPARC 认知循环，严格遵守物理隔离天条  

---

## 目录

1. [认知跃迁定位：从 Fund Manager 到 Signal Intelligence Agency](#1-认知跃迁定位从-fund-manager-到-signal-intelligence-agency)
2. [另类数据发现层 (Alternative Data Hooks)](#2-另类数据发现层-alternative-data-hooks)
3. [红方对抗监督模块 (Red Team Auditor)](#3-红方对抗监督模块-red-team-auditor)
4. [深度推演 Prompts 重构：马赛克推理协议](#4-深度推演-prompts-重构马赛克推理协议)
5. [模块交互与数据流](#5-模块交互与数据流)
6. [Phase 7 分步开发计划](#6-phase-7-分步开发计划)
7. [风险与降级预案](#7-风险与降级预案)

---

## 1. 认知跃迁定位：从 Fund Manager 到 Signal Intelligence Agency

```
Phase 5 (The Scout):               Phase 6 (The Fund Manager):        Phase 7 (认知引擎升维):

  "发现机会"         ────────▶       "权衡后下注或不注"   ────────▶    "从噪声中提取信号真相"
  雷达扫描 (Radar)                  双轨决策 (Dual-Track)              马赛克推理 + 红军对抗
  叙事提取 + 资产映射              风险收益画像 + 仓位建议             另类数据钩子 + 逻辑破绽攻击
  因果检验标记                      铁证卖出 + 触发阈值               物理验证指标 + 反身性检验
  信源三角形校验                    订单结构生成 (Order JSON)          跨界关联 + 逆向思考
```

**核心哲学跃迁**：Phase 6 的 Fund Manager 仍然在处理"表层公开数据"——宏观指标、技术图表、新闻情绪。这些数据已经被市场广泛定价，Alpha 衰减严重。

Phase 7 将系统升级为 **Signal Intelligence Agency（信号情报机构）**，核心能力包括：

1. **穿透公开噪声**：通过边缘/非传统数据维度，在信息不对称中获取认知优势。
2. **马赛克拼图**：将碎片化的另类数据拼接为连贯叙事，像分析师追踪爱泼斯坦案一样追踪资本暗流。
3. **自我对抗**：在生成最终结论前，由独立红方 AI 攻击所有逻辑链条，要求提供无法被操纵的物理验证指标。
4. **反身性思维**：不仅分析市场，还要分析"市场对市场预期的预期"——即索罗斯反身性理论在认知层的映射。

### 与现有架构的整合点

| 上游模块 (Phase 1-6) | 提供给 Phase 7 的数据 | Phase 7 消费方式 |
|---|---|---|
| `sentiment_collector.py` | 情绪汇总 (SentimentReport) | 作为"表层共识"基线，红方审计对比 |
| `scout_types.MacroTag` | 宏观叙事标签 + 置信度 | 作为主干叙事线，另类数据挂钩 |
| `causal_auditor.py` | 因果检验状态 + 触发器 | 红方模块在此之上增加二阶攻击 |
| `qualitative_judgment.py` | 三维打分明细 + 决策轨道 | Phase 7 新增"穿透修正系数" |
| `buy_protocol.py` | RiskProfile + AssetPenetration | 红方在买入建议生成前注入物理验证 |
| `sell_protocol.py` | LiquidationReport | 红方检验"铁证"是否真正是铁证 |

### 架构分层明确：Phase 7 不替代任何现有模块

Phase 7 在 Phase 5 (Scout) 输出之后、Phase 6 (Fund Manager) 决策之前，插入一个**平行的认知增强层**：

```
Phase 5 Scout Report
       │
       ▼
Phase 7 认知引擎升维 ─────────────────────────────────────┐
  ├─ 另类数据发现层 (Alternative Data Hooks)               │
  │   └─ 生成: AlternativeSignalMatrix                    │
  ├─ 深度推演 Prompt 重构 (Mosaic Reasoning Protocol)      │
  │   └─ 生成: MosaicNarrative（增强版 MacroTag）          │
  └─ 红方对抗监督 (Red Team Auditor)                      │
      └─ 生成: RedTeamAuditReport                         │
       │                                                   │
       ▼                                                   │
Phase 6 Fund Manager (原封不动，但输入增强)                 │
  └─ 定性判定引擎接收增强后的信号                          │
       │                                                   │
       ▼                                                   │
Final Markdown 研报（包含红方审计附录） ◄──────────────────┘
```

---

## 2. 另类数据发现层 (Alternative Data Hooks)

### 2.1 设计哲学

我们从三份顶级研报中提取出以下认知模式：

- **爱泼斯坦案分析**：同时追踪私人航空热力图（肉身流动）、日内瓦/新加坡自由港仓储（实物资产转移）、门罗币独立走势（匿名资本逃逸）、CEO离职潮异常率（职业信号）、VIX异常压制（衍生品操纵）——**五个完全独立的数据维度，在时间轴上严格收敛**。
- **美联储框架分析**：从 TGA 账户/银行准备金/短期国债发行结构/SLR 监管/基差套利/外汇掉期/稳定币——**七个看似不相关的金融基础设施变量中，推导出唯一的流动性结论**。
- **AI云服务与地缘分析**：从AI巨头计费模式转变（Token使用量）、阿联酋退出OPEC+、美元指数与WTI脱钩——**三个跨界维度中，推断出中东权力洗牌和云服务估值重定价的宏观趋势**。

共同特征：**每个分析都使用了至少 3 个以上非传统数据维度，在时间/空间/逻辑上形成交叉验证**。

### 2.2 另类数据维度分类体系

设计五层另类数据钩子（Alternative Data Hook Layers），从最公开到最隐秘逐层加深：

```
Layer 1 — 公开但被忽视的数据 (Public but Neglected)
  ├─ 监管文件变更追踪 (SEC EDGAR 13F/13D/Form 4 申报异动)
  ├─ 美联储逆回购/准备金/TGA 周度数据 (已部分在现有系统中)
  ├─ CFTC 期货持仓报告异常 (COT Report 非商业头寸极端值)
  └─ 公司债 CDS Spread 异动

Layer 2 — 半公开的结构化数据 (Semi-Public Structured)
  ├─ 高管离职/招聘数据：LinkedIn/Glassdoor 职位变动爬取
  │   (CEO/CFO/CTO 离职率、关键岗位招聘方向异常)
  ├─ 私募/风投融资轮次方向变化 (行业资金流向雷达)
  ├─ 专利申报方向聚类分析
  └─ 供应链中断/物流异常信号 (海运运价指数、港口拥堵数据)

Layer 3 — 金融市场微观结构异动 (Microstructure Anomalies)
  ├─ 期权市场异常：Put/Call Ratio 极端值、VIX 期限结构倒挂
  ├─ 加密货币异常：隐私币 vs 公链币 价格背离 (门罗币/大饼比率)
  ├─ 暗池交易量占比突增 (Dark Pool Volume %)
  ├─ 大宗交易折价率变化 (Block Trade Discount %)
  └─ 做空利息 vs 股价 背离信号 (Short Interest 与价格同涨)

Layer 4 — 地缘与物理世界信号 (Geo-Physical Signals)
  ├─ 私人航空热力图 (Private Jet Traffic to specific jurisdictions)
  ├─ 自由港/保税区仓储占用率 (Geneva Freeport / Singapore Le Freeport)
  ├─ 主权基金配置方向变更 (Sovereign Wealth Fund 13F 申报)
  ├─ 国家间货币互换协议签署动态
  └─ 特定法域离岸公司注册数量异常

Layer 5 — 反身性元信号 (Reflexive Meta-Signals)
  ├─ 金融媒体/分析师共识度指数 (Consensus Fragility Index)
  │   — 当 80% 以上分析师看多时，逆向标记为"拥挤交易风险"
  ├─ 联邦基金利率期货隐含概率突变 (FOMC Probability Spike)
  ├─ 信用评级机构评级展望变更前兆 (CDS 领先评级行动 30-90 天)
  └─ VIX 波动率曲面异常 (Volatility Smile/Skew 极端化)
```

### 2.3 核心数据结构：AlternativeSignalMatrix

```python
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum

class SignalLayer(Enum):
    L1_PUBLIC_NEGLECTED = "layer_1_public_neglected"
    L2_SEMI_PUBLIC = "layer_2_semi_public"
    L3_MICROSTRUCTURE = "layer_3_microstructure"
    L4_GEO_PHYSICAL = "layer_4_geo_physical"
    L5_REFLEXIVE_META = "layer_5_reflexive_meta"

class SignalDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    DIVERGENT = "divergent"  # 信号本身不明确方向，但表示异常值得关注
    CONTRARIAN = "contrarian"  # 与市场共识相反

@dataclass
class AlternativeSignal:
    """单个另类数据信号"""
    signal_id: str
    layer: SignalLayer
    source_name: str                    # e.g. "monero_btc_ratio", "ceo_departure_rate"
    source_description: str             # 数据源的人类可读描述
    current_value: float
    baseline_mean: float               # 历史均值 (作为偏离基准)
    z_score: float                     # 当前值偏离历史均值的标准差
    direction: SignalDirection
    confidence: float                  # 0.0-1.0 信号可靠性 (数据质量而非方向置信度)
    lookback_window_days: int          # 用于计算基线的回溯天数
    last_updated: str                  # ISO timestamp
    reasoning_hook: str                # 该信号如何链接到当前宏观叙事的提示 (供 LLM 使用)
    manipulation_risk: str             # 该指标的潜在被操纵风险描述

@dataclass
class AlternativeSignalMatrix:
    """五层另类数据信号矩阵"""
    matrix_id: str
    generated_at: str
    
    # 五层信号列表
    l1_signals: List[AlternativeSignal]  # 公开但被忽视
    l2_signals: List[AlternativeSignal]  # 半公开结构化
    l3_signals: List[AlternativeSignal]  # 微观结构异动
    l4_signals: List[AlternativeSignal]  # 地缘物理信号
    l5_signals: List[AlternativeSignal]  # 反身性元信号
    
    # 交叉验证统计
    layer_convergence_count: int       # 有多少层产生了同向信号
    total_signals_generated: int
    convergence_narrative: str         # LLM 基于信号矩阵生成的马赛克叙事
    divergence_warnings: List[str]     # 各层信号矛盾之处
    
    # 与 Phase 5 ScoutReport 的关联引用
    linked_macro_tag_refs: List[str]   # 关联的 MacroTag ID 列表
```

### 2.4 信号交叉收敛判定规则

受爱泼斯坦案分析启发：**每个结论至少需要 3 个以上独立层级的信号在时间轴上收敛，单一层级信号不能触发任何结论。**

```
收敛判定规则：

Rule 1 — 三维交叉最低标准：
  ├─ 至少 3 个不同 SignalLayer 的信号方向一致
  ├─ 每个信号 z_score 绝对值 > 1.5 (显著偏离历史均值)
  └─ 信号时间窗口在 30 天内 (非陈旧信号)

Rule 2 — 对抗性验证：
  ├─ 如果一个层级产生了与主流方向完全相反的信号
  │   (e.g. L1 看多但 L3 看空)，必须显式标记为 DIVERGENCE
  └─ 所有 DIVERGENCE 信号自动触发 Red Team 深度审计

Rule 3 — 操纵风险评估：
  ├─ 对于容易受单一实体操纵的指标
  │   (e.g. 单一股票期权 Put/Call Ratio) 减权处理
  ├─ 对于需要上千亿美元才能操纵的指标
  │   (e.g. 10年期美债利率、VIX) 加权处理
  └─ 权重体现为 confidence 乘数: 难以操纵 ×1.0, 易操纵 ×0.5
```

### 2.5 数据源实现策略（零外部依赖约束）

由于系统天条要求零新增第三方依赖，另类数据通过以下方式获取：

| 数据层 | 获取方式 | 技术路径 |
|---|---|---|
| SEC EDGAR (13F/Form 4) | SEC.gov 公开 RSS/HTML 抓取 | `urllib` + `html.parser` (标准库) |
| 美联储周度数据 (H.4.1/H.8) | Federal Reserve Data Download API | `urllib` GET CSV |
| CFTC COT Report | CFTC.gov 历史数据文件 | `urllib` GET TXT/CSV |
| 加密货币价格 | 公共 API (CoinGecko/CoinMarketCap 免费层) | `urllib` GET JSON |
| 高管离职数据 | 本地配置的观察列表 + 新闻标题抓取 | `urllib` + 本地 YAML 配置 |
| 期权/VIX 数据 | CBOE 公开延迟报价 | `urllib` GET |
| 主权基金 13F | SEC EDGAR (同上) | `urllib` + 解析 |

**所有数据获取均使用 Python 标准库，不引入任何新 pip 包。** 高频数据通过 `supervisor` 或 `cron` 定时拉取到本地缓存。

---

## 3. 红方对抗监督模块 (Red Team Auditor)

### 3.1 设计哲学

从三份顶级研报中提取出的"对抗性思维"模式：

- **爱泼斯坦案分析师**不断自问："如果这一切都是巧合呢？"然后用 VI 的异常、四巫日的精妙设计、离职潮的统计学反证来排除巧合假说。
- **美联储框架分析师**反复挑战"降息+缩表能否同时进行"的思维定式，从 TGA/银行准备金两个看似独立的账户中找到跷跷板关系。
- **AI/地缘分析师**拒绝将阿联酋退群简单归类为"亲美"或"反美"，而是用主权独立的经济逻辑重新解释。

**红方模块不是一个"批评者"，而是一个结构化的魔鬼代言人引擎**。它必须接受以下训练约束：

1. 不能无脑反对（那没有信息量）
2. 必须针对具体的逻辑节点发起攻击
3. 每个攻击必须附带"如果逻辑成立，应观察到什么物理验证指标"
4. 如果物理验证指标未兑现，该逻辑链直接标记为 INVALIDATED

### 3.2 红方审计的三层攻击矩阵

```
Layer 1 — 数据层攻击 (Data Poisoning Attack)
  目标: 质疑输入数据的真实性和代表性
  
  攻击向量:
  ├─ A1.1 样本偏误: 该数据是否仅反映某一类资产/地区/时间段？
  ├─ A1.2 幸存者偏差: 是否忽略了已退市/已倒闭的样本？
  ├─ A1.3 发布延迟: 该数据反映的是多久前的现实？是否存在滞后？
  ├─ A1.4 口径变更: 该指标的统计口径近期是否发生过变化？
  └─ A1.5 操纵嫌疑: 该数据是否可能被单一实体人为扭曲？
  
  物理验证指标: 
  └─ 必须提出一个不受同一主体控制的独立验证数据源

Layer 2 — 逻辑层攻击 (Logic Chain Attack)
  目标: 攻击因果推理的"因为A所以B，因此C"链条
  
  攻击向量:
  ├─ A2.1 反向因果: B 是否可能是导致 A 的原因，而非结果？
  ├─ A2.2 遗漏变量: 是否存在第三变量 C 同时驱动 A 和 B？
  ├─ A2.3 阈值任意性: 为什么选 z_score > 1.5 而非 > 2.0？
  ├─ A2.4 时间错配: A 和 B 的时间先后关系是否足够精确？
  ├─ A2.5 合成谬误: 微观上成立的逻辑在宏观层面是否仍然成立？
  └─ A2.6 反身性循环: 市场预期是否已经改变了底层现实？
  
  物理验证指标:
  └─ 必须提出如果因果关系成立，应在未来 N 天观察到的具体数值变化

Layer 3 — 叙事层攻击 (Narrative Hijacking Attack)
  目标: 攻击整个宏观叙事框架的竞争性解释
  
  攻击向量:
  ├─ A3.1 反叙事构造: 用相同数据构造一个完全相反的叙事
  ├─ A3.2 历史类比陷阱: 当前情况是否真的与历史先例可比？
  ├─ A3.3 范式转换误判: 是真正的结构性变化还是周期性波动？
  ├─ A3.4 群体迷思: 该叙事是否只是当前市场共识的自我强化？
  └─ A3.5 利益冲突: 传播该叙事的机构是否从中获利？
  
  物理验证指标:
  └─ 必须提出一个可以证伪该叙事的关键事件/数据点，如果该事件不发生，则叙事无效
```

### 3.3 核心数据结构：RedTeamAuditReport

```python
@dataclass
class RedTeamAttack:
    """单个红军攻击向量"""
    attack_id: str
    attack_layer: str                  # "data" | "logic" | "narrative"
    attack_type: str                   # e.g. "A1.1_sample_bias", "A2.4_time_mismatch"
    target_claim: str                  # 被攻击的具体论断 (精确引用原文)
    attack_question: str               # 攻击性问题 (魔鬼代言人的角度)
    evidence_required: str             # 如果原逻辑成立，必须满足的证据
    physical_verification: str         # 物理验证指标 (可观测、不可操纵)
    verification_deadline_days: int    # 该指标必须在多少天内兑现
    severity: str                      # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    
    # 如果物理验证指标未兑现的后果
    consequence_if_failed: str         # 逻辑链作废声明
    fallback_action: str               # 如果验证失败，应采取什么替代方案

@dataclass
class RedTeamAuditReport:
    """红方审计完整报告"""
    audit_id: str
    audited_at: str
    audited_report_ref: str            # 被审计的 ScoutReport / OrderSuggestion ID
    
    # 审计对象 (分层)
    audited_macro_narrative: str       # 被审计的宏观叙事
    audited_logic_chains: List[str]    # 被审计的逻辑链条列表
    audited_data_sources: List[str]    # 被审计的数据源列表
    
    # 攻击结果
    attacks_launched: List[RedTeamAttack]
    total_attacks: int
    critical_findings: int             # CRITICAL 级别攻击数量
    
    # 生存性评估
    claims_invalidated: List[str]      # 被证明无效的论断
    claims_survived: List[str]         # 经受住攻击的论断
    claims_need_verification: List[str] # 需要等待物理验证的论断
    
    # 整体评估
    overall_resilience_score: float    # 0-100 逻辑链韧性评分
    pass_audit: bool                   # 是否通过审计 (只有 resilience > 70 才能通过)
    
    # 修正建议
    suggested_narrative_amendment: str # 基于审计结果修正后的叙事
    blind_spots_identified: List[str]  # 识别出的认知盲区
```

### 3.4 红方审计的硬性流转规则

```
          Phase 5 ScoutReport
          + AlternativeSignalMatrix
                   │
                   ▼
    ┌──────────────────────────────┐
    │  Phase 7.1: Mosaic Reasoning  │  ← 深度推演生成 MosaicNarrative
    │  (增强版叙事生成)              │
    └──────────────┬───────────────┘
                   │
                   ▼
    ┌──────────────────────────────┐
    │  Phase 7.2: Red Team Audit    │  ← 三层攻击矩阵启动
    │                              │
    │  遍历所有逻辑链:              │
    │  ├─ 数据层攻击 (5 类)        │
    │  ├─ 逻辑层攻击 (6 类)        │
    │  └─ 叙事层攻击 (5 类)        │
    │                              │
    │  生成 RedTeamAuditReport     │
    └──────────────┬───────────────┘
                   │
                   │  检查: overall_resilience_score >= 70?
                   │
         ┌─────────┴─────────┐
         │                   │
         ▼                   ▼
    pass_audit=true     pass_audit=false
         │                   │
         ▼                   ▼
  进入 Phase 6        退回 Phase 7.1 重推演
  Fund Manager        (携带红方识别的盲区)
         │                   │
         ▼                   │
  OrderSuggestion     重新生成 MosaicNarrative
  (附带审计附录)      ──────────────────────┐
         │                                   │
         │   最多重试 3 次，若仍不通过        │
         │   → 强制进入 Track A (OBSERVE)    │
         │   → 标记为 "认知盲区事件"          │
         │   → 存入 activeContext.md          │
         ▼
  Final Markdown 研报
  (包含完整的 RedTeamAuditReport 附录)
```

### 3.5 红方 Prompt 核心指令片段（概念级）

红方 AI 实例化时使用独立于主推演的系统提示：

```text
You are the Red Team Auditor. Your sole purpose is to attack every logical claim 
in the provided macro narrative. You are NOT a critic for criticism's sake—you are 
a structured adversary that:

1. For each claim, identify the weakest logical link.
2. For each weak link, propose a PHYSICAL VERIFICATION INDICATOR:
   - Must be OBSERVABLE (real-world measurable data point)
   - Must be UNMANIPULABLE (cost of faking > $10B or structurally impossible)
   - Must have a DEADLINE (must be observable within N days)
3. If the physical verification indicator is NOT observed by the deadline,
   the claim is INVALIDATED and must be removed from the narrative.

You have ZERO tolerance for:
- Circular reasoning (A proves B because B proves A)
- Unfalsifiable claims (no possible observation could disprove it)
- Authority arguments without evidence chains
- Narrative-first-then-evidence (confirmation bias)
```

---

## 4. 深度推演 Prompts 重构：马赛克推理协议

### 4.1 现有 Phase 5 推演协议的局限性

Phase 5 (The Scout) 的推演协议主要依赖 `scout_types.MacroTag` 和线性叙事提取。虽然包含了 `causal_auditor.py` 的因果检验，但推演逻辑仍然偏向"在给定宏观主题下寻找证据支持"，存在确认偏误风险。

### 4.2 马赛克推理协议 (Mosaic Reasoning Protocol) 的五大核心变革

#### 变革 1：从"假设驱动"到"异常驱动" (Anomaly-First Discovery)

**旧模式**: "今天市场看多黄金，找证据支持看多黄金"（确认偏误）

**新模式**: "今天以下5个数据维度出现了统计异常 → 这些异常拼图指向什么隐藏叙事？"

```
Mosaic Discovery Prompt 片段:

你是一位情报分析师，正在使用马赛克理论。请执行以下推理流程：

STEP 1 — 异常识别: 
  扫描以下五层另类数据信号矩阵。不要预设任何结论。
  仅标记 z_score 绝对值 > 1.5 的信号为"异常"。

STEP 2 — 异常聚类:
  将这些异常按以下维度聚类：
  - 资产类别关联 (equity/credit/commodity/fx/crypto)
  - 地理/法域关联 (US/EU/Asia/Middle East/Offshore)
  - 时间窗口收敛 (所有异常是否集中在 30 天内)
  - 行为主体 (retail/institution/sovereign/insider)

STEP 3 — 反叙事构造:
  对每一个发现的方向性结论，主动构造一个完全相反的竞争性叙事。
  如果竞争性叙事也能被同样的异常数据"佐证"，则该推理方向不成立。

STEP 4 — 物理验证锁定:
  为最终叙事选择一个关键的可证伪预测点：
  "如果我的推理正确，未来 [X] 天内应观察到 [Y] 指标发生 [Z] 变化。"
  如果该预测未兑现，则整个叙事推演被视为失败。
```

#### 变革 2：强制跨界关联 (Forced Cross-Domain Mapping)

受 AI云服务分析启发：从 Token 计费模式切换到阿联酋退群，分析师发现了两者之间的隐藏桥梁——**港股权重中云服务占比**。

```
跨界关联 Prompt 片段:

你现在拥有以下三个看似无关的信息片段：
  [A] 谷歌/微软全面推行企业端 Token 按量计费
  [B] 阿联酋退出 OPEC+ 并寻求中美双重合作
  [C] 港元/美元利差近期收窄 15bp

请找出这三个事件之间可能存在的一条因果链或资本流动路径。
必须满足以下约束：
  - 每一步推理必须明确资金流向 (谁在买什么？谁在卖什么？)
  - 必须指出哪个中间变量连接了 A 和 B、B 和 C
  - 如果找不到连接，明确回答"无关联"（宁缺毋滥）

当找到关联后，追问：
  "这个关联链条中，最脆弱的假设是什么？如果该假设被推翻，整个推理是否崩塌？"
```

#### 变革 3：逆向时间线推演 (Reverse Timeline Reasoning)

受爱泼斯坦案分析启发：分析师从结果（四巫日 + VIX 压制）反推出过程（系统性资本逃逸）。

```
逆向推演 Prompt 片段:

我们观察到一个异常的市场状态 [X]。
请用逆向时间线法推理：

从 [X] 这个终点往回走——
T-0:   观察到 [X]
T-30:  为了在 T-0 实现 [X]，T-30 必须发生什么？
T-60:  为了在 T-30 实现必要的前置条件，T-60 必须发生什么？
T-90:  ...

在每一步逆向推演中，你必须回答：
1. 谁在做？(参与者身份)
2. 在做什么？(具体操作)
3. 为什么？(该操作对其的好处)
4. 留下了什么痕迹？(该操作在公开数据中应留下的可观测印记)

如果某个步骤的答案包含"他们为了爱国/信仰/情怀"等不可验证动机，
则该步骤推演无效，必须用利益驱动逻辑重新构建。
```

#### 变革 4：共识脆弱性评估 (Consensus Fragility Index)

受"波动率镇压"分析启发：当市场过于一致时，系统性脆弱度反而最高。

```
共识脆弱性 Prompt 片段:

当前市场对 [宏观叙事 X] 的共识度为 [Y]% (基于分析师调查/媒体情绪)。

请分析该共识的脆弱性：

1. 拥挤度评估:
   - 该叙事的拥挤交易程度如何？(定位资金/资产规模)
   - 如果共识反转，哪些资产会遭受最大冲击？(尾部风险识别)

2. 共识维持条件:
   - 列出维持当前共识必须持续的 3 个关键假设
   - 对每个假设，评估其未来 90 天内维持的概率

3. 反向押注的盈亏比:
   - 如果做反共识押注，最大亏损多少？(共识持续时的机会成本)
   - 最大收益多少？(共识崩塌时的非线性回报)
   - 盈亏比是否 >= 3:1？

如果盈亏比 >= 5:1 且共识维持条件中至少 1 个关键假设的概率 < 30%，
则标记为【高共识脆弱性】，建议观望或建立反向头寸。
```

#### 变革 5：物理验证锁定 (Physical Verification Lock)

这是 Phase 7 最重要的协议升级——**整个系统从"观点生成器"进化为"可证伪预测引擎"**。

```
物理验证锁定 Prompt 片段:

基于你的推理，你必须输出至少 3 个物理验证指标 (Physical Verification Indicator):

每个验证指标必须满足 ALL of:
  □ 可观测: 存在公开、定期、不可逆的发布机制
  □ 不可操纵: 伪造代价 > $100 亿，或涉及太多独立参与方
  □ 有期限: 有明确的观测截止日期 (精确到周)
  □ 可证伪: 如果未发生，该指标能明确推翻对应逻辑链

验证指标格式:
  "如果在 [日期] 之前，[指标名称] 达到 [阈值] [方向] 当前值 [当前值]，
   则 [对应逻辑链] 被视为验证通过。
   如果未达到，则该逻辑链作废，需重新推演。"

示例:
  "如果在 2026-06-15 之前，10年期美债利率跌破 4.0% (当前 4.35%)，
   则'美联储将在 Q3 启动降息周期'的逻辑链被视为验证通过。
   如果在 2026-06-15 之前利率未跌破 4.0%，则该逻辑链作废，
   系统应重新评估'higher for longer'叙事。"

物理验证指标与决策的关系:
  - 验证通过: 维持当前仓位，考虑加仓
  - 验证失败但未跌破止损: 保持仓位，削减 50%
  - 验证失败 + 跌破止损: 执行 Phase 6 LiquidationReport
  - 连续 3 次验证失败: 触发系统性盲区警报，进入 OBSERVE 模式 30 天
```

### 4.3 MosaicNarrative：增强版宏观叙事数据结构

```python
@dataclass
class PhysicalVerificationIndicator:
    """物理验证指标"""
    pvi_id: str
    indicator_name: str                # e.g. "us10y_yield"
    description: str                   # 人类可读描述
    current_value: float
    target_threshold: float
    target_direction: str              # "above" | "below" | "between"
    verification_deadline: str         # ISO date "2026-06-15"
    linked_logic_chain: str           # 该指标验证的逻辑链描述
    consequence_if_failed: str         # 验证失败后果
    data_source: str                   # 公开数据源 URL 或 API endpoint
    manipulation_risk: str             # 被操纵风险描述

@dataclass
class MosaicNarrative:
    """马赛克推理后的增强版宏观叙事 (替代/增强 MacroTag)"""
    narrative_id: str
    generated_at: str
    
    # 基础叙事 (继承自 Phase 5)
    macro_theme: str                   # e.g. "美联储政策路径重构"
    confidence: float                  # 马赛克推理后的综合置信度
    
    # 马赛克推理增强
    anomaly_signals_used: List[str]    # 引用的异常信号 ID 列表
    cross_domain_links: List[str]      # 跨界关联发现 (e.g. "AI Token 计费 → 港股云服务 → 地缘中立项")
    reverse_timeline: List[str]        # 逆向时间线推演步骤
    consensus_fragility: float         # 共识脆弱性评分 0-100 (越高越脆弱)
    
    # 物理验证锁定
    physical_verifications: List[PhysicalVerificationIndicator]  # 至少 3 个
    
    # 反叙事
    counter_narrative: str             # 主动构造的反叙事
    why_counter_is_weaker: str         # 为什么反叙事不如主叙事有说服力
    
    # 红方审计引用
    red_team_audit_ref: Optional[str]  # 关联的 RedTeamAuditReport ID
    audit_resilience_score: Optional[float]  # 红方审计韧性分数
```

---

## 5. 模块交互与数据流

### 5.1 Phase 7 模块全景图

```
                          Phase 5 ScoutReport
                               │
                               ▼
              ┌────────────────────────────────────┐
              │  alternative_data_hooks.py          │  ← Phase 7.1 新模块
              │  五层另类数据发现引擎                │
              │                                    │
              │  输入: 本地缓存市场数据             │
              │  输出: AlternativeSignalMatrix      │
              └────────────────┬───────────────────┘
                               │
                               ▼
              ┌────────────────────────────────────┐
              │  mosaic_reasoning.py                │  ← Phase 7.2 新模块
              │  马赛克推理协议引擎                  │
              │                                    │
              │  输入: ScoutReport +                │
              │        AlternativeSignalMatrix      │
              │  输出: MosaicNarrative              │
              │        (增强版 MacroTag)             │
              └────────────────┬───────────────────┘
                               │
                               ▼
              ┌────────────────────────────────────┐
              │  red_team_auditor.py                │  ← Phase 7.3 新模块
              │  红方对抗监督引擎                    │
              │                                    │
              │  输入: MosaicNarrative +            │
              │        AlternativeSignalMatrix      │
              │  输出: RedTeamAuditReport           │
              │        (pass/fail + 物理验证指标)    │
              └────────────────┬───────────────────┘
                               │
                    ┌──────────┴──────────┐
                    │                     │
                    ▼                     ▼
              pass_audit=true       pass_audit=false
                    │                     │
                    ▼                     ▼
            进入 Phase 6           退回 mosaic_reasoning.py
            Fund Manager           (最多 3 次重试)
                    │                     │
                    │             3 次仍未通过 →
                    │             强制 OBSERVE Mode
                    │
                    ▼
    ┌───────────────────────────────────────┐