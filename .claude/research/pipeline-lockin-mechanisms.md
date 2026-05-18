# Pipeline Lock-In Mechanisms: Research Findings

**Date**: 2026-05-17
**Purpose**: Concrete, implementable mechanisms to prevent pipeline architecture from being lost across AI sessions and developer rotations.

---

## Problem Statement

MarketMind has a multi-step pipeline. Previous sessions have lost track of the correct pipeline because:
1. Multiple conflicting documents exist (CONTEXT-MAP.md, CLAUDE.md, phase docs, progress files)
2. AI agents reconstruct the pipeline from code and get it wrong
3. Design decisions made in conversation aren't documented
4. CLAUDE.md files get stale

---

## 1. Architecture Decision Records (ADR)

### Recommended Format: Nygard ADR (Minimalist)

Empirical research (arXiv:2604.27333, April 2026) compared five ADR templates. **Nygard** scored highest for comprehension and usability. **MADR** excels when structured alternatives and explicit pros/cons are needed.

**Nygard template** (5 sections, 2-5 paragraphs total):

```markdown
# ADR-NNNN: Title

## Status
Proposed | Accepted | Deprecated | Superseded

## Context
[Forces at play — technical, political, social, project-local]

## Decision
We will [active voice, imperative]

## Consequences
- (+) [positive]
- (-) [negative — always include trade-offs honestly]
```

### Key Rules

1. **Store with source code** in `docs/adr/` (never Confluence/SharePoint — "graveyard storage")
2. **Append-only immutability**: Never edit accepted ADRs. If a decision changes, write a new ADR that supersedes the old one and link them.
3. **Number sequentially**: `ADR-0001-title.md`, never reuse numbers.
4. **Track status lifecycle**: Proposed -> Accepted -> Deprecated -> Superseded
5. **One ADR = one decision**: If multi-phase, write one per phase.

### Application to MarketMind

Create `projects/marketmind/docs/adr/` with:
- `README.md` — index table of all ADRs with status
- `template.md` — Nygard template
- `ADR-0001-pipeline-phases.md` — the authoritative pipeline definition
- `ADR-0002-data-isolation-boundary.md` — anti-overfitting rule
- One ADR per architectural decision made in conversation

**Enforcement**: When an architecture decision is made in conversation, immediately write an ADR. No ADR = decision doesn't exist.

---

## 2. Pipeline-as-Code Documentation

### Machine-Parseable Pipeline Definition

Instead of prose in CLAUDE.md, define the pipeline as a **machine-parseable YAML/JSON manifest** that both humans and AIs can read deterministically.

**Recommended format**: `pipeline-manifest.yaml`

```yaml
# projects/marketmind/pipeline-manifest.yaml
# Canonical pipeline definition — single source of truth.
# NEVER edit by hand after phase definition; changes require an ADR.

schema: "pipeline-manifest-v1"
pipeline: "marketmind-daily"
phases:
  - id: "scout"
    name: "Market Scout"
    order: 1
    entry_point: "pipeline/scout.py"
    entry_function: "run_scout"
    dependencies: []
    produces: ["raw_signals"]
    consumes: []

  - id: "ranking"
    name: "Signal Ranking"
    order: 2
    entry_point: "shadows/ranking_engine.py"
    entry_function: "rank_signals"
    dependencies: ["scout"]
    produces: ["ranked_signals"]
    consumes: ["raw_signals"]

  - id: "position_patrol"
    name: "Position Patrol"
    order: 3
    entry_point: "pipeline/position_patrol.py"
    entry_function: "patrol_positions"
    dependencies: ["ranking"]
    produces: ["position_alerts"]
    consumes: ["ranked_signals"]

  - id: "decision"
    name: "Decision Engine"
    order: 4
    entry_point: "decision.py"
    entry_function: "make_decision"
    dependencies: ["position_patrol"]
    produces: ["final_decision"]
    consumes: ["position_alerts"]

orchestrator:
  entry_point: "app.py"
  entry_function: "run_daily"
  phase_order: ["scout", "ranking", "position_patrol", "decision"]

verified_at: "2026-05-17T00:00:00Z"
```

### Why This Works

| Property | How Achieved |
|----------|---------------|
| **Machine-parseable** | YAML with defined schema — AIs read it deterministically, no prose-to-structure guesswork |
| **Self-verifying** | A script checks `entry_point` paths exist, `entry_function` names are importable, `dependencies` match actual imports |
| **Immutable** | Phase definitions change only via ADR; verifiable via git blame on each key |
| **Single source** | Every other doc (CLAUDE.md, CONTEXT-MAP.md) references this file, never duplicates |

### Verification Script

```python
# .claude/scripts/verify_pipeline.py
"""Verify that pipeline-manifest.yaml matches actual code."""
import yaml, importlib, sys
from pathlib import Path

def verify(manifest_path: str, project_root: str):
    with open(manifest_path) as f:
        manifest = yaml.safe_load(f)
    
    root = Path(project_root)
    errors = []
    
    for phase in manifest["phases"]:
        # Check entry_point exists
        ep = root / phase["entry_point"]
        if not ep.exists():
            errors.append(f"Phase '{phase['id']}': entry_point '{phase['entry_point']}' not found")
            continue
        
        # Check entry_function is importable
        try:
            mod = importlib.import_module(phase["entry_point"].replace("/", ".").replace(".py", ""))
            if not hasattr(mod, phase["entry_function"]):
                errors.append(f"Phase '{phase['id']}': function '{phase['entry_function']}' not in {phase['entry_point']}")
        except ImportError as e:
            errors.append(f"Phase '{phase['id']}': cannot import {phase['entry_point']}: {e}")
    
    if errors:
        print(f"PIPELINE VERIFICATION FAILED ({len(errors)} errors):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    
    print(f"PIPELINE VERIFICATION PASSED: {len(manifest['phases'])} phases verified")
    
if __name__ == "__main__":
    verify("projects/marketmind/pipeline-manifest.yaml", "projects/marketmind")
```

---

## 3. CLAUDE.md Best Practices for AI Drift Prevention

### Core Philosophy: Constrain, Don't Describe

> "The README documents. The CLAUDE.md constrains."

Every line should be **actionable**: "always X", "never Y", "when X then Y". Descriptive lines that an AI can discover from config files or grepping the codebase should be removed.

| Good | Bad |
|------|-----|
| "Always import pipeline phases from `pipeline-manifest.yaml`, never hardcode phase order" | "The frontend uses Recharts for data visualization" |
| "Never connect to brokerage APIs. Price data is a timing filter, not a signal source." | "We try to write good code." |

### Only Encode What Agents Cannot Discover

If information already exists in `package.json`, `tsconfig.json`, CI workflows, or config files — do NOT repeat it. Redundancy costs ~20% more inference tokens and reduces task success by ~3%.

**Include** (tribal knowledge):
- Non-obvious gotchas and past mistakes
- Architectural constraints not in code
- Business rules agents can't infer
- Security conventions not enforced by tooling

**Exclude** (already discoverable):
- Build/test/lint commands
- Code style rules enforced by linters
- Directory trees
- Deployment steps

### Drift Prevention: 7 Practices

1. **Post-hoc, not speculative**: Only add rules after an agent gets something wrong.
2. **Version stamp**: Use frontmatter with `last_reviewed` date. Stale date signals caution.
3. **Cite the incident**: Each rule carries error code, date, what crashed.
   ```
   - Never use createSupabaseServer in Server Components (2025-03-25, RLS silently returned zero rows)
   ```
4. **Single source of truth**: Author rules once in a directory like `.agents-doc/`, then compile to each agent's format. Never edit generated files directly.
5. **Regular pruning**: Re-read every 15 days. If a rule hasn't been invoked in a month, archive or rewrite.
6. **Never auto-generate**: Research shows self-generated procedures = -1.3pp vs human-curated = +16.2pp.
7. **Progressive disclosure**: Keep always-loaded context under ~70 lines. Load specialized context on demand.

### Application to MarketMind

Current `CLAUDE.md` should be restructured:

1. **Always-loaded (~50 lines)**: Pipeline reference, hard constraints, gotchas
2. **On-demand**: Phase details, architecture decisions, data schemas
3. **Key line to add**:
   ```
   ## Pipeline
   The canonical pipeline is defined in `pipeline-manifest.yaml`.
   NEVER hardcode phase order or entry points. Read from the manifest.
   ```

---

## 4. Single Source of Truth Pattern

### The Pattern: One Authoritative File, Everything Else Links

```
pipeline-manifest.yaml    ← SINGLE SOURCE OF TRUTH (all phase definitions)
                           ↑
CLAUDE.md                  ← Links to it: "Pipeline defined in pipeline-manifest.yaml"
CONTEXT-MAP.md             ← Links to it: "See pipeline-manifest.yaml"
docs/adr/README.md         ← Links to it: "Current pipeline: pipeline-manifest.yaml"
progress files             ← Reference phase names from manifest, not copied definitions
```

### Rules

1. **Link, don't duplicate**: Every secondary document references the SSOT file, never copies its content.
2. **Update SSOT first**: Changes to the pipeline start at `pipeline-manifest.yaml`, then links are verified.
3. **CI verifies**: A script checks that manifests match actual code (see Section 5).
4. **Git hooks enforce**: Pre-commit hook ensures `pipeline-manifest.yaml` is updated when pipeline code changes (see Section 6).

### Dual-Document Approach (from Microsoft Amplifier)

| File | Purpose | Audience |
|------|---------|----------|
| `pipeline-manifest.yaml` | **Machine-readable** fact store — phases, entry points, dependencies, order | CI verifiers, AI agents, generators |
| `docs/ARCHITECTURE.md` | **Human-readable** narrative — rationale, diagrams, ADR summaries | Developers, stakeholders |

Never duplicate information between them. YAML is the source; Markdown derives from it.

### Anti-Patterns

- Having a "Pipeline Overview" section in 3+ files with slightly different content
- Documenting phase order in CLAUDE.md AND CONTEXT-MAP.md AND progress files
- AI agents reconstructing the pipeline from `app.py` imports instead of reading the manifest

---

## 5. Automated Verification Mechanisms

### Architecture Comparison: Hybrid Pipeline

The research consensus: combine **deterministic static analysis** (filters out 99% of issues) with **LLM-powered verification** (handles nuanced semantic checks).

```
Source code → Static checks (regex/AST) → Filter false positives → LLM review → Report → Gate
```

### Verification Script: Doc-vs-Code Consistency Check

```python
# .claude/scripts/verify_docs_match_code.py
"""
Verify that documented pipeline steps match actual code.

Checks performed (deterministic, runs in <1s):
1. Every phase in manifest has an existing entry_point file
2. Every phase in manifest has an importable entry_function
3. Every import in the orchestrator (app.py) that looks like a phase
   is documented in the manifest
4. Manifest phase order matches orchestrator call order
5. No undocumented phase files (pipeline/*.py not in manifest)

Exit code 0 = everything matches. Exit code 1 = discrepancy found.
"""
import yaml, ast, sys
from pathlib import Path

# ... implementation as above, plus reverse checks
```

### DocAlign Pattern (from npm `docalign` tool)

A dedicated tool that:
1. **Extracts verifiable claims** from documentation (file paths, function names, CLI commands, behavioral assertions)
2. **On commit**, reverse-looks up which claims reference changed files
3. **Re-verifies only affected claims** — fast incremental check

Three confidence tiers:
- **Tier 1 (auto/deterministic)**: `file_ref`, `config_default`, `env_var`, `cli_command`, `symbol_ref`
- **Tier 2 (semi-auto)**: `version_req`, dependency pinning
- **Tier 3 (LLM-powered)**: `behavior`, `constraint`, architecture assertions

### Integration into PICA Protocol

The PICA protocol already verifies code correctness. Add a pre-PICA step:

```
pipeline-manifest.yaml changed?
  → Run verify_docs_match_code.py (deterministic, ~1s)
  → If fail: fix before proceeding to PICA-Unit
  → Then: PICA-Unit → PICA-Security → PICA-Integration → PICA-Regression
```

---

## 6. Git Hooks for Documentation Enforcement

### Pre-Commit Hook: Verify Pipeline Documentation Matches Code

Save as `.githooks/pre-commit` (or configure via `pre-commit` framework):

```bash
#!/usr/bin/env bash
# .githooks/pre-commit
# Enforce: when pipeline code changes, manifest must be updated too.

set -euo pipefail

MANIFEST="projects/marketmind/pipeline-manifest.yaml"
PIPELINE_DIR="projects/marketmind/pipeline"
STAGED_FILES=$(git diff --cached --name-only)

# Only check if pipeline code is staged
if echo "$STAGED_FILES" | grep -q "^$PIPELINE_DIR/"; then
    echo "==> Pipeline code staged. Verifying manifest is up to date..."

    # 1. Check manifest is also staged (or already committed)
    if ! echo "$STAGED_FILES" | grep -q "^$MANIFEST$"; then
        echo "ERROR: Pipeline code changed but '$MANIFEST' is NOT staged."
        echo "       Update the manifest and stage it before committing."
        echo "       Run: python .claude/scripts/verify_pipeline.py"
        exit 1
    fi

    # 2. Run verification script
    if ! python .claude/scripts/verify_pipeline.py; then
        echo ""
        echo "ERROR: Pipeline verification failed. See errors above."
        echo "       Fix discrepancies before committing."
        exit 1
    fi

    echo "==> Pipeline manifest verification passed."
fi

# Always run: check that CLAUDE.md last_reviewed is recent
if echo "$STAGED_FILES" | grep -q "CLAUDE.md$"; then
    LAST_REVIEWED=$(grep "last_reviewed:" CLAUDE.md 2>/dev/null || echo "MISSING")
    if [[ "$LAST_REVIEWED" == "MISSING" ]]; then
        echo "WARNING: CLAUDE.md has no 'last_reviewed' date in frontmatter."
        echo "         Consider adding: last_reviewed: $(date +%Y-%m-%d)"
    fi
fi

exit 0
```

### Pre-Commit Framework Configuration (`.pre-commit-config.yaml`)

For teams using the `pre-commit` framework:

```yaml
repos:
  - repo: local
    hooks:
      - id: verify-pipeline-manifest
        name: Verify pipeline manifest matches code
        entry: python .claude/scripts/verify_pipeline.py
        language: python
        files: ^projects/marketmind/(pipeline/|pipeline-manifest\.yaml)
        stages: [commit]
        pass_filenames: false

      - id: check-claude-md-freshness
        name: Check CLAUDE.md freshness
        entry: python .claude/scripts/check_claude_md_freshness.py
        language: python
        files: ^(CLAUDE\.md|projects/marketmind/CLAUDE\.md)$
        stages: [commit]
        pass_filenames: false
```

### Install Hooks

```bash
# Option A: Git native
git config core.hooksPath .githooks

# Option B: pre-commit framework
pip install pre-commit && pre-commit install
```

### Defense in Depth: Hooks + CI

Hooks can be bypassed with `--no-verify`. CI acts as the secondary enforcement layer:

```yaml
# .github/workflows/verify-pipeline.yml
name: Verify Pipeline Documentation
on: [push, pull_request]
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Verify pipeline manifest
        run: python .claude/scripts/verify_pipeline.py
      - name: Check CLAUDE.md freshness
        run: python .claude/scripts/check_claude_md_freshness.py
```

---

## Implementation Plan for MarketMind

### Immediate (This Phase)

1. **Create `pipeline-manifest.yaml`** in `projects/marketmind/` with the current pipeline phases.
2. **Update `CLAUDE.md`** to reference the manifest instead of describing the pipeline inline. Add `last_reviewed:` frontmatter.
3. **Create `.claude/scripts/verify_pipeline.py`** — the verification script.
4. **Run the verification script once** to ensure current code matches current understanding.

### Short-Term (Next 1-2 Sessions)

5. **Create `docs/adr/`** with template and first ADR (pipeline phases).
6. **Install pre-commit hook** (`.githooks/pre-commit`) that:
   - Requires `pipeline-manifest.yaml` to be staged when pipeline code changes
   - Runs `verify_pipeline.py` on commit
7. **Add CI workflow** for secondary enforcement.

### Ongoing

8. **ADR for every architecture decision** made in conversation. Before closing a session with a design decision, write the ADR.
9. **Monthly CLAUDE.md pruning**: remove rules that haven't been invoked.
10. **Progressive disclosure**: keep always-loaded CLAUDE.md under 50 lines; load specialized docs on demand.

---

## Summary of Mechanisms

| Mechanism | What It Solves | Effort |
|-----------|---------------|--------|
| `pipeline-manifest.yaml` | Machine-parseable SSOT that AIs read deterministically | Low (~30 min to create) |
| `verify_pipeline.py` | Self-verifying — catches drift automatically | Low (~50 lines of Python) |
| ADR directory (`docs/adr/`) | Design decisions survive conversation | Low (template + workflow) |
| Pre-commit hook | Enforces manifest updates when code changes | Low (~20-line bash script) |
| `CLAUDE.md` restructuring | Prevents AI drift with actionable constraints | Medium (~1 hr refactor) |
| Progressive disclosure | Keeps context focused; layers on demand | Medium (split existing CLAUDE.md) |
| CI verification workflow | Defense-in-depth if hooks are bypassed | Low (5-line GitHub Action) |

### Key Principle

**The pipeline is defined in ONE place that is BOTH human-readable AND machine-parseable.** Everything else references that place. Any deviation is caught by automated verification before it reaches a commit.

---

Sources:
- [Architecture Decision Record (ADR) Examples](https://github.com/joelparkerhenderson/architecture-decision-record)
- [One Size Fits All? ADR Template Comparison](https://arxiv.org/html/2604.27333v1)
- [Maintain ADR — Microsoft Well-Architected Framework](https://learn.microsoft.com/en-us/azure/well-architected/architect-role/architecture-decision-record)
- [4 Incidents, 4 Rules: How My CLAUDE.md Wrote Itself](https://dev.to/michelfaure/4-incidents-4-rules-how-my-claudemd-wrote-itself-o3n)
- [Writing a Good CLAUDE.md](https://dev.to/0xmariowu/writing-a-good-claudemd-mck)
- [Stop Writing CLAUDE.md From Scratch](https://dev.to/t3chn/stop-writing-claudemd-from-scratch-2fgm)
- [Single Source of Truth: Definition, Examples & Best Practices](https://www.docsie.io/blog/glossary/single-source-of-truth/)
- [Microsoft Amplifier Repository Rules](https://github.com/microsoft/amplifier/blob/main/docs/REPOSITORY_RULES.md)
- [RipStop: Git Hook Guardrails for AI-Assisted Development](https://github.com/jonverrier/RipStop)
- [Deterministic Verification for CI Security Decisions (Nono-Gate)](https://dev.to/88nonogdev/deterministic-verification-for-ci-security-decisions-introducing-nono-gate-2k87)
- [Receipt Chain Architecture (Signum)](https://github.com/heurema/signum/issues/7)
- [FlowSpec: Lightweight JSON Schema for Workflows](https://github.com/woodyhayday/FlowSpec)
- [docalign: Documentation-vs-Code Verification](https://www.npmjs.com/package/docalign)
