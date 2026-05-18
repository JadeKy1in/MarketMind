# Cleanup Audit — Safe-to-Delete Files

**Date**: 2026-05-18
**Scope**: 7 categories of potentially redundant files in the workspace

---

## SAFE TO DELETE

| File | Reason | Risk |
|------|--------|------|
| `E:\AI_Studio_Workspace\.clinerules` (37KB) | Old Cline SPARC/Matrix config, replaced by CLAUDE.md. No `.py`, `.bat`, `.sh`, or `.ps1` file references it. Only stale `.md` docs mention it. | Low |
| `E:\AI_Studio_Workspace\projects\marketmind\.clinerules` (37KB) | Identical duplicate of workspace `.clinerules`. Same rationale. | Low |
| `E:\AI_Studio_Workspace\projects\marketmind\E:AI_Studio_Workspaceprojectsmarketmind_run_test.bat` | Already deleted — does not exist on disk | None |
| `E:\AI_Studio_Workspace\E:AI_Studio_Workspaceprojectsmarketmind_run_test.bat` | Already deleted — does not exist on disk | None |
| `E:\AI_Studio_Workspace\.claude\worktrees\agent-*` (9 dirs, ~39K files each) | Agent worktrees from May 14-17, all LOCKED (completed). Code commits (`875a767a`) already on master. Branches contain only docs/restart-guide updates. Use `git worktree remove --force` for proper cleanup (not rm -rf). | Low |
| `E:\AI_Studio_Workspace\projects\marketmind\.claude\` (entire directory) | May 17 snapshot, superseded by workspace `.claude/`. The `settings.local.json` is a subset of workspace settings (missing ~55 lines). Plans dir has 2 files (`phase-d-shadow-completion.md`, `phase-f-shadow-ecology-v1.md`) already deleted from workspace. Audits dir has old `phase-c-batch3/`. All other files exist in newer form in workspace `.claude/`. | Low |
| `E:\AI_Studio_Workspace\projects\marketmind\node_modules\` (210MB) | npm dependencies, fully recoverable via `npm install` from the existing `package-lock.json`. Contains only published packages. | Low |
| `E:\AI_Studio_Workspace\projects\marketmind\data\batches.jsonl` (0 bytes) | Empty placeholder, no Python code references it. | None |
| `E:\AI_Studio_Workspace\projects\marketmind\data\predictions.jsonl` (0 bytes) | Empty placeholder, no Python code references it. | None |
| `E:\AI_Studio_Workspace\projects\marketmind\data\verdicts.jsonl` (0 bytes) | Empty placeholder, no Python code references it. | None |

---

## DO NOT DELETE

| File | Why it's needed |
|------|-----------------|
| `E:\AI_Studio_Workspace\.claude\` (workspace) | Active configuration, plans, audits, hooks. This is the authoritative `.claude/` directory. |
| `E:\AI_Studio_Workspace\CLAUDE.md` | Active project instructions, loaded by Claude Code on every session. |
| `E:\AI_Studio_Workspace\projects\marketmind\CLAUDE.md` | Active MarketMind-specific instructions. |

---

## NEEDS USER DECISION

| File | Why unclear |
|------|------------|
| `E:\AI_Studio_Workspace\projects\marketmind\projects\ro` (347 lines, tracked in git) | Garbled filename — this is actually `sentiment_collector.py` (a complete Python module for fetching sentiment data from Truth Social/CapitolTrades). **Only copy** in the repo — no `sentiment_collector.py` exists elsewhere. Not imported by any other Python file. Either: (a) rename to `sentiment_collector.py` and place in `pipeline/`, (b) delete if the feature is abandoned. |
| `E:\AI_Studio_Workspace\projects\marketmind\package.json` + `package-lock.json` + `jest.config.js` (project root) | These define a real TypeScript project (`@ai-studio/browser-automation-adapter`) with source in `src/`. It is a browser automation adapter for Playwright MCP tools — completely unrelated to the MarketMind Python pipeline. No Python code references it. However, `src/` contains ~36KB of TypeScript source across 3 files (`adapter.ts`, `coverage-analyzer.ts`, `types.ts`) plus tests. Either: (a) this is a separate tool the user maintains; keep it, (b) it's abandoned scaffolding; delete everything including `src/`. |
| `E:\AI_Studio_Workspace\projects\marketmind\src\` (TypeScript source, ~36KB) | See above. Part of the browser-automation-adapter project. Has `tsconfig.json`, test files, and `coverage/` output. |
| `C:\Users\Administrator\.cline\worktrees\d98d4\` (old Cline worktree) | Listed by `git worktree list` as "prunable" — from the old Cline tool (not Claude Code). Outside the workspace scope but on the same git repo. Can be cleaned up with `git worktree prune`. |

---

## Notes

1. **Worktree cleanup**: The 9 agent worktrees must be removed via `git worktree remove --force <path>` (not `rm -rf`) to properly clean up both the directory and the associated branches. Branches named `worktree-agent-*` contain only docs commits; no code would be lost.

2. **Project `.claude/` deletion**: Before deleting, verify no agent/runtime reads `.claude/` from the project working directory instead of the workspace root. The `settings.local.json` in project `.claude/` is a strict subset of workspace settings, so no permissions would be lost.

3. **Node.js project**: If the TypeScript browser-automation-adapter is still needed, only delete `node_modules/` (recoverable). Keep `package.json`, `package-lock.json`, `jest.config.js`, `tsconfig.json`, and `src/`.

4. **Empty `.jsonl` files**: These appear to be pre-created placeholders for Phase I prediction tracking. No code currently writes to or reads from them, but future Phase I code might expect the files to exist at those paths. Check `pipeline/entity_memory.py` and `pipeline/calibration_tracker.py` for expected file paths before deleting.
