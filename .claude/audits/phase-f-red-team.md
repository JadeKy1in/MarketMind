# Red Team Audit — Phase F

**Date**: 2026-05-12
**Status**: COMPLETE — all findings resolved or accepted
**Tests**: 29 passed (19 red-team + 10 integration), 0 failures

## Findings

| # | Attack Surface | Severity | Mitigation | Test |
|---|---------------|----------|------------|------|
| RT-1 | Prompt injection via screenshot OCR | MEDIUM | Statistical crystallization gate (>=10 votes required for promotion). Single injection cannot crystallize. | `test_injected_prompt_is_ingested_but_wont_crystallize` |
| RT-2 | Memory poisoning via crafted PDF | HIGH | SUSPICIOUS_CONTENT_PATTERNS in knowledge_filter ISOLATE insider/confidential/leaked content. | `test_insider_information_is_isolated` (4 tests) |
| RT-3 | Scheduler resource exhaustion | LOW | per_shadow_task_budget + max_concurrent_tasks via Semaphore. | `test_task_budget_limits_enforced` (2 tests) |
| RT-4 | Crystallization contamination | LOW | Cold-start guard (min_samples) + backtest validation against shadow_votes PnL. | `test_false_signal_rejected_by_cold_start` |
| RT-5 | Gemini API key leakage | LOW | Private `_api_key` attribute, no custom repr/str, error messages use env var name not value. | `test_repr_does_not_expose_key` (4 tests) |
| RT-6 | Cross-shadow memory isolation | LOW | Parameterized queries filter by shadow_id. Proposition naming convention enforces scoping. | `test_get_observations_respects_shadow_id_boundary` (2 tests) |
| RT-7 | SQL injection in belief queries | LOW | All queries use parameterized SQLite (?, ?, ?), no f-string interpolation. | `test_query_beliefs_handles_sql_injection_in_ticker` (4 tests) |

## Resolution Detail

### RT-1: Prompt Injection via OCR (ACCEPTED)

Injected prompt text in screenshot OCR output is ingested as an ExternalObservation but cannot crystallize — crystallization requires >=10 votes before promotion to semantic memory. Single injection produces at most 1 vote. Verified by `test_injected_prompt_is_ingested_but_wont_crystallize`.

### RT-2: Memory Poisoning via PDF (FIXED)

`SUSPICIOUS_CONTENT_PATTERNS` in `knowledge_filter.py` detect insider/confidential/leaked/mnpi content patterns. Matching observations receive ISOLATE verdict and are quarantined for 30 days. Four test variants cover different attack vectors (insider, confidential, MNPI, leaked).

### RT-3: Scheduler Resource Exhaustion (ACCEPTED)

`per_shadow_task_budget` limits per-shadow computational resources. `max_concurrent_tasks` enforced via `asyncio.Semaphore`. Verified by 2 tests.

### RT-4: Crystallization Contamination (ACCEPTED)

Cold-start guard (`min_samples`) prevents premature crystallization. Backtest validation against `shadow_votes` PnL adds a second statistical gate. Verified by `test_false_signal_rejected_by_cold_start`.

### RT-5: Gemini API Key Leakage (FIXED)

`_api_key` is a private attribute (name-mangled). `__repr__` and `__str__` never include the key value. Error messages reference the env var name (`GEMINI_API_KEY`), not the value. Verified by 4 tests.

### RT-6: Cross-Shadow Memory Isolation (ACCEPTED)

All belief queries use parameterized SQL with `shadow_id` boundary filter. Proposition naming convention enforces shadow-scoped namespacing. Verified by 2 tests.

### RT-7: SQL Injection in Belief Queries (ACCEPTED)

All queries use parameterized SQLite (`?` placeholders), no f-string or string concatenation. Verified by 4 tests with malicious input strings.
