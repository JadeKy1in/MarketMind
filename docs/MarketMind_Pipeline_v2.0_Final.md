# MarketMind Pipeline v2.0 — 最终版

**日期**: 2026-05-17 | **来源**: app.py 代码审计 + Phase B 设计文档 + 红方审计 | **状态**: 已锁定

---

## 管道总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                    MarketMind 每日分析管道                            │
│                                                                     │
│  Stage 0         Stage 1    Stage 2       Stage 3     Stage 4       │
│  ┌──────────┐   ┌───────┐ ┌─────────┐  ┌─────────┐ ┌───────────┐  │
│  │ Shadow   │   │ Scout │ │ Flash   │  │  L1     │ │ L2 (基本面) │  │
│  │ 初始化    │   │ 新闻   │→│ 信号    │→│  叙事   │→│      +      │  │
│  │ (可选)   │   │ 采集   │ │ 预处理  │  │  分析   │ │ L3 (技术面) │  │
│  └──────────┘   └───────┘ └─────────┘  └─────────┘ └───────────┘  │
│       │              │                                      │       │
│       │              └──────────────┬───────────────────────┘       │
│       │                             ↓                               │
│       │              ┌─────────────────────────────────────────┐    │
│       │              │         Stage 5: 影子生态运行 (可选)      │    │
│       │              │  21+ 影子独立分析原始新闻+市场数据         │    │
│       │              │  排名 → 结晶 → 进化 (不参与决策)          │    │
│       │              │  ⚠️ shadow_votes 永远是 None              │    │
│       │              └─────────────────────────────────────────┘    │
│       │                             ↓                               │
│       │              Stage 6 → Stage 7 → Stage 8 → Stage 9         │
│       │              Red Team  Resonance  Decision  Archive         │
│       │              对抗审查   统计检验    决策生成    归档         │
│       │                             ↑                               │
│       │              shadow_votes = None (DD-001)                   │
│       └────────────── ELITE 影子在 Gate 2 领域触发唤醒 ────────────┘
└─────────────────────────────────────────────────────────────────────┘
```

---

## 逐阶段详解

### Stage 0: 影子生态系统初始化（可选）

**何时运行**: `shadows_enabled=1` 时  
**模块**: `shadows/shadow_mother.py` → `ShadowMother.__init__`  
**Token 消耗**: 0（纯配置，无 LLM 调用）

**做什么**:
- 在 SQLite 中创建 15 Expert + 7+1 Daredevil + 1 Catfish 的影子配置
- 可选启动 BackgroundScheduler（结晶 + 记忆清理）
- 可选启动 MultimodalAdapter（Gemini Flash 截图/PDF）

**不是做什么**:
- ❌ 不运行影子分析（分析在 Stage 5）
- ❌ 不影响主决策管道（影子独立并行）

---

### Stage 1: Scout 新闻采集

**模块**: `pipeline/scout.py` → `fetch_all_sources()`  
**Token 消耗**: 0（纯 HTTP 请求）  
**安全**: `MAX_HEADLINE_LENGTH=300`, `MAX_SUMMARY_LENGTH=1000`

**做什么**:
- 35 个信息源（~33 个工作）→ ~587 条新闻
- NewsAPI/GNews JSON API + RSS + Bluesky AT Protocol + BLS API
- URL 去重 + 标题相似度去重（>0.85）
- 按来源等级排序（PRIMARY 优先）

**输出**: `news_items: list[NewsItem]`

---

### Stage 2: Flash 信号预处理

**模块**: `pipeline/flash_preprocessor.py` → `preprocess_batch(news_items[:50])`  
**Token 消耗**: ~8,000  
**状态**: ⚠️ 计划替换为启发式浏览

**做什么**:
- 取前 50 条新闻，每 15 条一批交给 Flash LLM
- 提取 FlashSignal: event_type, event_grade(A-E), direction, confidence, affected_assets, key_facts, noise_flag
- JSON 解析，处理 markdown 包装和格式错误

**计划替换**（红方审核通过，待实现）:
- Flash 轻量评分（5 轴 0-10）代替完整提取
- 主 AI 启发式浏览代替批量处理
- HVR 循环（Hypothesize-Verify-Refine）

---

### Stage 3: L1 叙事分析

**模块**: `pipeline/layer1_narrative.py` → `analyze_layer1(signals[:15], news_items)`  
**Token 消耗**: ~3,000

**做什么**:
- Pro LLM 对前 15 个信号进行深层叙事分析
- 输出: event_grade, matrix_quadrant(core_opportunity/trend_opportunity/arbitrage/observe_skip), sentiment_direction, cascade_rank, price_in_score, tail_risk_flags

**计划调整**（红方审计 C4）:
- 输入从"15 条信号"变为"HVR 循环确认的假设 + 验证结果"

---

### Stage 4: L2 基本面 + L3 技术面（并行）

**L2 模块**: `pipeline/layer2_fundamental.py` → `analyze_layer2(l1_result)`  
**L3 模块**: `pipeline/layer3_technical.py` → `analyze_layer3(tickers, {})`  
**Token 消耗**: ~12,000 (L2=4,000 + L3=8,000)

**L2 做什么** (5 层递进):
L2.1 宏观象限 → L2.2 资产配置 → L2.3 行业选择 → L2.4 因子扫描 → L2.5 标的推荐

**L3 做什么** (3 灯审查):
- 🔴 DD-004: L3 独立于 L1/L2——只接收原始市场数据+标的列表
- 绿灯(3/3) → 计算入场区间/止损/目标价
- 黄灯(1-2/3) → 等待
- 红灯(0/3) → 无论基本面多好，不买

---

### Stage 5: 影子生态运行（可选，独立于主决策）

**模块**: `shadows/shadow_mother.py` → `ShadowMother.orchestrate_daily_cycle()`  
**Token 消耗**: ~42,000 (21 影子 × ~2000)

**信息广播规则** (DD-003):

| 影子接收 | 影子不接收 |
|------|------|
| 原始新闻/事实 | 主 AI 的分析/报告 |
| 市场数据（价格、基本面） | 其他影子的分析输出 |
| 用户的原始意见和材料 | L1/L2/L3 结论 |

**影子内部 8 步循环**:
1. 事件扫描 → 临时影子生命周期
2. 创建/销毁临时影子
3. 并行运行所有影子分析
4. 排名计算 + 高原检测
5. 生态系统监控（合谋、健康、盲点）
6. 知识管理（记忆更新 + 结晶检查）
7. AEL 进化（月度复盘）
8. 维护（挑战者审判 + 紧急配额审计）

**🔴 DD-001: 影子不投票**
```
app.py:110  shadow_votes = None    # 永远是 None
app.py:151  generate_decision(shadow_votes=shadow_votes)  # 传入 None
```
影子是内部竞争生态系统。投票持久化（save_votes）仅用于回测验证和结晶假设检验。

---

### ELITE 影子在 Gate 2 参与

**协议** (DD-002):

1. ELITE 影子与主 AI **同时**分析（Stage 4 并行），预计算分析存储在 EliteRegistry
2. 用户讨论中提及影子领域关键词 → **领域触发唤醒**
3. 用户提到影子名字 → **点名唤醒**
4. 每影子每 Gate 2 最多 **一次**
5. 标记为 "SHADOW OPINION"，**无决策权**
6. 16 个领域关键词定义在 `EliteRegistry.DOMAIN_KEYWORDS`

---

### Stage 6: Red Team 对抗审查

**模块**: `pipeline/red_team.py` → `run_red_team()`  
**Token 消耗**: ~4,000

**做什么**:
- Pro LLM 对 L1+L2 原始分析提出对抗性挑战
- 挑战分级 A-D: A=critical logic flaw, B=missing evidence, C=overconfident claim, D=minor
- 输出: challenges + overall_assessment

---

### Stage 7: Resonance 统计检验

**模块**: `pipeline/resonance.py` → `evaluate_resonance()`  
**Token 消耗**: 0（纯 Python，不用 LLM）

**做什么**:
- DSR/CSCV/PBO 统计框架
- 验证信号组合是否有真正的预测结构（超越随机）
- 输出: passed, dsr, pbo, forward_validation_ratio, verdict

---

### Stage 8: Decision 决策生成

**模块**: `pipeline/decision.py` → `generate_decision()`  
**Token 消耗**: ~5,000

**输入**:
- l1_result, l2_result, l3_result
- red_team_report, resonance
- shadow_votes = **None**（DD-001）

**输出**:
- decision_cards: 最多 5 个结构化决策卡片（entry/stop/target/reward_risk）
- no_trade_card: 同等深度的"不做操作"论证

---

### Stage 9: Archive 归档

**模块**: `storage/archivist.py` → `get_archivist().index_document()`  
**Token 消耗**: 0

**做什么**:
- JSON + SQLite FTS5 全文检索
- 按日期/类别索引，供后续回测和复盘

---

## 锁定设计决定

| ID | 决定 | 证据 |
|:---:|------|------|
| DD-001 | 影子不投票 | `app.py:110` `shadow_votes=None` |
| DD-002 | ELITE Gate 2 顾问制 | `elite_participation.py` |
| DD-003 | 影子不看主 AI 分析 | `phase_b_ideation_notes.md` §1 |
| DD-004 | L3 独立于 L1/L2 | `layer3_technical.py` system prompt |

## 设计文档索引

| 内容 | 文档 |
|------|------|
| 影子生态完整设计 | `.claude/research/shadow-ecosystem-full-design.md` |
| Pipeline YAML 清单 | `projects/marketmind/pipeline-manifest.yaml` |
| 启发式搜索方案 | `docs/superpowers/plans/2026-05-17-heuristic-news-workflow.md` |
| 红方审计整合 | `.claude/audits/heuristic-plan-red-team-synthesis.md` |
| 权威 Pipeline（CLAUDE.md）| `projects/marketmind/CLAUDE.md` |
