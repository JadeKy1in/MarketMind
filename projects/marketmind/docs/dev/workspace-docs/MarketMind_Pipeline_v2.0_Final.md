# MarketMind Pipeline v2.0 — 最终版（含 3 门禁）

**日期**: 2026-05-17 | **来源**: app.py + Phase B 设计文档 + 设计规范 v1.2 §5 | **状态**: 已锁定

---

## 管道总览（3 门禁 × 9 阶段 × 2 平行轨道）

```
                    时间线 →
                    
主 AI 轨道:         ┌─ Gate 1 ──────────────┐  ┌─ Gate 2 ─────────────────┐  ┌─ Gate 3 ──┐
                    │ 方向确认               │  │ 信号确认                 │  │ 决策审批   │
                    │                        │  │                         │  │           │
  Stage 1 ──→ Stage 2 ──→ Stage 3 ──→ Stage 4 ──→ Stage 6 ──→ Stage 7 ──→ Stage 8 ──→ Stage 9
  Scout      Flash      L1叙事     L2基本面   Red Team  Resonance  Decision   Archive
  新闻采集   信号预处理  分析       L3技术面   对抗审查   统计检验   决策生成    归档
                                   (并行)

影子轨道:           Stage 0 ──→ Stage 5: 影子生态运行（与主AI并行，每天必跑）──→ ELITE 在 Gate 2 唤醒
                    初始化      21+ 影子独立分析原始新闻+市场数据              领域触发/点名
                                内部循环: 排名→结晶→进化
                                信息广播: 影子接收原始新闻，不看主AI分析
```

---

## 三个门禁

### 🚪 Gate 1: 方向确认

**位置**: Stage 3 (L1) 之后，Stage 4 (L2+L3) 之前  
**时间**: 用户看到方向简报后选择  
**交互**:
- 主 AI 呈现方向简报（80-120 字/方向）
- 用户选择方向 A → B 和 C 自动创建 MissedPath 影子追踪
- 用户可输入 "observe" 跳过
- ≤3 个引导问题

### 🚪 Gate 2: 信号确认

**位置**: Stage 7 (Resonance) 之后，Stage 8 (Decision) 之前  
**交互**:
- 信号共振图 (F/T/E/S)
- Red Team 对抗挑战要点
- ELITE 影子意见（领域触发或点名唤醒，标注 "SHADOW OPINION"）
- Layer 3 三灯结果
- ≤3 个引导问题

**ELITE 协议** (DD-002):
- ELITE 影子与主 AI 同时分析（Stage 4-5 并行），预计算分析存储在 EliteRegistry
- 用户提及领域关键词 → 领域触发唤醒
- 用户提及影子名称 → 点名唤醒
- 每影子每 Gate 2 最多参与 1 次，标注 "SHADOW OPINION"，无决策权
- Gate 2 结束后 2 分钟强制暂停（基于 Danziger 假释法官研究）

### 🚪 Gate 3: 决策审批

**位置**: Stage 8 (Decision) 之后  
**交互**:
- 结构化决策卡片（入场/止损/目标/R:R）
- 同等深度的"什么都不做"论证（NoTradeCard）
- 用户在 Gate 2 暂停 2 分钟后才能进入 Gate 3
- ≤3 个引导问题
- 每个门禁完成后自动存档→重启时可续接

---

## 影子生态信息流

**来源**: `phase_b_ideation_notes.md` §1, `shadows/elite_participation.py`

### 影子分析工作流（7 步，原文 phase_b_ideation_notes.md §1）

影子是拥有独立 Flash 配额和自主决策权的**独立研究者**：

```
Step 1: 读取个人记忆（过往决策、成功、失败）
Step 2: 读取今日原始新闻/事实（来自 Stage 1 的 news_items）
Step 3: 观察用户+主AI讨论（用户意见+提交材料）
        ——但【不看】主AI的预讨论报告/分析（避免锚定偏差）
Step 4: 初步分析
Step 5: 使用 Flash 配额请求额外数据
        （迭代，影子自主决定——"我想查一下德国PMI"）
Step 6: 判断是否继续深入还是做出决定
Step 7: 投资决策（输出 VOTE 块，内部排名用，不进入主决策）
```

### 信息接收矩阵

| 数据 | 影子接收✅ | 影子不接收❌ |
|------|:---:|:---:|
| Stage 1 原始新闻 | ✅ | — |
| Stage 2 Flash 信号 | — | ❌ 影子自己从新闻提取 |
| Stage 3 L1 叙事 | — | ❌ 主 AI 分析报告 |
| Stage 4 L2/L3 结论 | — | ❌ 主 AI 基本面/技术面 |
| 市场数据 API | ✅ 影子主动调 API | — |
| 宏观数据 API | ✅ 影子用 Flash 配额查 | — |
| 用户意见和材料 | ✅ | — |
| 其他影子分析输出 | — | ❌ 分析阶段内隔离 |
| Gate 2 ELITE | ✅ 贡献预计算意见（1次） | — |

### 关键原则
- **锚定偏差防御**: 影子不看主 AI 分析，防止跟风
- **Flash 配额自主**: 每个影子有独立配额，自主决定查什么
- **配额激励**: 省配额做对→加速晋升；省配额做错→轻微减速；不动→无奖励
- **所有影子默认 Pro**: Flash 仅用于简单查询
- **影子间不协调**: 即使发现其他影子同向，"该信息不得改变你自己的分析"

---

## Gate 之后的流程

### Gate 1 通过后

```
用户选择的方向 → L2 聚焦该方向的候选标的
被拒绝的方向 → 自动创建 MissedPath 影子跟踪
用户说 "observe" → 跳过，返回 0
```

### Gate 2 通过后

```
2 分钟强制暂停（pause_screen.py: "走开。喝水。"）
ELITE 贡献收入 Red Team 报告
→ Gate 3 决策审批
```

### Gate 3 通过后

```
决策卡片 + NoTradeCard → Stage 9 归档
每个门禁状态自动存档 → 可续接
```

---

## 逐阶段详解

### Stage 0: 影子生态初始化

**每天必跑**（不是可选）。  
**模块**: `shadows/shadow_mother.py` → `ShadowMother.__init__`  
**Token**: 0（纯 SQLite 配置创建）

- 创建 15 Expert + 7+1 Daredevil + 1 Catfish 的影子配置
- 可选启动 BackgroundScheduler + MultimodalAdapter
- 影子在 Stage 4-5 并行运行分析

### Stage 1: Scout 新闻采集

**模块**: `pipeline/scout.py` → `fetch_all_sources()`  
**输出**: news_items (35 源: 31 RSS 工作 + 3 API 跳过 + 1 OAuth，全部可用 → ~587 条)  
**安全**: MAX_HEADLINE=300, MAX_SUMMARY=1000

### Stage 2: Flash 信号预处理

**模块**: `pipeline/flash_preprocessor.py` → `preprocess_batch(50条)`  
**输出**: FlashSignal[] (事件分级/方向/置信度/受影响资产/关键事实)  
**计划**: ⚠️ 替换为启发式浏览（红方审核通过，待实现）

### Stage 3: L1 叙事分析

**模块**: `pipeline/layer1_narrative.py` → `analyze_layer1(15条)`  
**输出**: Layer1Result (事件等级/矩阵象限/情绪方向/级联/尾部风险)  
**→ 喂入 Gate 1 方向简报**

### Stage 4: L2+L3 并行

**L2**: `layer2_fundamental.py` → 5 层递进  
**L3**: `layer3_technical.py` → 3 灯审查（独立——不看 L1/L2 结论）

### Stage 5: 影子生态运行

**每天必跑**。与 Stage 4 同时进行（影子分析原始新闻，不看主 AI 的 L1/L2/L3 结论）。  
内部 8 步循环：事件扫描 → 临时影子 → 分析 → 排名 → 合谋 → 挑战者 → 记忆更新 → 结晶  
**输出**: 排名+进化+ELITE 预计算（存入 EliteRegistry，等待 Gate 2 唤醒）  
**🔴 shadow_votes 永远是 None**（DD-001）

### Stage 6: Red Team 对抗审查

Pro LLM 挑战 L1+L2 原始分析。输出: challenges + overall_assessment

### Stage 7: Resonance 统计检验

纯 Python DSR/CSCV/PBO。输出: passed, dsr, pbo, verdict

### → Gate 2: 信号确认

ELITE 影子领域触发/点名唤醒（预计算分析在此刻呈现）。

### → 2 分钟强制暂停

### Stage 8: Decision 决策生成

`generate_decision(l1,l2,l3,red_team,resonance,shadow_votes=None)`  
输出: decision_cards + no_trade_card

### → Gate 3: 决策审批

### Stage 9: Archive 归档

---

## 红方审计结果：启发式搜索方案

### 判定: 条件通过 ✅

三份审计（安全/逻辑/架构）一致认为方案的**结构性方向正确**（HVR 循环、渐进披露、多层验证、Flash+Pro 分工）。

### 8 个 CRITICAL 全部有修正方案

| # | 问题 | 修正 | 状态 |
|:---:|------|------|:---:|
| C1 | Flash→Pro 信任链零验证 | JSON schema 校验 + 工具白名单 | ✅ 已实现 |
| C2 | 标题无长度限制 | Scout 层 300/1000 字符硬截断 | ✅ 已实现 |
| C3 | Sybil 攻击 | 源独立性图 + 最少 3 个独立源 | ✅ 已实现 |
| C4 | L1/L2/L3 迁移未明确 | 保留旧模块，仅改接口 | 📋 待实现 |
| C5 | Token 预算差 10-15 倍 | 重算 ~105,000/session, 硬上限 150K | 📋 待实现 |
| C6 | 缺少期望差分析 | HVR 循环前插入"市场已定价什么？" | 📋 待实现 |
| C7 | L1/L3 不是真正独立 | 4 层重新分层（市场/基本面/新闻/历史） | 📋 待实现 |
| C8 | 对抗性自检是空占位符 | 强制看空 LLM 调用 + 置信度对比 | 📋 待实现 |

### 预计 Token: ~105,000/session | 工作量: 8-12 Agent-天

完整报告: `.claude/audits/heuristic-plan-red-team-synthesis.md`
