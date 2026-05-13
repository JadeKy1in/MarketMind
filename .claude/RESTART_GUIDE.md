# Restart Guide — MarketMind Development Continuation

**Last updated**: 2026-05-13
**Git branch**: master
**Last commit**: `875a767` (P2 statistical rigor)
**All pushed to GitHub**: ✅

---

## Current State

### Completed: 7 Implementation Phases (17 features)
All original Phase 0-7 implementation is complete. 218/218 tests pass.

### Completed: P0-P2 Improvement Plan (10 of 15 items)
P0-P3 is the improvement plan from the 3-agent review (Architect + Quant + Red Team).

| Priority | # | Item | Status |
|----------|---|------|--------|
| P0 | P0-1 | Knowledge filter wiring | ✅ |
| P0 | P0-2 | Challenger verdict execution | ✅ |
| P0 | P0-3 | Background scheduler data pollution | ✅ |
| P1 | P1-1 | MethodologyInjector primitive | ✅ |
| P1 | P1-2 | Crystallization→prompts | ✅ |
| P1 | P1-3 | AEL lessons→prompts | ✅ |
| P1 | P1-4 | Method breeding wired | ✅ |
| P1 | P1-5 | AEL lesson persistence | ✅ |
| P2 | P2-1 | Effective-N haircut | ✅ |
| P2 | P2-2 | Walk-forward validation | ⏸️ NOT DONE |
| P2 | P2-3 | Wilcoxon + 21-day trial | ✅ |
| P2 | P2-4 | External market anchor | ⏸️ NOT DONE |
| P2 | P2-5 | Holm-Bonferroni correction | ✅ |
| P3 | P3-1 | Challenger learns from failures | ⏸️ NOT DONE |
| P3 | P3-2 | Main AI gate iteration (SHARP) | ⏸️ NOT DONE |
| P3 | P3-3 | LLM gateway redundancy | ⏸️ NOT DONE |
| P3 | P3-4 | Partial-state recovery | ⏸️ NOT DONE |

---

## What to Do After Restart

### Step 1: Say this to Claude
```
继续 MarketMind 开发。上次停在了 P2 改进计划。P2-1/3/5 已完成，P2-2 和 P2-4 还没做。
重启指南在 .claude/RESTART_GUIDE.md。先实施 P2-2 和 P2-4。
```

### Step 2: Implement P2-2 (Walk-Forward Validation)
**What**: Rolling walk-forward to detect overfitting. Based on HypoDriven framework.
**Where**: `projects/marketmind/shadows/ranking_engine.py` + `shadow_mother.py`
**Specs**:
- 90-day train / 2-day purge / 20-day test windows
- Flag shadows with OOS_composite / IS_composite < 0.5
- Minimum 120 career days required
- Binomial sign test on test-period directional accuracy
- ~180 lines, 3-4 hours
**Red Team**: Approved with modifications (previous audit at `.claude/` logs)

### Step 3: Implement P2-4 (External Market Anchor)
**What**: Independent OHLC data source to break virtual PnL circularity.
**Where**: New files + `shadow_state.py` + `ranking_engine.py`
**Specs**:
- New `market_prices` table (ticker, date, O/H/L/C/volume)
- New `MarketDataFetcher` class using yfinance.history()
- Wire into daily cycle BEFORE ranking
- Hard tier gate: market_accuracy < 0.45 → cannot achieve ELITE
- ~170 lines, 3-4 hours
**Red Team**: Approved with modifications

### Step 4: Search External Research, then Implement P3-1 through P3-4
**Process for each**: Search external → analyze → Red Team audit → implement → commit
- P3-1: Challenger learns from predecessor failures (MNL/HHD frameworks)
- P3-2: Main AI SHARP rubric evolution
- P3-3: LLM gateway redundancy (fallback provider)
- P3-4: Partial-state recovery for orchestrate_daily_cycle

### Step 5: Start AEL Controlled Experiment
**How**: Set `ael_experiment_enabled = True` in `config/settings.py`
- Creates 4 treatment/control replica pairs
- Monthly Pro debriefs on treatment shadows
- After 2-3 months: compare treatment vs control with z-test
- Decision point: if treatment > control (statistically significant) → expand AEL to all shadows

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `projects/marketmind/shadows/ranking_engine.py` | Composite scoring, Bayesian haircut, dynamic WR line, walk-forward (P2-2), market anchor (P2-4) |
| `projects/marketmind/shadows/shadow_mother.py` | Daily orchestration, all Phase 0-7 wiring |
| `projects/marketmind/shadows/shadow_state.py` | SQLite schema, CRUD, methodology_changes audit |
| `projects/marketmind/shadows/methodology_evolver.py` | MethodologyInjector class (P1-1), method tracking |
| `projects/marketmind/shadows/ael_evolution.py` | AEL slow-layer engine (Phase 7) |
| `projects/marketmind/shadows/challenger_engine.py` | 3-stage elimination, Wilcoxon test (P2-3) |
| `projects/marketmind/shadows/knowledge_filter.py` | Knowledge inheritance with lineage tracking (P0-1) |
| `projects/marketmind/shadows/ecosystem_health.py` | Collective degradation detection (Phase 3) |
| `projects/marketmind/shadows/shadow_health_monitor.py` | Individual shadow health (Phase 3) |
| `projects/marketmind/shadows/ecosystem_auditor.py` | Blind-spot detection (Phase 0) |
| `projects/marketmind/shadows/elite_participation.py` | ELITE Gate 2 participation (Phase 5) |
| `projects/marketmind/shadows/parameter_beta_runner.py` | Quantitative parameter testing (Phase 4) |
| `projects/marketmind/config/settings.py` | All configuration, AEL experiment flag |
| `.claude/phase_b_ideation_notes.md` | Full ideation notes from Grill Me sessions |
| `.claude/grill_me_roadmap.md` | Grill Me question framework (Round 3-5 pending) |
| `.claude/forensics/phase-b-fdr.md` | Phase B forensic design reconstruction |
| `.claude/audits/` | All Red Team audit reports |
| `docs/superpowers/specs/2026-05-10-marketmind-design.md` | Original design document v1.2 |

---

## Grill Me Status

The 5-round Grill Me ideation session was partially completed:
- Round 1: ✅ Pain Mining (extensive — spawned all shadow redesign)
- Round 2: ✅ Vision Gap (all shadow types covered)
- Round 3: ✅ Cross-Pollination (external research integration)
- Round 4: ✅ Risk & Depth (5 questions covered)
- Round 5: ✅ Prioritization (17 items sorted into 7 phases)

Two closing questions for Round 5 remain unasked (optional):
- "One year from now, MarketMind has become indispensable. What does it do?"
- "Is there anything we should STOP doing?"

---

## Important Design Decisions (Don't Change Without Review)

1. **All shadows default to Pro model** (was Flash). Flash reserved for queries, preprocessing, one-line comments.
2. **Challengers inherit ORIGINAL methodology prompts**, not AEL-evolved ones (prevents bias accumulation).
3. **Daredevils are ENVIRONMENT-LOCKED** (7+1). Each always trades its environment regardless of broad market.
4. **Catfish is replaced** by EcosystemAuditor (mechanism, not shadow).
5. **Temp Events use Form C** milestone-triggered recording (3-5 Pro calls/30 days).
6. **Emergency quota triggers on exhaustion**, not confidence threshold.
7. **Tier quotas**: ELITE=7, EXCELLENT=6, NORMAL=5, WATCH=3, ENDANGERED=1.
8. **Dynamic win-rate line**: early career = boost WR weight, mature = allow WR-for-profitability trade.
9. **Negative profitability = largest penalty** in composite score (regardless of win rate).
10. **ELITE participation in Gate 2**: domain-triggered, no decision authority, once per session.
11. **SHARP rules apply the PATTERN (ID→decay→validation→audit) to main AI**, NOT shadow data.
