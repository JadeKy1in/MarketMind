# Phase C Red Team 安全审计

**日期**: 2026-05-11 | **结论**: ISSUES_FOUND | **范围**: 9个源码文件

## 总结

| 严重度 | 数量 | 关键发现 |
|--------|------|----------|
| CRITICAL | 1 | shadow_runtime_state 读-合并-写竞态导致静默数据丢失 |
| WARNING | 5 | Prompt注入、regex注入、批量崩溃、str.format错误、共享状态blob |
| INFO | 6 | INSERT OR REPLACE语义、投票解析、安全默认值、零SQL注入 |

## CRITICAL

**C-1**: EmergencyQuotaAuditor 和 PaperLiveGapManager 对同一 shadow_runtime_state 行执行非原子的读-合并-写。两者各自打开独立连接→SELECT→解析JSON→合并→INSERT OR REPLACE。后写入者静默覆盖先写入者的数据。

**修复**: 添加 per-shadow_id 的 asyncio.Lock，或拆分为两张独立表。

## WARNING

- **W-1**: 新闻标题、market_data值、trigger_ticker 直接拼入LLM提示词，无清理
- **W-2**: `_extract_field()` 中 `field` 参数未使用 `re.escape()`
- **W-3**: `chat_batch_flash()` 单个失败导致整批取消
- **W-4**: `CASH_REFRAMING_PROTOCOL.format()` 中ticker含`{}`会触发KeyError
- **W-5**: 两个模块共享一个state_json blob，无协调机制（C-1根因）

## INFO

- I-1: INSERT OR REPLACE语义 — 内部DELETE+INSERT，未来加CASCADE需注意
- I-2: 投票解析无法区分LLM生成和LLM回显的注入块
- I-3: 退出决策安全解析 — 仅"exit"触发，fail-closed设计
- I-4: 零SQL注入 — 所有查询使用`?`参数化
- I-5: 安全异常默认值 — LLM失败→空投票，退出分析→hold
- I-6: JSON损坏回退完整 — 6个json.loads()调用点均有异常处理

## 修复优先级

1. **立即**: C-1/W-5 — 添加per-shadow_id锁或拆分表
2. **本迭代**: W-3 — chat_batch_flash 添加 try/except
3. **下迭代**: W-1a — 验证 trigger_ticker 格式；W-2 — 添加 re.escape
4. **待办**: W-4 — 切换为Template格式化；W-1b/d — PromptSanitizer工具
