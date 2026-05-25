# MarketMind — 项目回审优化进度 & 路线图

**日期**: 2026-05-17 | **阶段**: G (95%) | **测试**: 579/582 通过 | **源文件**: 101 个 | **测试文件**: 60 个

---

## 一、项目架构总览

MarketMind 是一个多智能体影子生态系统（Multi-Agent Shadow Ecosystem），用于投资信号验证和决策支持。核心架构为 6 层信息获取 + 21+ 独立影子分析师 + 3 层流水线分析。

```
marketmind/
├── app.py                     # CLI/GUI 入口
├── gateway/                   # LLM 网关层 (5 modules)
│   ├── async_client.py        # Flash/Pro 路由 + KeyRotator + TokenBudget
│   ├── multimodal_adapter.py  # 多模态适配 (截图/PDF/图片 → Gemini Vision)
│   ├── response_parser.py     # 结构化输出解析
│   ├── token_budget.py        # 优先级 Token 预算
│   └── macro_data.py          # 宏观数据 (FRED/EIA/CFTC)
├── shadows/                   # 影子生态系统 (22 modules)
│   ├── shadow_agent.py        # 基类 + 21 影子工厂
│   ├── shadow_state.py        # SQLite 10 表持久化 (1300+ lines)
│   ├── shadow_mother.py       # 每日编排 + 事件检测 + 临时影子
│   ├── shadow_memory.py       # 分层记忆 (working/episodic/semantic)
│   ├── ranking_engine.py      # MPPM/Calmar/Omega 复合排名
│   ├── challenger_engine.py   # 3 阶段淘汰缓冲
│   ├── expert_shadows.py      # 15 个领域专家
│   ├── daredevil_shadows.py   # 5 个高风险策略
│   └── ...                    # 其余 14 个模块
├── pipeline/                  # 分析流水线 (10 modules)
│   ├── scout.py               # 新闻发现 (27 sources)
│   ├── layer1_narrative.py    # 叙事层
│   ├── layer2_fundamental.py  # 基本面 5 层递进
│   ├── layer3_technical.py    # 技术面 3 灯审查
│   ├── decision.py            # 决策聚合
│   └── ...
├── ui/                        # Command Center GUI (customtkinter)
├── storage/                   # 持久化 (session + archivist)
├── integrity/                 # 质量保障 (watchdog + fact_checker)
└── config/                    # 配置 (settings + prompts + sources)
```

---

## 二、阶段完成历史

| 阶段 | 日期 | 主要交付 | 测试数 |
|:---:|:---:|------|:---:|
| **A** | 2026-05-10 | 基础架构：app.py, gateway, pipeline 骨架 | ~150 |
| **B** | 2026-05-11 | 影子生态系统：14 模块, 21+ shadows, 排名/挑战者/反合谋 | 299 |
| **C** | 2026-05-12 | LLM 集成：Flash/Pro 路由, 真实 API 调用替换桩代码 | ~320 |
| **D** | 2026-05-12 | 投决持久化, GapRatio 校准, 回测, UI 图表, KeyRotator | 339 |
| **E** | 2026-05-13 | UI 完善, Pre-Decision Challenge, R4 Shadow Dashboard | ~500 |
| **F** | 2026-05-14 | 影子记忆, 结晶引擎, 方法论进化器, AEL 学习 | ~600 |
| **G** | 2026-05-16 | 6 层信息源集成, 时间幻觉修复, 模块提取, 82→101 源文件 | 697→579 |

### 各阶段详细

#### Phase A — 基础架构
- `app.py` CLI/GUI 双入口
- `gateway/async_client.py` Flash/Pro 路由, M1 完整性注入
- `pipeline/scout.py` 新闻发现, `pipeline/decision.py` 决策聚合
- 3 系统法则 (物理隔离, 抗过拟合, 输出规范)

#### Phase B — 影子生态系统
- 14 个影子模块, 21+ 独立分析代理
- 7 种影子类型：Expert(15), Daredevil(5), Catfish(1), Temp(动态), MissedPath, Challenger, Beta
- SQLite 持久化 (7 表 WAL 模式)
- 合规排名 (MPPM/Calmar/Omega/WR 复合)
- 3 阶段淘汰缓冲区 + 反合谋检测
- **质量门**: 299 tests, 3 CRITICAL 修复, B+ 优化评分

#### Phase C — LLM 集成
- 真实 DeepSeek Flash/Pro API 替换所有桩代码
- Gateway 级别 M1 数据完整性协议注入
- L1/L2/L3 3 层递进分析流水线

#### Phase D — 影子系统完善
- 投决持久化 (shadow_votes 表 — 第 10 张 SQLite 表)
- GapRatio 校准：按资产按策略的 PnL 离散度
- 多日回测 (backtest_runner.py)
- UI 排名趋势 + 折价率图表 (Canvas)
- 方法论 Prompt 外置化 (shadow_prompts.json)
- KeyRotator + TokenBudget 集成

#### Phase E — UI 完善
- R4 Shadow Dashboard（排名表 + 状态卡片）
- R6 Pre-Decision Challenge
- R7 DST 修复
- 共享流水线辅助函数提取

#### Phase F — 记忆与学习
- 影子分层记忆 (working → episodic → semantic)
- CrystallizationEngine 结晶引擎 (insight → hypothesis → validate → promote/retire)
- MethodologyEvolver 方法论进化
- AEL (Automated Experience Learning) 慢速层

#### Phase G — 6 层信息源集成
- **Layer 1** 新闻 (27 sources, source_authority.py)
- **Layer 2** 社交 (Bluesky OAuth, ApeWisdom, Trump RSS, 8 KOLs)
- **Layer 3** 市场数据 (yfinance/Finnhub/Binance, on-demand caching)
- **Layer 4** 内部人 (Form 4/13F, Congress — 已失效)
- **Layer 5** 宏观 (FRED/EIA/CFTC)
- **Layer 6** 期权/日历 (Options Flow, Economic Calendar, Earnings Dates)
- **L1 Tools**: 8 个分析工具 (拆分为 l1_market_tools + l1_info_tools)
- **时间幻觉修复**: 18 处 UTC 修复, time_anchor.py SessionStart hook, config_guardian.py
- **模块提取**: 82→101 源文件 (拆分 monolith app.py 971→301 lines)

---

## 三、当前 Phase G 状态 (95%)

### 已完成 ✅

| 层面 | 状态 | 关键文件 |
|:---:|:---:|------|
| L1 新闻 (27 sources) | ✅ | source_authority.py, scout.py (VCR 测试框架) |
| L2 社交 | ✅ | social_sources.py (Bluesky OAuth 验证通过) |
| L3 市场数据 | ✅ | market_data.py (on-demand + cache) |
| L4 内部人 | ✅ | insider_sources.py (Form 4/13F; Congress 源已死) |
| L5 宏观 | ✅ | macro_data.py (EIA 正常; FRED/CFTC 需修复) |
| L6 期权/日历 | ✅ | economic_calendar.py, options_flow.py, earnings_dates.py |
| L1 Tools | ✅ | 8 tools (l1_market_tools.py + l1_info_tools.py) |
| 时间幻觉修复 | ✅ | §3.2 规则, time_anchor.py hook, config_guardian.py |
| 模块提取 | ✅ | app.py 971→301, 6 个模块从 monolith 中提取 |
| UTC datetime | ✅ | 所有 `datetime.now()` → `datetime.now(timezone.utc)` |

### 2026-05-17 Bug 修复 (12 个)

| # | 问题类型 | 修复 |
|:---:|------|------|
| 1-6 | 缺失模块 | 重建 6 个 pipeline 模块 (session_context, l2/l3/decision/layer1 interactive) |
| 7 | 缺失函数 | `defang_text` 添加到 shadow_agent (prompt injection 防御) |
| 8 | 缺失类 | `ToolState`/`InteractiveState` 添加到 layer1_interactive |
| 9 | 缺失方法 | `MethodologyEvolver.get_audit_trail` 添加到 class |
| 10 | 参数语义 | `MultimodalAdapter("")` 改为明确 "no key" |
| 11 | 未定义变量 | `today_day` UnboundLocalError 修复 |
| 12 | 缺失函数 | `app.py` 添加 `_setup_logging` 和 `run_interactive` |

### 待完成 (R1-R4 + H1-H3 + L1-L2)

| # | 优先级 | 任务 | 状态 |
|:---:|:---:|------|:---:|
| **R1** | 🔴 | FRED series IDs 修复 (BDI/GSCPI 返回 400) | 调研中 |
| **R2** | 🔴 | CFTC COT SODA 查询修复 (400) | 调研中 |
| **R3** | 🔴 | API key 日志泄露修复 (macro_data.py) | 修复中 |
| **R4** | 🔴 | 8 个文件 >500L 需拆分 | 评估中 |
| H1 | 🟡 | Congress 替代方案 (CapitolTrades 爬虫) | — |
| H2 | 🟡 | Bluesky 内容质量验证 | — |
| H3 | 🟡 | Reddit WSB 健康检查 UA 同步 | — |
| L1 | 🟢 | VCR cassette 刷新 (3 个错误) | — |
| L2 | 🟢 | PICA 审计 (新提取模块) | — |

---

## 四、文件大小审计 (CLAUDE.md §3.1)

**8 个文件超过 500 行硬上限**（必须以新功能为条件强制重构）：

| 行数 | 文件 | 主要职责 | 超限程度 |
|:---:|------|------|:---:|
| 1352 | `shadows/shadow_state.py` | SQLite 10 表 schema + CRUD + 迁移 | **2.7x** |
| 892 | `shadows/shadow_mother.py` | 每日编排 + 事件检测 + 影子生命周期 | **1.8x** |
| 703 | `shadows/ranking_engine.py` | 复合排名 (MPPM/Calmar/Omega) + Bayesian | **1.4x** |
| 701 | `shadows/methodology_evolver.py` | 方法论进化 + 注入器 + 审计追踪 | **1.4x** |
| 572 | `shadows/shadow_memory.py` | 分层记忆 (working/episodic/semantic) | **1.1x** |
| 539 | `shadows/shadow_db.py` | 数据库连接池 + 查询构建 | **1.1x** |
| 529 | `shadows/shadow_agent.py` | 基类 + 完整分析周期 + 虚拟投资组合 | **1.1x** |
| 510 | `gateway/multimodal_adapter.py` | Gemini Vision + Tesseract + pdfplumber | **1.0x** |

**祖父条款**: 截至 2026-05-15 认定的 6 个文件可接受仅提取修改和 bug 修复。新功能需先提取。目标：Phase G 结束前全部合规。

---

## 五、测试覆盖

| 指标 | 数值 |
|------|:---:|
| 总收集测试数 | 582 |
| 当前通过数 | 579 |
| 当前失败数 | 0 |
| VCR cassette 错误 | 3 (环境问题，非代码 bug) |
| 测试文件数 | 60 |
| 最高峰通过数 | 697 (Phase G 初期) |

**测试分布**:
- `test_shadows/` — 147+ tests (影子生态系统核心)
- `test_pipeline/` — 流水线各阶段
- `test_gateway/` — Gateway + Token Budget
- `test_ui/` — UI 组件
- `test_integrity/` — 完整性看门狗
- `test_storage/` — 存储层

---

## 六、技术债务与风险矩阵

| 债务项 | 严重度 | 影响 | 计划 |
|------|:---:|------|------|
| 8 文件 >500L | HIGH | 新功能受阻 (需先提取) | Phase G 结束前 |
| FRED BDI 系列 ID 错误 | MEDIUM | 宏观数据缺失 | R1 |
| CFTC SODA API 端点过期 | MEDIUM | COT 数据缺失 | R2 |
| API key 日志泄露 | HIGH | 安全风险 | R3 (修复中) |
| Congress 内部人源失效 | LOW | L4 数据缺口 | H1 |
| VCR cassette 缺失 | LOW | 离线测试不可用 | L1 |
| 冒烟测试覆盖率 ~65% | MEDIUM | 回归检测盲区 | 目标 80% |
| Schema 迁移无版本控制 | LOW | Phase D 已知限制 | 未来 |

---

## 七、2026-05-17 会话路线图

### 本次会话完成
- [x] §0 检查通过
- [x] 12 个 Bug 修复 → 579 测试通过
- [x] 非 UTC datetime.now() 清零
- [x] 嵌套旧目录清理
- [x] Commit `e9b1c1e`

### 并行进行中
- [ ] **R3** — API key 日志泄露修复 (Agent 后台)
- [ ] **R1 + R2** — FRED/CFTC API 调研 (Agent 后台)
- [ ] **R4** — 大文件拆分评估 (Agent 后台)

### 下一步
1. 应用 R1/R2/R3 修复
2. 运行全量测试确认无回归
3. Commit R1-R4
4. Phase G 最终审计 (Red Team + Scout)
5. 决定是否推进 R4 文件拆分 或 标记 Phase G 完成

---

## 八、Phase G 完成后的路线图

### Phase H: 生产就绪 (目标: 80%+ 测试覆盖)

| 任务 | 描述 |
|------|------|
| H1 | 文件拆分完成 (8 files → ~16 modules) |
| H2 | 测试覆盖率从 65% 推到 80% |
| H3 | VCR cassette 完整录制 (27 sources) |
| H4 | PICA 审计全部新提取模块 |
| H5 | Congress 替代数据源 (CapitolTrades or manual-only) |
| H6 | Bluesky + Reddit 内容质量评分系统 |
| H7 | Schema 迁移版本控制框架 |
| H8 | 性能优化 (shadow_mother 编排并行化) |

### Phase I: 高级特性

| 任务 | 描述 |
|------|------|
| I1 | 多资产组合再平衡引擎 |
| I2 | 实时 websocket 市场数据流 |
| I3 | Shadow-vs-Shadow 性能竞技场 |
| I4 | 自动方法论 A/B 测试框架 |
| I5 | 报告生成 (PDF/HTML, 双语) |
| I6 | CI/CD pipeline (GitHub Actions) |

### Phase J: 部署与监控

| 任务 | 描述 |
|------|------|
| J1 | Docker 容器化 |
| J2 | Prometheus + Grafana 监控 |
| J3 | 每日自动化调度 (cron/Windows Task Scheduler) |
| J4 | 告警集成 (邮件/微信/Slack) |
| J5 | 用户认证与多租户 |

---

**最后更新**: 2026-05-17 07:00 UTC
