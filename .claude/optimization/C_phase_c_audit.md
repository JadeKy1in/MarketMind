# Phase C Operation Scout 审计报告
**日期**: 2026-05-11
**审计范围**: 17个文件（8源码 + 9测试）
**结论**: NEEDS_FIX（0 CRITICAL, 2 WARNING, 3 INFO）

## 发现

### WARNING W1: `shadow_runtime_state` 共享行 — 读-合并-写竞态

**位置**: `emergency_quota.py:_save_state()` + `paper_live_gap.py:_save_state()`

两个模块都读取同一个 `shadow_runtime_state` 行，合并各自的 JSON 段，然后写回。如果两者并发写入，后写入的会静默覆盖先写入的。当前编排循环（顺序执行 `audit_result()` → `update_discount_rate()`）不会触发此竞态，但设计是脆弱的。

**建议**: 将两个模块的 `shadow_runtime_state` 写入合并到一个协调方法中，或拆分为两个独立的表。

### WARNING W2: 内存字典无并发保护

**位置**: `emergency_quota.py:_shadow_states` + `paper_live_gap.py:_discount_rates`

两个字典在异步挂起点之间被读写，没有锁保护。Asyncio 的单线程模型当前防止了竞态，但未来任何按 shadow 并发访问都会出问题。

**建议**: 如果未来改为 per-shadow 并发，添加 `asyncio.Lock`。

### INFO I1: 测试 `test_init_schema_creates_all_tables` 未验证第8张表

测试检查了前7张表但未验证 `shadow_runtime_state` 的存在。因为使用 `issubset`，即使表缺失测试也能通过。

### INFO I2: `_safe_headline` 刚修复 NewsItem 兼容性

Mock 管道运行暴露了 `_filter_news_by_domain()` 直接调用 `item.get()` 的 bug——管道传来的 `NewsItem` 对象没有 `.get()` 方法。已通过添加 `_safe_headline()` 静态方法修复。

### INFO I3: Scout API 源不可达

Mock 管道运行中6个RSS源（FRED, BLS, SEC EDGAR等）返回4xx错误。这是外部依赖问题，非代码缺陷。不影响 mock 模式。

## 逐文件审查

### shadow_agent.py — PASS
- `_analyze()`: LLM调用正确，异常时安全回退到空content；`caller_agent` 格式 `"shadow:{type}:{display_name}"` 正确
- `analyze_position_exits()`: 5天闸门正确，`cash_reframing_ticker` 传递正确，异常默认 `should_exit=False`
- `create_shadow_agent()`: 工厂类型分发覆盖全部7种shadow_type，fallback到ShadowAgent安全
- `_parse_votes()`: regex 使用 `re.DOTALL`，confidence 被 clamp 到 [0,1]，Vote block 解析健壮

### shadow_mother.py — PASS
- `orchestrate_daily_cycle()`: `asyncio.gather` + `Semaphore(max_concurrent_shadows)` 正确控制并发
- 每个步骤都有独立的 try/except 隔离异常
- 工厂函数 `create_shadow_agent` 取代了之前的 base `ShadowAgent` 实例化
- `scan_events()` 去重逻辑正确（`seen_headlines` set）

### expert_shadows.py — PASS (修复后)
- `_safe_headline()`: 新增，正确处理 dict 和 object 两种输入
- `_filter_news_by_domain()`: 已修复，使用 `_safe_headline()` 替代 `item.get()`
- `_build_user_prompt()`: 领域上下文正确注入，使用 `_safe_headline()`

### daredevil_shadows.py — PASS
- `_build_user_prompt()`: 4种约束变体（DANGER ZONE, CONTRARIAN MODE等）基于 `shadow_id` 正确分支
- `_analyze()`: 正确委托给基类

### catfish_agent.py — PASS
- 共识触发条件正确（≥80%，≥3个非弃权投票）
- 仅在触发时调用LLM（节省配额）
- `_build_user_prompt()`: 触发模式正确注入反方提示

### shadow_state.py — PASS
- `shadow_runtime_state` 表: `INSERT OR REPLACE` + FK 引用正确
- `save_runtime_state()` / `load_runtime_state()`: 参数化查询（防SQL注入）
- 所有8张表通过 `CREATE TABLE IF NOT EXISTS` 创建

### emergency_quota.py — PASS
- 状态机转换正确：NORMAL→PENDING→AUDIT→REWARDED/PENALIZED→NORMAL
- 盈利/亏损惩罚逻辑已验证：3次连续失败→永久-1
- `_get_or_create_state()`: DB恢复优先，损坏JSON回退到默认值

### paper_live_gap.py — PASS
- 滑点方向正确：做多入场+滑点，做空入场-滑点
- 折扣率范围 [0.05, 0.20]，平滑调整因子0.75
- 6项Live-Ready标准全部正确实现

### 测试文件 — PASS（9个文件，322个测试）
- 错误路径覆盖良好（LLM失败、JSON损坏、空响应）
- Mock 模式一致：`patch("marketmind.gateway.async_client.chat_with_integrity", ...)`
- 工厂类型分发已验证
- E2E 和 LLM 集成测试已添加

## 首要建议

1. **W1修复**: 将 `EmergencyQuotaAuditor` 和 `PaperLiveGapManager` 的运行时状态拆分为两个独立的DB表，消除共享行竞态。
2. **W2加固**: 如果未来启用 per-shadow 并发分析，为 `_shadow_states` 和 `_discount_rates` 添加 `asyncio.Lock`。
3. **I1修复**: 更新 `test_init_schema_creates_all_tables` 验证第8张表。

## 结论

Phase C 代码质量良好。0个CRITICAL问题，2个WARNING都是设计层面的远期风险（当前编排不会触发）。所有LLM调用路径正确，状态持久化完整，测试覆盖充分。建议在 Phase D 中处理 W1/W2。
