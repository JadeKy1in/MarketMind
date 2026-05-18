# E2E Bugfix Plan Audit

**Date**: 2026-05-18
**Auditor**: Red Team Agent
**Plan under review**: `E:\AI_Studio_Workspace\.claude\plans\e2e-bugfix-plan.md`

---

## Summary Verdict

**3 of 5 bugs correctly identified.** Bug 1 root cause is confirmed. Bug 3 root cause is confirmed. **Bug 2 is the critical blocker** -- its root cause is UNKNOWN and INDEPENDENT of Bug 1 (contrary to the plan's speculation). Fixing Bug 1 alone will NOT resolve Bug 2. The risk that the pipeline still fails after all 3 fixes is **HIGH** due to Bug 2's unaddressed root cause.

---

## Bug 1: SanitizedText Type Error -- CONFIRMED

**Plan assessment**: CORRECT root cause, CORRECT fix, INCOMPLETE scope analysis.

### Evidence

**Root cause confirmed at TWO call sites**, not one:

**Call site 1** -- `event_clusterer.py:671-676` (`_flash_topic_synthesis`):
```python
sys_prompt = sanitize_for_llm_prompt(TOPIC_NAMING_SYSTEM, source="llm_prompt")        # SanitizedText
user_prompt_sanitized = sanitize_for_llm_prompt(user_prompt, source="llm_prompt")     # SanitizedText
result = await chat_flash(
    system_prompt=sys_prompt,              # ← passes SanitizedText, not str
    user_prompt=user_prompt_sanitized,     # ← passes SanitizedText, not str
    ...
)
```

**Call site 2** -- `event_clusterer.py:735-741` (`_flash_cross_cluster_detection`):
```python
sys_prompt = sanitize_for_llm_prompt(CROSS_CLUSTER_SYSTEM, source="llm_prompt")
user_prompt_sanitized = sanitize_for_llm_prompt(user_prompt, source="llm_prompt")
result = await chat_flash(
    system_prompt=sys_prompt,              # ← same bug
    user_prompt=user_prompt_sanitized,     # ← same bug
    ...
)
```

**Crash path** -- `async_client.py:204-206` (`chat_flash` internally calls `sanitize_for_llm_prompt` again):
```python
async def chat_flash(system_prompt: str, user_prompt: str, ...):
    sys_result = sanitize_for_llm_prompt(system_prompt, ...)  # system_prompt is SanitizedText
    ...
```
Inside `sanitize_for_llm_prompt` at `input_guard.py:216`:
```python
original_length = len(text)  # len(SanitizedText) → TypeError!
```

The error log "50x `Flash topic naming failed for cluster N`" matches `_flash_topic_synthesis` per-cluster loop + `_flash_cross_cluster_detection` (1 call), reasonably summing to ~50.

### Fix assessment

The plan's fix (add `.sanitized`) works but misses a design question: **`chat_flash` already calls `sanitize_for_llm_prompt` internally** (async_client.py:204-214). The cleaner fix is:

- **Option A (plan)**: Pass `.sanitized` in `event_clusterer.py` -- double-sanitization (harmless but wasteful)
- **Option B (cleaner)**: Remove pre-sanitization from `event_clusterer.py` entirely -- let `chat_flash` handle it

Either works. Option B eliminates the anti-pattern of callers pre-sanitizing before `chat_flash`.

### Audit of ALL SanitizedText call sites

Verified that `event_clusterer.py` is the ONLY file with this bug:
- `hypothesis_card.py:199,209,229,234,237,243` -- correctly uses `.sanitized`
- `gate1_interaction.py:232` -- correctly uses `.sanitized`
- `gate2_interaction.py:241` -- correctly uses `.sanitized`
- `gate3_interaction.py:242` -- correctly uses `.sanitized`

---

## Bug 2: Flash Triage Returns Empty -- ROOT CAUSE UNKNOWN

**Plan assessment**: INCORRECT linkage to Bug 1. Root cause is NOT identified. Fix (debug logging) is diagnostic, not curative.

**Severity**: CRITICAL -- this is the cascade trigger for the entire pipeline failure.

### Evidence that Bug 2 is INDEPENDENT of Bug 1

`flash_triage.py:148-152` passes RAW strings to `chat_flash`:
```python
flash_result = await chat_flash(
    system_prompt=FLASH_TRIAGE_SYSTEM_PROMPT,   # ← raw str, not SanitizedText
    user_prompt=user_prompt,                     # ← raw str from _build_triage_prompt()
    ...
)
```

There is NO pre-sanitization in `flash_triage.py`. `chat_flash` receives proper `str` arguments, sanitizes them internally, and proceeds. The SanitizedText crash CANNOT happen in this code path.

**The plan's question "Is Bug 2 the same root cause as Bug 1?" -- definitive answer: NO.**

### What Bug 2's root cause could be

Since SanitizedText is eliminated, the remaining possibilities:

1. **Flash LLM returning unstructured output**: Model doesn't follow JSON format despite instructions. `_parse_json_response` at `flash_triage.py:88-118` tries markdown fences and embedded arrays, then falls back to `[]`. If Flash returns prose, all batches parse as empty.

2. **`validate_flash_output` rejects all items**: `flash_output_schema.py:117` validates scores (must be int 0-10) and classification (must be known enum). If Flash returns scores as floats (e.g., 7.0 not 7) or non-standard classifications, ALL items are silently dropped. `flash_triage.py:203` catches validation failures with `logger.debug` (not `warning`!) -- invisible in normal log levels.

3. **API connectivity / rate limiting**: All `chat_flash` calls fail with exceptions caught at line 154-161, logged as warnings. Budget exhaustion also yields empty content at line 164.

4. **Input data issue**: `_build_triage_prompt` at line 76 builds prompts from `item.title` and `item.summary`. If all titles are empty strings, the prompt is structurally valid but semantically empty.

### Critical issue: validation failures are DEBUG not WARNING

`flash_triage.py:203-209`:
```python
if not validate_flash_output(validation_dict):
    logger.debug(...)  # ← DEBUG level -- invisible in default log config
    continue
```

This means if validation is rejecting items, the user sees "0 results" with NO explanation. The plan's debug logging fix partially addresses this, but should also upgrade validation-failure logging to WARNING.

---

## Bug 3: Shadow Direction CHECK Constraint -- CONFIRMED

**Plan assessment**: CORRECT root cause. Fix is appropriate.

### Evidence

`shadow_agent.py:479-481` (`_extract_field`):
```python
def _extract_field(block: str, field: str) -> str | None:
    match = re.search(rf'{re.escape(field)}:\s*(.+)', block, re.IGNORECASE)
    return match.group(1).strip() if match else None
```

This regex captures EVERYTHING after `direction:` to end of line with no validation. LLM outputs like:
```
direction: 0.6, thesis: bullish momentum building
```
...yield `direction = "0.6, thesis: bullish momentum building"` → passed directly to SQLite INSERT → CHECK constraint `direction IN ('long','short','abstain')` fails.

No direction normalization exists anywhere in the shadows directory (confirmed by grep).

### Fix assessment

The plan correctly identifies:
1. Normalization: `"bullish"→"long"`, `"bearish"→"short"`, `"neutral"→"abstain"`
2. Default fallback: `direction="abstain"` on parse failure
3. `could not convert string to float` is a SEPARATE issue from direction -- it's the confidence parsing at line 243: `confidence = float(_extract_field(block, "confidence") or 0.5)` which also has no protection against malformed output. The plan doesn't mention this.

**Missing**: `float()` conversion at line 243 has the same class of vulnerability -- no try/except. If the LLM outputs `confidence: high`, this also crashes. Add `try/except ValueError` there.

---

## Bug 4: BLS PPI No Data -- ACCEPTED

Low severity. Service-level issue. Plan's fix (silent skip, WARNING not ERROR) is appropriate.

---

## Bug 5: Bluesky Credentials -- ACCEPTED

Not a code bug. Configuration issue. Plan's approach (DEGRADED status, don't block) is correct.

---

## Missing Cascade Failures

The plan misses two failure modes:

### 1. Empty content not checked after Bug 1 fix

`event_clusterer.py:685-691`:
```python
content = result.get("content", "") if isinstance(result, dict) else ""
if result.get("error") if isinstance(result, dict) else False:
    logger.warning(...)
    ...fallback to keyword name...
    continue
```

After Bug 1 is fixed and `chat_flash` succeeds, it can return `{"content": "", "error": "budget_exhausted"}`. The code checks `result.get("error")` -- this is correct for budget exhaustion. But if `content` is empty WITHOUT an error field (e.g., LLM returned no text), the code proceeds with `content=""` → `_parse_topic_json("")` returns `{}` → title stays empty → falls through to `_keyword_topic_name`. This would work due to the fallback but produce degraded output without warning. Consider adding `if not content: logger.warning(...); fallback; continue`.

### 2. `_flash_cross_cluster_detection` failure degrades Gate 1 context silently

After Bug 1 fix at call site 2, if this call fails for other reasons (API error, bad output), `cross_cluster_causal_chains` is set to `[]` at line 745. The clustering result is still returned, but without causal relationships. Gate 1 cards show isolated clusters rather than interconnected themes. This degrades analysis quality but doesn't break the pipeline -- LOW severity.

---

## Risk Assessment: Will fixing Bugs 1-3 make the pipeline work?

**Risk: HIGH**

| Scenario | Likelihood | Impact |
|----------|:----------:|:------:|
| Bug 1 fix resolves event_clusterer, but Bug 2 (Flash triage empty) persists | **HIGH** | Pipeline has cluster names but 0 triage results → no HVR → no Gate 1 cards → no decision |
| Bug 2 root cause is Flash model output format (validation rejects) | **MEDIUM** | Requires prompt engineering or schema relaxation, not just debug logging |
| Bug 2 root cause is API/connectivity | **LOW** | Infrastructure issue, not code |
| All 3 bugs fixed, pipeline works | **LOW-MEDIUM** | Only if Bug 2 root cause is addressed |

### Cascade dependency chain

```
Flash Triage (Bug 2)
  ↓ produces scored items
filter_for_pro_browse()
  ↓ produces top signals
HVR Investigation
  ↓ produces HypothesisResult
Gate 1 Cards
  ↓ presents to user
L1 → L2 → L3 → Decision
```

Bug 2 at the TOP blocks EVERYTHING below. Bug 1 only affects cluster context enrichment (a quality improvement, not a pipeline requirement). Bug 3 affects shadow internals (independent from main pipeline by design).

**The plan overestimates Bug 1's impact**: "Bug 1 影响最大——修完它，Flash 分诊和事件聚类就能工作了" -- this is WRONG. Fixing Bug 1 fixes event clustering. It does NOT fix Flash triage (Bug 2). The plan conflates event clustering (event_clusterer.py) with news triage (flash_triage.py), which are separate stages.

### What must be true for the pipeline to work after fixes

1. Bug 1 fix: event_clusterer produces named clusters with cross-cluster links -- **likely fixed**
2. Bug 2 root cause must ALSO be addressed -- **NOT addressed by Bug 1**
3. Bug 3 fix: shadows produce valid direction values -- **likely fixed**
4. No additional undiscovered bugs in the HVR → Gate 1 → Decision chain

---

## Recommendations

### Before committing Bug 1 fix
1. **[CRITICAL]** Run `python app.py --mode full --mock --verbose` with ONLY Bug 1 fixed first, to isolate Bug 2's true root cause from the debug output
2. **[HIGH]** Add WARNING-level logging in `flash_triage.py` for validation failures (currently DEBUG)
3. **[HIGH]** Add `blog.setLevel(logging.DEBUG)` temporarily during the next run to capture all failure modes

### Bug 2 root cause investigation order
1. Add `logger.warning("Flash raw content [%d-%d]: %s", ..., content[:200])` to `flash_triage.py:173` (after parse)
2. Check if content is empty string, JSON, or prose
3. If empty: API/budget issue
4. If prose: Flash model not following JSON instruction → prompt or model issue
5. If JSON but empty array after parse: model returned wrong structure → `_parse_json_response` logic
6. If JSON with items but all filtered: `validate_flash_output` too strict → relax schema or fix Flash output

### Bug 3 additional fix
Add `try/except ValueError` around `float()` conversion at `shadow_agent.py:243` for `confidence` field, same class of vulnerability as `direction`.

### Design decision
Choose Option B for Bug 1: remove pre-sanitization from `event_clusterer.py` entirely since `chat_flash` does it internally. This prevents future callers from repeating this bug.

---

## Test Coverage Gaps

The plan's test checklist validates the happy path (pipeline works end-to-end) but does not include unit tests for:
- `event_clusterer._flash_topic_synthesis` with mocked `chat_flash` returning empty content
- `event_clusterer._flash_cross_cluster_detection` with mocked `chat_flash` returning malformed JSON
- `flash_triage.triage_batch` with mocked `chat_flash` returning prose (not JSON)
- `flash_triage.triage_batch` with mocked `validate_flash_output` rejecting all items
- `shadow_agent._parse_votes` with non-standard direction values ("bullish", "bearish", "neutral", "0.6, thesis: ...")
- `shadow_agent._parse_votes` with non-numeric confidence values ("high", "medium")

These tests would catch regressions in the exact failure modes observed.
