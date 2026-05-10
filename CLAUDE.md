# AI Studio Workspace

Investment analysis toolchain: SignalFoundry (daily macro research) + Command Center (interactive UI). Built on DeepSeek Flash/Pro for production, developed with Claude (Cowork) for engineering.

## Quick Start

```bash
# Command Center (GUI)
python -m projects.command_center.app

# SignalFoundry daily report (CLI)
cd projects/robinhood
python src/main.py --mode daily --mock --verbose

# Shadow simulation
python src/main.py --simulate --verbose
```

## Architecture

```
SignalFoundry (robinhood)          Command Center (command_center)
├── src/main.py (entry point)      ├── app.py (entry point)
├── deepseek_client.py (LLM gw)    ├── engine/ (optimizer, reporter)
├── scout_fetcher.py (news)        ├── ui/ (dashboard, chat)
├── fundamental_engine.py          ├── gateway/ (Flash/Pro adapters)
├── technical_engine.py            └── intelligence/ (scraper, OCR)
├── event_engine.py (Blue/Red)
├── sentiment_engine.py
├── resonance_aggregator.py
├── capital_manager.py
├── pro_model_deep_dive.py (prompt)
├── output_formatter.py
├── shadow_simulator.py
└── config/ (asset_universe, source_authority)
```

## Core Rules

### 1. Cognitive Loop (Triumvirate: Opus → Sonnet → Haiku)

Before any non-trivial code change:
- **Architect (Opus)**: Spawn an Opus Plan Agent for architecture review, prompt engineering, and strategic design
- **Plan (Sonnet)**: Spawn a Sonnet Plan Agent to decompose architecture into implementation steps
- **Execute (Haiku)**: Implement the plan yourself, following each step in order
- Verify changes by reading files back and running syntax checks

Invoke `/triumvirate` for automatic task classification or `/robinhood-plan-execute` for Robinhood-specific workflow.

### 2. Three System Laws

**Law 1 (Output Discipline):** Final Markdown reports must be ASCII-only, no emoji. Code comments and console output are exempt.

**Law 2 (Physical Isolation):** Robinhood is an ANALYSIS tool, not a trading bot. Never connect to brokerage APIs. Account state lives in `input/account_state.json` maintained manually.

**Law 3 (Anti-Overfitting):** Price data is a timing filter, not a signal source. Signals require >=3/4 dimension resonance. No parameter brute-forcing. Empty positions are valid outcomes.

### 3. Design Patterns

- **Single-Navigation Architecture**: Navigate once, all fallback tracks operate on the current page
- **Safe Timeout**: Use explicit `new Promise<T>` + `clearTimeout`, never `Promise.race()`
- **Context-Aware Matching**: Anti-crawl keywords use contextual verification (~500 chars), not global substring
- **Append-Only State**: Never modify early context; add updates as new messages at the tail

### 4. Model Routing (Flash vs Pro)

DeepSeek Flash: data collection, simple classification, auxiliary processing
DeepSeek Pro: deep analysis, adversarial reasoning, final report writing

All LLM calls route through `deepseek_client.py` — no module should call httpx directly.

### 5. Testing

- Tests live in `tests/` per project
- Run: `python -m pytest tests/ -v --tb=short`
- Mock mode available for all pipeline stages (`--mock` flag)

## Development Workflow

1. **Research first**: Search for existing solutions before building new
2. **Skill evaluation (Security-First)**: All skills MUST follow this protocol before installation:
   - **Sandbox**: Place skill files in isolated sandbox directory first
   - **Scan**: Check for malicious code injection (eval, exec, subprocess with user input, obfuscated strings, network calls to unknown hosts)
   - **Approve**: Only install after confirming no malicious patterns
   - **Update**: Re-scan skills on every update — same protocol applies
3. **Skill updates**: When updating existing skills, re-run the full sandbox-scan-approve cycle
3. **Plan before code**: Use Triumvirate pipeline (Opus→Sonnet→Haiku) for architecture decisions
4. **Verify after code**: Syntax check + run tests before declaring done
5. **Memory after milestone**: Save key decisions and state to Cowork Memory

## Merge-Readiness Pack (MRP) Format

When completing a major module or encountering a complex logic deadlock, halt and produce an MRP:

```
### MRP: <module name>
**Status**: READY_FOR_REVIEW / BLOCKED / NEEDS_DECISION
**Files changed**: <list>
**Test results**: <passed/failed count>
**Architecture decisions**: <list of AD-XXX if any>
**Open questions**: <things needing human input>
**Risk items**: <what could break>
**Review requested from**: Sonnet (code review) / Opus (architecture review)
```

## Health Check

```bash
python scripts/health_check.py        # Full check (syntax + config + tests)
python scripts/health_check.py --quick # Syntax only
```

## Self-Correction Protocol

When encountering repeated errors or inefficient patterns caused by existing rules:
1. Identify the root cause (specific rule, prompt, or workflow)
2. Propose a concrete amendment to this CLAUDE.md
3. Upon human approval, apply the edit
4. Log the correction to Cowork Memory


## Key Files

| File | Purpose |
|------|---------|
| `projects/robinhood/src/main.py` | SignalFoundry entry — daily/strict/shadow modes |
| `projects/robinhood/src/deepseek_client.py` | Single LLM gateway — all API calls route here |
| `projects/robinhood/config/asset_universe.py` | Robinhood-tradable asset matrix |
| `projects/robinhood/config/source_authority.py` | Source authority tiers (1-4) |
| `projects/command_center/app.py` | Command Center GUI entry |
| `infrastructure/SKILLS_MANIFEST.json` | Registered skills registry |
| `infrastructure/skills/browser-automation/` | Browser automation adapter (TypeScript) |
