# Harness Governance Workflow (HGW)

**Version:** 1.1.0
**Status:** Red Team reviewed — blocking issues resolved (2026-05-11)
**Purpose:** Systematically discover, evaluate, and adopt Harness Engineering solutions to optimize AI-assisted development output efficiency.

---

## Philosophy

Harness Engineering solutions (skills, agents, MCP servers, workflow frameworks) are the "tooling layer" between human intent and AI execution. They decay — new solutions emerge weekly, old ones stagnate. A static candidate list produces stale recommendations. This workflow ensures the project's harness layer evolves with the ecosystem.

**Core principle:** Harness selection should be evidence-based (project signals → element gaps → solution scoring), not preference-based. The assessment is only as good as the candidate list feeding it.

---

## Three-Tier Governance Model

Not every task needs a full market scan. Use the tier appropriate to the task's scope and novelty.

### Tier 1: Quick Health Check (routine tasks)

**Trigger:** Bug fix, minor edit, documentation, test addition — anything touching <5 files with no architecture change.

**Process:**
1. Check if last Tier 3 was within the current development phase
2. If current phase has a valid Tier 3 assessment → skip, use cached recommendation
3. If crossing a phase boundary (MRP filed) without re-assessment → prompt user: "Harness assessment is from previous phase. Run refresh? [y/N]"
4. If user explicitly requests skip ("skip harness check") → bypass all tiers for this task

**Output:** None (uses cached recommendation)

**Cost:** <5 seconds (phase check only)

### Tier 2: Standard Re-Assessment (new features, new modules)

**Trigger:** New module creation, feature that touches >10 files, pipeline stage addition, or cross-cutting architectural change. NOT for small features — those use Tier 1.

**Process:**
1. Re-run project scan (Step 1 of harness-assess) — detect any structural changes since last assessment
2. Re-evaluate 12 Harness Elements — have maturity levels changed?
3. Re-score the EXISTING 5 candidate solutions against updated signals
4. If the winner changed → report and ask whether to switch
5. If the winner is unchanged → confirm current harness is still optimal

**Output:** Updated Harness Assessment (abbreviated — only show changed scores)

**Cost:** 5-10 minutes (project scan + rescoring, no market search)

### Tier 3: Full Market-Scanned Assessment (major milestones, phase changes)

**Trigger:** Phase completion, project inception, architecture pivot, or user explicitly requests "full harness assessment". At minimum, run once per phase (aligned with MRP milestones).

**Process:**
1. **Market Scan** — Search for latest Harness solutions (see Market Scan Protocol below)
2. **Candidate List Update** — Add new solutions, deprecate obsolete ones, update descriptions
3. **Full Project Scan** — Complete 9-point scan per harness-assess Step 1
4. **Element Maturity Mapping** — Per harness-assess Step 2
5. **Architecture Classification** — Per harness-assess Step 3
6. **Four-Dimension Scoring** — Score ALL candidates (existing + newly discovered) per harness-assess Step 4
7. **Recommendation** — Per harness-assess Step 5
8. **Red Team Review** — Spawn Red Team agent to adversarially review the assessment (see Red Team Checkpoint below)

**Output:** Full Harness Engineering Assessment report + Red Team audit notes

**Cost:** 25-50 minutes (market scan: 8-15 min + project scan: 5-10 min + scoring: 5-10 min + Red Team review: 5-15 min). Token budget cap: if market scan finds no qualifying new candidates (4/4 filters), skip WebFetch verification and Red Team checkpoint to save ~15 min.

---

## Market Scan Protocol

Run at Tier 3 only. Searches execute in parallel where possible.

### Search Targets (6 dimensions)

| # | Dimension | Search Terms | Sources |
|---|-----------|-------------|---------|
| **S1** | Claude Code Harness Frameworks | "Claude Code harness engineering" "Claude Code workflow automation" "Claude Code agent framework 2026" | GitHub, npm, Reddit r/ClaudeCode, Anthropic forums |
| **S2** | MCP Server Ecosystem | "MCP server workflow orchestration" "MCP server agent delegation" "new MCP servers 2026" | GitHub, npm, mcp-registry, PulseMCP |
| **S3** | AI Agent Orchestration Research | "AI agent orchestration framework" "multi-agent workflow LLM" "agent harness engineering paper" | arxiv, arXiv, Google Scholar |
| **S4** | Claude Code Skills & Plugins | "Claude Code skills registry" ".claude/skills new 2026" "best Claude Code skills" | GitHub topics: claude-code, claude-code-skill; npm |
| **S5** | Competitor/Adjacent Tooling | "Cursor rules workflow" "Copilot agent workflow" "Codex CLI harness" "aider workflow" | Comparative — identify patterns to adopt or avoid |
| **S6** | Community Best Practices | "Claude Code best practices 2026" "Claude Code workflow optimization" "Claude Code large project setup" | Anthropic docs, community guides, case studies |

### Search Execution

For each dimension, run TWO searches with different query formulations:

```bash
# Example: S1 — two query variants
WebSearch "Claude Code harness engineering framework 2026"
WebSearch "Claude Code agent orchestration workflow automation latest"
```

**After all searches complete, deduplicate results by canonical URL/repo before individual evaluation.** A single solution may appear across multiple search dimensions (e.g., a workflow orchestrator appears in S1, S3, and S5). Deduplication prevents re-evaluating the same solution multiple times.

### Result Filtering Criteria

For each discovered solution, answer these 4 filter questions:

| Filter | Question | Pass Threshold |
|--------|----------|---------------|
| **F1: Freshness** | Published or significantly updated in the last 6 months? | Last commit/update >= 2025-11-01 |
| **F2: Relevance** | Does it integrate with Claude Code's ecosystem? | Must have integration path: directly via .claude/ hooks/skills/agents, OR indirectly via MCP protocol, CLI wrapping, or settings.json configuration |
| **F3: Differentiation** | Does it offer something the 5 base candidates don't? | At least 1 unique capability |
| **F4: Health** | Is the project active (not abandoned)? | Stars > 10 OR commits in last 3 months OR active npm downloads |

Solutions passing 4/4 filters → add to candidate list.
Solutions passing 3/4 → add to "watchlist" (don't score, but re-check next Tier 3).
Solutions passing <3 → discard.

### Integration with Existing Candidate List

After search, update the candidate list:

1. **Preserve base 5** — These are the reference set. They stay unless provably deprecated (repo archived, npm deprecated).
2. **Add qualified newcomers** — Append with source, key traits, best-for, signature signals (same format as base 5).
3. **Update stale entries** — If a base candidate's description is outdated, update it with current information.
4. **Deprecation log** — If a candidate is removed, log the reason and date. Don't delete — move to "Deprecated" section.

---

## Candidate List Management

### Current Candidates (Base 5)

Maintained in `harness-assess/SKILL.md` — the Five Candidate Solutions section.

### Adding a New Candidate

When a solution passes all 4 filters, add it in this format:

```markdown
### N. <solution-name>
- **Source:** `<repo-or-package-url>` (platform)
- **Key traits:** <3-5 distinctive capabilities>
- **Best for:** <project type it serves best>
- **Signature signals:** <4-6 indicators that suggest this solution is a fit>
- **Added:** <date> | **Last verified:** <date>
```

### Redundancy Check

Before adding, verify it's not a superset/subset of an existing candidate:
- If new solution ⊇ existing → replace existing with new
- If new solution ⊆ existing → skip, note as "covered by candidate X"
- If unique → add

### Candidate List Size Management

The active candidate list has a **maximum of 7 entries** (scoring more than 7 candidates on 4+ dimensions becomes LLM-expensive and dilutes result quality). When the list exceeds 7:

1. Run a "candidate tournament" — score ALL candidates (existing + newcomers)
2. The bottom-ranked candidates (lowest total score) are moved to the deprecated log
3. Exception: Base-5 candidates with a unique architecture pattern (pipeline, agent-swarm, review, safety, lean) are protected from removal to preserve architectural diversity
4. Deprecated candidates are archived from the log after 12 months

---

## Integration with Existing Workflows

### Position in Triumvirate Pipeline

The Triumvirate (Architect → Planner → Executor) is the development workflow. HGW is the meta-workflow that chooses which harness assists the Triumvirate.

```
Harness Governance (HGW)
        │
        ▼
  Harness Assessment ──→ Harness Installation
        │                      │
        ▼                      ▼
  Recommended Harness ──→ Assists Triumvirate (Opus → Sonnet → Haiku)
```

**Rule:** HGW runs BEFORE the Triumvirate for new phases. The selected harness informs how the Architect, Planner, and Executor operate.

**Mid-session rule:** If a Triumvirate cycle is already in progress when a Tier 2 trigger fires, defer harness reassessment until after the current cycle completes. Queue the reassessment as the first action before the next cycle. Never interrupt an active Architect → Planner → Executor pipeline.

**Opt-out:** At any tier, the user can say "skip harness check" to bypass governance for the current task. The skip is logged to `harness-health-log.md` with timestamp and reason (if provided).

### MRP Integration

Every Merge-Readiness Pack (MRP) at phase completion should trigger a Tier 3 re-assessment. The MRP already captures "Architecture decisions" and "Risk items" — these directly feed into the project scan and element re-evaluation.

Add to MRP template:
```
**Harness status:** <current recommendation> | <last assessment date> | <next scheduled Tier 3>
```

### Task Initiation Hook

When user starts a new task, apply this decision tree:

```
New task declared
  │
  ├─ Is this a bug fix or minor edit (<5 files)?
  │    YES → Tier 1: Quick health check
  │
  ├─ Is this a new feature or module?
  │    YES → Tier 2: Standard re-assessment
  │
  └─ Is this a phase change, architecture pivot, or project inception?
       YES → Tier 3: Full market-scanned assessment
```

---

## Red Team Checkpoint (Tier 3 Only)

After every Tier 3 assessment, spawn a Red Team agent to adversarially review:

### Review Scope

1. **Candidate Completeness:** Did the market scan miss any significant solutions? The Red Team should run independent searches to verify.
2. **Scoring Validity:** Are the D1-D4 scores defensible? Challenge each dimension.
3. **Gap Analysis:** Did the assessment correctly identify the project's gaps? Are there hidden gaps?
4. **Recommendation Soundness:** Is the winner actually the best choice? What's the strongest counter-argument?
5. **Implementation Feasibility:** Can the recommended solution actually be installed given the project's constraints?

### Red Team Execution

```bash
# Spawn Red Team with web access
Agent(
  subagent_type="red-team",
  prompt="""
    Adversarially review this Harness Assessment:
    [paste full assessment]
    
    Your tasks:
    1. Search the web for Harness Engineering solutions that might have been missed
    2. Challenge every D1-D4 score — find reasons they're too high or too low
    3. Identify failure modes if we adopt the winning solution
    4. Propose 1-2 alternative approaches not covered by any candidate
    
    You have WebSearch and WebFetch permissions. Use them.
  """
)
```

### Red Team Output Format

```markdown
# Red Team Audit: Harness Assessment <date>

## Missed Candidates
| Solution | Source | Why It Matters | Should Add? |
|----------|--------|---------------|-------------|
| ... | ... | ... | YES / WATCHLIST / NO |

## Score Challenges
| Candidate | Dimension | Assessment Score | Red Team Score | Reason |
|-----------|-----------|-----------------|----------------|--------|
| ... | ... | X/10 | Y/10 | ... |

## Failure Modes
1. **<Mode name>:** <description> — Likelihood: High/Med/Low — Impact: High/Med/Low
2. ...

## Alternative Approaches
1. **<Approach>:** <description> — Why it might be better: ...
2. ...

## Verdict
**Assessment quality:** STRONG / ADEQUATE / WEAK
**Recommendation agreement:** AGREE / AGREE WITH RESERVATIONS / DISAGREE
**Key concern:** <single most important issue>
```

### Red Team Resolution Protocol

When the Red Team verdict is **DISAGREE** or **ADEQUATE with blocking issues**:

1. **Human operator reviews both reports** (Assessment + Red Team Audit) and makes the final call
2. The disagreement, resolution, and rationale are logged to `harness-health-log.md`
3. If Red Team found missed candidates → those candidates are added and re-scored before a final recommendation is issued
4. If Red Team challenges specific scores → the challenged dimensions are re-evaluated with the Red Team's evidence in view
5. The Red Team does NOT have veto power — its role is to surface risks, not block decisions. The human operator is the final authority.

### Minimum Score Threshold

If the winning candidate scores **below 30/60**, do NOT recommend any harness installation. Instead:

1. Report: "No candidate meets the minimum fit threshold (30/60). The project's architecture may not align with available harness solutions."
2. Propose: Build a custom lightweight harness extracting patterns from the top-scoring candidates, OR re-evaluate the project's architecture before adopting any external harness.
3. Log the below-threshold result to `harness-health-log.md` with the top 3 candidates' scores.

---

## Governance Health Metrics

Track these over time to measure HGW effectiveness:

| Metric | How to Measure | Target |
|--------|---------------|--------|
| **Assessment Freshness** | Days since last Tier 3 | < 30 days |
| **Candidate List Growth** | New candidates added per quarter | 1-3 (healthy ecosystem) |
| **Winner Stability** | Consecutive assessments with same winner | > 1 but < 4 (stable but not stagnant) |
| **Gap Closure Rate** | Elements moving from 0-1 to 2-3 after harness install | >= 1 per phase |
| **Red Team Agreement** | % of Red Team reviews that AGREE with assessment | > 70% |

---

## File Manifest

| File | Purpose |
|------|---------|
| `.claude/methodology/harness-governance.md` | This document — the governance workflow |
| `.claude/skills/harness-assess/SKILL.md` | Assessment methodology + base 5 candidate list |
| `.claude/skills/harness-install/SKILL.md` | Installation procedures for each candidate |
| `.claude/methodology/harness-candidates-watchlist.md` | Watchlist (3/4 filter pass) — created by Tier 3 |
| `.claude/methodology/harness-deprecated.md` | Deprecated candidates log |
| `.claude/methodology/harness-health-log.md` | Governance health metrics history |

---

## Version History

| Version | Date | Change |
|---------|------|--------|
| 1.1.0 | 2026-05-11 | Red Team review applied — see audit report in memory |
| 1.1.0 | 2026-05-11 | Fixed C1: Added Red Team Resolution Protocol (tiebreaker + human authority) |
| 1.1.0 | 2026-05-11 | Fixed C2: Added Minimum Score Threshold (30/60 floor, NO_HARNESS option) |
| 1.1.0 | 2026-05-11 | Fixed C3: Updated Tier 3 cost to 25-50 min + token budget cap |
| 1.1.0 | 2026-05-11 | Fixed C4: Tier 1 freshness tied to MRP phase, not calendar days |
| 1.1.0 | 2026-05-11 | Fixed W1: Tier 2 trigger requires >10 files touched or new module |
| 1.1.0 | 2026-05-11 | Fixed W2/W3: Added search dedup step + broadened F2 to include MCP/CLI |
| 1.1.0 | 2026-05-11 | Fixed W4: Max 7 active candidates with tournament pruning |
| 1.1.0 | 2026-05-11 | Fixed W5/O4: Mid-Triumvirate deferral rule + explicit opt-out |
| 1.1.0 | 2026-05-11 | Scoring: D3 (Redundancy) weight increased from ×1 to ×2 per Red Team P1 |
| 1.0.0-draft | 2026-05-11 | Initial draft — awaiting Red Team review |
