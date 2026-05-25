# 影子记忆持久化与每日启动协议

**Date**: 2026-05-20
**问题**: 用户经常关机 → 主管道和影子都失去上下文 → 每天启动时缺乏连续性
**目标**: 每次启动自动注入历史经验 + 今日重点 + 待确认信号

---

## 1. 问题定义

当前影子生态有一个关键缺口：**跨会话记忆丢失**。

- 影子昨天的分析结论（"等待 FOMC 会议纪要确认方向"）→ 关机 → 今天开机，影子不知道自己在等什么
- 连续跟踪的事件（"关注 NVDA 内幕抛售趋势，连续3周"）→ 关机 → 跟踪链断裂
- 积累的方法论经验（"最近 3 个月这个策略在区间市场表现好，在趋势市场表现差"）→ 关机 → 经验丢失

LLM 本身无状态。所有"记忆"必须通过外部化机制实现。

---

## 2. 三层记忆体系

```
┌─────────────────────────────────────────────────────┐
│                   Working Memory                     │
│                   工作记忆 (~24h)                     │
│  - 今天的 Daily Briefing（启动时生成）                │
│  - 当前持仓状态                                       │
│  - 今天需要关注的信号                                  │
│  - 上次会话未完成的分析                                │
│  每次启动 → 重新生成（不持久化）                       │
└────────────────────────┬────────────────────────────┘
                         │ 每天结束后沉淀
                         ▼
┌─────────────────────────────────────────────────────┐
│                  Episodic Memory                     │
│                  情景记忆 (~90d)                      │
│  - 每笔交易决策 + 结果                                │
│  - 每次分析的 thesis + 后续验证                       │
│  - Reflection Agent 产出的事后复盘                     │
│  - "等待X信号"的跟踪结果                               │
│  持久化 → SQLite episodic_memory 表                   │
└────────────────────────┬────────────────────────────┘
                         │ 统计显著性检验通过后
                         ▼
┌─────────────────────────────────────────────────────┐
│                  Semantic Memory                     │
│                   语义记忆 (永久)                      │
│  - Crystallization 通过的洞察                         │
│  - 方法论有效性统计（"此策略在区间市场胜率 62%"）        │
│  - 跨影子可继承的知识                                  │
│  - 已废弃的方法论（保留但不使用）                        │
│  持久化 → SQLite semantic_memory 表 + methodology/     │
└─────────────────────────────────────────────────────┘
```

---

## 3. 每日启动协议 (Daily Startup Protocol)

### 3.1 启动流程

```
系统开机
    │
    ▼
Step 1: 加载市场上下文
    ├── 今天的经济日历（数据发布、财报、央行讲话）
    ├── 隔夜市场变动（期货、外汇、加密货币）
    ├── 上次会话以来的突发新闻
    └── 来源: economic_calendar API + 上次快照对比

Step 2: 加载待确认信号注册表 (Pending Signal Registry)
    ├── 查询所有 status='awaiting' 的信号
    ├── 自动检查：信号是否已触发？
    │   ├── 已触发 → 标记为 'triggered'，通知对应影子
    │   └── 未触发 → 保持 'awaiting'，纳入今日简报
    ├── 检查过期信号（超过预期日期 7 天）→ 标记 'expired'
    └── 来源: pending_signals SQLite 表

Step 3: 加载影子情景记忆
    ├── 每个影子加载最近 90 天的 episodic_memory
    ├── 包括：过去的决策 + 结果 + 复盘记录
    └── 来源: episodic_memory SQLite 表

Step 4: 加载语义记忆
    ├── 加载 crystallized 的永久知识
    ├── 加载方法论有效性统计
    └── 来源: semantic_memory + methodology_evolver

Step 5: 生成个性化 Daily Briefing
    ├── 为每个影子生成定制简报
    ├── 注入到分析 prompt 之前
    └── 格式见 §3.2

Step 6: 开始正常分析流程
    └── 影子带着"记忆"进行今天的分析
```

### 3.2 Daily Briefing 格式

每个影子在分析前收到这样一段上下文：

```
═══════════════════════════════════════════
DAILY BRIEFING — {shadow_display_name}
Date: {today}
═══════════════════════════════════════════

📋 你在等待这些信号（上次会话留下）:
  - [AWAITING] FOMC 会议纪要 — 预期 2026-05-22 — 用于确认利率方向判断
  - [AWAITING] AAPL Q2 财报 — 预期 2026-05-25 — 用于验证科技支出趋势
  - [TRIGGERED] NVDA 内幕抛售连续3周监测 — 已触发！内幕抛售比来到 6:1
  - [EXPIRED] 等待 OPEC 产量决议 — 已过期，相关判断自动失效

📊 你的近期表现（90天）:
  - 胜率: 58% | 累计收益: +12.3% | 最大回撤: -8.1%
  - 排名: 5/24 (Excellent) | 趋势: ↑ 上升中
  - 最近 3 笔交易: +2.1%, -1.5%, +3.8%

🔍 需要你持续跟踪的事件:
  - NVDA 内幕抛售趋势（已跟踪 17 天）— 今天需要更新判断
  - 半导体供应链库存周期（已跟踪 42 天）— 等待 Q2 数据确认拐点

📅 今天与你领域相关的数据发布:
  - 10:00 ISM 制造业 PMI（预期 49.2）
  - 14:00 Fed 褐皮书
  - Earnings: ORCL, AVGO (盘后)

💡 上次分析中未解决的问题:
  - "如果 PMI 连续 3 个月低于 50，需要重新评估工业金属的多头逻辑"
  - 上次判断: PMI 48.7（第2个月低于50）→ 今天需关注

═══════════════════════════════════════════
现在开始今天的分析。
```

### 3.3 Briefing 生成器

```python
class DailyBriefingGenerator:
    """每次启动时运行，为每个影子生成个性化简报。纯 Python + SQL——0 LLM 调用。"""
    
    async def generate_briefing(self, shadow_id: str) -> str:
        pending = self.pending_registry.get_awaiting(shadow_id)
        triggered = self.pending_registry.get_recently_triggered(shadow_id, days=3)
        performance = self.state_db.get_recent_performance(shadow_id, days=90)
        tracking = self.event_tracker.get_active_tracks(shadow_id)
        calendar = self.economic_calendar.get_today_relevant(shadow_domain)
        unresolved = self.state_db.get_unresolved_questions(shadow_id)
        
        return self._format_briefing(...)
```

---

## 4. 待确认信号注册表 (Pending Signal Registry)

### 4.1 是什么

一个 SQLite 表 + 管理模块，记录每个影子"正在等待什么信号来确认/否定之前的判断"。

### 4.2 数据结构

```sql
CREATE TABLE pending_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT NOT NULL,
    signal_type TEXT NOT NULL,        -- 'data_release', 'earnings', 'event', 'price_level', 'indicator', 'trend'
    signal_description TEXT NOT NULL,  -- 人类可读描述
    trigger_condition TEXT,            -- 触发条件（机器可解析或人类可读）
    related_ticker TEXT,               -- 相关标的
    related_decision_id INTEGER,       -- 关联的 shadow_decisions.id
    created_date TEXT NOT NULL,
    expected_date TEXT,                -- 预期信号出现的日期
    check_frequency TEXT DEFAULT 'daily',  -- 'daily', 'weekly', 'on_data_release'
    status TEXT DEFAULT 'awaiting',    -- 'awaiting', 'triggered', 'expired', 'cancelled'
    resolved_date TEXT,
    resolution_notes TEXT,
    impact_on_decision TEXT            -- 信号触发/未触发对原判断的影响
);
```

### 4.3 信号的生命周期

```
影子分析 → 产出决策 + 待确认信号
    │
    ▼
解析 shadow_analysis 输出 → 提取 "WAITING_FOR: ..." 块
    │
    ▼
创建 pending_signal 记录 (status='awaiting')
    │
    ▼
每次启动 → 检查信号是否已触发
    ├── 已触发 → status='triggered' → 通知影子 → 影子在新分析中确认/调整原判断
    ├── 超过预期日期 7 天 → status='expired' → 原判断自动失效
    └── 仍在等待 → 纳入 Daily Briefing
```

### 4.4 影子如何声明待确认信号

影子在 LLM 输出中新增一个代码块：

```
DECISION_START
ticker: NVDA
direction: short
confidence: 0.65
thesis: 内幕抛售加速 + 估值极端
risk_note: 如果 Q2 财报超预期，做空逻辑受损
DECISION_END

WAITING_FOR:
- signal: NVDA Q2 财报
  expected: 2026-05-28
  condition: 营收 > $30B → 做空逻辑需要重新评估
- signal: 半导体 SOX 指数跌破 4200
  expected: 持续监测
  condition: 跌破 → 加仓信号
END_WAITING_FOR
```

解析器提取 `WAITING_FOR` 块，创建 `pending_signal` 记录。

---

## 5. 持续跟踪事件注册表 (Event Tracker)

### 5.1 与 Pending Signal 的区别

- **Pending Signal**: 等待一个具体的、会发生的事件（财报、数据发布、价格触及某价位）
- **Event Tracker**: 持续观察一个趋势或主题（"关注 NVDA 内幕抛售趋势"、"跟踪半导体库存周期"）

### 5.2 数据结构

```sql
CREATE TABLE event_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT NOT NULL,
    track_topic TEXT NOT NULL,           -- "NVDA 内幕抛售趋势"
    track_category TEXT NOT NULL,        -- 'insider_activity', 'macro_trend', 'sector_cycle', 'geopolitical'
    started_date TEXT NOT NULL,
    last_updated_date TEXT NOT NULL,
    check_cadence TEXT DEFAULT 'daily',  -- 'daily', 'weekly', 'monthly'
    data_source_hint TEXT,               -- 需要查询什么数据源
    key_metric TEXT,                     -- 跟踪的核心指标
    current_status TEXT,                 -- 最近一次更新的摘要
    total_days_tracked INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',        -- 'active', 'paused', 'concluded'
    conclusion_notes TEXT
);
```

### 5.3 使用方式

影子在分析中写道：
```
TRACKING: NVDA 内幕抛售趋势
  category: insider_activity
  metric: 4周内幕卖出/买入比
  cadence: weekly
  current: 连续3周 > 3:1，本周来到 6:1 ← 加速中
```

解析器更新或创建 event_track 记录。下次启动时纳入 Daily Briefing。

---

## 6. 与现有模块的关系

| 现有模块 | 关系 |
|------|------|
| `shadow_memory.py` | 已实现 3 层记忆的基础结构。Daily Briefing Generator 是工作记忆层的实现。 |
| `shadow_state.py` | ShadowStateDB 需要新增 `pending_signals` 和 `event_tracks` 表的 CRUD。 |
| `shadow_schema.py` | 新增两张表的 DDL + 迁移。 |
| `background_scheduler.py` | 可以用调度器定期检查待确认信号（如每小时检查是否有新数据发布）。 |
| `crystallization.py` | 已验证的 pending_signal 结果（信号触发 → 判断正确/错误）沉淀为语义记忆。 |

---

## 7. 边界条件

### 7.1 如果连续关机 30 天

- 启动时检查所有 pending_signals → 大量信号可能已过期
- 过期信号不删除——标记为 'expired'，保留为审计记录
- 情景记忆可能部分超过 90 天有效期 → 被修剪
- Daily Briefing 中特别标注："您已离线 30 天，以下是此期间发生的重大变化"

### 7.2 如果影子被淘汰

- 该影子的 pending_signals → 全部标记为 'cancelled'
- event_tracks → 标记为 'concluded'
- 情景记忆保留（供后继影子参考）

### 7.3 内存限制

- Daily Briefing 大小控制在 ~2000 tokens 以内
- 如果 pending_signals 超过 20 条 → 只显示最近 10 条 + 摘要
- 如果 event_tracks 超过 10 条 → 按最近更新日期截断
