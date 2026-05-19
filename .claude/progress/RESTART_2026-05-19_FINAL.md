# Restart Guide — 2026-05-19 Final

**Read FIRST. Pre-session check BEFORE code.**

---

## 0. Launch

```bash
# Double-click: D:\Claude Code\Claude Code.bat
# OR terminal: claude --effort max
```

Pre-session validator runs automatically. Expected output:
```
Plugins enabled: 5
Plugin files OK: 5/5
Sandbox pending: 0
Errors: 0
Ready to launch Claude Code.
```

SessionStart report (appears after launch):
```
STARTUP HEALTH REPORT
  Time anchor:     OK
  Plugins active:  5 (superpowers, mattpocock-skills, feature-dev, claude-hud, andrej-karpathy-skills)
  MCP servers:     4 (context7, github, chrome-devtools, figma-developer)
  Agent Teams:     ENABLED
  All systems operational. Ready.
```

---

## 1. Skills Verification

After launch, verify in Skill tool list:

- [ ] Superpowers: brainstorming, writing-plans, executing-plans, TDD, debugging, verification-before-completion
- [ ] Mattpocock: triage, diagnose, tdd, architecture, caveman, grill-me, handoff
- [ ] feature-dev: feature-dev (for non-MarketMind projects only)
- [ ] find-skills: find-skills
- [ ] frontend-design: frontend-design (Anthropic)
- [ ] vercel-react-best-practices
- [ ] parallel-feature-development
- [ ] Karpathy: karpathy-guidelines

If skills missing: `claude mcp list` and `npx skills list` to diagnose.

---

## 2. MCP Check

```bash
claude mcp list
```

Expected: `context7`, `github`, `chrome-devtools` = Connected. `figma-developer` = optional.

---

## 3. Quick Pipeline Check

```bash
cd E:\AI_Studio_Workspace\projects\marketmind
python -m pytest tests/ -q --tb=no
# Expected: ~1302 pass
```

---

## 4. Current State

### Pipeline: 10/10 stages, 1302 tests

| Fixed today (9 bugs) | |
|------|------|
| Flash JSON trailing comma + max_tokens 4096→8192 |
| Flash reasoning_effort max→minimal |
| Flash direction/confidence/event_type for HVR |
| Red Team + Causal/Flow + Investigation JSON trailing comma |
| Layer 3 None-safe float + Layer 1 EST: prefix |
| Pre-Act planner headline gap |
| Shadow DB 31→24 cleanup |
| 17+ JSON parse sites hardened |

### Fixture System: operational
- 7 tests in 0.20s, 3 synthetic fixtures
- `load_fixture("stage1_scout")` → feed to flash_triage in isolation
- Sub-chain debugging: load A's fixture → run B→C→D only

### Skills: 5 plugins (35 skills) + 5 MCP

| Plugin | Skills |
|------|:---:|
| Superpowers v5.1.0 | 13 |
| Mattpocock v1.0.0 | 15 |
| Karpathy v1.0.0 | 1 |
| feature-dev | 1 |
| Claude HUD | 1 |

| MCP | Status |
|------|:---:|
| Context7 | ✓ |
| GitHub | ✓ |
| Chrome DevTools | ✓ |
| Figma Developer | ⚠️ connect issue — troubleshoot later |

### Today's Commits

```
0a4e7020 fix: pre_session.py detect /plugin-installed plugins
9f098a8d fix: Red Team final — 8 findings resolved
b0e7f8d9 fix: config_guardian skill-creator→feature-dev, plan
bbfeb5ec feat: startup_report.py + SessionStart hook chain
f259ac8e chore: remove stale web-design-guidelines
e2a653c4 feat: workspace flow plan + PreCompact + Context7 + skills
... (19 total commits today)
```

---

## 5. Pending Tasks (after restart)

| Priority | Task | Note |
|:---:|------|------|
| **#1** | Shadow system design discussion | Fade Master redesign + 16E/8D audit |
| **#2** | Political sentiment tracking | Restore from archive, integrate |
| **#3** | Figma MCP troubleshoot | Token validation or proxy issue |
| **#4** | Fixture Phase 2 real data | Needs pipeline run → regenerate_all() |
| **#5** | Skill profiling (1 week) | Check which of 35 skills actually trigger |
| **#6** | CLAUDE.md [GLOBAL-IMMUTABLE] tags | Tag root rules as immutable or overridable |

---

## 6. Periodic Checks

| Check | Frequency | Command |
|------|:---:|------|
| Skill updates | Weekly | `npx skills update` |
| Plugin staleness | Auto | pre_session.py warns at 30d, blocks at 60d |
| Figma token expiry | 90 days | Regenerate at figma.com → Settings → Security |
| Full pipeline | Before commit | `python app.py --mode daily --mock --verbose` |

---

## 7. Workflow After Restart

```
Session starts
  → Startup Report (confirm all green)
  → Task discovery: Skill("mattpocock-skills:productivity/grill-me")
  → Planning: Skill("superpowers:brainstorming")
  → Implementation: Agent Team (Architect→Builder→Red Team×2)
  → PICA: Unit→Security→Integration→Regression
  → Verify: Skill("superpowers:verification-before-completion")
  → Commit
```

---

**Updated**: 2026-05-19 12:35 UTC
