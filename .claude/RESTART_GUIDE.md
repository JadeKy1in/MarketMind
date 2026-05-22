# MarketMind Restart Guide — 2026-05-23

**Last updated**: 2026-05-23 | **Branch**: master | **Tests**: 1,749 pass, 11 fail, 44 skip
**All pushed to GitHub**: ✅
**CLAUDE.md auto-loads Git Safety Protocol**: ✅ §8 enforced every session

---

## 重启指令：

> 继续 MarketMind 开发。阅读 `.claude/RESTART_GUIDE.md`。上次完成：Phase J+K 全部。测试 1,749 pass, 11 fail, 44 skip。第一优先修 skip+failed 测试，然后 l1 最终提取。

---

## 明天第一优先：修 skip + fail

**44 skip**：`@pytest.mark.skip` 跳过的测试——对应生产代码 API 被完全重新设计，需要根据新 API 重写测试逻辑。
**11 fail**：实际断言失败——生产代码签名变了，测试调用需要更新。

| 文件 | Fail | Skip | 原因 |
|------|:--:|:--:|------|
| test_methodology_evolution.py | 0 | 14 | RuleValidator/RuleEvolver/assemble_dynamic_prompt API 重写 |
| test_shadow_types.py | 0 | 12 | EventDetector + BetaShadow API 移除 |
| test_partial_recovery.py | 0 | 6 | Checkpoint 从 per-day 改为 per-shadow |
| test_challenger_failure_learning.py | 3 | 5 | MethodologyInjector API 重写 |
| test_figure_signal.py | 0 | 3 | KeyPerson.category 移除 |
| test_e2e_phase_c.py | 2 | 2 | Pipeline E2E API 变更 |
| test_scout_vcr.py | 1 | 2 | VCR cassette 缺失 |
| test_e2e_shadow_ecosystem.py | 3 | 0 | Shadow ecosystem API 变更 |
| test_phase_f_integration.py | 1 | 0 | memory_store API 变更 |
| test_market_anchor.py | 1 | 0 | market_prices 表结构变更 |

**修复策略**：逐个文件处理——去 skip → 读生产代码新 API → 重写测试 → 跑测试验证。

## 其他待办

| # | 任务 | 说明 |
|:--:|------|------|
| 2 | l1 最终提取 | `layer1_interactive.py` 722→440（tool_executor + display） |
| 3 | T6 实盘测试 | 启动 api_server + 跑 daily pipeline + 浏览器验证 dashboard |
| 4 | market_figure WS 测试 | `broadcast_person_signal` 已实现，待测试 |

## Quick Start

```bash
cd E:/AI_Studio_Workspace/projects/marketmind
python api_server.py                    # Dashboard → http://localhost:8520
python app.py --mode daily --mock -v    # Daily pipeline
python scripts/ael_experiment.py        # AEL 90-day experiment
python -m pytest tests/ -v --tb=short   # Run tests
```
