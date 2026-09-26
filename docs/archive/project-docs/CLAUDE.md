# MarketMind — Investment Analysis Platform

**Scope:** This file applies when working in `projects/marketmind/`. Load this FIRST for architecture, quick start, model routing, testing commands, and key file paths. For global conventions (Cognitive Loop, Three System Laws, Development Workflow, MRP format, Self-Correction Protocol), fall back to the root `CLAUDE.md` at the workspace level.

Multi-agent shadow ecosystem for investment signal validation and decision support. Built on DeepSeek Flash/Pro for production, developed with Claude (Cowork) for engineering.

## Development Order (LOCKED — do NOT reorder)

**CRITICAL: Main AI analysis pipeline comes FIRST. Shadow ecosystem SECOND. This order is written into this file to prevent development chaos. Every restart MUST follow this sequence.**

```
Phase 1: Main AI Analysis Pipeline (current)
  ├── Scout news collection ✅
  ├── Flash triage (Stage 2 replacement) ✅
  ├── Event clustering ✅
  ├── Pro HVR investigation loop ✅
  ├── Expectation gap analysis ✅
  ├── Adversarial self-check ✅
  ├── L2 + L3 (fundamental + technical) ✅
  ├── Red Team + Resonance ✅
  ├── Decision + Archive ✅
  └── End-to-end integration ✅

Phase 2: Shadow Ecosystem ✅
  ├── Shadow initialization + parallel analysis ✅
  ├── ELITE participation + domain-triggered awakening ✅
  ├── Broadcast mechanism + 7-day isolation period ✅
  ├── Ranking + Crystallization + Memory ✅
  └── Cross-shadow interaction (collusion, challenger) ✅
```

**Rule**: If you find yourself working on shadow code while the main AI pipeline is broken or incomplete, STOP. Fix the main pipeline first. Shadows are an ENHANCEMENT, not a replacement for the core analysis.

## Phase Status (2026-05-23)

**Test count: 1,998 pass, 0 fail, 0 skip** | **PICA artifacts: 131** | **Red Team audits: 17**

### Phase J: API + WebSocket + AEL + Upload — COMPLETE
### Phase K: Grandfather extraction + API tests + Regression fixes — COMPLETE

### Pipeline: 10 stages + 3 gates — COMPLETE
| Stage | Status |
|-------|--------|
| Stage 0 (Shadow Init) | COMPLETE |
| Stage 1 (Scout) | COMPLETE |
| Stage 2 (Flash Triage) | COMPLETE |
| Stage 2b (HVR Investigation) | COMPLETE |
| Gate 1 (Direction) | COMPLETE |
| Stage 3 (L1 Narrative) | COMPLETE |
| Stage 4 (L2+L3) | COMPLETE |
| Stage 5 (Shadows) | COMPLETE |
| Stage 6 (Red Team) | COMPLETE |
| Stage 7 (Resonance) | COMPLETE |
| Stage 7b (Fragility) | COMPLETE |
| Stage 8 (Decision) | COMPLETE |
| Stage 9 (Archive) | COMPLETE |
| Gate 2 (Confirmation) | COMPLETE |
| Gate 3 (Position) | COMPLETE |

## Quick Start

```bash
# GUI (Command Center dashboard)
cd projects/marketmind
python app.py

# CLI daily analysis
python app.py --mode daily --mock --verbose

# Dashboard
python api_server.py
# Open http://localhost:8520

# AEL experiment
python scripts/ael_experiment.py
```

## Model Routing (Flash vs Pro)

DeepSeek Flash: data collection, simple classification, auxiliary processing
DeepSeek Pro: deep analysis, adversarial reasoning, shadow analysis, final report writing

All LLM calls route through `gateway/async_client.py` — no module should call httpx directly.

## Code Organization — Module-First (LOCKED — mechanical enforcement)

**Core rule: code is born modular. Never append to existing files.**

| Rule | Threshold | Enforcement |
|------|:--:|------|
| New feature → new module | ≥50 lines | Mandatory — no appending to existing `.py` |
| Per-file hard ceiling | 500 lines | Pre-commit hook blocks commit if any `.py` exceeds |
| One module, one responsibility | always | File name = what it does. No "utils" or "helpers" dumping grounds |
| Extraction is technical debt | any | If you find yourself extracting, you already violated the rule. Stop and ask why |

**Module naming convention:**
- `pipeline/l1_tool_executor.py` — domain prefix + single responsibility
- `shadows/shadow_checkpoint_repo.py` — noun + role suffix
- `tests/test_<module>.py` — mirrors source structure 1:1

**Existing files over 500 lines (technical debt — not a template):**
None. All files now under 550-line ceiling.

## Development Process — Mechanical Gates (LOCKED)

Each gate is silent unless violated — no manual confirmation, no prompts, no slowdown. You only notice them if you skip a step.

| Trigger | Required Action | Enforced By |
|---------|----------------|-------------|
| Editing any `.py` file | `current_task.json` must list the file | PreToolUse `danger_guard.py` — blocks Edit/Write |
| New module >50 lines | Write a plan artifact first | Stop gate — requires `pica-plan-*.json` at architect level |
| Completing enhance+ work | Code review must exist | Stop gate — requires `pica-review-*.json` at enhance+ level |
| Session end with changes | All PICA audits must pass | Stop gate — hash-chain verification |

**Plan artifact format** (`.claude/audits/pica-plan-{date}.json`):
```json
{"gate":"plan", "date":"2026-05-23", "what":"extract X from Y to Z", "why":"500-line ceiling", "files_checked":{}}
```

**Review artifact format** (`.claude/audits/pica-review-{date}.json`):
```json
{"gate":"review", "date":"2026-05-23", "reviewer":"self or agent", "findings":"...", "files_checked":{}}
```

**Session Frontload — sync decisions first, async after:**

1. Flash scans RESTART_GUIDE + task list (cheap, <10s) → lists decision points
2. If complex: inform user "需要 Pro 分析 X 分钟", let user decide to wait or delegate
3. User present → complete all sync decisions. User away → User Proxy Agent handles per confidence tiers
4. Sync done → launch async work. User can leave.

**Key rule**: NEVER launch async work before sync decisions are resolved. User should know exactly what will run and what was decided.

**Continuous Execution After Plan Approval (LOCKED — mechanical enforcement):**
Once a plan is approved by the user AND task is declared in `current_task.json`:
1. **Do NOT ask "要开始吗?" "要继续吗?" "要我做X吗?"** — the answer is always yes
2. Execute all tasks sequentially without pausing for confirmation between steps
3. Only stop when: BLOCKED (cannot resolve), ambiguity that genuinely prevents progress, or ALL tasks complete
4. Routine "continue to next step" decisions have confidence >0.85 — auto-proceed
5. This rule is MECHANICAL: PreToolUse hooks check for unnecessary AskUserQuestion calls during active task execution

**Flash vs Pro routing:**
- Flash: task classification, decision-point identification, confidence estimation
- Pro: deep analysis, code generation, architecture planning

**User Proxy Agent** (autonomous decision delegate + active advisor):

*Design doc:* `.claude/state/user_proxy_design.json`

*Dual role:*
- **Advisor mode** (user IS present, confidence < 0.85): presents analysis + recommendation, does NOT act
- **Delegate mode** (user NOT present): acts per confidence tiers, logs all decisions

*Confidence tiers (calibrated, not raw probabilities):*
| Score | Action |
|:--:|------|
| >0.85 | Auto-execute |
| 0.70-0.85 | Execute, flag for review |
| 0.50-0.70 | Request user clarification |
| <0.50 | Escalate — defer entirely |

*Decision mechanism:*
- Routine decisions: single Proxy Agent
- High-stakes (confidence < 0.50 or critical file): 3-4 agent council (proxy + risk + quality + devil's advocate)

*Learning (anti-overfitting):*
- EMA low-alpha (0.1-0.2) — single corrections nudge, don't flip
- 3+ consistent signals across distinct contexts → promote to rule
- Single corrections decay with 7-day half-life unless reinforced
- Corrections scoped by context fingerprint (project + domain + decision type)

*Three-tier preference store (transferable across projects):*
- Universal: style invariants (naming, commits, language)
- Domain: per-domain patterns (Python→FastAPI, DB→Postgres)
- Project: project-specific overrides (highest priority on lookup)

*Audit:*
- All decisions logged to `.claude/decisions/proxy_decisions.jsonl`
- User can review/override any decision retroactively
- Audit corrections feed back into preference learning

## Testing

```bash
# All tests
cd projects/marketmind
python -m pytest tests/ -v --tb=short -p no:warnings

# Shadow ecosystem only
python -m pytest tests/test_shadows/ -v --tb=short

# API tests
python -m pytest tests/test_api/ -v --tb=short

# Specific module
python -m pytest tests/test_shadows/test_ranking_engine.py -v --tb=short
```

Mock mode available for all pipeline stages via `--mock` flag.

## Design Constraints

1. All tickers must be Robinhood-tradable (from `config/asset_universe.py`)
2. DeepSeek Flash for data tasks, Pro for analysis tasks
3. All LLM calls through `gateway/async_client.py` gateway
4. Account state from `input/account_state.json` — no brokerage API
5. Final report in Chinese, ASCII-only, narrative essay style
6. Include specific price levels, not ranges
7. Shadow analysis is independent — no shadow reads another's output during analysis
8. Challenger data is opaque — invisible to target shadow until trial completes
9. Append-only state — never modify early context
