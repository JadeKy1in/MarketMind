---
name: harness-install
description: Install and customize a Harness Engineering solution for a project. Use after harness-assess has produced a recommendation, or when asked to set up a specific harness solution like autonomous-dev, everything-claude-code, cc-devflow, or claudecode-harness.
---

# Harness Install

Install and customize a Harness Engineering solution. Run after harness-assess completes, or when user explicitly asks to install a specific harness.

## Phase 1: Fetch the Solution

For GitHub repos: clone to `~/.claude/harness-repos/[repo-name]/`, read README and structure, identify skills/hooks/CLAUDE.md/config — do NOT copy entire repo into project. For npm packages: `npm install -g [package]`, run init/setup if provided.

## Phase 2: Component Mapping

Map harness components to project one-to-one. Install only components that: map to existing project patterns, fill a verified gap, and don't duplicate existing skill functionality.

autonomous-dev mapping:
- 13-phase state machine → project pipeline stages
- 27 deterministic hooks → project stage boundaries (PreToolUse at transitions, PostToolUse at completions)
- Planner-critic review → project's existing verification step
- TDD enforcement hooks → project's test suite

## Phase 3: Generate Configuration

Create in project root:

### `.claude/CLAUDE.md`
State machine stages mapped to project, stage gates (what must pass before advancing), context discipline (compaction thresholds, clear between stages, sub-agent usage), model routing (Opus for planning, Sonnet for implementation, Haiku for research/tests), hooks reference, skill integration mapping.

### `.claude/hooks/`
For each hook: when it fires, what it checks (deterministic, hard stop vs warning), what user sees.

### `.claude/settings.json`
Compaction strategy, model preferences, permission boundaries.

### `.claudeignore`
Exclude: node_modules, __pycache__, .git, venv, large data/logs/cache.

## Phase 4: Skill Integration

Map installed skills into harness workflow. For each: identify which stage it serves, check for overlap with harness components, document integration in CLAUDE.md. Prefer existing user-trusted skills over harness equivalents.

## Phase 5: Verify

Smoke test (no code changes): hooks fire correctly, state machine transitions clear, skill chain intact, existing test suite passes. Report: installed components, what was NOT installed (and why), skill integration table, verification results.
