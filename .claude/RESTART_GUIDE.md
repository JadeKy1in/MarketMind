# MarketMind Restart Guide — 2026-05-22 EOD

**Last updated**: 2026-05-22 | **Branch**: master | **Tests**: 1,746 pass, 32 fail (git divergence), 26 skip
**All pushed to GitHub**: ⏸️ 2 commits pending (VPN down — push on restart)
**CLAUDE.md auto-loads Git Safety Protocol**: ✅ §8 enforced every session

---

## Restart Command

Type this exactly:

> 继续 MarketMind 开发。阅读 `.claude/RESTART_GUIDE.md`。上次完成：Phase J+K（API重构、祖父提取、AEL实验+控制组+3月扩展、WebSocket、文件上传UI、PICA+Red Team双审、API测试、回归修复25/69）。下一步：git push、32回归收尾、l1最终提取、T6实盘测试。

---

## First Actions on Restart

### 1. Git Safety Check (CLAUDE.md §8 enforces this)

```bash
# Check GitHub connectivity
curl -s -o /dev/null -w "%{http_code}" https://github.com

# If OK: push everything
cd E:/AI_Studio_Workspace/projects/marketmind && git push origin master
cd E:/AI_Studio_Workspace && git push origin master

# Before ANY git pull, check remote divergence:
git fetch origin master
git log HEAD..origin/master --oneline | wc -l
# If > 10 commits: STOP, ask user before pulling
```

### 2. Commit remaining uncommitted changes

```bash
cd E:/AI_Studio_Workspace/projects/marketmind
git add shadows/challenger_stats.py shadows/methodology_injector.py
git commit -m "fix: remaining caller_id cleanup"
```

### 3. Run tests to confirm baseline

```bash
cd E:/AI_Studio_Workspace/projects/marketmind
python -m pytest tests/ --tb=no -p no:warnings
# Expected: ~1,746 pass, 32 fail, 26 skip
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
| PICA Full Chain | ✅ | Unit/Security/Integration/Regression |
| Red Team Dual Audit | ✅ | Code + Logic — GREEN |

## Phase K Progress (2026-05-22)

| Task | Status | Detail |
|------|:--:|------|
| K1 API Tests | ✅ | 16/16 FastAPI TestClient tests |
| K2 app.py extraction | ✅ | 556→69 (run_interactive → interactive_orchestration.py) |
| K2 layer1_interactive | 722→target<500 | l1_prompts + l1_mock_data extracted (968→722) |
| K2 methodology_rules | ✅ | 494→372 (removed stale duplicate AttributionAgent) |
| AEL Control Group | ✅ | ensure_control_replicas() in 3 files |
| AEL 3-Month | ✅ | 30→90 day experiment expansion |
| Regression fixes | 25/57 | contrarian, momentum, figure_signal, gate2, shadow_types, partial_recovery |

## Grandfather Compliance

| File | Before | After | Status |
|------|:--:|:--:|:--:|
| ranking_engine.py | 495 | **379** | ✅ |
| shadow_state.py | 333 | **303** | ✅ |
| app.py | 556 | **69** | ✅ |
| methodology_rules.py | 494 | **372** | ✅ |
| layer1_interactive.py | 968 | **722** | ⏸️ target 440 |
| api_server.py | 211 | **25** | ✅ |

## New Modules Created (Phase J+K)

```
api/__init__.py, routes.py, data_providers.py, websocket.py
pipeline/l1_prompts.py, l1_mock_data.py, interactive_orchestration.py
scripts/ael_experiment.py
tests/test_api/__init__.py, test_routes.py
tests/test_shadows/test_ael_integration.py
shadows/defang.py (extraction attempted — needs redo)
```

## Pending Tasks

| Priority | Task | Detail |
|:--:|------|------|
| 1 | **Git push** | VPN restore → `git push` both repos |
| 2 | l1 final extraction | tool_executor + display → target <500 |
| 3 | 32 regression fixes | test_methodology_evolution (14), test_e2e (5), test_challenger (5), etc. |
| 4 | T6 Live Trading Test | Start api_server.py, run daily pipeline, verify dashboard |
| 5 | Market Figure WebSocket | broadcast_person_signal already added — needs test |
| 5 | defang.py redo | First attempt extracted too much — redo with proper boundaries |

## Quick Start

```bash
# Dashboard
cd projects/marketmind && python api_server.py
# Open http://localhost:8520

# Daily pipeline
cd projects/marketmind && python app.py --mode daily --mock --verbose

# AEL experiment
cd projects/marketmind && python scripts/ael_experiment.py

# Run tests
cd projects/marketmind && python -m pytest tests/ -v --tb=short
```
