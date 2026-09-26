# 启发式新闻浏览与投资逻辑链推理 — 实施方案

**日期**: 2026-05-17 | **基于**: 4 份外网研究报告 + 代码现状审计 | **状态**: 待红方审核

---

## 一、问题诊断

**当前流程**（app.py Step 1-2）：
```
Scout 采集 587 条新闻 → Flash 批量预处理 50 条 → 提取信号 → L1 分析前 15 条
```

问题：
- Flash 对所有 50 条新闻做**同等深度的结构化提取**，不区分重要性
- 主 AI（Pro）被动接收信号，**无自主浏览和追问能力**
- 没有从"标题 → 启发 → 查数据 → 交叉验证 → 深化 → 结论"的推理链
- Token 浪费：不重要的新闻也被完整提取

**目标**：让主 AI 像分析师一样**主动浏览、追踪线索、验证猜想**。

---

## 二、新架构：三级渐进式新闻处理

### 第一级：Flash 轻量分流（~500 tokens）

Flash 对所有标题做**最小化评分**，不做完整提取：

```json
{
  "headline": "ECB keeps rates on hold in the face of inflation threat",
  "source_tier": 1,
  "scores": {
    "market_impact": 7,
    "cross_source_corroboration": 5,
    "contradicts_consensus": 3,
    "investigative_depth_needed": 6,
    "urgency": 8
  },
  "classification": "macro",
  "suggested_tools": ["fred_api", "ecb_rss"],
  "affected_assets": ["EUR/USD", "DAX", "TLT"]
}
```

输出：80-120 条这样的结构化 JSON 给主 AI。

### 第二级：主 AI 启发式浏览（Pro，~2000 tokens 初始 + 按需增加）

主 AI 收到分级标题后，按研究 1（分析师模式）的认知决策树操作：

```
Step 1: 查看高分标题（impact≥7 或 urgency≥8 的优先）
        ↓
Step 2: 选定一个线索 → 生成假设
        例："ECB 维持利率但通胀威胁上升 → 欧央行可能被逼加息 → EUR 可能走强"
        ↓
Step 3: 调用工具验证假设（按研究 3 的验证链）
        - Layer 1（市场真值）：CME FedWatch、利率期货
        - Layer 2（多源佐证）：交叉查其他新闻源、ECB 声明原文
        - Layer 3（市场数据）：债券收益率、EUR/USD 走势
        - Layer 4（历史模式）：类似 ECB 情境下的历史走势
        ↓
Step 4: 分析结果 → 假设被确认/削弱/推翻
        ↓
Step 5: 决定下一步：
        - 深化：查领先指标（HY 利差、PMI 等）
        - 展开：查受影响资产链（EUR→DAX→欧股→全球）
        - 关闭：假设被否定或置信度不够
        ↓
Step 6: 回到 Step 1 选下一条线索（重复直到预算用尽或时间到）
```

### 第三级：深度验证（按需触发）

当主 AI 判定某个线索值得深入时，调用完整 API 获取真值数据——FRED、EIA、yfinance、SEC EDGAR 等。不预先拉取全部。

---

## 三、主 AI 逻辑链推理流程

基于研究 1（分析师认知决策树）和研究 2（LLM Pre-Act + HVR 循环）：

```
┌─────────────────────────────────────────────────────┐
│  Phase 1: 浏览 & 形成初始假设（Pre-Act 规划）         │
│                                                     │
│  主 AI 查看 Flash 评分的 Top 20 标题                  │
│  → 识别 3-5 个潜在投资主题                           │
│  → 每个主题生成一个可验证的假设                       │
│  → 按 impact×urgency 排序，选定调查顺序               │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  Phase 2: 逐线索深入调查（HVR 循环）                  │
│                                                     │
│  对每个假设：                                        │
│  H (Hypothesize): 形成具体可验证声明                  │
│    例："ECB 可能在下次会议加息 25bp"                  │
│                                                     │
│  V (Verify): 调用工具验证                             │
│    - 查利率期货定价（市场隐含概率）                    │
│    - 查 ECB 近期声明（政策信号）                      │
│    - 查 EUR/USD 近期走势（市场定价）                   │
│    - 查欧洲通胀数据（基本面）                          │
│                                                     │
│  R (Refine): 更新假设                                │
│    - 如果市场已定价 80% → "加息预期已被定价，           │
│      关注实际加息幅度是否超预期"                       │
│    - 如果通胀数据不支持 → "加息概率低，                 │
│      关注 ECB 措辞变化而非实际行动"                    │
│                                                     │
│  置信度校准（研究 3 §5）：                            │
│  - Market Ground Truth (30%): 利率期货定价            │
│  - Multi-Source Corroboration (25%): 3+ 独立源       │
│  - Market Data Validation (25%): EUR/USD + DAX       │
│  - Historical Pattern Match (20%): 类似 ECB 周期      │
│                                                     │
│  判定阈值：                                          │
│    confidence ≥ 0.7 且 ≥2 层确认 → 可以形成投资建议    │
│    confidence 0.4-0.7 → 标记为"需要继续观察"          │
│    confidence < 0.4 → 放弃该假设                      │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  Phase 3: 综合 & 形成投资逻辑链                        │
│                                                     │
│  将确认的假设链接成完整的逻辑链：                      │
│                                                     │
│  例：                                                │
│  1. ECB 声明暗示加息 → 查利率期货确认市场定价80%       │
│  2. 欧洲 PMI 连续 3 个月 >55 → 经济基本面支持加息     │
│  3. EUR/USD 仍在 1.05 低位 → 加息可能推动 EUR 走强    │
│  4. 德国 DAX 成分股中出口企业占比高 → EUR 走强利空    │
│  5. 结论：EUR 看涨、DAX 谨慎（出口拖累 vs 金融受益）   │
│                                                     │
│  每个逻辑步骤标注信息来源和验证层级                    │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  Phase 4: 输出结构化投资建议                           │
│                                                     │
│  - 逻辑链（每步标注信息来源 + 验证状态）               │
│  - 置信度评分（4 层加权）                              │
│  - 反对意见（Adversarial self-check）                  │
│  - 需要人类确认的假设（≤3 个）                         │
│  - 如果判断"不做任何操作"，输出同等深度的不做论证        │
└─────────────────────────────────────────────────────┘
```

---

## 四、管道集成方案

### 替换当前 Step 2（Flash 预处理）

```
旧：Flash preprocess_batch(50条) → 全部提取信号 → L1
新：Flash triage(全部587条) → 结构化评分 → 主AI启发式浏览 → L1(仅被选中的信号)
```

### 新增模块

| 模块 | 功能 | 行数估计 |
|------|------|:---:|
| `pipeline/flash_triage.py` | Flash 轻量标题评分（5 轴 0-10） | ~100 |
| `pipeline/investigation_loop.py` | 主 AI 的 HVR 循环引擎 | ~300 |
| `pipeline/verification_chain.py` | 4 层验证链 API 调用 | ~200 |
| `pipeline/logic_chain_builder.py` | 逻辑链构建 + 置信度校准 | ~150 |
| `config/investigation_config.yaml` | 工具映射 + 预算配置 | ~50 |

### Token 预算（研究 4）

| 阶段 | 模型 | Token 估计 |
|------|:---:|:---:|
| Flash 分流（587 条） | Flash | ~500 |
| 主 AI 浏览（20 条精选） | Pro | ~2,000 |
| HVR 循环（5 个假设 × 3 轮） | Pro | ~5,000 |
| 逻辑链综合 | Pro | ~2,000 |
| **总计** | | **~9,500** |

对比旧方案（Flash 50 条完整提取 ~8,000 + L1 ~3,000 = ~11,000），新方案总 Token 略低但信息价值显著更高。

---

## 五、与影子生态的交互

新流程不影响影子生态的独立性：
- 影子仍接收**原始新闻+市场数据**（不受主 AI 分析影响）
- 主 AI 的启发式搜索结果**不同步**给影子
- ELITE 影子在 Gate 2 按领域触发参与，看到的是用户讨论内容（可能包含主 AI 的逻辑链），但不影响其独立判断

---

## 六、实施步骤

| 步骤 | 内容 | 依赖 |
|:---:|------|:---:|
| 1 | 红方审核本方案 | — |
| 2 | 实现 `flash_triage.py` — Flash 轻量评分 | 步骤 1 通过 |
| 3 | 实现 `verification_chain.py` — 4 层验证 | 步骤 1 通过 |
| 4 | 实现 `investigation_loop.py` — HVR 循环 | 步骤 2+3 |
| 5 | 实现 `logic_chain_builder.py` — 逻辑链构建 | 步骤 4 |
| 6 | 集成到 app.py — 替换旧 Step 2 | 步骤 5 |
| 7 | 测试 + PICA 审计 | 步骤 6 |
| 8 | 跑真实数据验证 | 步骤 7 |

---

**研究依据**:
1. `heuristic-workflow-1-analyst-patterns.md` — 分析师认知决策树、Druckenmiller/Soros/Dalio 框架
2. `heuristic-workflow-2-llm-patterns.md` — Pre-Act、HVR 循环、ReAct、置信度校准
3. `heuristic-workflow-3-signal-verification.md` — 4 层验证链、领先-滞后关系、信号融合
4. `heuristic-workflow-4-token-efficiency.md` — Flash+Pro 分工、渐进式披露、预算管理
