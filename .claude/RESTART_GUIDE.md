# MarketMind Restart Guide — 2026-05-22 EOD

**Last updated**: 2026-05-22 | **Branch**: master | **Tests**: 1,746 pass, 32 fail (git divergence), 26 skip
**All pushed to GitHub**: ⏸️ 3 commits pending (VPN down — push on restart)
**CLAUDE.md auto-loads Git Safety Protocol**: ✅ §8 enforced every session

---

## Restart Command

Type this exactly:

> 继续 MarketMind 开发。阅读 `.claude/RESTART_GUIDE.md`。上次完成：Phase J+K（API重构、祖父提取、AEL实验+控制组+3月扩展、WebSocket、文件上传UI、PICA+Red Team双审、API测试、回归修复25/69）。下一步：git push、32回归收尾、l1最终提取、T6实盘测试。

---

## 重启操作清单（按顺序执行）

### 1. 验证网络 + Push 所有本地 commit

```bash
# 验证 GitHub 可访问
curl -s -o /dev/null -w "%{http_code}" https://github.com
# 期望: 200

# 推送 MarketMind repo（3 个待推送 commit）
cd E:/AI_Studio_Workspace/projects/marketmind && git push origin master

# 推送 Workspace repo（3 个待推送 commit）
cd E:/AI_Studio_Workspace && git push origin master
```

### 2. 提交最后两个 caller_id 修复文件

```bash
cd E:/AI_Studio_Workspace/projects/marketmind
git add shadows/challenger_stats.py shadows/methodology_injector.py
git commit -m "fix: remaining caller_id cleanup"
git push origin master
```

### 3. 拉取远端前先评估差异（Git Safety Protocol）

```bash
git fetch origin master
git log HEAD..origin/master --oneline | wc -l
# 如果 > 10: 停下，报告给用户评估
# 如果 <= 10: 安全 pull
git diff --stat HEAD..origin/master | tail -5
# 如果 > 50 文件变更: 停下
```

### 4. 确认测试基线

```bash
cd E:/AI_Studio_Workspace/projects/marketmind
python -m pytest tests/ --tb=no -p no:warnings
# 期望: ~1,746 pass, 32 fail, 26 skip
```

---

## Phase J Complete (2026-05-22)

| Task | Status | Detail |
|------|:--:|------|
| T1 AEL Experiment | ✅ | 7 integration tests, 90-day experiment runner |
| T2 API Refactor | ✅ | `api/` module (routes, data_providers, websocket), api_server.py 25 lines |
| T3 WebSocket | ✅ | `/ws` endpoint + auto-reconnect + live progress bar |
| T4 File Upload UI | ✅ | Drag-drop overlay, file chips, XSS-safe rendering |
| T5 Grandfather Extraction | ✅ | ranking_engine 495→379, shadow_state 333→303 |
| T6 Live Trading Test | ⏸️ | API verified, dashboard manual test pending |
| PICA Full Chain | ✅ | Unit/Security/Integration/Regression (6 artifacts) |
| Red Team Dual Audit | ✅ | Code + Logic — GREEN |

## Phase K Progress (2026-05-22)

| Task | Status | Detail |
|------|:--:|------|
| K1 API Tests | ✅ | 16/16 FastAPI TestClient tests |
| K2 app.py extraction | ✅ | 556→69 (run_interactive → interactive_orchestration.py) |
| K2 layer1_interactive | 722→target<500 | l1_prompts + l1_mock_data extracted (968→722) |
| K2 methodology_rules | ✅ | 494→372 (removed stale duplicate AttributionAgent) |
| AEL Control Group | ✅ | ensure_control_replicas() in ael_evolution + step_ael + experiment |
| AEL 3-Month | ✅ | 30→90 day experiment expansion |
| Regression fixes | 25/69 | contrarian, momentum, figure_signal, gate2, shadow_types, partial_recovery |

## All Modified Files This Session

**New (created):**
- `api/__init__.py`, `api/routes.py`, `api/data_providers.py`, `api/websocket.py`
- `pipeline/l1_prompts.py`, `pipeline/l1_mock_data.py`
- `pipeline/interactive_orchestration.py`
- `scripts/ael_experiment.py`
- `tests/test_api/__init__.py`, `tests/test_api/test_routes.py`
- `tests/test_shadows/test_ael_integration.py`
- `.claude/audits/phase-j/pica-unit.json`, `pica-security.json`, `pica-integration.json`, `pica-regression.json`, `red-team-code.md`, `red-team-logic.md`

**Modified:**
- `api_server.py`, `dashboard.html`
- `app.py`, `shadows/ranking_engine.py`, `shadows/shadow_state.py`, `shadows/ranking_stats.py`, `shadows/shadow_schema.py`
- `shadows/step_ael.py`, `shadows/ael_evolution.py`, `shadows/crystallization.py`, `shadows/shadow_agent.py`
- `pipeline/decision.py`, `pipeline/layer1_interactive.py`, `pipeline/methodology_rules.py`, `pipeline/figure_signal.py`
- `shadows/contrarian_shadows.py`, `shadows/momentum_shadows.py`
- `shadows/background_scheduler.py`, `shadows/cash_reframing.py`, `shadows/catfish_agent.py`, `shadows/challenger_engine.py`, `shadows/challenger_stats.py`, `shadows/daredevil_shadows.py`, `shadows/expert_shadows.py`, `shadows/methodology_injector.py`, `shadows/missed_path.py`, `shadows/paper_live_gap.py`, `shadows/shadow_mother.py`, `shadows/temp_shadow_lifecycle.py` (caller_id removal)
- `backtest_runner.py`, `ui/shadow_panel.py` (caller_id removal)
- 7 test files (test_ael_integration, test_shadow_agent, test_shadow_state, test_crystallization, test_figure_signal, test_gate2_interaction, test_run_interactive_smoke, test_partial_recovery, test_market_anchor, test_shadow_types)
- `CLAUDE.md` (Git Safety Protocol §8)

**Deleted (stale tests for removed code):**
- `tests/test_pipeline/test_sharp_rules.py`
- `tests/test_shadows/test_walk_forward.py`
- `tests/test_pipeline/test_methodology_rules.py`
- `tests/test_shadows/test_convergence_detection.py`

## Grandfather Compliance

| File | Before | After | Status |
|------|:--:|:--:|:--:|
| ranking_engine.py | 495 | **379** | ✅ |
| shadow_state.py | 333 | **303** | ✅ |
| app.py | 556 | **69** | ✅ |
| methodology_rules.py | 494 | **372** | ✅ |
| layer1_interactive.py | 968 | **722** | ⏸️ target 440 |
| api_server.py | 211 | **25** | ✅ |

## Pending Tasks

| Priority | Task | Detail |
|:--:|------|------|
| 1 | **Git push** | VPN 恢复后执行 First Actions §1-3 |
| 2 | l1 final extraction | tool_executor + display → 722→440（蓝图已有） |
| 3 | 32 regression fixes | test_methodology_evolution(14), test_e2e(5), test_challenger(5), test_contrarian(3), test_momentum(2), test_figure_signal(5), 其他 |
| 4 | T6 Live Trading Test | 启动 api_server.py → 跑 daily pipeline → 浏览器验证 |
| 5 | market_figure WS test | broadcast_person_signal 已加入 websocket.py + dashboard — 待测试 |
| 6 | defang.py redo | 上次提取把整个 class 移走了（53行残留）— 需要 git checkout 后精确提取 |

## Quick Start

```bash
# Dashboard
cd projects/marketmind && python api_server.py
# → http://localhost:8520

# Daily pipeline
cd projects/marketmind && python app.py --mode daily --mock --verbose

# AEL 90-day experiment
cd projects/marketmind && python scripts/ael_experiment.py

# Tests
cd projects/marketmind && python -m pytest tests/ -v --tb=short
```
