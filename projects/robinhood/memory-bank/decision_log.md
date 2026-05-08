# decision_log.md - 外部决策日志

## 用途

本文件记录 PM 注入的外部业务决策。每次开始新 Session 编码前，必须首先读取本文件并校验当前任务目标是否与最新决策一致。

## 决策记录

| 日期 | 决策 ID | 决策描述 | 影响范围 | 状态 |
|---|---|---|---|---|
| 2026-05-04 | AD-001 | 采纳《智能量化投资分析系统架构》作为设计蓝本。三大天条固化：无 Emoji、无券商 API、四维共振打分。 | 全局架构 | 生效 |
| 2026-05-04 | AD-002 | 物理隔离纪律：系统决不允许直接调用任何券商 API 执行买卖。所有账户数据基于本地 JSON 文件手动输入。 | 数据采集层 | 生效 |
| 2026-05-04 | AD-003 | 唯一 LLM 供应商锁定为 DeepSeek。系统内部 Model Router 仅配置 DeepSeek 的 Act 与 Pro 两个模型。 | 决策层 | 生效 |
| 2026-05-04 | AD-004 | Task 1.1 修正为纯本地 JSON 文件读取。移除原设计中所有涉及 robin_stocks 库的引用。 | Phase 1 | 已执行 |
| 2026-05-04 | AD-005 | Phase 1 Task 1.1 实现完毕并通过测试验收（5/5 passed）。PM 批准进入后续 Phase 1 任务的编码阶段。 | Phase 1 | 批准 |
| 2026-05-04 | AD-006 | 批准使用 yfinance 作为市场行情数据源。新增依赖白名单: yfinance, pandas。 | Task 1.2 | 生效 |
| 2026-05-04 | AD-007 | JSON 本地缓存策略：按 (ticker, timeframe, last_updated) 键值存取，基于日期不匹配判定过期。 | Task 1.2 | 生效 |
| 2026-05-04 | AD-008 | `now` 参数注入设计：所有缓存对象接受可选的 `now` callable，测试无需 mock 系统时钟。 | Task 1.2~1.4 | 生效 |
| 2026-05-04 | AD-009 | 宏观日历优雅降级：网络请求失败时返回本地预设的静态测试日历，而非抛出异常。 | Task 1.3 | 生效 |
| 2026-05-04 | AD-010 | 情绪采集多源接口：Truth Social 通过 RSS 抓取，Capitol Trades 通过公开 JSON API 获取。 | Task 1.4 | 生效 |
| 2026-05-04 | AD-011 | 一致性缓存模式：所有采集模块使用统一的 JSON 缓存基类模式，缓存行为可预测、测试方式统一。 | Phase 1 | 生效 |
| 2026-05-05 | AD-012 | 采纳 ROI 评估推荐方案 B（借鉴蓝图自研）。核心逻辑借鉴桥水全天候框架四象限分类法，零外部依赖自研。 | Phase 5 | 生效 |
| 2026-05-05 | AD-013 | asset_mapper 三维配置篮子设计：按流动性 (High Liquidity) / 低费率 (Low Expense Ratio) / 高弹性 (High Beta) 三轨映射。所有 Ticker 通过宏观 Tag 路由计算权重。 | Phase 5 | 生效 |
| 2026-05-05 | AD-014 | causal_auditor 采用 InMemoryStateMachine 驱动失效触发器。48 小时后通过 market_fetcher 自动读取 trigger 价格阈值进行打分验证。 | Phase 5 | 生效 |
| 2026-05-05 | AD-015 | source_governor 三角形校验法则：任何叙事必须至少 2 个互不相关的官方物理流量数据佐证。官方信源 (Fed/OPEC/EIA) 权重最高。 | Phase 5 | 生效 |
| 2026-05-05 | AD-016 | continuation_protocol 采用输出 JSON 块 + 续写指令模式。多轮 API 递归调用后在中转层合并 JSON，再交由 output_formatter 渲染。 | Phase 5 | 生效 |
| 2026-05-07 | AD-P8-001 | ShadowTribunal 位置签名固定为 `(store, config)` — 所有调用者使用此顺序。`__init__` 已纠正以匹配。 | Phase 8 | 生效 |
| 2026-05-07 | AD-P8-002 | ShadowFormatter 将 batch 判定委托给 ShadowTribunal.judge_batch() — 确保法庭裁决在格式化时始终可用。 | Phase 8 | 生效 |

## 下一 Session 对齐清单

在开始新 Session 前，请确认以下事项:

- [x] 当前任务目标是否在 AD-001 ~ AD-016 + AD-P8-001 ~ AD-P8-002 的有效范围内?
- [ ] 是否有新的外部决策导致当前设计方案需要调整?
- [ ] 本文件中是否有与本 Session 冲突的未完成指令?
- [x] Phase 8 核心测试 87/87 100% 通过 — 可安全进入 Phase 8.1
