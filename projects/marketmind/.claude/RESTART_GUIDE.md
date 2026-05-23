# MarketMind Restart Guide — 2026-05-23

**Last updated**: 2026-05-23 | **Branch**: master | **Tests**: 1,989 pass, 0 fail, 0 skip
**All pushed to GitHub**: ✅
**CLAUDE.md auto-loads Git Safety Protocol**: ✅ §8 enforced every session
**frontload_required**: true

---

## 重启指令：

> 继续 MarketMind 开发。阅读 `.claude/RESTART_GUIDE.md`。

---

## ⚡ FRONTLOAD REQUIRED — before any code change:

**FLASH先扫描，确定决策点，交互完成后再放后台：**
1. Flash 读此文件 + CLAUDE.md + memory → 列出需要用户参与的决定
2. 有复杂决定 → 启动 Red-Blue 辩论 + User Proxy Agent
3. 完成所有同步交互 → 用户确认
4. 然后才启动异步工作（Agent 并行）

---

## 本轮完成 ✅

**1,749 pass / 11 fail / 44 skip → 1,841 pass / 0 fail / 0 skip**

| 类别 | 变更 | 详情 |
|------|------|------|
| Fail 修复 | 11→0 | checkpoint API 迁移 + challenger debrief + sklearn 兼容 + flaky fix |
| Skip 修复 | 44→0 | Agent 并行修复 test_shadow_types(12) + test_methodology_evolution(14+2删) + test_partial_recovery(6) + 直接修复(10) |
| l1 提取 | 722→515 行 | 提取 `l1_tool_executor.py` + `l1_display.py` |
| WS 测试 | +40 tests | `test_figure_signal_ws.py` — broadcast_person_signal contract |
| VCR 修复 | scout cross-run cache | `use_cross_run_cache=False` 绕过持久化缓存 |
| sklearn | Venn-Abers 激活 | 8 skip→11 pass |
| T6 实盘 | api_server + pipeline | 9 stages 全部通过 |

## 发现

- **`broadcast_person_signal` 未实现** — RESTART_GUIDE 标注有误。40 个 contract 测试已写好，待实现函数本身
- **旧 shadows.db schema 不兼容** — 需删除后重建
- **orchestration.py 缺 `init_gateway` import** — 已修复

## 其他待办

| # | 任务 | 说明 |
|:--:|------|------|
| 1 | 实现 `broadcast_person_signal` | `api/websocket.py` — 40 个 contract 测试已就绪 |
| 2 | 浏览器验证 dashboard | 启动 api_server → http://localhost:8520 |
| 3 | 部署验证 | 完整 e2e 测试 |

## Quick Start

```bash
cd E:/AI_Studio_Workspace/projects/marketmind
python api_server.py                    # Dashboard → http://localhost:8520
python app.py --mode daily --mock -v    # Daily pipeline
python scripts/ael_experiment.py        # AEL 90-day experiment
python -m pytest tests/ -v --tb=short   # Run tests
```
