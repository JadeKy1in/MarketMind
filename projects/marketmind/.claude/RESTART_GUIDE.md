# MarketMind Restart Guide — 2026-05-25 EOD

**Tests**: 2,049 pass, 0 fail, 0 skip | **CI**: green | **Branch**: master
**All pushed**: no | **frontload_required**: true

---

## 重启指令

> 继续 MarketMind 开发。阅读 `.claude/RESTART_GUIDE.md`。
> 上次完成：影子生态全面优化方案 Phase 1-4 + 投票系统重命名 + 国会交易复活 + UI 多发言人

---

## 今日完成 (2026-05-25)

### Phase 1：配额+等级+激励
- 5级→4级（合并 WATCH+ENDANGERED 为 ENDANGERED@20%）
- 胜率地板保护（胜率>50% + 累计回报>0 + 仓位>1%）
- 等级配额：ELITE=10 / EXCELLENT=8 / NORMAL=5 / ENDANGERED=2
- 紧急配额上限+5，`"normal"`→`"idle"` 命名修正
- 状态卡注入：每个影子 prompt 开头显示等级/配额/晋升路径/毕业目标

### Phase 2：Flash 研究助理
- `shadows/flash_research_assistant.py` — 影子→Flash 调用协议
- 4 个 Flash 工具：市场快照、存档搜索、同行共识(N≥5)、缓存分析
- 预算感知 prompt：影子看到剩余配额，自主规划
- Gate 2 模式：毕业影子不限额 Flash

### Phase 3：三层 AEL + 策略趋同
- `shadows/ael_weekly_flash.py` — 周度 Flash 战术复盘（Snorkel 规则）
- `shadows/ael_evolution.py` — ELITE 巩固模式（不批判，只强化）
- `shadows/ael_quarterly_pro.py` — 季度 Pro 结构审计（Q4 赢，2-of-3 门控）
- `shadows/diversity_controller.py` — 同类型内策略趋同检测
- `shadows/shadow_mother.py` — 领域人口守卫（最少 1 影子/领域）

### Phase 4：交互式 Gate 2 + 毕业考试
- `shadows/gate2_graduation.py` — 自定义毕业考试注册 + ELITE 回退模式
- `pipeline/gate2_interaction.py` — 主持人防火墙 + 影子邀请 + 匿名互评
- `shadows/elite_participation.py` — 扩展至 EXCELLENT 毕业影子
- `dashboard.html` — 多发言人 UI（颜色前缀 + 自动补全 + ⏳等待态）

### 其他
- `ShadowVote`→`ShadowDecision` 全量重命名（14 源文件 + 7 测试文件）
- Congress Trades MCP 复活（`insider_sources.py` + `congress_mcp_client.py`）
- Bluesky 认证验证通过
- `danger_guard.py` 扩展：Bash/Agent 工作命令也需任务声明
- `danger_guard.py` 新增：连续执行模式下阻止确认性 AskUserQuestion
- 126 个开发文档迁移到 `docs/dev/`
- MCP 配置：capitol-trades(项目级) + context7+chrome-devtools(全局)
- CLAUDE.md 写入连续执行规则
- 9 个 Agent worktree 已清理（0 残留）

---

## 明天可以做的

| # | 任务 | 说明 |
|:--:|------|------|
| **1** | **Dashboard 验证** | `python api_server.py` → `http://localhost:8520`，Ctrl+Shift+R 强刷。验证多发言人 UI、影子数据显示、信息源数量恢复 35 |
| **2** | **主管线进化机制核查** | 审计主管线（非影子）的迭代进化机制：Flash Triage→HVR→L1→L2→L3→RedTeam→Resonance→Decision，看看有哪些可以自我优化 |
| 3 | 管线实盘验证 | `python app.py --mode daily`（需要 API 预算） |
| 4 | 未提交代码 Git commit | 大量改动未提交，建议按 Phase 分批提交 |

---

## 快速命令

```bash
cd E:/AI_Studio_Workspace/projects/marketmind
python api_server.py                    # Dashboard → http://localhost:8520
python app.py --mode daily --mock -v    # 模拟分析
python -m pytest tests/ -q -m "not slow" -p no:warnings  # 测试 (2,049 pass)
```

---

## 新增模块

| 模块 | 用途 |
|------|------|
| `shadows/congress_mcp_client.py` | MCP 国会交易客户端 |
| `shadows/flash_research_assistant.py` | Flash 研究助理（影子→Flash→工具） |
| `shadows/ael_weekly_flash.py` | 周度 Flash 战术复盘 |
| `shadows/ael_quarterly_pro.py` | 季度 Pro 结构审计 |
| `shadows/gate2_graduation.py` | 毕业考试注册 + ELITE 回退 |

## Dashboard UI 改动

`dashboard.html` 新增：发言人颜色前缀、影子颜色映射、`shadow <name>` 自动补全、⏳等待态样式。
**如果页面数据不显示**：Ctrl+Shift+R 强刷清除缓存。

## 5级→4级说明

WATCH(30%) 和 ENDANGERED(15%) 合并为统一的 ENDANGERED(20%)，14 天连续触发。Dashboard 同步改为显示 4 个等级条（不再显示 WATCH）。这是方案 §1 的设计决策。
