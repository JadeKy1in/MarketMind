# Workspace Flow Implementation Plan

**Date**: 2026-05-19
**Status**: RED_TEAM_FIXES_APPLIED
**Based on**: External research (2 agents) + Anthropic official docs + skills.sh registry
**Red Team**: Audited 2026-05-19 — 2 HIGH, 3 MEDIUM, 2 LOW → all fixed

## 1. Architecture: Dual-Layer CLAUDE.md

```
Root CLAUDE.md (<200 lines)
  ├── Map of all projects (what they ARE, not how they WORK)
  ├── Global rules tagged [GLOBAL-IMMUTABLE] or [GLOBAL-OVERRIDABLE]
  │     [GLOBAL-IMMUTABLE]: PICA, sandbox protocol, pre-session validation
  │     [GLOBAL-OVERRIDABLE]: skill preferences, model routing, commit style
  ├── Skill inventory (what's installed, what it does, when to use)
  ├── Pre-session validation procedure
  └── Delegates to: "Load projects/<name>/CLAUDE.md for details"

Project CLAUDE.md (project-specific)
  ├── Architecture, file paths, commands, constraints
  ├── May override [GLOBAL-OVERRIDABLE] rules only
  ├── Must NOT override [GLOBAL-IMMUTABLE] rules
  └── Project-specific skill activation
```

**Loading order** (confirmed by Anthropic docs): User global → Root workspace → Project directory. More specific files override broader ones.

**Conflict resolution**: Root rules tagged `[GLOBAL-IMMUTABLE]` (PICA, sandbox, pre-session) cannot be overridden by project CLAUDE.md. `[GLOBAL-OVERRIDABLE]` rules may be adjusted per project. [Fix: L6]

## 2. Startup Sequence

```
D:\Claude Code\Claude Code.bat
  ├── pre_session.py — validate plugins/config/sandbox (blocking)
  ├── env vars — API, Agent Teams, Tool Search, Proxy
  ├── claude --effort max
  │     ├── SessionStart: config_guardian.py (2nd defense)
  │     ├── SessionStart: time_anchor.py (time awareness)
  │     └── Skills loaded: 34 across 4 plugins + 5 workspace skills
  │
  ├── Discovery Phase (new project/task):
  │     Skill("mattpocock-skills:productivity/grill-me") — Socratic interview
  │     Skill("superpowers:brainstorming") — 9-step: clarify→propose→spec→review
  │     Skill("superpowers:writing-plans") — formal plan document
  │
  ├── Implementation Phase:
  │     Agent Team: Architect→Builder→Red Team Code→Red Team Logic
  │     PICA: Unit→Security→Integration→Regression
  │     Skill("superpowers:verification-before-completion")
  │
  └── PreCompact: pre_compact.py — save progress snapshot before compaction
```

## 3. Skill Inventory (Final)

### Infrastructure (user-level plugins, ~/.claude/plugins/cache/)

| Plugin | Skills | Key Capabilities |
|------|:---:|------|
| Superpowers v5.1.0 | 13 | brainstorming, TDD, debugging, parallel agents, code review, verification |
| Mattpocock v1.0.0 | 15 | triage, diagnose, tdd, architecture, caveman, grill-me, handoff |
| Karpathy v1.0.0 | 1 | karpathy-guidelines (AI/ML best practices) |
| Claude HUD v0.1.0 | 1 | Status line display |
| **Subtotal** | **30** | |

### Workspace Skills (npx-installed, .agents/skills/)

| Skill | Source | Use Case |
|------|------|------|
| find-skills | vercel-labs/skills | Ecosystem search — discover new tools |
| frontend-design | anthropics/skills | UI aesthetic direction (non-MarketMind projects) |
| vercel-react-best-practices | vercel-labs/agent-skills | React/Next.js performance (non-MarketMind projects) |
| parallel-feature-development | wshobson/agents | Multi-agent parallel implementation |
| feature-dev | anthropic/feature-dev | 7-phase structured feature workflow (non-MarketMind projects) |
| **Subtotal** | **5** | |

### MCP Servers

| Server | Transport | Status |
|------|------|:---:|
| Context7 | HTTP → mcp.context7.com/mcp | ✓ Connected |

**Total skills: 35** (at Anthropic's 20-30 ceiling — profile actual triggers over 1 week, disable unused, target ≤25. Mattpocock's 15 skills are the most likely underused.) [Fix: M3]

## 4. New Project Bootstrap Flow

```
1. /init → generate project CLAUDE.md skeleton
2. Skill("mattpocock-skills:productivity/grill-me") → clarify project goals
3. Skill("superpowers:brainstorming") → design architecture
4. Skill("superpowers:writing-plans") → formalize plan
5. Environment & dependency setup [Fix: M5]:
   - Python version, venv, requirements.txt / pyproject.toml
   - Dependency audit (pip-audit or safety check)
6. Security & constraint review [Fix: M5]:
   - Define project boundaries (no API access, no network, etc.)
   - Set up PICA risk tier assignments
7. Configure project skills:
   - Python data pipeline → PICA + Agent Team (default)
   - React frontend → vercel-react-best-practices + frontend-design
   - General → feature-dev for structured workflow
8. Set up project .claude/settings.local.json (permissions, hooks)
9. Add to root CLAUDE.md project map
10. Commit
```

## 5. Context7 Integration (Time + Knowledge Gap Fix)

Two complementary mechanisms eliminate AI knowledge gaps:

| Gap | Mechanism | How |
|------|------|------|
| **Time awareness** | time_anchor.py (SessionStart) | Forces real `date` check, writes current_time.txt |
| **Knowledge cutoff** | Context7 MCP | Injects latest library docs (pandas, numpy, aiohttp) on demand |

Usage: mention `use context7` when working with libraries to get version-specific docs.

**Data exposure mitigation** [Fix: H1]: Context7 sends queries to `mcp.context7.com`. To prevent proprietary data leakage:
- Only invoke Context7 for explicit library API lookups (not general conversation)
- Never invoke when discussing proprietary analysis, API keys, or internal architecture
- Monitor: if accuracy degrades, replace with offline doc index (downloaded pandas/numpy docs + ripgrep)
- Rule: add to CLAUDE.md — "Context7: use only for library API reference. Do NOT invoke during analysis of proprietary data."

## 6. PreCompact Hook

Compaction is the #1 source of context loss (confirmed by external research). New hook:

```
PreCompact → pre_compact.py
  └── Saves snapshot to .claude/progress/compact_snapshots.jsonl
      ├── Timestamp
      ├── git status --short (modified files)
      ├── git log --oneline -3 (recent commits)
      ├── Active task description (from latest progress file) [Fix: M4]
      ├── Last completed sub-task [Fix: M4]
      └── Pending next step [Fix: M4]
```

Non-blocking (always exit 0). Enables crash recovery from compaction events.
Reads the most recent `.claude/progress/` file to capture semantic task state, not just mechanical git state.

## 7. Third-Party Install Safety

All new tools follow sandbox protocol:

```
1. Isolate → .claude/sandbox/incoming/<name>/
2. Scan → check for eval/exec/subprocess/socket/obfuscation
3. Approve → only after confirming no malicious patterns
4. Update → re-run FULL protocol for updates
```

`pre_session.py` checks sandbox/incoming/ at every launch and warns if unprocessed.

## 8. Update Checking

- **Weekly**: `npx skills update` via scheduled reminder (restart guide) [Fix: L7 — was monthly]
- **Plugins**: pre_session.py WARNING at 30 days stale, ERROR (block launch) at 60 days stale [Fix: L7]
- **Automated**: Future — GitHub Actions cron job for weekly `npx skills update --dry-run` to flag outdated skills

## 9. Feature-Dev Private Repo Mitigation [Fix: H2]

`anthropic/feature-dev` is a private repo requiring `gh auth login`. Safety protocol:
1. Clone into `.claude/sandbox/incoming/feature-dev/` FIRST (read-only)
2. Run full sandbox scan before installing
3. Pin to specific commit hash after approval
4. Never grant `gh auth` during active development — authenticate once beforehand
5. Private-sourced skills require 2-person review (user + agent) before install

## 9. Files Created/Modified

```
NEW:
  .claude/hooks/pre_session.py          # Pre-launch validator
  .claude/hooks/pre_compact.py          # Compaction safety net
  .claude/hooks/launch_claude.sh        # Launch wrapper
  .claude/plans/workspace-flow-implementation-plan.md  # This file
  .claude/progress/RESTART_2026-05-19_v2.md

MODIFIED:
  D:\Claude Code\Claude Code.bat        # Startup script
  C:\Users\Administrator\.claude\settings.json  # Hooks + plugins
  C:\Users\Administrator\.claude.json   # MCP config (Context7)
  CLAUDE.md                             # Mandatory skill checkpoints

INSTALLED:
  .agents/skills/find-skills/
  .agents/skills/frontend-design/
  .agents/skills/vercel-react-best-practices/
  .agents/skills/parallel-feature-development/
  .agents/skills/feature-dev/

REMOVED:
  skill-creator@claude-plugins-official (replaced by find-skills)
  web-design-guidelines (wrong install, corrected to frontend-design)
```

---

**MRP Status**: RED_TEAM_FIXES_APPLIED
**Estimated new code**: ~350 lines (hooks + plan doc + Red Team fixes)
**Risk**: LOW — all additions are additive, no pipeline code modified
**Dependencies**: Context7 needs session restart to load tools; feature-dev needs gh auth + sandbox first
**Pending manual actions**: (1) `gh auth login` for anthropic/feature-dev, (2) session restart to load Context7 MCP tools + 28 plugins
