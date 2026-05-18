# Gate 2/3 Architecture Plan — Security Audit

**Audit type**: Red Team (design-level)
**Date**: 2026-05-18
**Auditor**: AI Red Team Security Agent
**Source**: `.claude/plans/gate23-architecture.md`
**Risk scale**: CRITICAL > HIGH > MEDIUM > LOW

---

## Finding 1: [HIGH] Kelly Formula — No Input Validation on User-Overridden Values

### Exploit scenario

The user can override pre-filled values in the Decision Ticket (Step 3.1). The plan states: "The user fills in missing fields or overrides pre-filled values." The `compute_position_size()` function in the plan takes 8 float parameters with **zero validation** before entering the Kelly formula:

```python
K% = W - (1 - W) / R    where R = avg_gain / avg_loss
```

**Attack vectors**:

1. **Division by zero**: If `avg_loss_pct = 0.0`, then `R → ∞`, `K%` is undefined. Python returns `ZeroDivisionError`, crashing the pipeline. If wrapped in try/except, the crash path may leave the session state file partially written.

2. **Negative size injection**: If `existing_heat > 0.25`, then `heat_adj = (0.25 - 0.30) / 0.25 = -0.20`. This produces a **negative** position size, which could be interpreted as "go short" when the user intended "go long" — a direction flip without user awareness.

3. **Unbounded conviction_score**: If `conviction_score = 1.5` (user fat-fingers), the Half-Kelly could produce `f* > 25%`, exceeding the hard cap. The hard cap is applied *after* the formula — if the cap check has a logic error, oversized positions slip through.

4. **Negative win_probability**: If `win_probability = -0.2` (data corruption upstream), `K% = -0.2 - (1 - (-0.2)) / R = -0.2 - 1.2/R`, which is always negative. This produces a negative position size → direction flip.

### Severity: HIGH

Financial position sizing math with unvalidated user inputs can produce silently wrong allocations. A negative or zero position size from bad inputs is not the same as "no trade" — it's a computation error that could be archived as a valid DecisionTicket.

### Recommended fix

```python
def compute_position_size(...) -> tuple[float, dict]:
    # Validate all inputs BEFORE the formula
    if not (0.0 <= conviction_score <= 1.0):
        raise ValueError(f"conviction_score {conviction_score} out of [0, 1]")
    if not (0.0 <= win_probability <= 1.0):
        raise ValueError(f"win_probability {win_probability} out of [0, 1]")
    if avg_loss_pct <= 0.0:
        raise ValueError(f"avg_loss_pct must be > 0, got {avg_loss_pct}")
    if avg_gain_pct <= 0.0:
        raise ValueError(f"avg_gain_pct must be > 0, got {avg_gain_pct}")
    if not (-1.0 <= correlation_to_portfolio <= 1.0):
        raise ValueError(f"correlation_to_portfolio {correlation_to_portfolio} out of [-1, 1]")
    if not (0.0 <= volatility_percentile <= 1.0):
        raise ValueError(f"volatility_percentile {volatility_percentile} out of [0, 1]")
    if not (0.0 <= existing_heat <= 1.0):
        raise ValueError(f"existing_heat {existing_heat} out of [0, 1]")
    if portfolio_value <= 0:
        raise ValueError(f"portfolio_value must be positive, got {portfolio_value}")
    # ... then compute
```

Also: Gate 3 must present validation failures to the user as actionable errors, not silently clamp values.

---

## Finding 2: [HIGH] DecisionTicket Stores Sensitive Financial Data in Plain JSON

### Exploit scenario

The `DecisionTicket` dataclass (lines 357-396) contains:

| Field | Sensitivity | Why |
|-------|:----------:|-----|
| `position_size_absolute` | HIGH | In account currency — reveals capital deployed |
| `position_size_pct` | HIGH | Combined with `position_size_absolute`, reverse-engineers total portfolio value |
| `stop_loss` | HIGH | Specific exit price — reveals max loss in currency terms |
| `entry_level` | HIGH | Specific entry price |
| `risk_budget_consumed_bp` | HIGH | Basis points of portfolio at risk |
| `conviction_score` | MEDIUM | Internal decision confidence |
| `correlation_to_portfolio` | MEDIUM | Portfolio construction data |
| `existing_heat_pct` | MEDIUM | Reveals other positions' risk profile |

The plan says `DecisionTicket → decision.json (atomic write)` and `DecisionTicket → FTS5 index`. Both destinations store unencrypted JSON on disk.

**Attack**: An attacker with filesystem access to `data/archive/YYYY-MM-DD/gates/gate3_decision.json` can:
1. Read exact position sizes and stop-loss levels
2. Reverse-engineer total portfolio value from `position_size_pct` and `position_size_absolute`
3. Build a complete picture of the user's trading strategy, risk tolerance, and active positions
4. Front-run the user's entries/exits if they have market access

The same data flows into FTS5 full-text search, making it queryable via SQLite — expanding the attack surface.

### Severity: HIGH

This is a local-only application (no network API), so the threat model is local filesystem access. However, the current `archivist.py` writes JSON with default file permissions (inherited from umask). On a multi-user system, this data could be world-readable.

### Recommended fix

1. Set file permissions to `0o600` on all files written under `data/archive/` and `data/sessions/`:
   ```python
   tmp.write_text(...)
   os.chmod(tmp, 0o600)  # before rename
   tmp.replace(filepath)
   ```
2. Consider encrypting `position_size_absolute` and `stop_loss` at rest (Fernet key from environment variable).
3. Do NOT index `position_size_absolute`, `stop_loss`, `entry_level` in FTS5 — these are quantitative values, not searchable text. Index only `ticket_id`, `session_id`, `direction`, `instrument`, `catalyst_description`.

---

## Finding 3: [MEDIUM] ELITE Shadow Content — No Markdown Sanitization Before Gate 2 Display

### Exploit scenario

ELITE shadows analyze news **independently** (same daily cycle as main AI) and store pre-computed analysis in `EliteRegistry`. During Gate 2 Step 2.2, matching shadows are "awakened" and their content is displayed:

```
── SHADOW OPINION ──
[Gold Expert · ELITE] — the gold shadow's pre-computed view on the direction
── END SHADOW OPINIONS ──
```

The shadow's pre-computed view is rendered inline. If the terminal/UI renders Markdown (which it does — the Command Center uses Markdown-formatted output), a shadow whose analysis output contains Markdown control characters could inject formatting into the user's Gate 2 conversation.

**Attack chain**:
1. A shadow is fed maliciously crafted news text (e.g., from a compromised RSS feed or a fake news article with embedded Markdown)
2. The shadow's LLM analysis echoes the injected Markdown into its opinion text
3. During Gate 2, the shadow opinion is rendered, and the injected Markdown creates a fake heading, code block, or link
4. The user could be misled by visually-authoritative formatting (e.g., `# CONFIRMED: Direction is CORRECT` rendered as a large heading)

**Mitigation already in place**: The `GateArchiver` wraps user content in `<!-- USER_TEXT_START/END -->` HTML comments (C1 mitigation). But **shadow opinions are AI content** and are NOT wrapped. The `gate_archiver.py` only wraps `speaker="USER"` content and `content_type="system_decision"` content. Shadow opinions would be `speaker="AI"`, `type="shadow_opinion"` — passing through unsanitized.

### Severity: MEDIUM

Requires (a) a compromised news source that a specific shadow ingests AND (b) the LLM echoing the injected Markdown into its output. The attack surface is narrow but real. The visual impact on user decision-making is the primary concern — a fake "strong conviction" visual cue could nudge the user toward a bad trade.

### Recommended fix

1. Apply `_escape_markdown()` from `input_guard.py` to all shadow opinion text before display in Gate 2.
2. Add a new `content_type` for shadow opinions (e.g., `"shadow_opinion"`) and wrap them in `<!-- SHADOW_OPINION_START/END -->` in the Markdown archive, following the same pattern as user content.
3. Consider a line-length cap on shadow opinion display (e.g., max 300 chars in the table, with "expand for full" option).

---

## Finding 4: [MEDIUM] Gate 2 Direction Text — Keyword Bomb Triggers All ELITE Shadows

### Exploit scenario

Gate 2 Step 2.2: The `EliteRegistry` matches the user's `selected_direction` text from Gate 1 against `DOMAIN_KEYWORDS` using substring matching. If a user (or a compromised Gate 1 session file) crafts a direction text that contains ALL domain keywords:

```
"I want to trade gold bitcoin oil bonds SPY VIX China tech banks pharma retail industrial macro steel REIT"
```

...this triggers **every ELITE shadow** simultaneously. Consequences:
1. The Gate 2 display floods the user with 15+ shadow opinions, overwhelming the evidence summary
2. If ELITE shadows consume LLM quota when "awakened" (even if pre-computed, surfacing them has a display cost), this could be a DoS vector
3. A malicious session file edit could inject this keyword-bomb direction, and on resume (`--mode gate2`), the user sees a flood of shadow content

### Severity: MEDIUM

This is a UX/display DoS, not a data breach. But it could be used to obscure a specific shadow's dissent by flooding the user with too many opinions to read carefully.

### Recommended fix

1. Cap the number of awakened ELITE shadows per Gate 2 session (e.g., max 5). If more than 5 match, show the top 5 by domain-keyword-relevance score.
2. Log a warning if >50% of registered domains match — this is anomalous and should trigger review.
3. Display: "7 of 15 ELITE shadows matched (showing top 5 by relevance)" with expand-for-all option.

---

## Finding 5: [MEDIUM] Pre-Trade Checklist — External Data Dependency Without Integrity Verification

### Exploit scenario

Step 3.5 checklist includes:

| Check | Source | Risk |
|-------|--------|------|
| Entry level within market range | `market_data: dict` | If market data API returns stale/cached/manipulated prices, entry validation passes on bad data |
| Stop-loss above fragility zone | `fragility_scanner.py` | Fragility thresholds are versioned config — if config file is tampered with, stop-loss validation is bypassed |
| No conflicting open positions | `PortfolioSnapshot` | Source unclear — if this is `input/account_state.json` (a user-editable file), the user can delete conflicting positions to pass the check |

The `market_data` dict is passed into `run_gate3()` from the caller. The plan does not specify:
- How fresh the market data must be (staleness tolerance)
- Whether a data source integrity check runs before checklist execution
- What happens if market data is unavailable (does the check fail-open or fail-closed?)

**Attack**: If `market_data` is fetched from a cache that's 24+ hours stale (e.g., the pipeline ran overnight, market data refreshed at open, but Gate 3 runs mid-session), the entry level validation uses yesterday's price. An entry 5% away from yesterday's close could be 10%+ away from today's open — the check passes but the price is stale.

### Severity: MEDIUM

Requires coordination of stale data + volatile market conditions to exploit. The 5% threshold provides some buffer, but after-hours gaps (earnings, Fed statements) can exceed 5%.

### Recommended fix

1. Add a `market_data_timestamp` field to the `market_data` dict. The checklist must verify `now - timestamp < MAX_STALENESS` (default: 300 seconds / 5 minutes) before using prices.
2. If market data is stale, fail the checklist check with a clear warning: "Market data is X minutes old — entry validation deferred. Refresh data and re-run."
3. The `PortfolioSnapshot` source must be documented explicitly — if it comes from `input/account_state.json`, add an integrity hash check against the last known state.

---

## Finding 6: [LOW] Gate 2/3 Checkpoint Files — Atomic Writes Already Exist, But New Data Types Need Registration

### Analysis

The existing infrastructure already handles atomic writes correctly:

- `SessionManager.save()` (session.py:53-60): temp file → rename ✅
- `MarketMindArchive.save_json()` (archivist.py:47-55): temp file → rename ✅
- `GateArchiver.log_decision()` (gate_archiver.py:109-126): delegates to `save_json()` ✅

The plan calls `save_gate2_checkpoint(gate2_record)` and `save_gate3_checkpoint(decision_ticket)` — these are wrapper functions that need to be implemented. They will call the existing atomic-write infrastructure. **No new atomic write gaps are introduced.**

However, one concern: the `GateArchiver.log_turn()` JSONL append (gate_archiver.py:93-100) uses a validate-then-append pattern rather than atomic rename. This is acceptable for append-only logs (JSONL), but if a crash occurs between the tmp validation and the append, the tmp file lingers. The `tmp.unlink(missing_ok=True)` cleanup is at line 100, but if the process dies at line 98 (the `open/append`), the tmp file remains on disk and the next `log_turn()` call will overwrite it — which is safe but leaves stale tmp files.

### Severity: LOW

No new atomic write gaps. Existing pattern is sound. The tmp file accumulation is a minor housekeeping concern, not a security issue.

### Recommended fix

Add a cleanup step in `GateArchiver.start_session()` that removes any orphaned `.tmp` files in the gates directory. This is hygiene, not security-critical.

---

## Finding 7: [LOW] Session Resume — No Integrity Check on Checkpoint Files

### Exploit scenario

The plan adds `--mode gate2 --session-id <id>` and `--mode gate3 --session-id <id>` resume modes. On resume, `SessionManager.load(session_id)` reads the checkpoint JSON. If an attacker modifies the checkpoint file between sessions:

1. Change `gate1.data.selected_direction` to a different direction → Gate 2 displays evidence for the wrong thesis
2. Change `gate2.data.conviction_level` from "WEAK" to "STRONG" → Gate 3 uses inflated conviction in position sizing
3. Change `gate2.data.kill_criteria` to remove a critical criterion → no kill switch on the position

The `SessionManager.load()` has graceful corruption recovery (catches `JSONDecodeError`), but no integrity verification. A valid JSON file with tampered values loads successfully.

### Severity: LOW

Requires filesystem access to `data/sessions/`. On a single-user machine, this is self-sabotage. On a shared machine, this is a valid concern.

### Recommended fix

1. Add an HMAC or content hash to the session checkpoint file on save.
2. On load, verify the hash matches. If not, reject the load and log a warning.
3. For resumption, display the checkpoint data to the user and confirm before proceeding: "Resuming Gate 2 with direction: X. Proceed? (y/n)"

---

## Summary

| # | Finding | Severity | Category |
|---|---------|:--------:|----------|
| 1 | Kelly formula: no input validation on user-overridden values | **HIGH** | Input validation |
| 2 | DecisionTicket: sensitive financial data in plain JSON | **HIGH** | Data at rest |
| 3 | ELITE shadow content: no Markdown sanitization before display | MEDIUM | Injection |
| 4 | Direction text keyword bomb triggers all shadows | MEDIUM | DoS / UI flooding |
| 5 | Pre-trade checklist: external data without integrity verification | MEDIUM | Data integrity |
| 6 | Gate 2/3 checkpoint files: no new atomic write gaps | LOW | Storage |
| 7 | Session resume: no integrity check on checkpoint files | LOW | Tampering |

### Pre-implementation requirements

Before Phase 1 implementation begins:

1. **Finding 1 (HIGH)**: Add input validation to `compute_position_size()` signature in the plan. All 8 parameters must be range-checked before the Kelly formula executes.
2. **Finding 2 (HIGH)**: Document file permission requirements (0o600) for all files under `data/archive/` and `data/sessions/`. Add `os.chmod` calls to `archivist.py` and `session.py`.
3. **Finding 3 (MEDIUM)**: Add shadow opinion Markdown escaping and content-type wrapping to `gate2_interaction.py` design.
4. **Finding 4 (MEDIUM)**: Add ELITE shadow awakening cap (max 5) to `gate2_interaction.py` design.
5. **Finding 5 (MEDIUM)**: Add market data staleness check and timestamp validation to `pre_trade_checklist.py` design.

### Post-implementation verification

After Phase 4 integration, run these specific tests:

- [ ] Kelly formula with `avg_loss_pct=0` → raises ValueError, does not crash pipeline
- [ ] Kelly formula with `existing_heat=0.30` → `heat_adj` clamped, not negative
- [ ] DecisionTicket JSON on disk has `0o600` permissions (Windows: check ACL)
- [ ] Shadow opinion containing ``# Fake Heading`` renders as literal text, not a heading
- [ ] Direction text with 15+ domain keywords → max 5 shadows surfaced, warning logged
- [ ] Market data 10 minutes stale → checklist entry-level check fails with clear message
- [ ] Tampered session checkpoint → load rejected or user warned
