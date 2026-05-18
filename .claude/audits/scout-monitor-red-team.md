# Red Team Audit: `tools/scout_monitor.py`

**Date**: 2026-05-17  
**Auditor**: Red Team (Security + Data + Integration)  
**File audited**: `projects/marketmind/tools/scout_monitor.py` (244 lines)  
**Dependencies**: `config/source_authority.py`, `config/settings.py`, `pipeline/scout.py`

---

## Executive Summary

**Verdict: CONDITIONAL** — 2 HIGH-severity issues must be fixed before production use. 5 MEDIUM issues and 5 LOW issues noted. No CRITICAL vulnerabilities found.

The monitor correctly identifies source health changes in the happy path, but has a corrupted-state crash bug, silently skips PRIMARY-tier API sources, and has a first-run false-positive that would trigger spurious "RECOVERED" alerts.

---

## 1. Security

### 1.1 State File Path (SAFE)

```
STATE_FILE = PROJECT_ROOT / "data" / "scout_state.json"
```

Path is computed from `Path(__file__).resolve().parent.parent` (the `marketmind/` directory). No user input touches the path — no path traversal, no arbitrary write.

**Finding**: SAFE. Fixed path, no injection vector.

### 1.2 Source Name Injection (SAFE)

State file writes `{r.name: r.status for r in reports}` where `r.name` originates from `Source.name` field in `source_authority.py`. All source names are hardcoded string literals. Error messages (`str(e)[:100]`, `f"HTTP {r.status_code}"`) are printed to stdout but never written to the state file.

**Finding**: SAFE. No user-controlled data enters persistent storage.

### 1.3 JSON Deserialization (SAFE)

`json.loads()` is used without custom `object_hook` — no deserialization attack surface.

**Finding**: SAFE.

### 1.4 Latent API Key Exposure via `__repr__` (LOW)

`fetch_one()` accepts a `MarketMindConfig` parameter. The `MarketMindConfig` dataclass reads API keys (`DEEPSEEK_API_KEY`, `NEWSAPI_KEY`, `GNEWS_API_KEY`) from environment in its `__init__`. If `repr(config)` were ever logged or printed (e.g., in debug output or an error traceback), API keys would be exposed because `@dataclass` generates a default `__repr__` that includes all fields.

Currently this is not triggered — `config` is accepted but **never used** in `fetch_one()` (see §4.3). However, this is a latent risk if anyone later adds `logger.debug(config)` or similar.

**Finding**: LOW. Latent risk only if config is logged. Mitigation: never log config objects; or add a custom `__repr__` that masks secrets.

### 1.5 RSS Content Handling (SAFE)

RSS summary/description text is only used for length measurement:
```python
s = (e.get("summary") or e.get("description") or "").strip()
total_len += len(re.sub(r"<[^>]+>", "", s))
```

Content is never rendered, stored, or passed to downstream systems.

**Finding**: SAFE. No XSS or content injection risk.

---

## 2. Privacy

### 2.1 API Key Logging (SAFE)

- No API key is logged, printed, or written to the state file.
- HTTP requests include `User-Agent: "MarketMind/0.1 (contact@marketmind.dev)"` — the email is intentionally public.
- RSS URLs in `source_authority.py` contain no credentials.
- Error messages are truncated to 100 chars via `str(e)[:100]`, limiting accidental exposure.

**Finding**: SAFE. No credential leakage.

### 2.2 State File Content (SAFE)

The state file stores only `{"last_run": "<ISO timestamp>", "sources": {"Source Name": "OK/FAILED/..."}}`. No PII, no keys, no article content.

**Finding**: SAFE.

---

## 3. Reliability

### 3.1 Corrupted State File Crash (HIGH)

```python
def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"sources": {}, "last_run": None}
```

**Issue**: No try/except around `json.loads()`. If the state file is corrupted (partial write from crash, disk error, manual edit), the entire monitor crashes with `json.JSONDecodeError`.

**Reproduction**: `echo "{" > data/scout_state.json` then run the monitor.

**Fix**: Wrap in try/except, return default state on parse failure, log the corruption.

### 3.2 Non-Atomic State File Write (MEDIUM)

```python
STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
```

**Issue**: Direct `write_text()` is not atomic. If the process crashes mid-write, the state file is left corrupted or empty, triggering §3.1's crash on next run.

**Fix**: Write to a temp file, then `os.replace()` (atomic on POSIX/Windows):
```python
import tempfile, os
tmp = tempfile.NamedTemporaryFile(mode='w', dir=STATE_FILE.parent,
    prefix='.scout_state.', delete=False, encoding='utf-8')
try:
    json.dump(state, tmp, indent=2, ensure_ascii=False)
    tmp.flush(); os.fsync(tmp.fileno())
finally:
    tmp.close()
os.replace(tmp.name, STATE_FILE)
```

### 3.3 State File Read 35 Times Per Run (MEDIUM)

```python
async def fetch_one(source, config):
    prev = load_state()["sources"].get(source.name, "unknown")  # 35 reads!
```

`load_state()` reads and parses the state file on every `fetch_one()` call. With 35 sources, the file is opened, read, and JSON-parsed 35 times. This wastes I/O and creates a window where concurrent runs could see inconsistent state (see §3.4).

**Fix**: Load state once in `run_monitor()`, pass `prev_statuses` dict to `fetch_one()`.

### 3.4 Concurrent Execution Race (LOW)

If two monitor instances run simultaneously, both read the initial state file, both fetch sources, then both write state — the last writer wins. This could cause flapping alerts (e.g., instance A reports source X as OK, instance B reports it as FAILED, and whichever writes last determines the persisted state).

**Finding**: LOW. Only matters if scheduled + manual runs overlap. File locking would be ideal but is not critical for this use case.

### 3.5 Network Outage Handling (SAFE)

All source fetches are wrapped in `try/except Exception`. Network failures produce individual "FAILED" reports:
```python
except Exception as e:
    return SourceReport(..., "FAILED", prev,
        "NEW_FAILURE" if prev == "OK" else "STABLE",
        str(e)[:100], source.tier == SourceTier.PRIMARY)
```

If the network is down entirely, all 35 sources fail — the report correctly shows this.

**Finding**: SAFE. Broad except is appropriate for health monitoring.

---

## 4. Integration

### 4.1 PRIMARY API Sources Silently Skipped (HIGH)

Sources with `feed_type` in `("api", "bluesky", "bls_api")` are unconditionally skipped:

```python
elif source.feed_type in ("api", "bluesky", "bls_api"):
    return SourceReport(source.name, ..., "API", prev, "STABLE", "API source — skipped", False)
```

Of the 35 total sources, **5 are API-type sources**, including **2 PRIMARY-tier sources** that are critical to investment analysis:

| Source | Tier | feed_type | Impact |
|--------|------|-----------|--------|
| BLS | PRIMARY | bls_api | CPI/PPI/employment data — **never checked** |
| CFTC COT | PRIMARY | api | Commitments of Traders — **never checked** |
| NewsAPI | RELIABLE | api | Business headlines — skipped (needs API key) |
| GNews | RELIABLE | api | Business headlines — skipped (needs API key) |
| Bluesky | BEST_EFFORT | bluesky | Social media — skipped |

BLS and CFTC COT are PRIMARY sources. The monitor's report will never show them as FAILED, so a critical data loss (BLS API 503, CFTC site down) would be invisible. This undermines the entire purpose of the CRITICAL alert section.

**Note**: `pipeline/scout.py` handles `bls_api` and `bluesky` by calling their dedicated fetchers (`bls_fetcher.fetch_bls_indicators()`, `social_sources.fetch_bluesky_posts()`). The monitor should do the same, or delegate to `scout.py`'s `fetch_source()`.

**Fix**: Either call the same dedicated fetchers, or delegate to `pipeline/scout.py:fetch_source()` for these types.

### 4.2 Duplicate RSS Fetching Logic (MEDIUM)

`scout_monitor.py:fetch_one()` reimplements RSS fetching that already exists in `pipeline/scout.py:fetch_source()`. Both modules:
- Use `httpx.AsyncClient` with timeout and User-Agent header
- Call `feedparser.parse(resp.text)`
- Iterate `feed.entries`
- Extract `title`, `summary`/`description`

But they do it differently (monitor has a simpler version). Any fix to RSS parsing (e.g., handling a new RSS namespace, adding a header) must be applied in both places.

**Fix**: The monitor should call `scout.fetch_source()` for actual fetching and only add its own health-reporting layer on top.

### 4.3 Dead `--pipeline` Flag and Unused `config` Parameter (MEDIUM)

The docstring and argparse both reference `--pipeline`:
```python
parser.add_argument("--pipeline", action="store_true", help="Called from run_daily pipeline")
```

But `main()` never checks `args.pipeline`. The flag is parsed and discarded. Furthermore, `app.py`'s `run_daily()` only calls `scout.fetch_all_sources()` — it does not call `run_monitor()` or `scout_monitor.py` at all. The pipeline integration stated in the docstring does not exist.

Similarly, the `config: MarketMindConfig` parameter in `fetch_one()` is accepted but never referenced in the function body. `MarketMindConfig()` is instantiated in `run_monitor()` (reading API keys from env) and passed to all 35 `fetch_one()` calls but never used — wasted initialization.

**Fix**: Either wire the integration or remove the dead flag/parameter. If wired, call `run_monitor()` from `app.py:run_daily()` in Step 1 (after scout fetch).

### 4.4 Monitor State Decoupled from Source Objects (MEDIUM)

`Source` dataclass in `source_authority.py` has built-in health fields:
```python
status: SourceStatus = SourceStatus.UNTESTED
last_checked: str | None = None
consecutive_failures: int = 0
```

`pipeline/scout.py` updates these fields after each fetch:
```python
source.status = SourceStatus.WORKING
source.consecutive_failures = 0  # or += 1
source.last_checked = datetime.now(timezone.utc).isoformat()
```

But `scout_monitor.py` ignores these entirely — it maintains a completely separate state file (`scout_state.json`) with its own status strings ("OK"/"FAILED"/"EMPTY"). This creates two parallel truth-sources for source health that can diverge.

**Fix**: Either read `source.status` from the in-memory Source objects (post-scout fetch) instead of maintaining a separate state file, OR update source objects from monitor state.

---

## 5. Correctness

### 5.1 First-Run False "RECOVERED" (MEDIUM)

On first run, `prev = "unknown"` for all sources (state file doesn't exist). The change detection logic:

```python
# For successful sources:
if prev != "OK":
    change = "RECOVERED"  # ← triggered for all working sources on first run

# For failed sources:
change = "NEW_FAILURE" if prev == "OK" else "STABLE"  # ← "STABLE" on first run
```

**Result on first run**: Every working source shows as **RECOVERED** (green), which is semantically wrong — they were never broken. The report gives a misleading "recovered" story.

**Fix**: Check for `prev == "unknown"` first-run state:
```python
if prev == "unknown":
    change = "FIRST_RUN"
elif prev != "OK":
    change = "RECOVERED"
else:
    change = "STABLE"
```

### 5.2 "DEGRADED" Status Never Emitted (LOW)

`SourceStatus.DEGRADED` exists in the enum (value=2) and is used by `pipeline/scout.py`. But `scout_monitor.py` only emits "OK", "FAILED", "EMPTY", "API", "SKIPPED" — never "DEGRADED". The report has a "HEADLINES ONLY" section for sources with `with_content == 0`, which partially covers this case, but the status string itself is always "OK" for working sources with no content.

**Finding**: LOW. The "HEADLINES ONLY" section in the report partially compensates.

### 5.3 `is_critical` Field Redundancy (LOW)

```python
is_critical: bool = source.tier == SourceTier.PRIMARY  # set at construction

# In print_report:
critical = [r for r in reports if r.is_critical and r.status == "FAILED"]
```

`is_critical` is set to `True` for ALL PRIMARY sources regardless of status. Then `print_report()` re-checks `r.status == "FAILED"` to filter. This means `is_critical` is really just `is_primary` and the field name is misleading. The "CRITICAL" report section only shows PRIMARY + FAILED, but the field makes it seem like all PRIMARY sources are critical status.

**Fix**: Rename `is_critical` to `is_primary` or compute `is_critical = source.tier == SourceTier.PRIMARY and status == "FAILED"`.

### 5.4 Edge Case: Empty SOURCES List (LOW)

If `SOURCES` is empty: `asyncio.gather(*[])` returns `[]`. `print_report([])` prints "All sources healthy" — misleading since there are no sources at all.

**Fix**: Check for empty reports: "No sources configured."

### 5.5 `re` Import Inside Function (LOW)

```python
async def fetch_one(source, config):
    import re  # inside hot function, called 35 times
```

Python caches module imports, so this is only a style issue, not a performance one. But it violates PEP 8 (imports at top of file).

**Fix**: Move `import re` to module level (line 16).

### 5.6 `ensure_ascii=False` Unnecessary (LOW)

```python
STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
```

All source names and statuses are ASCII. `ensure_ascii=False` is harmless but unnecessary. If a non-ASCII source name were ever added, `ensure_ascii=False` with `encoding="utf-8"` is correct — so this is fine.

**Finding**: OK as-is.

---

## 6. Summary Table

| # | Severity | Category | Issue | Status |
|---|:---:|---|------|:---:|
| 1 | HIGH | Reliability | `load_state()` crashes on corrupted JSON | Must fix |
| 2 | HIGH | Integration | PRIMARY BLS/CFTC sources never checked (skipped as API) | Must fix |
| 3 | MEDIUM | Reliability | Non-atomic state file write risks corruption | Should fix |
| 4 | MEDIUM | Performance | State file read 35 times (once per source fetch) | Should fix |
| 5 | MEDIUM | Integration | Duplicate RSS logic with `pipeline/scout.py` | Should fix |
| 6 | MEDIUM | Integration | `--pipeline` flag dead, `config` parameter unused | Should fix or wire |
| 7 | MEDIUM | Correctness | First-run false "RECOVERED" for all working sources | Should fix |
| 8 | LOW | Integration | Monitor state decoupled from Source.status fields | Nice to fix |
| 9 | LOW | Security | Latent API key exposure via `MarketMindConfig.__repr__` | Low risk |
| 10 | LOW | Correctness | "DEGRADED" status never emitted | Low impact |
| 11 | LOW | Correctness | `is_critical` field name misleading (means is_primary) | Style |
| 12 | LOW | Correctness | Empty SOURCES list prints "All sources healthy" | Edge case |
| 13 | LOW | Style | `import re` inside function body | Style |

---

## 7. Recommended Fix Priority

### Blockers (before production use)

1. **State file corruption recovery** — wrap `json.loads()` in try/except, return default state on parse failure
2. **PRIMARY API source monitoring** — add actual health checks for BLS and CFTC COT (call their dedicated fetchers or delegate to `scout.py`)

### Strongly Recommended

3. **Atomic state file writes** — temp file + `os.replace()`
4. **Load state once** — move `load_state()` out of `fetch_one()` into `run_monitor()`
5. **First-run detection** — check for `prev == "unknown"` and suppress RECOVERED
6. **Wire or remove** `--pipeline` flag and `config` parameter

### Nice to Have

7. Deduplicate RSS logic with `scout.py`
8. Rename `is_critical` to `is_primary`
9. Move `import re` to module level
10. Handle empty SOURCES edge case

---

## 8. PICA Compliance

| Level | Status | Notes |
|-------|:---:|------|
| PICA-Unit | **MISSING** | No test file exists for `scout_monitor.py` |
| PICA-Security | Covered by this audit | This Red Team report covers security |
| PICA-Integration | Covered by this audit | §4 details all integration gaps |
| PICA-Regression | **MISSING** | Must run full test suite after fixes |

Required before merge: PICA-Unit audit artifact + PICA-Regression audit artifact.
