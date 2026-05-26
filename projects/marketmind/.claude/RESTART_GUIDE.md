# MarketMind Restart Guide — 2026-05-26 EOD

**Tests**: 2,049 pass, 0 fail, 0 skip | **CI**: green | **Branch**: master
**Latest commits**: 862743cf → 0e00cd74 → a6ea164f → 1eee6be9 → cd44fe9c
**All pushed**: no | **frontload_required**: true

---

## 重启指令

> 继续 MarketMind 开发。阅读 `.claude/RESTART_GUIDE.md`。
> 上次完成：5→4 级合并彻底清理 + VOTE→DECISION 全量重命名 + --mock 模式 + 主管线自校准 + 实盘验证

---

## 今日完成 (2026-05-26)

### Session 1：Dashboard + 管线修复
- `dashboard.html`: JS 语法错误（反引号→引号）+ 未定义 API 变量
- `api/data_providers.py`: IntEnum str() 比较 bug → 所有信息源误判不可用
- `config/settings.py`: 5→4 级 `watch` key 残留 → KeyError
- `pipeline/orchestration.py`: L1/L2/L3/Decision None 防护
- `shadow_analysis_runner.py`: `save_votes` → `save_analyses`
- `shadow_agent.py`: `_extract_field` 正则加 `|` 分隔符

### Session 1.5：决策数据链路修复
- `api/data_providers.py`: `get_decision_history` 从 shadow DB 读取（替代损坏的 archive FTS）

### Session 2：P1 VOTE→DECISION 全量重命名
- `shadow_agent.py`: `VOTE_START/END` → `DECISION_START/END` + `_parse_votes` → `_parse_decisions`
- 反向兼容正则：`(?:DECISION|VOTE)_START` / `(?:DECISION|VOTE)_END`
- 6 个 prompt 文件 token 更新（daredevil, expert, momentum, contrarian, catfish, shadow_mother）
- `shadow_mother.py` + `shadow_analysis_runner.py`: `votes_collected` → `decisions_collected`, `all_votes` → `all_decisions`
- `orchestrator.py` + `shadow_ranking_compute.py` + `shadow_vote_collector.py`: `all_votes` → `all_decisions`
- 4 个测试文件更新

### Session 2.5：P2 --mock 模式实现
- `gateway/async_client.py`: 新增 `set_mock_mode()` + `chat_flash/chat_pro` 拦截
- Mock 模式管线 6m27s → 46s（8x 加速）
- `pipeline/orchestration.py`: `run_daily` 接入 `set_mock_mode(mock)`

### Session 3：主管线自校准 + 实盘验证 + P3 + 5→4 合并清理
- **新增** `pipeline/daily_calibration.py`: 保存每日预测，次日加载并对比实际市场（shadow DB next-day returns），生成校准上下文注入 L1 prompt
- `pipeline/layer1_narrative.py`: `analyze_layer1` 接受 `calibration_context` 参数
- **实盘验证**: 真实 API 管线 9/9 全通（3m45s），影子生态产出实际决策
- **P3**: `storage/archivist.py` 默认路径 `"data/archive"` → `"data"`（统一存档数据库）
- **5→4 合并清理**: 9 文件移除残留 `"watch"` 引用（composite_scoring, post_graduation_monitor, shadow_data_types, shadow_status_card, shadow_panel + 4 个测试）
- `shadow_ranking_compute.py`: `market_accuracy` → `market_accuracies`

---

## 明天可以做的

| # | 任务 | 说明 |
|:--:|------|------|
| **1** | **主管线迭代进化体系** | 审计 Flash Triage→HVR→L1→L2→L3→RedTeam→Resonance→Decision 的自我优化能力。影子有 AEL（三层：周度 Flash 复盘 + ELITE 巩固 + 季度 Pro 审计），主管线目前只有刚加的每日校准。可以设计类似的多层自优化机制 |
| 2 | 影子生态投票→决策命名收尾 | `shadow_vote_collector.py` 文件名 + `collect_votes` 函数名 + 内部 `votes` 变量 → decisions 术语。该文件未在任何地方导入，可能是死代码，可审计后清理 |
| 3 | 影子 AEL 进化机制验证 | 验证影子三层 AEL 是否正常运行：周度 Flash 复盘、ELITE 巩固模式、季度 Pro 审计 |
| 4 | Dashboard Evolution 页面 | `evolution.html` 已存在但未验证是否正常显示数据 |
| 5 | Git push | 4 个 commits 未推送（cd44fe9c, 1eee6be9, a6ea164f, 0e00cd74, 862743cf） |

---

## 快速命令

```bash
cd E:/AI_Studio_Workspace/projects/marketmind
python api_server.py                    # Dashboard → http://localhost:8520
python app.py --mode daily --mock -v    # Mock 管线 (~46s)
python app.py --mode daily -v           # 实盘管线 (~4min, 需要 API 预算)
python -m pytest tests/ -q -m "not slow" -p no:warnings  # 测试 (2,049 pass)
```

---

## 关键架构变更 (本次 Session)

| 变更 | 影响 |
|------|------|
| `--mock` 模式真正生效 | 管线从 6m27s → 46s，不消耗 API 预算 |
| VOTE→DECISION 重命名 | 40+ 处引用，反向兼容 LLM 输出格式 |
| 主管线自校准 | 新模块 `pipeline/daily_calibration.py`，每日保存预测 → 次日对比实际 → 注入 L1 |
| 决策历史 API | 从 shadow DB 直接读取（不再依赖损坏的 archive FTS） |
| 5→4 级合并完成 | 全量代码 `"watch"` 零残留 |
| 存档路径统一 | `data/archive.db`（单一数据库） |

## 5→4 级说明

WATCH(30%) 和 ENDANGERED(15%) 合并为统一的 ENDANGERED(20%)，14 天连续触发。Dashboard 显示 4 个等级条（ELITE / EXCELLENT / NORMAL / ENDANGERED）。此合并现已彻底完成——所有源文件、UI、测试均无 `"watch"` 残留。

## 管线架构 (2026-05-26)

```
[0/9] Shadow Mother → 25 shadows init
[1/9] Scout → RSS fetch (33 sources, ~40s)
[2/9] Flash → chat_flash (signal extraction)
[3/9] L1 → chat_pro (narrative + calibration context)
[4/9] L2+L3 → chat_pro parallel (fundamental + technical)
[5/9] Shadows → background launch (non-blocking)
[6/9] Red Team → chat_pro (adversarial challenges)
[7/9] Resonance → statistical validation
[8/9] Decision → chat_pro (synthesis + no-trade check)
[9/9] Archive → save session + calibration prediction
```

反馈环：Step 9 保存预测 → 次日 Step 3 注入校准上下文 → 后续分析据此调整。
