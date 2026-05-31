# MarketMind 主管线迭代优化结构审计

**日期**: 2026-05-31 | **来源**: 代码层审计 (orchestration.py, 11 个 Stage 模块, 3 个 Gate, 5 个反馈层)

---

## 1. 管线全貌

MarketMind 有 **两条并行管线**，共享 Stage 模块但编排逻辑不同：

| 维度 | Daily 管线 (CLI) | Interactive 管线 (GUI/API) |
|------|:--|:--|
| 入口 | `app.py --mode daily` | `app.py --mode interactive` |
| 编排器 | `orchestration.run_daily()` (720行) | `interactive_orchestration.run_interactive()` (501行) |
| 数据传递 | 直接参数传递 (plain objects) | `SessionContext` dataclass |
| Gate | 无 (线性执行) | Gate 1/2/3 (人机对话) |
| 影子启动 | 非阻塞后台 Task | 广播后启动，带超时等待 |
| 语言注入 | ✅ 全模块 | ✅ 全模块 |

### Daily 管线 9 阶段

```
Stage 0: Shadow Init      ── 初始化 16 expert + 8 daredevil，僵尸检测
Stage 1: Scout            ── 37 源异步采集 → 去重 → 优先级排序 → list[NewsItem]
Stage 2: Flash            ── chat_flash 批量预处理 → list[FlashSignal] (grade A-E)
Stage 3: L1 Narrative     ── chat_pro 叙事分析 → Layer1Result (grade/quadrant/direction)
         ↓ 校准上下文注入 (7天历史预测精度)
Stage 4: L2+L3 Parallel   ── L2 基本面 + L3 技术面并行
Stage 5: Shadows          ── 非阻塞后台 asyncio.Task (60/40 token split)
Stage 6: Red Team         ── chat_pro 对抗审计 (temp=0.5, 更高创造力)
Stage 7: Resonance        ── 纯计算: DSR + CSCV PBO + Spearman (零 LLM)
Stage 8: Decision         ── chat_pro 决策合成 + 独立 contrarian 挑战
Stage 9: Archive          ── JSON + SQLite FTS5 双持久化
Post:                      ── 保存预测 (供次日校准) + 记录指标 + 可能触发周审计
```

### Interactive 管线 10 阶段 (含 Gate)

```
Stage 0:   Shadow Init
Stage 0.5: Economic Calendar ── 如果 FOMC/NFP/CPI 日 → confidence discount
Stage 1:   Scout
Stage 2:   Flash (routes by content_type)
Stage 3:   L1 Interactive ── 苏格拉底式对话，用户可输入 'observe' 跳过
Stage 3.5A: Broadcast L1 → 影子接收用户视角 (不包含 AI 分析)
Stage 3.5B: Broadcast L1 Session → 7 天隔离期后可见
Stage 3.6: Launch Shadows (广播后启动)
Stage 4:   L2 Interactive ── 两阶段：板块选择 → 策略组选择
Stage 4.5: ELITE 检查 → 完成分析的 ELITE 影子意见注入 (只显示，不参与 AI 提示词)
Stage 6:   L3 Interactive ── 逐标的审查技术面
Stage 7:   Red Team (自动)
Stage 8:   Resonance (自动)
Stage 8.5: Shadow Consensus ── 影子共识显示
Stage 9:   Decision Interactive ── 用户确认/修改
Stage 10:  Archive
```

---

## 2. Gate 体系 (仅 Interactive 模式)

三个 Gate 都是**人机对话循环**，纯编排逻辑，零 LLM 调用：

### Gate 1: Direction (gate1_interaction.py, 433行)

```
流程: 用户先说方向 → 展示假设卡片 → 交互循环 → 确认
意图: select | detail | compare | confirm | pivot | parking_lot
上限: 50 轮，40 轮警告
输出: Gate1Session.selected_direction
```

**关键设计**: 用户必须在看到 AI 分析之前先陈述自己的方向判断 (CONVICTION_FIRST 原则)

### Gate 2: Confirmation (gate2_interaction.py, 651行)

```
流程: 用户先给信念 1-10 → 展示多角度分析 → 用户调整 → CONTINUE/MODIFY/PAUSE
展示内容:
  - L1 市场定价 + L2 基本面 + L3 多源 + L4 历史证据
  - Red Team 存活挑战 (critical/major 级别)
  - Fragility 报告 (整体分数、越过阈值、过时警告)
  - 历史 regime 类比 (前 3 匹配 + forward equity returns)
  - 信号冲突 + Kill 标准
  - 去偏置提醒: AI 在 0.75-0.85 区间系统性地高估约 15%
影子集成: /invite <name> → 邀请毕业影子 | @shadow <question> → 提问
防火墙: 5 条规则确保影子之间互相看不到分析
输出: Gate2Session.final_conviction + outcome
```

### Gate 3: Position (gate3_interaction.py, 457行)

```
流程: 展示决策票据 → 交互修改 → confirm → 前交易检查清单
头寸大小: Full/Half/Quarter Kelly (波动率调整 + 相关性折扣)
必须字段: instrument, stop_loss > 0
前交易检查: blocker 项失败 → 必须用户强制确认
上限: 40 轮，30 轮警告
输出: EXECUTED | DEFERRED | CANCELLED
```

---

## 3. HVR 调查循环 (investigation_loop.py, 517行)

管线最内层的迭代引擎。从 `pre_gate1.py` 调用，最多 20 个候选方向。

```
Phase 1: Pre-Act ── Pro 扫描 30 条头条 → 生成 3-5 个可测试假设
Phase 2: Expectation Gap ── Pro 评估市场定价比例 → gap > 0.15 进入 HVR
            ↓ gap < 0.15 → 判定 PRICED_IN，跳过
Phase 3: HVR Cycle ── 最多 3 轮 Hypothesize → Verify → Refine
           4 层验证: Market(30%) + Fundamental(25%) + Multisource(25%) + Historical(20%)
           confidence >= 0.80 → KEEP | <= 0.30 → ABANDON (不弱化，Druckenmiller 原则)
           0.30 < c < 0.80 → REFINE (收窄主张/添加条件/改变范围)
           收益递减阈值 (DIMINISHING_RETURNS_THRESHOLD=0.05) 停止早期循环
Phase 4: Adversarial Bear Case ── Pro 扮演卖空者
           bear_confidence > bear_discount * main_confidence → HIGH_CONTENTION
Phase 5: Verdict ── PRICED_IN | ACTIONABLE | MONITOR | DISCARD | HIGH_CONTENTION
Phase 6: Layer Narratives ── Flash 生成 L1-L4 叙事 + Pro 因果分解 + 流分解
```

**Pro 调用上限**: `MAX_PRO_CALLS_PER_SESSION` 强制限制，通过可变列表计数器追踪

---

## 4. 三层反馈闭环

### Layer 1: 日校准 (Daily)

```
每次运行后 → save_prediction() → .claude/calibration/{date}.json
下次 L1 前   → get_calibration_context(shadow_db, days=7)
              → 计算: 方向精度、量级加权分数、等级分布、象限精度、
                      Flash 冲击验证率、HVR ROI 比
              → 生成警告标志 (精度<40%、Flash验证<30%、等级过多D/E)
              → 注入 L1 system prompt 前缀 "## Calibration Context"
```

**P3 量级警告**: 如果方向精度 >55% 但量级分数为负 → "判断对小波动正确、对大波动错误"

### Layer 2: 周战术审计 (Weekly, 7天间隔)

```
_maybe_run_weekly_audit() → run_weekly_audit(shadow_db)
  → 发送管道指标 + settlement 数据给 Flash
  → Flash 分析 Stage 级健康度
  → 建议存入 .claude/metrics/weekly_audit_latest.json
  → 下次 L1 读取 get_suggestion_context() 注入提示词
```

### Layer 3: SHARP 规则进化 (Attribution, 仅持续性精度差时触发)

```
触发条件: direction_accuracy < 0.45 (7天 AND 30天 均低于)
  → StageAttributionAnalyzer 用 Flash 追溯 Decision 错误到 Stage
  → 生成 RuleImpactHypothesis (positive/negative/neutral)
  → RuleValidator walk-forward backtest (5个最小验证窗口)
     IS/OOS 分离 → 决定 keep/retire
     "LLM is NOT the judge. Statistical gate is the judge."
  → RuleEvolver 执行原子操作: tune_threshold | add_constraint | remove_constraint
  → record_evolution() → .claude/metrics/evolutions.jsonl
  → L1 下次运行时读取 _load_recent_evolutions()
```

### Phase I 学习层 (辅助)

| 组件 | 功能 | 触发 |
|------|------|------|
| ReflectionAgent | 事后反思，Flash(成功)/Pro(失败) | 预测过期后批处理 |
| EntityMemory | 按实体积累知识 (模式、盲点、关键价位) | 每次反思后更新 |
| CalibrationTracker | Brier/ECE/Platt 置信度校准 | 10+ 验证预测后 |
| ForecastTracker | A→B 场景预测存续追踪 | 每次产生场景预测时 |

---

## 5. 关键设计模式与潜在优化点

### 5.1 已实现的好模式

| 模式 | 位置 | 效果 |
|------|------|------|
| L3 独立于 L1/L2 | layer3_technical.py | 防止确认偏误 |
| 影子不可见排名 | challenger_engine.py | 防止博弈排名 |
| 7天隔离期 | broadcast.py | 防止影子锚定用户观点 |
| Fail-soft | 所有 Stage | 单点故障不崩溃 |
| 统计 Gate > LLM 判断 | methodology_evolution.py | 防止 LLM 自证循环 |
| 非阻塞影子 | orchestration.py:358 | 主线程不停等影子 |
| 影子共识不可见 AI 分析 | broadcast.py + Gate 2 防火墙 | Chinese Wall 合规 |

### 5.2 潜在优化空间

| 问题 | 位置 | 严重度 | 建议 |
|------|------|:--:|------|
| **Daily 管线无 Gate** | orchestration.py:276-329 | 高 | Daily 模式绕过全部 Gate 直接执行 Decision。如果 L1 给出 E 级 (observe_skip)，后面的 L2/L3/Decision 照常跑，浪费 API 调用。建议: L1 grade=E → 提前终止 |
| **L2+L3 并行但无共享检查** | orchestration.py:124-142 | 中 | L2 选标的、L3 技术审查并行跑，但不互相等待。可能出现 L2 选了 5 个标的但 L3 全红灯，没有 "L2→L3 再选一轮" 的回退机制 |
| **Red Team + Resonance 之间无反馈** | orchestration.py:144-171 | 中 | Red Team 挑战不被 Resonance 统计验证。Red Team 说 "可能存在幸存偏误" 但 Resonance 不会因此调整 PBO 计算 |
| **校准上下文仅注入 L1** | orchestration.py:99-104 | 中 | 7天校准只给 L1，L2/L3/Decision 看不到自己的历史精度。每个 Stage 应该有独立的校准反馈 |
| **HVR 调查循环未纳入 Daily 管线** | investigation_loop.py vs orchestration.py | 中 | HVR 是管线中最精密的迭代引擎 (6 Phase, 4 层验证, 3 轮精炼)，但只被 Interactive 模式调用。Daily 模式跳过了全部深层调查 |
| **周审计仅分析不执行** | weekly_tactical_audit.py | 低 | Flash 分析 Stage 健康度并给出建议，但没有自动执行机制——建议需要人工审查才能注入 |
| **Shadow consensus 仅显示** | interactive_orchestration.py:365-391 | 低 | ELITE 影子意见在 Decision 前展示，但不参与 Decision 合成。影子与主 AI 之间存在 Chinese Wall——合规正确，但可能错过有价值的对立观点 |
| **影子结果等待 5 分钟** | orchestration.py:712 | 低 | Daily 模式末尾等待影子完成，但影子分析可能需要更长时间。超时后静默丢弃结果 |
| **DSR 需要历史收益** | resonance.py:126 | 低 | Resonance 需要 historical_returns 输入，但 Daily 管线传入的可能是人工构造的 fallback 数据 `[0.001, -0.002, ...]`。在无真实历史数据时，统计验证失效 |
| **fragility_scanner 未接入 Decision** | fragility_scanner.py | 低 | Fragility 报告独立生成，但 Decision stage 不接收 fragility 数据。市场脆弱性不影响最终决策 |

### 5.3 迭代死点排查

| 检查项 | 状态 | 说明 |
|------|:--:|------|
| pipe buffer 死锁 | ✅ 已修复 | `stdout=subprocess.DEVNULL` (2026-05-30) |
| 影子后台任务泄漏 | ✅ 安全 | `asyncio.create_task` + `done_callback` + 超时等待 |
| LLM 调用无限等待 | ✅ 安全 | `httpx.Timeout(120.0)` 硬超时 |
| Gate 无限循环 | ✅ 安全 | 50 轮上限，40 轮警告 |
| HVR 无限精炼 | ✅ 安全 | 3 轮上限 + 收益递减阈值 |
| Token 预算耗尽死锁 | ⚠️ 部分 | Budget exhausted → 返回 `{"error":"budget_exhausted"}` → Stage 取空值 → 使用 fallback default。不会死锁但输出质量退化 |
| Calibration 文件无限增长 | ⚠️ 部分 | 每天写入 `.claude/calibration/{date}.json`，无自动清理。长时间运行后目录膨胀 |
| 影子 SQLite 无限增长 | ⚠️ 部分 | 每日分析记录持续追加。temp_event 30天后自动删除，但 permanent 影子数据无归档清理 |

---

## 6. 数据流向总图

```
                          ┌──────────────────────┐
                          │   Historical Data     │
                          │  (7d calibration)     │
                          │  (7d evolutions)      │
                          │  (weekly audit)       │
                          └──────────┬───────────┘
                                     │ 读取
                                     ▼
┌──────┐   ┌───────┐   ┌──────┐   ┌──────┐   ┌─────────┐   ┌──────────┐   ┌──────┐
│Scout │──▶│ Flash │──▶│  L1  │──▶│L2+L3 │──▶│Red Team │──▶│Resonance │──▶│Decision│
│37源  │   │A-E级  │   │叙事  │   │基本面 │   │对抗挑战 │   │DSR+PBO   │   │+Contrar│
└──────┘   └───────┘   │+校准 │   │+技术面│   │5挑战类型│   │纯计算    │   │+Paper  │
                       └──┬───┘   └──┬───┘   └────┬────┘   └──────────┘   └───┬────┘
                          │           │            │                          │
                          │    ┌──────┘            │         ┌────────────────┘
                          │    │                   │         │
                          ▼    ▼                   ▼         ▼
                       ┌────────────────────────────────────────────┐
                       │          Shadows (非阻塞后台)                │
                       │  24 初始影子 → 分析 → 排名 → 结晶 → 挑战者  │
                       │  13-step daily cycle (ShadowMother)         │
                       └─────────────────┬──────────────────────────┘
                                         │ 完成后
                                         ▼
                       ┌────────────────────────────────────────────┐
                       │          后处理 & 持久化                     │
                       │  save_prediction → .claude/calibration/    │
                       │  save_decision_brief → .claude/briefs/     │
                       │  record_pipeline_metrics → .claude/metrics/│
                       │  archive → data/{year}/{month}/{day}/      │
                       │  FTS5 index → archive.db                   │
                       └────────────────────────────────────────────┘
```

---

## 7. 配置关键参数

| 参数 | 值 | 位置 | 影响 |
|------|:--|------|------|
| `MAX_HYPOTHESES_PER_SESSION` | 5 | investigation_config.py | HVR 每会话最大假设数 |
| `MAX_DEEPENING_STEPS_PER_THREAD` | 3 | investigation_config.py | HVR 每个假设最大精炼轮数 |
| `DIMINISHING_RETURNS_THRESHOLD` | 0.05 | investigation_config.py | 置信度增益 <5% 停止精炼 |
| `EXPECTATION_GAP_THRESHOLD` | 0.15 | investigation_config.py | 预期差 >15% 才有交易价值 |
| `calibration_days` | 7 | daily_calibration.py | 日校准回溯天数 |
| `weekly_audit_interval` | 7 | orchestration.py | 周审计间隔 (天) |
| `shadow_timeout` | 300 | orchestration.py:712 | 影子等待超时 (秒) |
| `gate_turn_limit` | 50/50/40 | gate1/2/3_interaction.py | 各 Gate 最大交互轮数 |
| `challenger_stage1_periods` | 2 | settings.py | 连续倒数 20% 触发 Stage 1 |
| `challenger_stage2_periods` | 3 | settings.py | 连续倒数 20% 触发 Stage 2 |
| `challenger_stage3_weeks` | 2 | settings.py | 挑战者比较审判周期 |
| `MAX_PRO_CALLS_PER_SESSION` | - | investigation_loop.py | Pro 调用硬上限 |

---

## References

| # | Source | Date | Type |
|---|--------|------|------|
| 1 | `pipeline/orchestration.py` (720行) | 2026-05 | `[V]` primary |
| 2 | `pipeline/interactive_orchestration.py` (501行) | 2026-05 | `[V]` primary |
| 3 | `pipeline/investigation_loop.py` (517行) | 2026-05 | `[V]` primary |
| 4 | `pipeline/gate1_interaction.py` (433行) | 2026-05 | `[V]` primary |
| 5 | `pipeline/gate2_interaction.py` (651行) | 2026-05 | `[V]` primary |
| 6 | `pipeline/gate3_interaction.py` (457行) | 2026-05 | `[V]` primary |
| 7 | `pipeline/daily_calibration.py` (357行) | 2026-05 | `[V]` primary |
| 8 | `pipeline/methodology_evolution.py` | 2026-05 | `[V]` primary |
| 9 | `pipeline/weekly_tactical_audit.py` | 2026-05 | `[V]` primary |
| 10 | `config/settings.py` | 2026-05 | `[V]` primary |
