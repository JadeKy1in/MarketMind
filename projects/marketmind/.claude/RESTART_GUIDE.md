# MarketMind Restart Guide — 2026-05-28 EOD

**Tests**: 2,129 passing (excl. dryrun) | **CI**: green | **Branch**: master
**All pushed**: yes | **frontload_required**: false

---

## 重启指令

> 继续 MarketMind 开发。阅读 `.claude/RESTART_GUIDE.md`。
> 上次完成：进化体系 P0-P3 修复 + Playground 入驻指南 + README 全面更新 + dryrun 修复。
> **下次主要任务**：UI 调试（Dashboard 面板、影子卡片、Playground 页面交互逻辑）+ 等数据积累。

---

## 快速命令

```bash
cd E:/AI_Studio_Workspace/projects/marketmind

# 启动 Dashboard
python api_server.py
# → http://localhost:8520/
# → http://localhost:8520/playground
# → http://localhost:8520/evolution

# Mock 管线 (无 API 消耗, ~1min)
python app.py --mode daily --mock -v

# Mock 管线 + Playground agents
python app.py --mode daily --mock --playground -v

# 实盘管线 (~7min, 消耗 API)
python app.py --mode daily --playground -v

# 交互模式 (Socratic 对话 + 决策确认)
python app.py --mode interactive -v

# 测试 (全量，跳过实盘)
python -m pytest tests/ -q -p no:warnings --ignore=tests/test_dryrun_real_api.py --ignore=tests/test_playground/test_fetcher.py

# 测试 (含实盘，需 API key + 网络正常)
python -m pytest tests/ -q -p no:warnings
```

---

## 今日完成 (2026-05-28)

### 进化体系审查与修复 (P0-P3)
- **P0**: `weekly_tactical_audit.py` — 结算数据注入（方向准确率、Flash 验证率、HVR ROI）。之前周审计只看操作指标（"管线忙不忙"），现在能看到"管线对不对"。
- **P1**: `methodology_evolution.py` — 归因触发改为双窗口确认。7 天准确率 <45% AND 30 天 <50% 才触发，单日波动被抑制。日志记录抑制原因。
- **P2**: L3→L1 反馈闭环。规则演化（退休/进化/移除）写入 `evolutions.jsonl`，`CalibrationContext` 加载并注入 L1 prompt。管线知道自己最近的规则变更。
- **P3**: 结算机制从二元方向判断升级为 magnitude-weighted scoring。新增 `magnitude_score`（avg expected×actual return）和 `magnitude_mean_return`（正确调用的平均幅度）。检测 adverse selection（小赚大亏）。
- 3 文件修改：`daily_calibration.py`、`weekly_tactical_audit.py`、`methodology_evolution.py`

### Bug 修复
- `decision.py:281` — 合成失败时返回带 `no_trade_card` 的 fallback，不再返回 `None`
- `test_dryrun_real_api.py` — fixture scope 改为 `function`，每次测试前重置 CircuitBreaker，防级联熔断
- `shadow_ranking_compute.py:198` — WalkForwardValidator 导入路径修复 (`ranking_engine` → `walk_forward`)
- `walk_forward.py` — 添加 `min_career_days` property

### Playground 入驻指南
- `docs/playground-agent-onboarding.md` — 中英双语完整文档
- 覆盖：架构、manifest.json 规范、adapter.py 接口、数据源注册、测试模板、6 关升级门控、serenity_reply 参考实现

### README 全面更新
- 根目录 `README.md`：当前架构（10 阶段 + Playground + 自进化三层）、24 影子、37 信源、项目结构、入驻指南链接
- GitHub Description：中英双语

---

## 当前架构快照

```
主管线: Scout(37源) → Flash → HVR → L1 → L2+L3 → Shadows → RedTeam → Resonance → Decision
         │                                    │
   每日校准 + 周审计建议注入            非阻塞后台启动
         │         │                          │
   Calibration   周审计                 zombie_detector
   (含L3演化通知) (含结算数据)           启动代码vsDB检查
         │
   L3 归因分析 (双窗口确认, <45%持续才触发)

Playground: WP API(6) + RSS(2) → agent.adapter.analyze() → daily report + audit log
               │                       │
        信息防火墙               serenity-reply (2轮Flash)
        (无主管道数据)

影子生态: 24 shadows (16 Experts + 8 Daredevils)
         Tier: ELITE/EXCELLENT/NORMAL/ENDANGERED
         淘汰: 3 阶段管道 (警告→挑战者→21天配对检验)
```

---

## 已知问题

| 问题 | 严重度 | 说明 |
|:--|:--|:--|
| 网络/代理不稳定 | 中 | `test_fetcher` + 部分 dryrun 测试在网络差时失败。所有 HTTP 源返回 0 条。非代码 bug |
| Reddit WSB 403 | 低 | Reddit 封锁了 RSS endpoint，返回 403 Blocked |
| SHADOW_DB_CACHE 泄漏 | 低 | 模块级 dict 永不过期，长期运行会累积。影响小（仅缓存 ticker:date 对） |
| tune_threshold 字符串替换 | 低 | 用字符串替换改规则阈值，多出现时会损坏。当前规则数量少，暂无实际风险 |

---

## 待办 (优先级排序)

1. **UI 调试** — Dashboard 面板展开/折叠、影子卡片 Tier 配色、Playground 页面交互逻辑
2. **数据积累** — 多跑几天 mock/实盘管线让 metrics/Tier 有真实数据
3. **Playground 入驻流程实操** — 按入驻指南创建一个新 agent 验证流程完整性
4. **结算机制进一步强化** — 添加 market beta 剥离 (`_get_next_day_return` 减去同期 SPY 收益)
5. **tune_threshold 结构化** — 改为字段级操作，不用字符串替换
