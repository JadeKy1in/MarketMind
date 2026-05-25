# Gate 2 交互机制 + 记忆持久化

**日期**: 2026-05-20
**研究基础**: Agent 2 (Gate 2 交互), Agent 4 (记忆持久化)

---

## Section A: Gate 2 影子-用户-主管道交互机制

### A.1 核心约束

1. 影子是独立决策者，不是投票者——从不参与主管道最终决策
2. 用户是唯一桥梁——系统不自动传递影子/主管道之间的任何结论
3. 只有 Elite + 毕业的影子可以对话
4. 毕业后仍接受每日考核，可被降级
5. 主管道做最终投资决策（仅 Robinhood 可交易）
6. 影子产出独立分析报告——用户可参考

### A.2 四阶段交互流程

```
Gate 2 开启
    │
    ▼
Phase 1: 独立展示
  ├── 左面板: 主管道结论（推理链、置信度、风险警告）
  ├── 右面板: Shadow Research Feed
  │   ├── 领域覆盖图: 各领域分析师覆盖情况（哪个领域有影子在看、方向如何）
  │   ├── 按领域/标的聚合的方向视图（如"贵金属: 2看多, 1弃权"而不是全局"14多6空"）
  │   ├── Elite 影子个体观点（thesis + 置信度）
  │   └── 跨策略分歧高亮（同一领域内 Momentum/Contrarian/Expert 方向不一致时标注）
  └── 系统不自动交叉引用
    │
    ▼
Phase 2: 结构化提问
  ├── 12 个预设问题，分 4 类
  │   ├── 基础验证 Q1-Q3: 最脆弱环节、什么改变判断、校准历史
  │   ├── 风险探查 Q4-Q6: 5%不利怎么办、尾部风险、缺失数据
  │   ├── 时机 Q7-Q9: 时间窗口、催化事件、入场时机
  │   └── 替代场景 Q10-Q12: 反方辩护、第二可能、无法量化因素
  ├── 用户选择: 一键全部 / 按类发送 / 单选 / 手动
  └── AI 回答格式: 结构化（非自由对话），强制引用来源上下文ID
    │
    ▼
Phase 3: 交叉验证（用户驱动）
  ├── 污染评级:
  │   ├── LOW:    "如果有人持相反观点，你怎么回应？"（不透露来源）
  │   ├── MEDIUM: "另一位分析师认为 X。你的回应？"（透露来源，记入审计日志）
  │   ├── HIGH:   直接分享完整结论 → 系统温和提醒
  │   └── CRITICAL: 系统自动传递 → 禁止
  ├── 用户是唯一完成交叉引用的人
  └── 所有交叉引用写入审计日志
    │
    ▼
Phase 4: 最终决策
  ├── 用户操作: CONFIRM / MODIFY / OVERRIDE / PAUSE
  ├── 影响因子清单（用户记录哪些输入影响了决策）
  └── 完整审计日志
```

### A.3 信息隔离设计（对标 Millennium "中国墙"）

```
系统架构层强制隔离:
  - 影子之间: 0 通信路径（无消息传递、无共享输出可见性）
  - 影子 ↔ 主管道: 0 自动通信（只有用户手动桥接）
  - 用户可见: 两边各自的独立输出

BlackRock 拥挤警告应用:
  - ConcentrationDetector 监控影子输入同质化
  - 当 ≥ 50% 影子依赖相同主数据源 → 警告
  - 每影子必须有独特的信息源指纹
```

### A.4 Elite 影子交互规则

- **领域限制**: 只讨论自己领域（Bullion Broker 不谈科技股）
- **Devil's Advocate 角色**: 被设计为挑战者，不是确认者（Ma et al. 2023）
- **干净状态**: 每轮 Q&A 从干净状态开始（BEAM 教训——不累积对话状态）
- **引用强制**: 每个回答必须引用来源上下文 ID
- **无决策权**: 标记为"影子意见"，仅供参考

### A.5 独立性保持的多层架构

| 层 | 方法 | 防止 |
|------|------|------|
| 模型层 | DeepSeek 内 Persona+温度+推理框架差异化 | 行为纠缠。东京大学研究(arXiv 2411.19515)证明同模型内不同 Persona 可产生有意义预测分歧 |
| 数据层 | 不同信息源指纹 | 输入同质化（BlackRock 警告） |
| Persona 层 | 不同分析人格 | 输出趋同 |
| 交互层 | 无状态 Q&A | 上下文污染（BEAM） |

### A.6 审计日志完整性保护

- **追加写**: 审计日志仅支持 append，不提供 modify/delete API
- **哈希链**: 每条日志含 `prev_hash = SHA-256(上一条日志)` 和 `entry_hash = SHA-256(本条内容)`
- **完整性表**: 哈希链头存储于独立的 `audit_integrity` 表中（只写一次）
- **启动验证**: 每次 Gate 2 会话启动时重算哈希链，与存储的链头对比
- **篡改检测**: 任何不匹配 → 标记 "INTEGRITY_BREACH"，Gate 2 进入只读模式

**来源**: Bloomberg ANR 分布直方图、Millennium 信息隔离、Ma et al. Devil's Advocate (arXiv 2403.01791)、BEAM 基准 (OpenReview)、行为纠缠 (arXiv:2604.07650)

---

## Section B: 记忆持久化与每日启动协议

### B.1 三层记忆架构

```
Working Memory (~24h)
  - Daily Briefing（每次启动生成）
  - ≤ 3200 tokens
  - 会话结束后丢弃
        │ 每天沉淀
        ▼
Episodic Memory (~90d)
  - SQLite: trade decisions + outcomes + reflection
  - Ebbinghaus 衰减加权检索
  - RecMem 启发: 延迟固化——仅相似模式重现时触发 LLM 总结
        │ 统计显著性检验
        ▼
Semantic Memory (永久)
  - Crystallization 通过的洞察
  - 方法论有效性统计
  - 可继承知识（PKT 蒸馏传递）— 需 OOS 验证（30天观察期 + 方向准确率 ≥ 50% + 二项检验 p<0.10）
  - ACE 风险评分
  - 验证失败 → "unvalidated"（仍存储，不进入 PKT 可继承池）
```

### B.2 每日启动协议（6 步）

```
Step 1: 加载市场上下文
  - 今日经济日历、隔夜变动、突发新闻

Step 2: 加载待确认信号注册表
  - 查询 status='awaiting' 的信号
  - 自动检查: 信号已触发？→ 标记 'triggered'，通知影子
  - 过期信号 (> 预期日期 7 天) → 标记 'expired'

Step 3: 加载情景记忆（90 天，Ebbinghaus 加权）

Step 4: 加载语义记忆（结晶知识）

Step 5: 生成个性化 Daily Briefing（per shadow）
  - 结构化分层格式:
    [1] PERSONA & STRATEGY (~150 tokens, 固定)
    [2] CUMULATIVE EXPERIENCE (~600 tokens, 衰减加权)
    [3] PENDING SIGNALS (~400 tokens, 结构化表格)
    [4] TODAY'S MARKET (~800 tokens, 领域过滤)
    [5] INSTRUCTION (~200 tokens, 关键要求重复)

Step 6: 正常分析流程开始
```

**Lost in the Middle 缓解**: 最重要信息放开头（Persona + Experience）和结尾（Instruction）。中间放数据密集但优先级低的内容（Market）。

### B.3 待确认信号注册表

```sql
CREATE TABLE pending_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    trigger_condition TEXT,
    related_ticker TEXT,
    created_date TEXT NOT NULL,
    expected_date TEXT,
    status TEXT DEFAULT 'awaiting',  -- awaiting/triggered/expired/cancelled
    resolved_date TEXT,
    resolution_notes TEXT
);
```

影子在 LLM 输出中声明:
```
WAITING_FOR:
- signal: AAPL Q2 财报; expected: 2026-05-25
  condition: 营收 > $90B → 确认做多逻辑
END_WAITING_FOR
```

解析器提取 → 创建 pending_signal 记录。下次启动自动检查。

#### 输出解析安全

影子 LLM 输出在块解析前进行安全检查：

1. **块计数**: 每影子每天最多 1 个 DECISION_START 块，最多 10 个 WAITING_FOR 条目。超出 → 拒绝整份输出
2. **顶层匹配**: DECISION_START/DECISION_END 和 WAITING_FOR/END_WAITING_FOR 必须出现在行首（零缩进）
3. **嵌套禁止**: 块内不允许出现同类块标记
4. **Prompt 规范**: 影子 prompt 明确要求 "不要在 thesis 或 risk_note 中输出 DECISION_START 或 WAITING_FOR 字面量"
5. **解析器防御**: 解析器只提取第一个 DECISION_START...DECISION_END 对。内部嵌套的标记忽略
6. **审计日志**: 拒绝的输出写入审计日志，记录拒绝原因

### B.4 持续跟踪事件注册表

```sql
CREATE TABLE event_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT NOT NULL,
    track_topic TEXT NOT NULL,
    track_category TEXT NOT NULL,
    started_date TEXT NOT NULL,
    last_updated_date TEXT NOT NULL,
    check_cadence TEXT DEFAULT 'daily',
    key_metric TEXT,
    current_status TEXT,
    status TEXT DEFAULT 'active'
);
```

影子声明:
```
TRACKING: NVDA 内幕抛售趋势; category: insider_activity
  metric: 4周内幕卖出/买入比; cadence: weekly
  current: 连续3周 > 3:1，本周 6:1
```

### B.5 边界条件

- **30 天关机**: 批量信号过期，显式"离线通知"。情景记忆可能部分超过 90 天 → 修剪
- **影子淘汰 — 孤儿信号处理**: pending_signals 不取消。所有权转移至 `system`（orphaned 状态），系统继续检查。孤儿信号触发时记录 `retroactive_hit` 事件（含被淘汰影子 ID + 实际结果）。月度"过早淘汰审计"聚合 retroactive_hit，识别被淘汰但方向正确的影子（若某策略类型过早淘汰率 > 30%，Challenger 对比期自动延长）。event_tracks → concluded，归档至影子退役档案
- **记忆溢出**: 按新近度 + 重要性截断（详见 §B.5.1）
- **首次启动**: 无情景记忆 → 仅加载 Persona + 今日数据 + 空信号列表

#### B.5.1 Pending Signal 截断规则

待确认信号注册表可能随运行时间膨胀至 200+ 条目。400 token 预算的截断规则：

1. **预过滤**: 排除 `expired` 和 `cancelled` 状态的信号（不计入预算）
2. **优先级排序**（复合评分降序）: `priority_score = signal_importance_weight / (days_until_expected_date + 1)`。signal_importance_weight: 影子声明信号时的 1-5 评分（默认 3）
3. **截断**: 按 priority_score 降序取前 N 条，N = ⌊400 / avg_tokens_per_signal⌋
4. **关键保护**: 如果任何 `expected_date` ≤ 3 天的信号被截断 → 发出系统警告 "CRITICAL SIGNAL TRUNCATED"
5. **自动过期**: `expected_date` 超过 7 天未触发 → 自动标记 `expired`
6. **预算追踪**: PENDING SIGNALS 部分实际 token 使用量写入日志，用于调整 avg_tokens_per_signal 估计

### B.6 实现清单

| # | 任务 | 文件 |
|:--:|------|------|
| 1 | Pending Signal Registry | `shadows/pending_signals.py` (~150行) |
| 2 | Event Tracker | `shadows/event_tracker.py` (~120行) |
| 3 | Daily Briefing Generator | `shadows/daily_briefing.py` (~250行) |
| 4 | Startup Protocol | `shadows/startup.py` (~200行) |
| 5 | DB Schema 扩展 | `shadows/shadow_schema.py` (+2表) |
| 6 | Gate 2 交互面板 | `ui/gate_panel.py` (修改) |
| 7 | 结构化问题框架 | `pipeline/gate2_interaction.py` (修改) |
| 8 | ConcentrationDetector 重命名 | `shadows/collusion_detector.py` → `shadows/concentration_detector.py` |

**来源**: FinMem (AAAI 2024)、RecMem (2026)、BEAM 基准、SimpleMem (2026)、Alcidion/Accuro 医疗随访系统、Lost in the Middle (Liu et al. 2024)、Attention Basin (Yi et al. 2025)
