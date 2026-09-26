# Pipeline Test Fixture System — Solution Plan

**Status**: RED_TEAM_FIXES_APPLIED — ready for implementation
**Date**: 2026-05-19
**Red Team**: Audited 2026-05-19 01:15 UTC — 2 CRITICAL, 2 HIGH, 2 MEDIUM, 2 LOW → all fixed
**Based on**: External research on Golden File / Snapshot Testing best practices

## 1. Problem

Running `--mode daily` takes 5+ minutes. Debugging Stage N requires re-running Stages 1..N-1.
Bug-fix cycles waste hours on redundant upstream computation.

## 2. Solution: Per-Stage JSON Fixtures

### Architecture

```
test_fixtures/
  ├── README.md                  # Usage + regeneration instructions
  ├── stage1_scout/
  │   ├── normal_output.json     # Representative 349-article batch
  │   └── metadata.json          # Created: date, source_version, pipeline_version
  ├── stage2_flash_triage/
  │   ├── normal_25items.json
  │   └── edgecase_empty.json
  ├── stage2b_hvr/
  ├── stage3_l1/
  ├── stage4_l2l3/
  ├── stage5_shadows/
  ├── stage6_redteam/
  ├── stage7_resonance/
  ├── stage8_decision/
  └── stage9_archive/
```

### Core API

```python
# test_fixtures/__init__.py
def load_fixture(stage: str, name: str = "normal") -> dict | list:
    """Load a stage's output fixture. Raises FixtureStaleError if >7 days old."""

def save_fixture(stage: str, name: str, data) -> None:
    """Serialize pipeline stage output to JSON. Writes metadata.json."""

def regenerate_all(config) -> None:
    """Run full pipeline once, capture every stage output as fixture."""
```

### Key Design Decisions

1. **Verify-only mode** (default): Test against fixture, fail on mismatch. CI runs this.
2. **Regenerate mode** (`--regenerate-fixtures`): Local only, intentional. Writes new fixtures.
3. **Staleness detection**: Each fixture has `metadata.json` with timestamps. Tests warn if >7 days old.
4. **Scrubbing**: Non-deterministic fields (timestamps, UUIDs) normalized to `[TIMESTAMP]`, `[UUID-N]` before comparison.

## 3. Risks Mitigated (from External Research)

| Risk | Severity | Mitigation |
|------|:---:|------|
| Golden file stale (code changed, fixture unchanged) | HIGH | Staleness check (7-day max); CI warning on stale |
| Blind update masks regression | CRITICAL | Regenerate mode local-only; never in CI |
| Global fixture coupling | MEDIUM | Per-test data, no shared mutable state |
| Non-deterministic output (timestamps/UUIDs) | MEDIUM | Scrubber normalizes before comparison |
| Large unreviewable fixtures | LOW | Keep fixtures focused (1-3 per stage, not hundreds) |
| False confidence (fixtures pass, pipeline fails) | HIGH | Full `--mode daily` still required pre-commit |
| Catfish/legacy entries persist | LOW | DB cleanup on regenerate |
| API exhaustion during regeneration | LOW | `--mock` flag uses mock data for regeneration |

## 4. Red Team Findings & Fixes (2026-05-19)

| ID | Severity | Finding | Fix Applied |
|------|:---:|------|------|
| C1 | CRITICAL | Blind regeneration risk — no diff, no approval | Regeneration is 2-step: write to temp dir → display diff → require `--force` to overwrite. `regeneration_log.json` records who/when/ diff summary |
| C2 | CRITICAL | Pre-commit enforcement unspecified | `.pre-commit-config.yaml` entry: `python app.py --mode daily --mock` blocks commit on failure |
| H1 | HIGH | Staleness suppressible (touch resets timestamp) | `pipeline_content_hash` (SHA256 of all pipeline .py) in metadata.json. Fail if hash mismatch, regardless of timestamp. 7-day hard fail in CI |
| H2 | HIGH | No PICA audit integration for fixtures | Fixture regeneration writes PICA-Unit + PICA-Security artifacts. CI checks fixture timestamps newer than audit artifacts |
| M1 | MEDIUM | No numeric tolerance for float comparison | `--atol` parameter (default 1e-6) for float fields |
| M2 | MEDIUM | VCR extension alternative not evaluated | See §4.1 below — VCR rejected due to prompt-change brittleness |
| L1 | LOW | Future-proofing: no deserialization guardrail | `test_fixtures/__init__.py` docstring: "JSON only — no pickle, no YAML unsafe loaders" |
| L2 | LOW | Directory nesting unnecessary | Flat directory with naming convention: `stage1_scout_normal.json` |

### 4.1 Why Not VCR Extension

The project already uses VCR cassettes for HTTP replay. Extending VCR to record LLM responses per stage was considered but rejected:
- **VCR cassettes couple to exact HTTP request bodies** — any prompt change invalidates all cassettes. Stage-output fixtures are prompt-change-agnostic.
- **VCR replay mode bypasses validation** — it replays raw HTTP responses without exercising `_parse_json_response` or `validate_flash_output`. Fixtures test the actual parsing/validation path.
- **VCR record modes require network** — `new_episodes` mode still calls the real API. Fixture regeneration works offline with `--mock`.

### 4.2 Pre-Commit Hook Specification

```yaml
# .pre-commit-config.yaml (addition)
- repo: local
  hooks:
    - id: marketmind-pipeline
      name: MarketMind full pipeline check
      entry: python app.py --mode daily --mock
      language: system
      pass_filenames: false
      stages: [pre-commit]
```

## 5. Implementation Phases

### Phase 1: Infrastructure (30 min)
- [ ] Create flat `test_fixtures/` directory with `__init__.py` (docstring: "JSON only — no pickle, no YAML unsafe loaders")
- [ ] Implement `load_fixture(stage, name)` — loads JSON, validates against metadata.json content hash, hard-fails if hash mismatched
- [ ] Implement `save_fixture(stage, name, data)` — writes to temp, serializes with scrubbers
- [ ] Implement `regenerate_all(config)` — 2-step: write to temp dir → display diff → require `--force`
- [ ] Add `--regenerate-fixtures` and `--atol` CLI flags to app.py
- [ ] Add `regeneration_log.json` recording who, when, diff summary for each regeneration
- [ ] Add `pipeline_content_hash` (SHA256 of all pipeline .py files) to metadata.json
- [ ] Staleness check: warn at 7 days in dev, hard-fail at 7 days in CI
- [ ] Output scrubbing: `[TIMESTAMP]`, `[UUID-N]`, `[WORKDIR]` normalization
- [ ] Write PICA-Unit + PICA-Security artifacts after first fixture generation
- [ ] Add `.pre-commit-config.yaml` entry: `python app.py --mode daily --mock`

### Phase 2: Stage Fixtures (30 min)
- [ ] Stage 1 (Scout) — 1 fixture
- [ ] Stage 2 (Flash Triage) — 2 fixtures (normal + edgecase_empty)
- [ ] Stage 2b (HVR) — 1 fixture
- [ ] Stage 3 (L1) — 1 fixture
- [ ] Stage 4 (L2+L3) — 1 fixture
- [ ] Stage 6 (Red Team) — 1 fixture
- [ ] Stage 7 (Resonance) — 1 fixture
- [ ] Stage 8 (Decision) — 1 fixture

### Phase 3: Testing (30 min)
- [ ] Write 1 isolated test per stage that loads fixture and validates output schema
- [ ] Verify all 1295 existing tests still pass
- [ ] Verify `--regenerate-fixtures` works end-to-end

## 5. When NOT to Use Fixtures

Fixtures are a poor fit for:
- Tests that must verify live API behavior
- Tests where exact output is non-deterministic beyond scrubbable fields
- Integration tests that verify stage interaction (keep these in existing test suite)

## 6. Golden Rules (from Industry Best Practice)

1. **Fixtures = source code** — commit, review, track in version control
2. **Never regenerate in CI** — regeneration is a local, human-supervised operation
3. **Scrub non-determinism** — timestamps, UUIDs, paths normalized before compare
4. **Detect staleness explicitly** — warn on fixtures >7 days old
5. **Review diffs carefully** — fixture changes ARE behavior changes
6. **One logical behavior per fixture** — avoid monolithic snapshot files
7. **Full pipeline still runs pre-commit** — fixtures supplement, not replace, integration tests

### Key References

- Node.js Best Practices: [Avoid global test fixtures, add data per-test](https://github.com/goldbergyoni/nodebestpractices/blob/master/sections/testingandquality/avoid-global-test-fixture.md)
- Go Golden Files: [Your Go Golden Tests Don't Need to Regenerate Everything](https://dev.to/bala_paranj_059d338e44e7e/your-go-golden-tests-dont-need-to-regenerate-everything-2o6g)
- Playwright Snapshot Modes: `'none' | 'missing' | 'all'` — strict separation of verify vs update
- Approval Tests: Test stays red until human explicitly approves output

## 7. MRP Status

**Status**: NEEDS_RED_TEAM_REVIEW
**Files affected**: New files under `test_fixtures/`, minor addition to `app.py`
**Estimated new code**: ~150 lines
**Risk**: LOW — supplements existing tests, doesn't modify pipeline code
**Dependencies**: None — purely additive
