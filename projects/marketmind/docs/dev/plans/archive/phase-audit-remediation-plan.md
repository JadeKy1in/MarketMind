# Plan: Phase Audit & Remediation (Pre-Phase G) — v2

Red Team reviewed. Key fix: document forensics before user recall.

## WHY

After autonomous-dev cleanup, Phase A-F code exists but was never systematically audited against intended functionality. Phase G must not build on unverified ground.

## SCOPE

### Phase 0: Foundation (1 session)
- [x] Agent Team definitions verified (8 agents, AGENTS.md intact)
- [x] Red Team model upgraded: Haiku → Opus (maximum depth for adversarial audit)
- [ ] Skills verification: invoke one mattpocock skill + one superpowers skill to confirm global installation works
- [ ] Workflow dry-run: run a mock audit on a trivial module to validate the protocol
- [ ] Commit foundation state

### Phase 1: Document Forensics (1 session, no user recall needed)
Before asking the user anything, reconstruct each phase's intended design from EXISTING evidence:

For each phase (A→F), extract:
1. Commit messages and their scope claims
2. Handoff documents in `.claude/handoffs/`
3. Plan files in `.claude/plans/`
4. Audit reports in `.claude/audits/` (Red Team + Scout)
5. CLAUDE.md evolution (what rules were added when)
6. Code structure: what modules exist, what they import/export
7. Test files: what's tested, what's not, test names as behavioral claims

Produce a **Forensic Design Reconstruction** (FDR) per phase — a one-page summary of "this is what the evidence says Phase X was supposed to do."

### Phase 2: Intent Verification (1-2 sessions, user confirms/refutes FDR)
For each phase:
1. Present the FDR to the user: "Here's what the evidence says Phase A was building. Is this right?"
2. User confirms or corrects: "Yes, but you missed X" or "No, Y was never part of it"
3. I update the EXPECTED map based on user input
4. I compare EXPECTED vs ACTUAL (code audit)
5. Red Team challenges gaps: "did you consider Z?"
6. Gap report: MATCH / PARTIAL / MISSING / OVERBUILT
7. User decides: FIX-NOW / FIX-LATER / WONTFIX / DEFER-TO-G

### Phase 3: Prioritized Remediation (N sessions, parallel where possible)
- Sort gaps by impact × effort
- Parallel agent teams fix independent gaps
- Each fix gate: implement → test pass → Red Team sign-off → commit
- All HIGH gaps resolved before Phase G

### Phase 4: Phase G Ready
- Foundation verified
- Phase G development begins with clean baseline

## Audit Order: Criticality, Not Chronology

| Order | Phase | Why First |
|-------|-------|-----------|
| 1 | **B** (Shadow Core) | Core engine. If shadow agents/votes/ranking are wrong, everything built on top is suspect. |
| 2 | **C** (Pipeline) | Production pipeline. 339 tests exist — verify they test the right things. |
| 3 | **A** (Foundation) | Agent definitions + project structure. Mostly verified already in Phase 0. |
| 4 | **D** (Shadow Completion) | Enhancements on B+C. Lower risk. |
| 5 | **F** (Shadow Ecology) | Newest code. Scout report already identified process gaps. |
| 6 | **E** (Infrastructure Fixes) | Plan exists but no commits. Verify: intentionally skipped or lost work? |

## Workflow Protocol

### Pre-Flight (every session)
1. `using-superpowers` — skill check before any action
2. Verify working directory is repo root (`E:/AI_Studio_Workspace`)
3. No hooks active (settings.local.json is hook-free)

### Per-Phase Audit
```
FORENSICS (Phase 1)           USER VERIFICATION (Phase 2)        REMEDIATION (Phase 3)
─────────────────            ─────────────────────────        ─────────────────────
Mine docs/commits/code   →    Present FDR to user          →   Fix HIGH gaps first
Produce FDR (1 page)          User confirms/corrects           Parallel where possible
Identify evidence gaps         I run code audit                Each fix: test + commit
                               Red Team challenges             Red Team gate per fix
                               Gap report produced             Scout tracks rework
                               User decides priority
```

### Severity Classification
| Label | Definition | Action |
|-------|-----------|--------|
| CRITICAL | Would cause wrong investment signal or data loss | FIX-NOW |
| HIGH | Missing functionality claimed in plan/commit | FIX-NOW |
| MEDIUM | Works but not as intended, or overbuilt | FIX-LATER |
| LOW | Cosmetic, naming, unused code | WONTFIX or cleanup |

## Skills-to-Agent Mapping

| Agent | Primary Skills | When |
|-------|---------------|------|
| Architect | `brainstorming`, `writing-plans`, `grill-with-docs` | Design & planning |
| Quant Analyst | `grill-me`, `scientific-validation` | Investment logic audit |
| Data Engineer | `diagnose`, `systematic-debugging` | Data pipeline fixes |
| UI Engineer | `prototype` | UI verification |
| Builder | `tdd`, `test-driven-development`, `verification-before-completion` | Implementation |
| Red Team (Sonnet) | `grill-me`, `security-review`, `receiving-code-review` | Audit & challenge |
| Optimization Scout | `improve-codebase-architecture`, `zoom-out` | Process health |

## Success Criteria
- [ ] Skills verified working (1 mattpocock + 1 superpowers invocation test)
- [ ] Forensic Design Reconstructions for phases A-F
- [ ] User intent confirmed for each phase
- [ ] Gap reports with severity classification
- [ ] All CRITICAL + HIGH gaps resolved
- [ ] All fixes committed with passing tests
- [ ] Phase G ready to start
