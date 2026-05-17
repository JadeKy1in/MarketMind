# Red Team Audit — Phase G Final

**Auditor**: Red Team (AI Agent)  
**Date**: 2026-05-17  
**Scope**: Source pipeline architecture, proposed Phase H tasks, architecture risks, security  
**Methodology**: Static analysis of all source-code files referenced in the audit scope

---

## CRITICAL (must fix before Phase H)

### C1. Bluesky `config.proxy_url` AttributeError — wired integration crashes on first use

**File**: `pipeline/social_sources.py:107`

```python
if config.proxy_url:
    client_kwargs["proxy"] = config.proxy_url
```

`MarketMindConfig` (in `config/settings.py`) has **no `proxy_url` attribute**. This access raises `AttributeError` before the try/except block on line 109. The error is caught by `scout.py:214` (`except Exception`), which marks Bluesky as `DEGRADED` or `DEAD` after 3 consecutive failures. **Result**: Bluesky is wired in the code path but will never fetch successfully in production. This undermines the claim that Bluesky is "wired" as a Phase G deliverable.

**Fix**: Either add `proxy_url: str | None` to `MarketMindConfig` or guard with `getattr(config, "proxy_url", None)`.

### C2. BLS source has no fetch handler — perpetually silent dead source

**File**: `config/source_authority.py:44-50`, `pipeline/scout.py:181-222`

BLS is configured with `feed_type="bls_api"` and `status=SourceStatus.UNTESTED`. In `fetch_source()`, the routing chain is:

1. `source.name == "NewsAPI"` → no
2. `source.name == "GNews"` → no
3. `source.feed_type in ("rss", "api")` → no (feed_type is `"bls_api"`)
4. `source.feed_type == "html"` → no
5. `source.feed_type == "bluesky"` → no
6. **No matching branch — falls through entirely**

The try block never executes any fetch logic. The source status stays `UNTESTED`, zero items are returned, no error is logged. The `bls_api` feed_type has no implementation. The source_authority comment even says "Implementation TBD — macro_data.py or dedicated pipeline/bls_fetcher.py" — this was never completed.

**Fix**: Implement `_fetch_bls()` in scout.py (or macro_data.py) using the BLS Public Data API v2 and add a `source.feed_type == "bls_api"` branch in `fetch_source()`.

### C3. CFTC COT data silently lost — text file parsed as RSS returns empty feed

**File**: `config/source_authority.py:58-60`, `pipeline/scout.py:191`

CFTC COT is configured with `feed_type="api"`. The source_authority comment says "handled by macro_data.py, not RSS parser." But in `fetch_source()`, the branch `source.feed_type in ("rss", "api")` applies. It fetches `https://www.cftc.gov/dea/newcot/c_disagg.txt` (a **plain text file**, not RSS) and passes it to `feedparser.parse()`. `feedparser` returns an empty FeedParserDict with zero entries. **No exception is raised**. `source.status` is set to `WORKING`, `consecutive_failures` reset to 0. The function returns `[]` silently.

**Result**: A PRIMARY-tier institutional source (reliability=0.99) produces zero data every session with no error indication. This is silent data loss — the worst kind of failure.

**Fix**: Either exclude `feed_type="api"` from the RSS branch (separate the API handler) or give CFTC COT a unique feed_type and route it to `macro_data.py`.

### C4. Track D (human-in-loop) degradation completely unimplemented

**File**: `pipeline/scout.py` (entire file), design spec §11.3

The design spec defines a **4-track degradation strategy**:
- Track A: RSS/API structured sources
- Track B: HTML scraping (stated as "not yet implemented" in scout.py:207-208)
- Track C: NewsAPI/GNews paid pipeline (implemented but requires API keys)
- **Track D: Human-in-loop** — AI triggers a desktop notification "help me look up X," user provides information manually within 30 seconds

Track D is the **circuit breaker** — the final fallback when all automated sources fail. It is not implemented anywhere in the codebase. There is no desktop notification, no user prompt mechanism, no manual data injection path. When all sources fail:
- `get_working_sources()` returns `[]`
- The fallback tries UNTESTED sources (BLS — broken per C2)
- If those fail too, `fetch_all_sources()` returns `[]` and the pipeline proceeds with zero news items
- The analysis will be based on stale or missing data with no alert to the user

**Fix**: Implement a `scout.manual_fallback()` function that triggers a UI prompt (via `ui/gate_panel.py` or a new mechanism) allowing the user to paste headlines or URLs when all automated tracks fail.

---

## HIGH (should fix in Phase H)

### H1. `ranking_engine.py` at 703 lines violates hard ceiling with NO grandfather exemption

**File**: `shadows/ranking_engine.py` — 703 lines

The grandfather clause in `CLAUDE.md` covers: `app.py`, `layer1_interactive.py`, `methodology_rules.py`, `shadow_agent.py`, `multimodal_adapter.py`. `ranking_engine.py` is **NOT in the list**. At 703 lines, it exceeds the 500-line hard ceiling for Python modules.

Per §3.1 rules: "Files exceeding the hard maximum trigger a mandatory refactoring before any new features can be added to that file." The Phase G changes modified this file (git status shows `M projects/marketmind/shadows/ranking_engine.py`). If Phase G added new features to this file without extraction first, that is a process violation.

**Required**: Extract at least one cohesive concern (e.g., achievement tier logic, composite scoring, or Bayesian haircut computation) into its own module before any further work on this file.

### H2. `lateral_proxy.py` completely missing — design spec requirement never fulfilled

**File**: Not found anywhere in the codebase. Referenced in design spec §10.1 in the reusable module list.

`lateral_proxy.py` is listed as a reusable module for "indirect data validation engine" — cross-source data verification. Without it, there is **no defense against a single bad source** polluting the analysis. If one source publishes incorrect or fabricated data, it flows directly into the signal pipeline with no cross-validation. This is especially dangerous given the reliance on community-tier sources (XCancel, Bluesky).

**Fix**: Implement `lateral_proxy.py` as proposed in P3, but **elevate its priority to P1** — this is a data integrity concern that directly impacts Law 7 compliance.

### H3. `fact_checker.py` exists but is NEVER called from the pipeline

**File**: `integrity/fact_checker.py` (implemented, tested, exported in `__init__.py`)

`run_fact_check()` is implemented, has 6 tests in `tests/test_integrity/test_fact_checker.py`, and is exported via `integrity/__init__.py`. But **no pipeline stage calls it**. A grep for `run_fact_check` across all `.py` files in `projects/marketmind/` shows it appears only in:
- `integrity/fact_checker.py` (definition)
- `integrity/__init__.py` (export)
- `tests/test_integrity/test_fact_checker.py` (tests)

It is NOT called from `app.py`, not from any pipeline stage, not from any shadow module. This is dead code that the proposed P2 implies doesn't exist yet — but it does exist; it's just not wired. The task should be "Wire fact_checker.py into the Layer 1-2-3 pipeline and Decision stage," not "create fact_checker.py."

**Fix**: Call `run_fact_check()` after each Pro-generated analysis output (layer1, layer2, layer3, decision) to verify numeric claims before they reach the user.

### H4. Static reliability scores are dead data — never recalibrate

**File**: `config/source_authority.py` (reliability field), `pipeline/scout.py` (consecutive_failures counter)

The `Source.reliability` field is set at definition time (0.99, 0.90, 0.85, 0.80, 0.75, 0.70, 0.60) and **never updated**. The `consecutive_failures` counter in `scout.py:216-220` tracks failures but is only used to set `source.status` (WORKING/DEGRADED/DEAD). The `reliability` score — which feeds into `NewsItem.source_reliability` and propagates through the entire analysis pipeline — **never changes** regardless of actual source performance.

A source could fail 100 consecutive times (status=DEAD), and its `NewsItem.source_reliability` would still show 0.99. This means the downstream signal weighting is based on fiction.

**Fix**: Implement dynamic recalibration in `scout.py` — after each fetch, adjust `source.reliability` toward an empirical success rate (e.g., EMA of success/failure over last 30 attempts).

### H5. BEA source missing from SOURCES list

**File**: `config/source_authority.py` — no BEA entry; design spec §11.1 lists BEA

The design spec lists "BLS, BEA, Federal Reserve RSS" as free RSS sources. BLS exists (broken per C2), Federal Reserve exists, but **BEA (Bureau of Economic Analysis)** is absent. BEA provides GDP, trade balance, and personal income data — core macro indicators.

**Fix**: Add BEA source entry with appropriate URL and feed_type, or document why it was excluded.

### H6. Reddit WSB RSS source missing — mentioned in code but not configured

**File**: `pipeline/social_sources.py:4-5` mentions "Reddit WSB RSS provides retail sentiment coverage" as replacement for dead ApeWisdom. But `config/source_authority.py` has **no Reddit WSB RSS entry**.

The comment claims retail sentiment coverage exists via Reddit RSS, but the source is never added to `SOURCES`. The only social/community sources are XCancel (fragile) and Bluesky (broken per C1). This means there is **zero working social sentiment data** in the pipeline.

**Fix**: Add a Reddit WSB RSS source entry (e.g., `https://www.reddit.com/r/wallstreetbets/.rss`) to SOURCES, or explicitly document that Reddit WSB RSS was evaluated and rejected.

### H7. Bluesky credentials bypass MarketMindConfig abstraction

**File**: `pipeline/social_sources.py:60-67`

Bluesky credentials are read directly from `os.environ`:
```python
username = _os.environ.get("BLUESKY_USERNAME", "")
app_password = _os.environ.get("BLUESKY_APP_PASSWORD", "")
```

Contrast with NewsAPI/GNews which use `config.newsapi_key` / `config.gnews_key` from `MarketMindConfig`. Bluesky credentials are invisible to the configuration system — they don't appear in `MarketMindConfig.validate()`, can't be checked by health scripts, and break the pattern established by other API sources.

**Fix**: Add `bluesky_username: str | None` and `bluesky_app_password: str | None` to `MarketMindConfig`, read them from `BLUESKY_USERNAME` / `BLUESKY_APP_PASSWORD` env vars in the default factory, and pass them through `fetch_bluesky_posts()` as config parameters.

---

## MEDIUM (fix when convenient)

### M1. `__import__` anti-pattern in `scout.py:229`

```python
sources = [s for s in __import__("marketmind.config.source_authority", fromlist=["SOURCES"]).SOURCES
           if s.status == SourceStatus.UNTESTED]
```

This runtime string-based import bypasses static analysis, linters, and IDE tooling. The `SOURCES` list is already imported at the top of the file (line 16). This line should use the already-imported name directly, not re-import it via `__import__`.

**Fix**: Replace with `from marketmind.config.source_authority import SOURCES` (already imported at line 16, but SOURCES is not in that import). Add `SOURCES` to the existing import statement.

### M2. NewsAPI/GNews cache failure results for 24 hours

```python
# scout.py:81-82
if _newsapi_cache is not None and (time.time() - _newsapi_cache_time) < 86400:
    return _newsapi_cache
```

If NewsAPI returns non-ok status on line 98, the cache is populated with an empty list (lines 100-101). This empty result is cached for 24 hours, meaning a single transient API error prevents all retries for the rest of the day.

**Fix**: Only cache successful responses. If the API returns non-ok status, leave the cache as None and let the next call retry. Add exponential backoff for repeated failures.

### M3. Nikkei Asia Google News RSS fallback contradicts design spec

**File**: `config/source_authority.py:70-75`

The Nikkei Asia source uses `https://news.google.com/rss/search?q=Japan+business+markets+stocks&hl=en-US&gl=US&ceid=US:en` as fallback. But the design spec §11.1 states: "不再使用：Google News RSS（已死 2023）" (No longer use: Google News RSS (dead 2023)).

Either Google News RSS still partially works (contradicting the spec) or this source is dead and the design spec is correct. The source is marked `UNTESTED`, so its actual status is unknown.

**Fix**: Test the Nikkei Asia Google News RSS URL and either update the design spec (if it still works) or remove/replace the source (if it doesn't). The current state is contradictory.

### M4. Two grandfathered files still exceed hard ceiling

| File | Original (2026-05-15) | Current | Delta |
|------|:---:|:---:|:---:|
| `app.py` | 971 | 315 | -656 |
| `layer1_interactive.py` | 657 | 71 | -586 |
| `methodology_rules.py` | 639 | DELETED | -639 |
| `shadow_agent.py` | 567 | 529 | -38 |
| `multimodal_adapter.py` | 591 | 510 | -81 |

`app.py` (315) exceeds the 300-line hard ceiling for glue/orchestration files. `shadow_agent.py` (529) and `multimodal_adapter.py` (510) exceed the 500-line hard ceiling for modules. Per the grandfather clause, bug fixes are permitted but new feature work requires extraction first. If Phase G added new features to any of these, that is a process violation.

**Note**: `layer1_interactive.py` went from 657 to 71 — excellent work. This proves extraction works.

### M5. `challenger_engine.py` at 493 lines — dangerously close to ceiling

This file is 7 lines from the 500-line hard ceiling. Any bug fix exceeding 7 lines of net addition will trigger mandatory refactoring. This should be proactively extracted or at minimum have a planned extraction boundary documented.

### M6. `scout.py` source list discrepancy — says "6/13 working" but only 5 sources can actually produce data

**Actual working state based on code analysis**:

| Source | Stated Status | Actual Status | Issue |
|--------|:---:|:---:|------|
| FRED | WORKING | Likely working | RSS feed |
| BLS | UNTESTED | **BROKEN** | C2 — no handler for bls_api |
| SEC EDGAR | WORKING | Likely working | RSS feed (User-Agent compliance TBD) |
| Federal Reserve | WORKING | Likely working | RSS feed |
| CFTC COT | WORKING | **BROKEN** | C3 — text file parsed as RSS |
| NewsAPI | UNTESTED | Needs API key | Code exists, key required |
| GNews | UNTESTED | Needs API key | Code exists, key required |
| MarketWatch | UNTESTED | Unknown | RSS feed, untested |
| Investing.com | UNTESTED | Unknown | RSS feed, untested |
| Nikkei Asia | UNTESTED | **CONTRADICTORY** | M3 — Google News RSS "dead per spec" |
| XCancel | UNTESTED | Unknown | Fragile by design |
| Bluesky | UNTESTED | **BROKEN** | C1 — AttributeError on first fetch |

The "6/13 working" claim in the progress notes is **unverifiable** from code analysis — at least 2 of those "working" sources (CFTC COT, BLS) are silently broken, and a third (Bluesky) will crash on first use.

---

## LOW / INFO

### L1. No `.env` file or environment template

No `.env.example`, `.env.template`, or documentation listing required environment variables for API keys. Setup requires tribal knowledge: `DEEPSEEK_API_KEY`, `NEWSAPI_KEY`, `GNEWS_API_KEY`, `BLUESKY_USERNAME`, `BLUESKY_APP_PASSWORD`, `FRED_KEY`, `EIA_KEY`.

### L2. XCancel source fragility acknowledged but not mitigated

The design spec §11.2 says XCancel is "single-person maintained, fragile." Combined with Bluesky being broken (C1) and Reddit WSB RSS missing (H6), there is **zero working social/community sentiment data** in the Phase G pipeline. Social sentiment was a design requirement.

### L3. Track B (HTML scraping) declared as "not yet implemented" — design debt

`scout.py:207-208`: `source.status = SourceStatus.DEGRADED  # HTML scraping not yet implemented`. This is documented technical debt. The design spec §11.3 notes that HTML scraping has "<10% success rate against Cloudflare AI defenses." This is acceptable — Track B is arguably not worth implementing given the low success rate.

### L4. `fetch_all_sources` fallback to UNTESTED sources includes known-broken sources

When `get_working_sources()` returns `[]` (all sources DEAD), the fallback at `scout.py:229-230` tries all UNTESTED sources. This includes BLS (broken per C2) and Nikkei Asia (questionable per M3). The fallback will attempt known-broken sources every session in this state, grinding through failures with no benefit.

### L5. API key warnings are appropriate — no sensitive data leakage detected

All log statements about missing API keys use generic messages ("NEWSAPI_KEY not configured") without logging the actual key values. The Bluesky authentication code logs the username (`logger.info("Bluesky session created for @%s", username)`) but never logs the password. No credential leakage found.

---

## Proposed Task Priority Reassessment

| Proposed | Task | Verdict | Correct Priority |
|:---:|------|------|:---:|
| P1 | "NewsAPI + GNews API implementation" | **MISLEADING**. Both are already implemented in `scout.py` (lines 77-178). The gap is API key configuration, not code. Task should be: "Configure and validate NewsAPI + GNews API keys." | P2 (keys are a config concern, not a development task) |
| P2 | "fact_checker.py — AI claim verification" | **MISLEADING**. `fact_checker.py` already exists (103 lines), is tested (6 tests), and is exported. The gap is INTEGRATION — it's never called from any pipeline stage. Task should be: "Wire fact_checker.py into Layer 1-2-3 pipeline and Decision stage." | P2 (but only after P1 bugs are fixed) |
| P3 | "lateral_proxy.py — cross-source data validation" | **SHOULD BE P1**. This is a design spec requirement (§10.1) for data integrity. Without it, there's no defense against single-source data pollution. This absence is a Law 7 compliance gap. | **P1** |
| P4 | "Dynamic source reliability weighting" | **CORRECT**. Important but not urgent. | P3 |
| P5 | "Heuristic source selection" | **CORRECT**. AI-driven source selection is a nice-to-have. | P5 |

### MISSING tasks that must be added to Phase H

These are not in the proposed list but are required based on the CRITICAL findings above:

| Priority | Task | Rationale |
|:---:|------|------|
| **P0** | Fix Bluesky `config.proxy_url` AttributeError (C1) | Bluesky is claimed "wired" but crashes on first use |
| **P0** | Implement BLS `bls_api` fetch handler (C2) | Primary-tier source is a silent no-op |
| **P0** | Fix CFTC COT fetch routing (C3) | Primary-tier source silently returns empty data |
| **P0** | Implement Track D human-in-loop degradation (C4) | No circuit breaker when all automated sources fail |
| **P1** | Extract `ranking_engine.py` below 500 lines (H1) | No grandfather exemption; mandatory before new features |
| **P2** | Wire `fact_checker.py` into pipeline stages (H3) | Dead code that exists but isn't used |
| **P2** | Add BEA source to SOURCES (H5) | Missing from design spec source list |
| **P2** | Add Reddit WSB RSS source (H6) | Mentioned in code as replacement but never configured |
| **P2** | Add Bluesky credentials to `MarketMindConfig` (H7) | Breaks config abstraction pattern |

---

## Architecture Risk Summary

### Import DAG analysis

Pipeline modules import from:
- `gateway/` (async_client, response_parser) — allowed, gateway is a shared dependency
- `pipeline/` siblings (layer1_narrative, layer2_fundamental, etc.) — allowed per CLI reference architecture
- `shadows/` — **only `decision.py:16` imports `ShadowVote`** from shadows. This is an up-stream import (pipeline depends on shadows) but is justified by data flow (decision aggregates shadow votes). No circular dependency created.
- `config/` — allowed, config is shared data

Shadow modules import from:
- `gateway/` — allowed
- `config/` — allowed
- **No imports from `pipeline/`** — clean separation: shadows don't depend on pipeline internals

UI modules import from:
- `pipeline/` — no imports found (UI uses session context)
- `shadows/` — no imports found

**Verdict**: Import structure is clean. No circular dependencies. One cross-layer import (pipeline→shadows via decision.py) is architecturally justified.

### File size compliance

| Status | Files |
|:---:|------|
| Over hard ceiling, no grandfather | `ranking_engine.py` (703) — **VIOLATION** |
| Over hard ceiling, grandfathered | `shadow_agent.py` (529), `multimodal_adapter.py` (510), `app.py` (315 vs 300 glue limit) |
| Dangerously close to ceiling | `challenger_engine.py` (493), `shadow_mother.py` (433) |
| Successfully extracted | `layer1_interactive.py` (657→71), `methodology_rules.py` (639→deleted) |

### Dead code paths

1. **`fact_checker.py`**: Fully implemented and tested but never called from any pipeline stage
2. **BLS `bls_api` handler**: Source configured, fetch path doesn't exist
3. **CFTC COT as RSS**: Wrong parser type, data silently lost
4. **Track B HTML scraping**: `source.status = SourceStatus.DEGRADED` with comment "not yet implemented" — this is intentional design debt, not dead code
5. **`config.proxy_url`**: Referenced but doesn't exist on the config object

---

## Security

### API key isolation

| Key | Storage | Isolation |
|-----|---------|-----------|
| `DEEPSEEK_API_KEY` | `os.getenv()` | Standard env var |
| `DEEPSEEK_API_KEYS` | `os.getenv()` | Standard env var (comma-separated) |
| `NEWSAPI_KEY` | `os.getenv()` | Standard env var |
| `GNEWS_API_KEY` | `os.getenv()` | Standard env var |
| `BLUESKY_USERNAME` | `os.getenv()` | Standard env var — **not abstracted through config** |
| `BLUESKY_APP_PASSWORD` | `os.getenv()` | Standard env var — **not abstracted through config** |
| `FRED_KEY` | `os.getenv()` | Standard env var (used in macro_data.py) |
| `EIA_KEY` | `os.getenv()` | Standard env var (used in macro_data.py) |

**Assessment**: All keys use environment variable isolation. No keys are hardcoded. No `.env` file was found (keys must be set in the system environment or a shell profile). Bluesky credentials bypass the `MarketMindConfig` pattern but still read from env vars — this is an abstraction issue (H7), not a security vulnerability.

### Logging of sensitive data

No instances of credential logging found. All log statements use generic messages. Bluesky auth logs username but not password — acceptable.

### User-Agent compliance

`scout.py:195` uses a single User-Agent for all RSS/API sources: `"MarketMind/0.1 (contact@marketmind.dev)"`. Per the design spec §11.3, SEC EDGAR "requires User-Agent: 'OrgName/version (email)'" — the current header approximately matches this format. However, if contact@marketmind.dev is not a real email address, SEC may block requests. This is a compliance risk, not a security vulnerability.

---

## Verdict: CONDITIONAL

Phase G produced real improvements (file sizes down, 582 tests pass, Bluesky skeleton exists). However, four CRITICAL bugs (C1-C4) mean the source pipeline cannot reliably produce data in production:

1. Bluesky **crashes** on first use (C1)
2. BLS is a **silent no-op** (C2)
3. CFTC COT is a **silent no-op** (C3)
4. No **circuit breaker** when all automated sources fail (C4)

Additionally, `ranking_engine.py` (703 lines) violates the mandatory file-size rule with no grandfather exemption (H1).

**Conditions for approval**:
1. Fix C1, C2, C3 before any Phase H work begins (estimated: 2-3 hours)
2. Implement Track D stubs (at minimum: a log warning + UI notification framework; full interactive prompt can follow) before any Phase H work begins
3. Extract `ranking_engine.py` below 500 lines OR formally add it to the grandfather clause with documented justification before any new features are added to it
4. Add the 8 missing tasks (P0-P2 listed above) to the Phase H plan

**Recommended Phase H start order**:
1. Fix C1-C4 (critical bugs — no features until pipeline works)
2. Extract ranking_engine.py (compliance — mandatory before new features)
3. P3 (lateral_proxy.py) — elevated to P1 for data integrity
4. Wire fact_checker.py into pipeline stages (H3)
5. Add missing sources (BEA, Reddit WSB RSS)
6. Then proceed with proposed P1-P5 in adjusted priority order

**Bottom line**: Phase G did good structural work. But the source pipeline has 3 sources that will silently fail and 1 that will crash. This must be fixed before claiming the source architecture is production-ready.
