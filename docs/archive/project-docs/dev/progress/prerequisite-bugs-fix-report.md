# Prerequisite Bugs Fix Report

**Date**: 2026-05-18
**Status**: All 3 bugs resolved. 31 tests pass (0 regressions).

---

## Bug 1: HypothesisResult missing card fields (Architecture H1)

**File**: `pipeline/investigation_loop.py`

**Changes**:
1. Added 8 new fields to `HypothesisResult` dataclass with empty string defaults:
   - `direction: str = ""`
   - `risk_level: str = ""`
   - `time_window: str = ""`
   - `layer_1_narrative: str = ""`
   - `layer_2_narrative: str = ""`
   - `layer_3_narrative: str = ""`
   - `layer_4_narrative: str = ""`
   - `core_logic: str = ""`

2. Added three heuristic helper functions:
   - `_extract_direction(hypothesis_text)` -- matches asset names (forex pairs, ETFs, commodities, Chinese asset names) against the hypothesis text, detects directional keywords (看涨/看跌/多头/空头 etc.), returns label like "EUR/USD 看涨"
   - `_estimate_risk_level(confidence, bear_case_confidence)` -- 低 (conf>0.7 & bear<0.3), 高 (conf<0.5 | bear>0.6), 中等 (else)
   - `_estimate_time_window(verdict)` -- ACTIONABLE→"1-4周", MONITOR→"1-3个月", HIGH_CONTENTION→"2-6周", DISCARD→"N/A", PRICED_IN→"已过期"

3. Added `_generate_layer_narratives(result)` async function that:
   - Populates direction, risk_level, time_window via heuristic functions (no LLM)
   - Calls `chat_flash` (already imported, cheap + fast) to generate 4 layer narratives + core_logic in one shot
   - Returns gracefully on parse failure or API error (narratives remain empty, non-blocking)

4. In `run_investigation_loop()`, added step 6 after verdict classification and before `results.append()`:
   ```python
   hvr_result = await _generate_layer_narratives(hvr_result)
   ```

**Design decisions**:
- Did NOT modify `VerificationResult` (as instructed). Narratives are generated post-hoc from float scores.
- PRICED_IN skip path does NOT call Flash (already skipped deep verification; new fields get empty defaults).
- All new fields use defaults so existing tests are unaffected.

**Tests**: 18/18 passed (before: 18, after: 18)

---

## Bug 2: session.py list_sessions() corruption logging

**File**: `storage/session.py`

**Change**: Added `import logging` and `logger = logging.getLogger("marketmind.storage.session")` at module level (lines 4, 11).

**Root cause**: Line 78 used `logger.warning(...)` in the `list_sessions()` exception handler, but `logger` was never imported or defined. This would raise `NameError` at runtime if a corrupted session file is encountered during listing.

**Tests**: 6/6 passed (before: 6, after: 6)

---

## Bug 3: Verify archivist atomic writes

**File**: `storage/archivist.py`

**Verdict**: No changes needed. Verification confirmed the atomic write pattern is correct.

**Analysis**:
- `save_json()` uses temp-file-then-rename: `tmp.write_text(...)` followed by `tmp.replace(filepath)`.
- `Path.replace()` delegates to `os.replace()`, which is atomic on NTFS (Windows) since Python 3.3+. The `.tmp` file is atomically renamed to `.json` -- no leftover `.tmp` file after a successful call.
- Crash-safety: if the process crashes during `write_text()`, the partial `.tmp` file is orphaned but the original `.json` is intact. The orphan `.tmp` is harmlessly overwritten on the next save.
- `save()` in `session.py` uses the same pattern and is also correct.

**Tests**: 7/7 passed (before: 7, after: 7)

---

## Summary

| Bug | File | Lines Changed | Tests (before/after) | Regressions |
|-----|------|:---:|:---:|:---:|
| 1 | `pipeline/investigation_loop.py` | ~130 added | 18 / 18 | 0 |
| 2 | `storage/session.py` | 3 added | 6 / 6 | 0 |
| 3 | `storage/archivist.py` | 0 (verified) | 7 / 7 | 0 |
| **Total** | 2 files modified | ~133 added | **31 / 31** | **0** |

**Updated**: 2026-05-18 12:00
