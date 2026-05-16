# AI Studio Workspace (Global)

**Scope:** This file applies to ALL projects in this workspace. It contains global conventions, workflow rules, and design philosophy. Claude Code loads this file automatically for every session.

**Project-specific instructions:** Each project has its own `projects/<name>/CLAUDE.md`. When working inside a project directory, load that project's CLAUDE.md FIRST, then fall back to this file for global rules. The project CLAUDE.md takes precedence for architecture, commands, and file paths; this file governs workflow, methodology, and cross-project standards.

**Active project:** MarketMind (`projects/marketmind/`). See `projects/marketmind/CLAUDE.md`.

**Archived projects:** `projects/robinhood/` and `projects/command_center/` have been removed locally and archived on GitHub. Do not reference them.

## Core Rules

### 1. Cognitive Loop (Triumvirate: Opus → Sonnet → Haiku)

Before any non-trivial code change:
- **Architect (Opus)**: Spawn an Opus Plan Agent for architecture review, prompt engineering, and strategic design
- **Plan (Sonnet)**: Spawn a Sonnet Plan Agent to decompose architecture into implementation steps
- **Execute (Haiku)**: Implement the plan yourself, following each step in order
- Verify changes by reading files back and running syntax checks

This cognitive loop is a design philosophy — apply it manually when scoping architecture changes.

### 2. Three System Laws

**Law 1 (Output Discipline):** Final Markdown reports must be ASCII-only, no emoji. Code comments and console output are exempt.

**Law 2 (Physical Isolation):** Analysis tools only — never connect to brokerage APIs. Account state is maintained manually, never automated.

**Law 3 (Anti-Overfitting):** Price data is a timing filter, not a signal source. No parameter brute-forcing. Empty positions are valid outcomes.

### 3. Design Patterns

- **Single-Navigation Architecture**: Navigate once, all fallback tracks operate on the current page
- **Safe Timeout**: Use explicit timeout + clear pattern, never bare Promise.race()
- **Context-Aware Matching**: Anti-crawl keywords use contextual verification (~500 chars), not global substring
- **Append-Only State**: Never modify early context; add updates as new messages at the tail

## Development Workflow

1. **Research first**: Search for existing solutions before building new
2. **Skill evaluation (Security-First)**: All third-party files (skills, plugins, GitHub repos, MCP servers) MUST pass through `.claude/sandbox/` before installation. See `.claude/sandbox/SANDBOX.md` for the full protocol: isolate → scan → approve → install. Updates follow the same process.
3. **Plan before code**: Use Triumvirate pipeline (Opus→Sonnet→Haiku) for architecture decisions
4. **Verify after code**: Syntax check + run tests before declaring done
5. **Commit after each sub-phase**: `git add` + `git commit` after every sub-phase completes with passing tests. Never accumulate multiple sub-phases in the working directory without version control.
6. **Red Team before completion**: Independent Red Team audit produces `.claude/audits/phase-X-red-team.md` BEFORE the phase is marked complete. Completion is never self-declared without external audit confirmation.
7. **Memory after milestone**: Save key decisions and state to auto-memory

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

## Self-Correction Protocol

When encountering repeated errors or inefficient patterns caused by existing rules:
1. Identify the root cause (specific rule, prompt, or workflow)
2. Propose a concrete amendment to this CLAUDE.md
3. Upon human approval, apply the edit
4. Log the correction to auto-memory

## Agent Skills

### Issue tracker
GitHub Issues — use `gh issue` CLI for all operations. See `docs/agents/issue-tracker.md`.

### Triage labels
Default five-label vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs
Multi-context — `CONTEXT-MAP.md` at repo root points to per-context `CONTEXT.md` files. Currently active: `projects/marketmind/`. See `docs/agents/domain.md`.
