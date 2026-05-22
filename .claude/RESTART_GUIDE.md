# MarketMind Restart Guide — 2026-05-22 EOD

**Last updated**: 2026-05-22 | **Branch**: master | **Tests**: 1,746 pass, 32 fail (git divergence), 26 skip
**All pushed to GitHub**: ⏸️ pending (network issue — retry next session)

---

## Restart Command

Type this exactly:

> 继续 MarketMind 开发。阅读 `.claude/RESTART_GUIDE.md`。上次完成：Phase J+K+L（API重构、祖父提取、AEL实验+控制组+3月扩展、WebSocket、文件上传UI、PICA+Red Team双审、32/57回归修复）。下一步：git push、l1最终提取（722→440）、32回归修复收尾。

---

## Git Safety Protocol (MANDATORY — every session)

**This rule prevents the 2026-05-22 git pull disaster (69 test regressions from remote divergence).**

### Before ANY git pull:

```bash
# Step 1: Fetch without merging
git fetch origin master

# Step 2: Check what's coming
git log HEAD..origin/master --oneline | wc -l  # count new commits
git diff --stat HEAD..origin/master | tail -5   # see file changes

# Step 3: Decide
#   If new commits > 10 OR files changed > 50: STOP and evaluate
#   If massive restructuring detected (files moved/renamed): STOP
#   Otherwise: safe to pull
```

### Decision matrix:

| Remote has | Local has unpushed? | Action |
|------------|:--:|--------|
| Few new commits | No | `git pull --rebase` — safe |
| Few new commits | Yes | `git push` FIRST, then `git pull --rebase` |
| Many new commits or restructuring | No | Evaluate: do local changes depend on remote? If not, skip pull |
| Many new commits or restructuring | Yes | **STOP** — user must decide merge strategy |

### Golden rule:

**本地改动优先。** When in doubt, `git push` your local work first. Remote can always pull from you. Never let a remote restructure silently overwrite local code.

---

## Current State (2026-05-22 EOD)

### ✅ Phase J Complete (2026-05-22)
- **T2 API Layer Refactor**: `api/` module (routes + data_providers + websocket), `api_server.py` 211→25 lines
- **T5 Grandfather Extraction**: `ranking_engine.py` 495→379, `shadow_state.py` 333→303, `ranking_stats.py` +140 lines
- **T1 AEL Experiment**: 7 integration tests, `scripts/ael_experiment.py` (30-day simulation, 3/4 lessons injected)
- **T3 WebSocket**: `/ws` endpoint, `api/websocket.py`, JS client with auto-reconnect, progress bar + log live updates
- **T4 File Upload UI**: Drag-and-drop overlay, file chip previews, XSS-safe rendering
- **PICA Audit**: All 4 levels complete (Unit/Security/Integration/Regression), 3 High XSS fixed

### ✅ Previously Completed
- **RESTART_GUIDE 6/6**: P2-2 Walk-Forward, P2-4 Market Anchor, P3-1 Challenger Learning, P3-3 Circuit Breaker, P3-4 Partial Recovery, P3-2a+b SHARP
- **Shadow Phase A-F**: Data foundation → Type system → Tools → Middleware → Integration → Graduation
- **Info Sources 5 Phase**: 10 fetchers (FRED 32 series, sentiment, commodities, crypto, volatility surface)
- **Market Figure Module**: FigureSignal + AWA + EventStudy + NewsPusher (16 persons)
- **SHARP Evolution**: Main AI rule decomposition, attribution, WFA gate, atomic edits
- **Grandfather Module Compliance**: All 4 files under hard ceilings (ranking_engine 495, shadow_state 333, shadow_mother 286, event_clusterer 437)
- **Web Dashboard**: FastAPI + Bloomberg-style HTML, bilingual, 14 timezones
- **PICA Audit**: Unit + Security + Integration + Regression + Red Team dual
- **Module Count**: 329 Python files, ~79,000 lines

### ⏸️ Next Steps

| Priority | Task | Detail |
|:--:|------|------|
| 1 | Red Team Dual Audit | Code + Logic review for Phase J (6 new/modified modules) |
| 2 | Live Trading Test | Full daily cycle with WebSocket + real positions |
| 3 | AEL 3-Month Expansion | Extend from 1-month to 2-3 months (after validation) |
| 4 | Portfolio Real Data | Fix `get_all_open_trades` → wire real portfolio endpoint |
| 5 | GitHub Push | Commit Phase J + push to remote |

---

## Key Dashboard

```bash
cd projects/marketmind
python api_server.py
# Open http://localhost:8520
```

## Key Files

| File | Purpose |
|------|---------|
| `api_server.py` | FastAPI server with embedded dashboard |
| `dashboard.html` | Bloomberg dark theme, Apple typography |
| `app.py` | CLI/GUI entry point |
| `start.bat` | One-click launcher |
| `shadows/shadow_mother.py` | Glue layer (286 lines) |
| `pipeline/decision.py` | Main AI decision synthesis |
| `gateway/async_client.py` | LLM gateway + circuit breaker |

## All Commands

```bash
# Full test suite
python -m pytest projects/marketmind/tests/ -v --tb=short

# Shadow tests only
python -m pytest projects/marketmind/tests/test_shadows/ -v

# Dashboard server
cd projects/marketmind && python api_server.py

# CLI with info injection
python app.py --mode daily --mock --verbose --inject "Your info here" --inject-files report.pdf
```
