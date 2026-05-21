# MarketMind Restart Guide — 2026-05-22 更新

**Last updated**: 2026-05-22 | **Branch**: master | **Tests**: 1,744 pass
**All pushed to GitHub**: ✅

---

## Restart Command

Type this exactly:

> 继续 MarketMind 开发。阅读 `.claude/RESTART_GUIDE.md`。上次完成：RESTART_GUIDE 6/6、影子 Phase A-F、信息源 5 Phase、市场人物模块、祖父文件合规、Web 仪表盘。下一步：AEL 受控实验、UI 接真实数据、WebSocket 实时推送。

---

## Current State (2026-05-22)

### ✅ All Completed
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
| 1 | AEL Controlled Experiment | Set `ael_experiment_enabled=True`, run 2-3 months |
| 2 | UI Real Data Wiring | API endpoints pull from live pipeline |
| 3 | WebSocket Progress | Real-time pipeline stage updates |
| 4 | File Upload UI | Drag-drop images/PDFs in dashboard |
| 5 | Live Trading Test | Full daily cycle with real positions |
| 6 | Remaining Grandfather Extraction | ranking_engine 495→400, shadow_state 333→300 |

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
