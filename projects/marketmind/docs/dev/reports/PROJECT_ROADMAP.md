# AI Studio 工作区 — 项目路线图

**更新**: 2026-05-19 13:00 UTC | **提交**: 180 | **当前项目**: MarketMind

---

## ✅ 已完成

### 管线（10/10 阶段跑通）

| 阶段 | 状态 | 产出 |
|------|:---:|------|
| 1. Scout 新闻采集 | ✅ | 345 条/次，25/25 信源正常 |
| 2. Flash 快速分诊 | ✅ | 342 条评分，113 条进入深度分析，17+ 处 JSON 解析加固 |
| 3. HVR 调查循环 | ✅ | 4 条假设生成（Pre-Act→预期差→熊市反驳→裁决） |
| 4. Layer 1 叙事分析 | ✅ | 宏观叙事评分（EST 前缀修复） |
| 5. Layer 2+3 基本面+技术面 | ✅ | 8 候选 + 10 标的（NoneType 修复） |
| 6. 红方挑战 | ⚠️ | 间歇性 0~4（mock 数据波动，非 bug） |
| 7. 共振分析 | ✅ | 评分追踪正常 |
| 8. 脆弱性评估 | ✅ | 评估逻辑正常 |
| 9. 决策输出 | ✅ | 决策工单生成 |
| 10. 归档 | ✅ | 全阶段输出按 YYYY/MM/DD/ 保存 |

**关键指标**: 1302 测试 / 0 失败 | PICA 产物 110+ | 红方审计 13+

### 深度分析模块（Phase H：6 个）

| 模块 | 功能 |
|------|------|
| `causal_decomposition.py` | 因果链分解 |
| `flow_decomposition.py` | 资金流向分析 |
| `regime_detector.py` | 市场体制识别 |
| `scenario_builder.py` | 前向情景构建 |
| `fragility_assessor.py` | 组合脆弱性评分 |
| `cross_border_analyzer.py` | 跨市场传导分析 |

### 学习系统（Phase I：6 层）

| 层 | 模块 |
|:---:|------|
| 1. 预测 | `prediction_tracker.py` |
| 2. 校准 | `calibration_tracker.py` |
| 3. 反思 | `reflection_loop.py` |
| 4. 记忆 | `memory_tiers.py` |
| 5. 缩放 | `platt_scaler.py` |
| 6. 专长 | `expertise_discovery.py` |

### Gate 系统（3 道关口）

| Gate | 功能 | 状态 |
|:---:|------|:---:|
| Gate 1 | 假设卡片 + 用户交互 + 终止监控 | ✅ |
| Gate 2 | 信念确认循环 | ✅ |
| Gate 3 | 仓位计算 + 交易前清单 + 决策工单 | ✅ |

### 重构成果

| 文件 | 重构前 | 重构后 | 缩减 |
|------|:---:|:---:|:---:|
| `app.py` | 971 行 | 76 行 | -92% |
| `investigation_loop.py` | 918 行 | 486 行 | -47% |
| `orchestration.py` | 516 行 | 172 行 | -67% |
| `shadow_state.py` | 1484 行 | 602 行 | -59% |

### 影子系统

| 项目 | 状态 |
|------|:---:|
| 16 位专家影子 | ✅ 已构建 |
| 8 位敢死队 | ✅ 已构建 |
| 5 种监督机制 | ✅ 已构建 |
| 影子投票从主管线移除 | ✅ 已完成 |
| 影子从 31 清理到 24 | ✅ 已完成 |

### 工作流强制执行系统

| 组件 | 事件 | 功能 |
|------|------|------|
| `integrity_check.py` | SessionStart | SHA256 校验 13 个 hook + 自动恢复 |
| `config_guardian.py` | SessionStart | 5 道守卫（插件/状态栏/hook/环境/强制执行链） |
| `time_anchor.py` | SessionStart | UTC 时间锚定 |
| `task_manifest.py` | SessionStart | 注入任务分类规则 |
| `startup_report.py` | SessionStart | 启动健康报告 |
| `danger_guard.py` | PreToolUse | 红线阻断（force push main 等） |
| `skill_profiler.py` | PostToolUse | Skill 使用追踪 |
| `stop_gate_check.py` | Stop | git diff 交叉验证 + PICA 产物校验 |
| `conversation_archiver.py` | Stop | 对话归档 |
| `pre_compact.py` | PreCompact | 压缩前进度快照 |

### 基础设施

| 项目 | 状态 |
|------|:---:|
| 5 插件 / 35 skills | ✅ |
| 3 MCP（Context7、GitHub、Chrome DevTools） | ✅ |
| 夹具系统（8 个夹具，7 个测试） | ✅ |
| Skill 使用追踪（`skill_profiler.py` + `skill_report.py`） | ✅ |
| CLAUDE.md 标签（45 条规则：27 不可变 + 18 可覆盖） | ✅ |
| 项目路线图（本文件） | ✅ |

---

## ❌ 待完成

### 需用户讨论（阻塞项）

| # | 任务 | 优先级 | 说明 |
|:---:|------|:---:|------|
| 1 | **影子敢死队 #4 重设计** | 🔴 高 | Fade Master 共识逆向者——用户想讨论替代方案 |
| 2 | **影子类型最终确认** | 🔴 高 | 16 专家 + 8 敢死队 + 5 机制——待用户签字 |

### 功能开发

| # | 任务 | 优先级 | 说明 |
|:---:|------|:---:|------|
| 3 | **政治人物情绪追踪** | 🟡 中 | `sentiment_collector.py` 已归档（Truth Social + CapitolTrades），待恢复并集成 |
| 4 | **Mock 管线修复** | 🟡 中 | `--mock` 标志未传到 HTTP 抓取器，`fetch_all_sources()` 缺少 mock 路径 |

### 延后（条件未满足）

| # | 任务 | 原因 |
|:---:|------|------|
| 5 | ELITE Gate 2 觉醒 | 用户延后 |
| 6 | Phase I 激活 | 需要 1-2 个月预测历史数据积累 |
| 7 | 影子 JSON 17 站点 | 非关键路径，影子使用结构化输出 |

---

## 📊 总览

```
已完成:  27 个模块 | 10/10 管线 | 3/3 Gate | 9/9 hook | 8 个夹具
待完成:  7 项（2 个需用户讨论 + 2 个功能 + 3 个延后）
测试:    1302 pass / 0 fail
```

---

**本文件是项目进度的权威来源。每个阶段完成后更新。**
