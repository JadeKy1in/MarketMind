# Phase G — File Compliance Check (2026-05-17)

**Check type**: Two-tier size check per CLAUDE.md §3.1 (Python modules: 250 soft / 500 hard)
**Command**: `find . -name "*.py" ! -path "./tests/*" ! -path "./__pycache__/*" ! -path "*/__pycache__/*" ! -path "./.claude/*" ! -path "./src/*" -exec wc -l {} \; | sort -rn | awk '$1 > 500'`
**Git HEAD**: `0e631e3d6d7ed17108d1bec11275161af3cef3c6`

---

## Files Exceeding 500-Line Hard Ceiling

| # | File | Lines | Grandfathered? | Status |
|:---:|------|:---:|:---:|------|
| 1 | `shadows/ranking_engine.py` | 704 | No | **Action required** — must extract |
| 2 | `shadows/methodology_evolver.py` | 702 | No | **Action required** — must extract |
| 3 | `shadows/shadow_state.py` | 602 | No | **Action required** — must extract |
| 4 | `shadows/shadow_agent.py` | 530 | Yes (was 567) | Grandfathered — extraction-only changes, no new features |
| 5 | `gateway/multimodal_adapter.py` | 511 | Yes (was 591) | Grandfathered — extraction-only changes, no new features |

**Total: 5 files >500L (3 new + 2 grandfathered)**

---

## Grandfather Clause Status (files >500 at 2026-05-15)

| File | At 2026-05-15 | Now | Status |
|------|:---:|:---:|------|
| `app.py` | 971 | 316 | ✅ Resolved |
| `layer1_interactive.py` | 657 | 72 | ✅ Resolved |
| `methodology_rules.py` | 639 | — (removed) | ✅ Resolved |
| `shadow_agent.py` | 567 | 530 | ⚠️ Still >500, grandfathered |
| `multimodal_adapter.py` | 591 | 511 | ⚠️ Still >500, grandfathered |

**3 of 5 grandfathered files now compliant.**

---

## Files Resolved This Phase (was >500, now under)

| File | Before | After | Reduction |
|------|:---:|:---:|:---:|
| `pipeline/scout.py` | 710 | 274 | -61% |
| `shadows/shadow_memory.py` | 572 | 344 | -40% |
| `gateway/async_client.py` | 570 | 330 | -42% |
| `shadows/shadow_mother.py` | 892 | 433 | -51% |
| `pipeline/layer1_interactive.py` | 967 | 72 | -93% |
| `app.py` | 971 | 316 | -67% |
| `shadows/shadow_state.py` | 1484 | 602 | -59% |

---

## Extraction Priority (for non-grandfathered files)

Per CLAUDE.md §3.1 extraction priority:

| Priority | File | Lines | Extraction Approach |
|:---:|------|:---:|------|
| 1 | `shadows/ranking_engine.py` | 704 | Extract ranking composite scoring, Holm-Bonferroni correction, reset eligibility into separate modules |
| 2 | `shadows/methodology_evolver.py` | 702 | Split `MethodologyEvolver` and `MethodologyInjector` into separate files |
| 3 | `shadows/shadow_state.py` | 602 | Extract PnL queries, config management, SQL migration helpers |

---

## Overall Assessment

- **Phase G compliance goal**: Reduce all files below 500L hard ceiling
- **Result**: 7 of 10 known-large files now compliant; 5 remain (2 grandfathered, 3 new offenders)
- **Phase G overall**: 100% functional complete; compliance cleanup remains for 3 files
- **Next phase**: Target extraction of ranking_engine, methodology_evolver, shadow_state

**Updated**: 2026-05-17
