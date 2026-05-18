# Phase H — Batch 1 Progress

**Updated**: 2026-05-18 — Massive implementation push: module extraction, security fixes, Gate 1 prep, 732 tests pass

## Completed

### Security fixes
- [x] `storage/session.py`: Atomic writes (temp+rename) + graceful KeyError handling + corruption logging
- [x] `storage/archivist.py`: Atomic writes in save_json() + "gates" in ensure_dirs()
- [x] `pipeline-manifest.yaml`: Added stage_2b_investigation (resolves Architecture C3)
- [x] All 13 storage tests pass

### Module extraction (investigation_loop.py 918→486 lines)
- [x] `pipeline/hvr_cycle.py` — HVR investigation cycle (extracted from investigation_loop)
- [x] `pipeline/investigation_prompts.py` — HVR system prompt constants (data module)
- [x] `pipeline/investigation_types.py` — HVR data types (data module)
- [x] `pipeline/investigation_direction.py` — HVR direction extraction (data module)

### Module extraction (app.py 971→392 lines)
- [x] `pipeline/backtest_entry.py` — Backtest runner entry point (extracted from app.py)
- [x] `pipeline/orchestration.py` — Pipeline orchestration (run_interactive extracted from app.py)

### New modules
- [x] `integrity/input_guard.py` — Shared input sanitization (prompt injection, Markdown escaping, Unicode normalization). 47 tests.
- [x] `storage/gate_archiver.py` — Gate conversation JSONL+MD archiver. 10 tests.
- [x] `pipeline/hypothesis_card.py` — Gate 1 hypothesis card generation (3-card, frequency framing, progressive disclosure). 15 tests.
- [x] `pipeline/kill_monitor.py` — Downstream kill-criteria monitoring. 12 tests.

### Gate 1 interaction loop
- [x] `pipeline/gate1_interaction.py` — Gate 1 conversation loop + state machine (in progress)
- [ ] Gate 1 interaction loop completion

### Data model changes
- [x] HypothesisResult +11 fields (direction, core_logic, risk_level, time_window, layer narratives)
- [x] HypothesisResult wired into generate_decision()

### Gateway changes
- [x] input_guard wired into gateway (async_client, macro_data)
- [x] API cost ceiling added (MAX_PRO_CALLS_PER_SESSION=30)

### PICA audit artifacts
- [x] 12 Security audits (PICA-Security): `.claude/audits/phase-h/`
- [x] 7 Integration audits (PICA-Integration): `.claude/audits/phase-h/`
- [x] 1 Regression audit (PICA-Regression): `.claude/audits/phase-h/`
- [x] Test count: 732 pass (was 689)

### Research files (7 total)
- [x] `.claude/research/gate1-9-critical-synthesis.md`
- [x] `.claude/research/analysis-style-extraction.md`
- [x] `.claude/research/balance-sheet-flow-frameworks.md`
- [x] `.claude/research/historical-cycle-comparison.md`
- [x] `.claude/research/pipeline-methodology-gap.md`

## Agents running
- [ ] `agent-gate1-interaction` — Gate 1 interactive conversation loop

## Blocked (needs user decision)
- [ ] Gate 1 fix plan approval → `.claude/research/gate1-9-critical-synthesis.md`
- [ ] Phase H comprehensive architecture plan revision (asset-class routing, 6 new modules)
- [ ] app.py further extraction (currently 392 lines, target 150)

## Pipeline gap priority (from analysis)
1. Mechanism naming (prompt edits, zero blast radius)
2. Causal decomposition (asset/liability lens)
3. Entity-level flow tracking (who buys what)
4. Historical regime mapping (replace Layer 4 placeholder)
5. Conditional forecasting (scenario trees)
6. Counter-intuitive + consensus-break discovery
7. Fragility analysis (system thresholds)
8. Cross-border flows (TIC/BIS/SWIFT data)
9. Charts as reasoning (text specs → renderer)

Estimated total: ~2,600 lines across 9 new modules
