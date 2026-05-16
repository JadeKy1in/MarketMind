---
name: harness-assess
description: Analyze a project's architecture and recommend the best Harness Engineering solution. Use when starting a new project, when asked to optimize Claude Code's harness setup, or when the user mentions "harness engineering", "harness assessment", or wants to improve Claude Code's project execution quality.
---

# Harness Assess

Analyze any project's architecture and recommend the optimal Harness Engineering solution.

## Phase 1: Project Architecture Scan

Use find/grep/read on key entry points. Look for: Pipeline/Stage signals, Agent/Multi-entity signals, Adversarial/Verification signals, Test infrastructure, State persistence, Observability, Error recovery.

## Phase 2: Harness Element Mapping

Map findings against 12 Harness Engineering Elements. Score each PRESENT, PARTIAL, or MISSING:

1. State Machines — Pipeline stages, workflow engines, state trackers
2. Validation Loops — Test suites, verification steps, quality gates
3. Isolated Sub-agents — Independent agents, worker pools, shadow entities
4. Virtual File System — Git worktrees, sandboxed execution, isolated workspaces
5. Human-in-the-loop — UI panels, approval gates, manual review steps
6. Hook Enforcement — Pre/post execution hooks, guard checks, gate validators
7. State Persistence — DB, archival, checkpoint/snapshot systems
8. Context Management — Compaction strategies, context window discipline
9. Deterministic Ordering — Fixed execution order, DAG-based pipelines
10. Output Validation — Adversarial review, fact checking, resonance validation
11. Observability — Logging, monitoring, progress tracking, dashboards
12. Error Recovery — Retry, fallback, graceful degradation

## Phase 3: Solution Matching

Evaluate against known harness solutions:

**autonomous-dev** (GitHub: akaszubski/autonomous-dev)
- 13-phase state machine, 27 deterministic hooks, planner-critic adversarial review
- Best fit: Pipeline-heavy projects with adversarial/verification patterns

**everything-claude-code** (GitHub: affaan-m/everything-claude-code)
- 38+ sub-agents, 156+ skills, memory persistence
- Best fit: Large projects, multi-language, general development

**cc-devflow** (npm: cc-devflow)
- 5-stage workflow (init→spec→dev→verify→release), git worktree parallelization
- Best fit: Small-to-medium projects, rapid iteration

**claudecode-harness** (GitHub: anothervibecoder-s/claudecode-harness)
- Multi-model consensus, hub-and-spoke, guardrails
- Best fit: Security-critical, consensus-required projects

**agent-harness-kit** (npm: agent-harness-kit)
- 10 skills, 5 review sub-agents, garbage collection rituals
- Best fit: Code review-heavy workflows

Score each on: Architecture Fit (0-10), Gap Fill (0-10), Overhead (0-10 inverted), Skill Complement (0-10).
Final = (ArchFit×0.35) + (GapFill×0.30) + (Overhead×0.15) + (SkillComp×0.20)

## Phase 4: Output

Present assessment with: Architecture Summary, Harness Element Map, Solution Scores table, Recommendation with reasoning, Runner-up, Existing Skill Integration, and Action Plan. Ask user if they want to proceed with harness-install.
