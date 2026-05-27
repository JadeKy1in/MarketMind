# MarketMind Restart Guide — 2026-05-27 EOD

**Tests**: 1,645+ pass, 0 fail | **CI**: green | **Branch**: master
**All pushed**: no | **frontload_required**: true

---

## 重启指令

> 继续 MarketMind 开发。阅读 `.claude/RESTART_GUIDE.md`。
> 上次完成：Playground 实验层搭建 + serenity-reply 入驻 + 主管线三层进化体系 + 4个半导体源合入主Scout + shadow_vote_collector 死代码清理

---

## 今日完成 (2026-05-27)

### Session 1: Playground 实验层搭建
- **新模块**: `playground/` — 独立于主管道的 Agent 实验沙箱
- **信息防火墙**: Playground agent 只收公开数据，不得接触主管道/影子输出
- **Agent 自声明**: `agent_manifest.py` — 无硬编码分类，类型从观察中涌现
- **评估体系**: 通用层（稳定性+合法性+无数据泄露）+ 类型特定层 + 相关性检查
- **升级门控**: 60天观察期 + 20次决策 + 准确率>55% + 夏普>0.5 + 回撤<25%
- **serenity-reply**: 首个入驻 Agent（@aleabitoreddit 半导体供应链瓶颈理论蒸馏）
- `playground_runner.py`: 每日运行 + 信息防火墙 + JSONL 审计日志
- `playground_tracker.py`: 次日结算 + 绩效追踪 + 夏普/回撤/利润因子
- `playground_auditor.py`: 月度审计 + 升级门控检查 + 个案集成路径
- `playground_fetcher.py`: WP API + RSS 双通道数据抓取
- `playground_sources.py`: 16 源三档分类（8 CORE + 1 SUPPLEMENTAL + 6 RETIRED + 1 退役）

### Session 2: serenity-reply 数据源配置
- **WP API 通道**: 6 个源提供完整文章（EDN 15k, ServeTheHome 23k, Solid State Tech 8k, EE Times 7k, Semiconductor Digest 4.7k, SemiEngineering 1.9k chars）
- **RSS 通道**: 2 个源（EE Times Asia 3.2k, Photonics Spectra 720 chars）
- **三档机制**: CORE 每日必取，SUPPLEMENTAL 核心<15篇时触发，RETIRED 审计可查
- **淘汰 6 源**: Tom's Hardware, TechPowerUp, Ars Technica, The Register, WCCFTech, Power Electronics News
- **4 源合入主 Scout**: EE Times, Semiconductor Engineering, EDN, EE Times Asia

### Session 3: serenity-reply Flash 研究循环
- **两轮分析**: Pass 1 初始瓶颈分析 → 研究轮（confidence 0.6-0.8 触发）→ Pass 2 综合重评
- **研究日志**: 每次 Flash 调用记录完整 system_prompt + user_prompt + response
- **文章匹配**: 按 ticker + 关键词评分取 top 5 全文，格式化为研究输入
- **审计字段**: `_research_log`, `_passes`, `_research_leads_identified`, `_research_rounds_completed`

### Session 4: 主管线三层迭代进化体系
- **新增** `pipeline/pipeline_metrics.py`: 每日指标快照（Flash/L1/L2/L3/RedTeam/Resonance/Decision 各阶段数据）
- **新增** `pipeline/weekly_tactical_audit.py`: Layer 2 周度战术审计（Flash 驱动，7维度阶段健康检查）
- **集成**: 指标自动记录到 `run_daily()` 结尾 + 周度审计每 7 天自动触发
- **注入**: 周度审计建议通过 `get_suggestion_context()` 注入 L1 prompt（与日校准并列）

### Session 5: 影子命名收尾 + 基础设施
- `shadows/shadow_vote_collector.py` → 确认为死代码，已删除
- **验证**: 影子 AEL 三层全部健康（weekly_flash / evolution / quarterly_pro）
- `app.py --playground` flag: 主管线后自动运行 Playground agents

### Session 6: 主管道迭代进化体系设计（设计完成，部分实现）
- Layer 1: 每日校准（`daily_calibration.py` 已有）+ 增强（Flash 评分准确率 + HVR 回报率 — 待实现）
- Layer 2: 每周战术审计（`weekly_tactical_audit.py` 已实现）
- Layer 3: 跨阶段归因审计（`methodology_evolution.py` 已有 walk-forward，跨阶段扩展待实现）

---

## 明天可以做的

| # | 任务 | 说明 |
|:--:|------|------|
| 1 | **主管线迭代进化体系完结** | Layer 1 增强（Flash/HVR 追踪）+ Layer 3 跨阶段归因（Decision 错误回溯到具体阶段） |
| 2 | Playground 实盘验证 | `python app.py --mode daily --mock --playground` 跑一次完整流程 |
| 3 | serenity-reply 数据源验证 | 真实 WP API 返回是否正常（模拟 vs 实盘）|
| 4 | Git push | 所有更改未推送 |

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
python app.py --mode daily --mock --playground  # Mock 管线 + Playground agents
python -m pytest tests/ -q -m "not slow" -p no:warnings  # 测试
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

反馈环：Step 9 保存预测 → 次日 Step 3 注入校准上下文 + 每周审计建议 → 后续分析据此调整。

## 主管线进化体系 (2026-05-27 新增)

```
Layer 1 每日校准: daily_calibration.py
  └── 保存预测 → 次日加载 → 对比实际 → 注入 L1 prompt

Layer 2 每周战术审计: weekly_tactical_audit.py  [NEW]
  └── 读取 pipeline_metrics.jsonl → Flash 分析 7 维度 → 建议注入 L1

Layer 3 跨阶段归因: methodology_evolution.py
  └── Walk-forward backtest gate → RuleEvolver → SHARP registry 更新
  (待实现: 跨阶段归因链 — Decision 错误 → Red Team/L2/Flash 溯源)
```

数据流: `run_daily()` → 记录 `pipeline_metrics.jsonl` → 每 7 天触发 `weekly_tactical_audit` → 建议保存 JSON → 次日注入 L1 prompt
