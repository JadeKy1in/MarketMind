# Workspace-Level Development Rules

**Scope:** This file applies to ALL projects in this workspace. Project-specific rules go in `projects/<name>/CLAUDE.md`.

**Proxy Mode: [Advisor]** — set by `.claude/tools/proxy_mode.py`

---

## HARD GATE #1: Analysis Workflow (LOCKED — auto-triggered)

**When ANY task involves market analysis, competitive analysis, strategic planning, customer segmentation, or industry research — you MUST follow the 6-Phase workflow in `docs/methodology/analysis-workflow.md`.**

**Auto-trigger keywords**: 市场分析、竞品分析、战略分析、客群细分、行业分析、市场选择、product strategy、market analysis、competitive analysis、go-to-market

**Enforcement**: Before starting any analysis work, read the workflow document. Phase gates are binary — all exit criteria must be TRUE before advancing. Phase 3 (divergent analysis) explicitly forbids convergence language (no scoring, no ranking, no "leading candidate"). Red teams deploy at every phase boundary. User checkpoints at 4 mandatory pauses.

**Gate Advance Rule (LOCKED)**: Before proposing "enter Phase N+1", you MUST:
1. Recite every exit criterion of Phase N (e.g., "2.1/2.2/2.3/2.4/2.5")
2. Confirm each is TRUE with a brief note
3. **Check HARD GATE #3**: If a report file was written or updated in this Phase, verify the reference list is complete
4. **Cross-Market Calibration**: If the same gate/filter was applied to multiple markets in this Phase, verify the evidence standard was consistent. If Market A passed a gate with D1-level evidence, Market B cannot pass the same gate with D2-level evidence without explicit justification.
5. If any criterion is FALSE or unchecked, you CANNOT propose the next phase. Complete the missing criteria first.

**Violation**: Skipping phase gates, scoring before Phase 4, converging before Phase 3, OR proposing phase advance with unchecked gates → stop, acknowledge the violation, and restart the phase correctly.

---

## HARD GATE #2: Training Data Staleness (LOCKED — applies to ALL communication)

**Training data cutoff: ~January 2025 (~17 months ago as of May 2026).**

**YOU DO NOT KNOW the current state of anything that could have changed since January 2025.** This includes — but is not limited to — company metrics, product features, pricing, LLM capabilities, market data, regulations, geopolitical events, competitor information.

**Before you state ANY factual claim about current state:**
1. Ask: "Could this have changed since January 2025?" If yes → **you must real-time search before speaking.**
2. If you cannot search → you must explicitly say "I don't know the current state — my data is from before January 2025" — NEVER state training data as current fact.
3. This applies to ALL contexts: analysis, chat, writing, planning, everything. No exceptions.

**Violation response**: If you catch yourself stating an unverified current-state fact, immediately correct: "I just stated [X] but I haven't verified it — let me check."

---

## HARD GATE #3: Report Reference List (LOCKED — applies to ALL analysis reports)

**Every analysis report, strategy document, or research output written to a file MUST include a reference list section at the end.**

**Format**:

```markdown
## References

| # | Source | Date | Type |
|---|--------|------|------|
| 1 | [Source name](URL if available) | YYYY-MM | `[V]` primary / `[V]` secondary |
```

**Rules**:
1. Every `[V: source]` cited in the report body must appear in the reference list
2. Sources are numbered in order of first citation
3. If URL is unavailable, note the publisher/author and report title
4. `[H]` logic-only claims are not in the reference list — the reasoning chain is in the report body
5. This applies to ALL `.md` files written as analysis outputs. Code files and internal notes excluded

**Violation**: Report file written without a reference section → incomplete delivery. Add it before claiming the report is done.

**Mechanical enforcement (added 2026-05-27)**: 
1. Every new `.md` analysis file MUST start with `## References` placeholder before any content is written.
2. Every Phase gate advance checklist MUST include "Reference section complete for all files written/updated in this Phase."
3. References are added inline as sources are cited in the body, not collected at the end.

When creating a new project under `projects/`:

1. **Directory**: `projects/<project-name>/` — ALL code goes here. Never create `pipeline/`, `shadows/`, `api/` etc. at workspace root.
2. **CLAUDE.md**: Create `projects/<project-name>/CLAUDE.md` with project-specific rules. This root file covers universal rules.
3. **Git**: This entire workspace is ONE git repo. No `git init` inside project folders. No git submodules.
4. **CI**: Add a job to `.github/workflows/ci.yml` targeting the new project's test path.
5. **Module-first from day one**: New feature ≥50 lines = independent module. No appending to existing files.
6. **Shared resources**: `.claude/hooks/` (gates), User Proxy Agent (preferences), worktree cleanup — all auto-apply to new projects.
7. **Tests first**: `tests/` directory at project root, mirroring source structure 1:1.

---

## Universal Development Gates (apply to ALL projects)

| Gate | When | What |
|------|------|------|
| **PreToolUse** | Before Write/Edit `.py` | Task declaration in `current_task.json` required |
| **Pre-commit** | Before commit | 500-line ceiling per `.py` file + grandfather baseline |
| **Stop Gate** | Session end | PICA audits (unit, security, integration, regression, architecture, plan, review) |
| **Worktree Cleanup** | Session start | Auto-prune agent worktrees older than 24h |
| **CI** | On push | GitHub Actions auto-test |

---

## Module-First Principle

- New code ≥50 lines → independent module with single responsibility
- File name = what it does. No "utils" or "helpers" dumping grounds.
- Extraction is a code smell — if you're extracting, you already violated this rule.
- 500-line hard ceiling per file (grandfathered files may not grow)

---

## Development Process

```
Session Start → Flash frontload (decision points) → Sync decisions → Async agents → PICA → Commit
```

- **Frontload first**: Flash scans tasks, identifies decisions, presents to user BEFORE any code changes.
- **Sync before async**: Complete all user-interaction steps while user is present.
- **Never block on human**: If user unavailable, User Proxy Agent handles decisions per confidence tiers. All decisions logged.

---

## Active Projects

| Project | Path | Status |
|---------|------|--------|
| MarketMind | `projects/marketmind/` | Active — 1,998 tests, 0 fail |
| Singoo | `projects/singoo/` | Active — 89 tests, PoC complete |

---

## Do NOT

- Create code directories at workspace root (`pipeline/`, `shadows/`, etc.)
- `git init` inside any project folder
- Add `node_modules`, `__pycache__`, `.env` to git
- Skip the PreToolUse task declaration before editing code
- Launch async work before sync decisions are resolved
