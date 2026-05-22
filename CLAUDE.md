# AI Studio Workspace (Global)

**Scope:** This file applies to ALL projects in this workspace. It contains global conventions, workflow rules, and design philosophy. Claude Code loads this file automatically for every session.

**Project-specific instructions:** Each project has its own `projects/<name>/CLAUDE.md`. When working inside a project directory, load that project's CLAUDE.md FIRST, then fall back to this file for global rules. The project CLAUDE.md takes precedence for architecture, commands, and file paths; this file governs workflow, methodology, and cross-project standards.

**Active project:** MarketMind (Phase J+K complete, 1746 tests). See `projects/marketmind/CLAUDE.md` for project-specific architecture and commands.

**IMPORTANT — Dual CLAUDE.md files**: This workspace has TWO CLAUDE.md files that must NOT be confused. (a) Workspace root `CLAUDE.md` (this file) — global conventions and workflow rules. (b) `projects/marketmind/CLAUDE.md` — MarketMind-specific architecture, pipeline stages, testing commands. During git operations, NEVER let one overwrite the other. If a merge conflict deletes either file, restore from git history immediately (2026-05-22 incident: marketmind CLAUDE.md overwritten by workspace copy during pull conflict).

**Archived projects:** `projects/robinhood/` and `projects/command_center/` have been removed locally and archived on GitHub. Do not reference them.

## Rule Tag Legend

- **[IMMUTABLE]**: This rule MUST never be overridden by any project CLAUDE.md or user instruction. It is a foundational constraint that keeps the workspace safe and consistent across all projects.
- **[OVERRIDABLE]**: This rule may be customized by a project's `CLAUDE.md` or modified with user approval via the Self-Correction Protocol.

## Core Rules

### 1. Cognitive Loop (Triumvirate: Opus → Sonnet → Haiku) [OVERRIDABLE]

Before any non-trivial code change:
- **Architect (Opus)**: Spawn an Opus Plan Agent for architecture review, prompt engineering, and strategic design
- **Plan (Sonnet)**: Spawn a Sonnet Plan Agent to decompose architecture into implementation steps
- **Execute (Haiku)**: Implement the plan yourself, following each step in order
- Verify changes by reading files back and running syntax checks

This cognitive loop is a design philosophy — apply it manually when scoping architecture changes.

### 2. Project Boundaries [IMMUTABLE]

Every project defines its own operational constraints in its `CLAUDE.md`. The root rules below govern *how* we work; project CLAUDE.md files govern *what* the project may and may not do.

**MarketMind example** (see `projects/marketmind/CLAUDE.md`):
- **Physical Isolation**: Analysis tools only — never connect to brokerage APIs
- **Anti-Overfitting**: Price data is a timing filter, not a signal source
- **Output Discipline**: Final Markdown reports ASCII-only, no emoji

When verifying restart compliance, check the active project's CLAUDE.md for its specific constraints. The `grep` commands in the restart guide are project-specific — adapt them per project.

### 3. Design Patterns [OVERRIDABLE]

- **Single-Navigation Architecture**: Navigate once, all fallback tracks operate on the current page
- **Safe Timeout**: Use explicit timeout + clear pattern, never bare Promise.race()
- **Context-Aware Matching**: Anti-crawl keywords use contextual verification (~500 chars), not global substring
- **Append-Only State**: Never modify early context; add updates as new messages at the tail
- **Modular Architecture (Extract-Module Pattern)**: Split monoliths by extracting one cohesive concern at a time into focused modules with clear interfaces. Keep the top-level file as a thin glue/orchestration layer that composes modules — it should call and coordinate, not implement. Each module handles exactly one business capability (Single Responsibility). See §3.1 below for size limits and extraction rules.

### 3.1 Modular Architecture Rules (MANDATORY) [IMMUTABLE]

**These rules apply to ALL projects in this workspace. They prevent monoliths from forming and keep blast radius small.**

#### File Size: Two-Tier Check [OVERRIDABLE]

Check once at commit time or phase completion — NOT during active development.

The table below is the **default for Python projects**. Static-language projects (Java, Go, Rust) should scale up ~20% (e.g., 300/600 for modules). Each project may override these in its own `CLAUDE.md`; document the reason (e.g., "data pipeline with long transformation chains → soft threshold 350"). Review thresholds at phase boundaries, not mid-phase.

| Role | Soft Threshold | Hard Ceiling |
|------|:---:|:---:|
| Python modules | 250 lines | 500 lines |
| CLI entry points | 100 lines | 150 lines |
| Glue / orchestration | 200 lines | 300 lines |
| Test files | 300 lines | 500 lines |

**Tier 1 — Soft threshold (triggers investigation):** [IMMUTABLE]
When a file exceeds the soft threshold, answer 4 questions:
1. Does the module do more than one thing? (description needs "and"/"or" → SRP violation)
2. Does it export more than 10 public functions? (likely mixed responsibilities)
3. Do any functions have >4 parameters? (poor encapsulation)
4. Is any function's cyclomatic complexity >10? (run `radon cc <file> -a`; >10 means too many paths)

If ALL answers are "no" → the file is large but clean; proceed.
If ANY answer is "yes" → extract the violating responsibility into its own module.

**Tier 2 — Hard ceiling (automatic split):** [IMMUTABLE]
At this size, SRP violation is presumed. Do NOT run the 4 questions — split the file.
The hard ceiling exists to save debate time, not to punish long files.

**Principle**: Size triggers the question, responsibility answers it.
A 200-line module doing one thing is clean. A 40-line module doing three things is not.

Files exceeding the hard maximum trigger a mandatory refactoring before any new features can be added to that file.

**Grandfather clause**: [OVERRIDABLE] Files that exceed limits as of 2026-05-15 (app.py: 971, layer1_interactive.py: 657, methodology_rules.py: 639, shadow_agent.py: 567, multimodal_adapter.py: 591) may receive extraction-only changes and bug fixes. New feature work on these files requires extraction first. Bug fixes exceeding 20 lines require a brief justification in the commit message. Target: all files compliant by end of Phase D.

#### Extraction Rules [IMMUTABLE]

1. **One module = one concern.** Each extracted module handles exactly one business capability (e.g., `l3_interactive.py` for L3 review, not "pipeline utilities").
2. **Clear contract.** Every module exports a single public entry point with well-defined inputs/outputs (e.g., `async def run_X(ctx: SessionContext, cli_handler) -> bool`).
3. **No back-imports.** Extracted modules must NOT import from the glue layer or from sibling modules at the same level. Imports form a DAG: glue → modules → shared data types.
4. **Test-before-extract.** Write at least 3 tests for the new module (confirm/observe/question paths) BEFORE integrating it into the glue layer.
5. **PICA triggers on extraction.** Every new extracted `.py` file triggers the full PICA protocol (§4): PICA-Unit → PICA-Security → PICA-Integration → PICA-Regression before commit. Extraction is a code change like any other.
6. **Commit after each extraction.** Extract one module → PICA → test → commit. Never extract multiple modules in one commit.

**Anti-pattern — over-extraction**: Files under 30 lines exporting a single function create unnecessary indirection. Keep these in the parent module unless the function is shared across 3+ consumers.

**Exception — data modules**: Constants, enums, label maps, and configuration modules may export multiple names. The single-entry-point rule applies to behavioral modules, not data containers.

#### Extraction Priority (extract in this order) [OVERRIDABLE]

| Priority | What to Extract | Why First |
|:---:|------|------|
| 1 | Independent interaction stages (L1, L2, L3, Decision) | Zero dependencies, lowest risk |
| 2 | Shared data types (SessionContext, dataclasses) | Needed by stages above |
| 3 | Utility/shared logic (output filter, parsers) | Depends on data types |
| 4 | Orchestration helpers (broadcast, ELITE) | May depend on glue globals — use snapshots |

#### Glue Layer Contract [IMMUTABLE]

The glue layer (e.g., `app.py`) must ONLY:
- Initialize shared state (SessionContext)
- Call extracted modules in sequence
- Handle module-level coordination (shadow launch, archive)
- Display cross-module results (shadow consensus, ELITE)

The glue layer must NOT:
- Contain business logic (analysis, decision-making, formatting)
- Access module-internal implementation details
- Include standalone execution paths (these belong in separate modules, e.g., `pipeline/orchestration.py`)

**Glue file size**: The two-tier check above applies — 200 lines soft (trigger SRP investigation), 300 lines hard (automatic split). The soft check asks one primary question: "Is there business logic hiding here?" A 250-line file that only orchestrates is acceptable; a 150-line file with inline analysis is not. The hard ceiling exists because at 300+ lines of orchestration, the coordination logic itself has become complex enough to warrant decomposition.

**Entry point files** (`app.py`, `main.py`): These naturally contain CLI argument parsing, mode dispatch, and initialization (~50-100 lines). If run-mode functions (e.g., `run_daily`, `run_gui`) live in the same file, extract them to a dedicated orchestration module. The entry point should read like a table of contents.

#### Measurable Criteria [IMMUTABLE]

After extraction, verify:
- [ ] Glue layer contains only orchestration calls (no analysis/decision code)
- [ ] Standalone run modes extracted to orchestration module
- [ ] Each module ≤ 500 lines (hard)
- [ ] Each module has ≥ 3 tests
- [ ] No module imports from glue or sibling modules
- [ ] 0 test regressions (full suite passes)
- [ ] New module interface documented with docstring Args/Returns

### 3.2 Time-Awareness Rule (MANDATORY) [IMMUTABLE]

**AI has no native time awareness — the mental anchor for "now" defaults to training cutoff (~Jan 2026). This rule prevents timestamp hallucination.**

1. **Always verify current date before time-sensitive operations.** Run `date` or `powershell Get-Date -AsUTC -Format 'yyyy-MM-dd HH:mm:ss'` before generating any timestamp.
2. **Progress files**: `**Updated**: YYYY-MM-DD HH:MM` must use command output, never LLM-generated.
3. **Git commits**: Verify date references against `date` output.
4. **Relative dates** ("next Monday", "tomorrow"): Compute from `date` output, never training data.
5. **MarketMind runtime**: [OVERRIDABLE] `datetime.now()` MUST use `datetime.now(timezone.utc)`. Verify with `grep -rn "datetime.now()" --include="*.py" projects/marketmind/ | grep -v "timezone.utc" | grep -v tests/` — must return empty. New code must follow this pattern. Do NOT reference the date the audit was done — the requirement is ongoing.
6. **Dual time anchor**: LLM prompts must include BOTH current date AND knowledge cutoff.
7. **Memory freshness**: Verify memory entries against current file/code state before recommending.
8. **Mechanical enforcement**: The `time_anchor.py` SessionStart hook (see `.claude/hooks/time_anchor.py`) runs `date` on every session start, writes `current_time.txt`, and prints the training-cutoff delta. This mechanizes Points 1–6 above so enforcement does not rely on AI memory. If the hook output is absent, the AI should run `date` manually — because the enforcement mechanism itself may be down.

## Development Workflow

1. **Research first**: Search for existing solutions before building new [OVERRIDABLE]
2. **Skill evaluation (Security-First)**: All third-party files (skills, plugins, GitHub repos, MCP servers) MUST pass through `.claude/sandbox/` before installation. See `.claude/sandbox/SANDBOX.md` for the full protocol: isolate → scan → approve → install. Updates follow the same process. [IMMUTABLE]
3. **Plan before code**: Use Triumvirate pipeline (Opus→Sonnet→Haiku) for architecture decisions [OVERRIDABLE]
4. **Verify after code**: Syntax check + run tests before declaring done [IMMUTABLE]
5. **Commit after each sub-phase**: `git add` + `git commit` after every sub-phase completes with passing tests. Never accumulate multiple sub-phases in the working directory without version control. [IMMUTABLE]
6. **Red Team before completion**: Independent Red Team audit produces `.claude/audits/phase-X-red-team.md` BEFORE the phase is marked complete. Completion is never self-declared without external audit confirmation. [IMMUTABLE]
7. **Memory after milestone**: Save key decisions and state to auto-memory [OVERRIDABLE]
8. **Git Safety Protocol (pre-pull/push)**: [IMMUTABLE] Before ANY `git pull` or `git push`, verify authentication and assess remote divergence. Steps: (a) `git fetch origin master` first to see what's coming, (b) `git log HEAD..origin/master --oneline | wc -l` — if >10 new commits, STOP and evaluate before pulling, (c) if local has unpushed commits, push FIRST before pulling, (d) if large restructuring detected (>50 files changed), do NOT pull — ask user. Rationale: 2026-05-22 git pull caused 69 test regressions from massive remote divergence. See `.claude/RESTART_GUIDE.md` §Git Safety Protocol for the full decision matrix. [IMMUTABLE]

### 4. PICA Protocol: Pre-Integration Code Audit (MANDATORY) [IMMUTABLE]

**Every code change MUST pass through the 4-level PICA protocol before integration. This applies to ALL projects in this workspace, now and in the future. This is NOT optional — it is enforced by audit artifact requirements.**

Full specification: defined in this file under §4. PICA protocol — no external file needed.

#### PICA Levels (sequential, each must pass before proceeding) [IMMUTABLE]

```
Code written → PICA-Unit → PICA-Security → PICA-Integration → PICA-Regression → Commit
```

| Level | What | Who | Mandatory? |
|-------|------|-----|:---:|
| **PICA-Unit** | pytest: 0 failures, 0 regressions | Developer | Always |
| **PICA-Security** | Security Agent + Data Agent (parallel audit) | 2 AI Agents | For new modules, API changes, schema migrations, config changes, dependency upgrades |
| **PICA-Integration** | Static: backward compat, data flow, dead loops, import boundaries. Dynamic: generated integration test scenarios | 1 AI Agent + pytest | For new modules, API changes, control flow changes, schema migrations |
| **PICA-Regression** | Full pytest suite + optimization review | Developer + 1 AI Agent | Always (except test-only and doc changes) |

#### Risk Tiers (Critical/High/Medium/Low) [OVERRIDABLE]

PICA-Security and PICA-Integration requirements scale with risk:
- **Critical** (`async_client.py`, `shadow_state.py`, `decision.py`): Full PICA-Security (2 agents) + Full PICA-Integration
- **High** (pipeline stages, shadow logic): Full PICA-Security + Static-only PICA-Integration
- **Medium** (config, storage, utilities): 1 Security Agent only
- **Low** (UI, formatting, comments): Skip to PICA-Regression

#### Enforcement: Audit Artifacts [IMMUTABLE]

After each level passes, write a JSON or Markdown artifact to `.claude/audits/{phase}/`:
- `pica-unit-{module}.json`
- `pica-security-{module}.json`
- `pica-integration-{module}.json`
- `pica-regression.json`

**Artifact rule**: For every modified `.py` file, the corresponding audit artifact MUST exist with a timestamp newer than the file's last modification. If missing, stop and run the missing level. No artifact = no commit.

#### Emergency Channel [IMMUTABLE]

Production hotfixes and security patches: PICA-Unit + 1 Security Agent + PICA-Regression (mandatory). Remaining levels must be backfilled within 24 hours with a recorded justification.

#### Verification (do this at session START) [IMMUTABLE]

When starting a session with modified files:
1. Check each modified `.py` file against `.claude/audits/` for matching artifacts
2. If artifacts missing or stale, run the missing PICA level BEFORE any new work
3. Record findings in the progress file

### 5. Hard Rule: Progress Checkpoint After EVERY Sub-Task (MANDATORY) [IMMUTABLE]

**This rule exists to prevent lost work from crashes, power loss, or session termination. It is NOT optional. Violating it means progress is invisible to future sessions.**

#### When to write a checkpoint: [IMMUTABLE]
- After completing ANY sub-task (a single bug fix, a file edit, a test passing, a commit)
- After finishing a discussion/design decision
- Before starting a risky operation (destructive git, large refactor)
- When stopping work (end of session, or user says they're done for now)
- **Rule of thumb: if you did something you'd hate to redo, write it down.**

#### Where to write it: [IMMUTABLE]
- **Active progress file**: `.claude/progress/phase-X-batch-Y-progress.md` (or create one if it doesn't exist)
- **Format**: Markdown checklist. Mark completed items with `[x]`, add new items with `[ ]`. Append a timestamp line at the bottom: `**Updated**: YYYY-MM-DD HH:MM — <what just happened>`

#### What to record (minimum): [IMMUTABLE]
```
**Updated**: 2026-05-15 14:30 — Fixed C1 wfe_ratios NameError, tests pass
```
For new tasks:
```
- [ ] <task id>: <description> — <file(s) affected>
```

#### Verification (do this at session START): [IMMUTABLE]
1. Check `.claude/progress/` for the most recent progress file
2. Cross-reference with `git log` and `git diff` to verify the recorded state matches reality
3. If there's a discrepancy, update the progress file BEFORE doing any new work
4. If no progress file exists, create one immediately from `git log` + working tree state

#### Crash recovery: [IMMUTABLE]
When a session starts and uncommitted changes exist with no matching progress file, the FIRST action is to reconstruct state:
1. Read `git diff --stat` to see what files changed
2. Read any new untracked files
3. Write a progress file capturing what was in flight
4. Then (and only then) continue work

#### Anti-patterns (DO NOT DO): [IMMUTABLE]
- "I'll write the checkpoint after I finish this next thing" → crash happens first
- "This is a small change, no need to log it" → 10 small changes = 1 lost day
- "The git log is enough" → git doesn't track task-level progress or what's half-done

## Merge-Readiness Pack (MRP) Format [OVERRIDABLE]

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

## Self-Correction Protocol [IMMUTABLE]

When encountering repeated errors or inefficient patterns caused by existing rules:
1. Identify the root cause (specific rule, prompt, or workflow)
2. Propose a concrete amendment to this CLAUDE.md
3. Upon human approval, apply the edit
4. Log the correction to auto-memory

## Agent Skills

### Mandatory Skill Checkpoints (MANDATORY) [OVERRIDABLE]

**Every non-trivial task MUST invoke these skill groups. This is NOT optional.**

### Context7 & MCP Security Rule (MANDATORY) [IMMUTABLE]

Context7 MCP injects latest library docs. It sends queries to `mcp.context7.com` (Upstash). To prevent proprietary data leakage:
- Context7: use ONLY for library API reference (pandas, numpy, aiohttp, etc.)
- Do NOT invoke Context7 during analysis of proprietary data, API keys, or internal architecture
- GitHub MCP: read-only operations preferred; never expose tokens in prompts
- Figma MCP: limited to 6 free calls/month — use sparingly
- Chrome DevTools MCP: local-only, no data exfiltration risk

1. **Superpowers** (`superpowers@claude-plugins-official`): Before writing plan/design code, invoke `Skill("superpowers:brainstorming")` to clarify the problem. Before implementing, invoke `Skill("superpowers:writing-plans")` to formalize approach. After implementation, invoke `Skill("superpowers:verification-before-completion")` to validate completeness. [OVERRIDABLE]

2. **Mattpocock Engineering Skills** (`mattpocock-skills@mattpocock-skills`): For architecture changes, invoke `Skill("mattpocock-skills:engineering/improve-codebase-architecture")`. For bug triage, invoke `Skill("mattpocock-skills:engineering/triage")`. For TDD workflow, invoke `Skill("mattpocock-skills:engineering/tdd")`. For diagnosing complex issues, invoke `Skill("mattpocock-skills:engineering/diagnose")`. [OVERRIDABLE]

3. **Agent Team** (`.claude/agents/AGENTS.md`): The 8-agent team MUST be spawned for architecture work. At minimum: Architect (design) → Builder (implement) → Red Team Code (syntax) → Red Team Logic (audit). Each agent has distinct responsibilities and restrictions (see AGENTS.md Discipline Rules). [OVERRIDABLE]

**Enforcement**: If these skills aren't available in the `Skill` tool list, the session has an initialization problem that must be fixed BEFORE any code work proceeds. [IMMUTABLE]

### Issue tracker [OVERRIDABLE]
GitHub Issues — use `gh issue` CLI for all operations. See `docs/agents/issue-tracker.md`.

### Triage labels [OVERRIDABLE]
Default five-label vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs [OVERRIDABLE]
Multi-context — `CONTEXT-MAP.md` at repo root points to per-context `CONTEXT.md` files. Currently active: `projects/marketmind/`. See `docs/agents/domain.md`.
