# MarketMind Notification System & Evolution Tracking — Design Spec

**Date**: 2026-05-24 | **Status**: Draft | **Type**: enhance

---

## Overview

Three independent but coordinated deliverables:

| # | System | Goal | UI |
|:--:|------|------|------|
| 1 | **AlertManager** | Real-time degradation/error notification with impact scope + action advice | Dashboard bell + toast + scroll log |
| 2 | **Evolution Tracking** | Quantify improvement over time for shadows + main pipeline, detect stagnation | Separate `/evolution` page |
| 3 | **max_token Fix** | Ensure Pro model thinking is never truncated by low token limits | Backend only |

---

## 1. AlertManager

### 1.1 Architecture

```
Pipeline Stages / Gateway / Shadows
        │
        ├── @monitor decorator (auto: exception, empty return, timeout)
        │
        ├── emit_alert() manual (deep: JSON fallback, fallback routing, budget exhausted)
        │
        ▼
   AlertManager (dedup, group, route, rate-limit, persist)
        │
        ├── Sanitize (strip keys/paths/raw bodies before broadcast)
        │
        ├── WebSocket broadcast → Dashboard UI (bell + toast + log)
        │
        ├── Fallback: Python logging (if AlertLog DB unavailable)
        │
        ▼
   AlertLog (persistent storage, reused by Evolution Tracking)
```

### 1.1a Rate Limiting & Dedup

**Dedup algorithm**: Same `source` + same `severity` + `title` prefix match (first 40 chars) within a 60s sliding window → increment `repeat_count` on existing alert, suppress re-broadcast. Only the count-updated event is sent to the UI (not a new alert).

**Rate limiting**: Per-source cooldown — same source + same dedup key within 30s = count incremented, no new broadcast. Global throttle: max 10 alert broadcasts/sec. Max 200 alerts stored per pipeline run; oldest INFO alerts evicted first.

**Frequency escalation**: WARN repeated > 5 times within 10 minutes for the same dedup group → auto-upgrade to ERROR. Counter resets on resolution or manual acknowledgment.

**Alert DB fallback**: If `alerts.db` is locked/corrupt/unavailable, AlertManager falls back to Python `logging.Logger("marketmind.alert")` as secondary channel. Dashboard UI shows "Alert DB Unavailable — logs only" indicator via health endpoint. DB health check runs at AlertManager init and every 60s thereafter; recovery auto-restores DB persistence.

**Sanitization**: Before broadcast, `Alert.detail` and `Alert.title` are scrubbed: API key patterns (`sk-[a-zA-Z0-9]+` → `sk-***`), file system paths (`[A-Z]:\\...` → `[path]`), raw HTTP response bodies truncated to 200 chars max.

### 1.2 Alert Schema

```python
@dataclass
class Alert:
    id: str                    # uuid, unique
    severity: Severity         # INFO | WARN | ERROR | CRITICAL
    source: str                # module name (e.g. "l1_narrative", "shadow_07")
    impact_scope: ImpactScope  # MAIN_PIPELINE | SHADOW_SYSTEM | INFRASTRUCTURE | NONE
    title: str                 # one-line summary
    detail: str                # what happened
    action_advice: str         # "需要修复" | "影子弹窗" | "仅通知，无需操作" | "检查数据源"
    degraded_output: bool      # True if output quality is affected
    timestamp: datetime
    resolved: bool = False
```

### 1.3 Severity Levels

| Level | Definition | UI Behavior |
|:--:|------|------|
| **CRITICAL** | Pipeline core output corrupted — analysis result unreliable | Persistent banner top of Dashboard + manual dismiss required |
| **ERROR** | Stage/shadow failed but pipeline continues | Toast (auto-dismiss 30s) + bell badge |
| **WARN** | Degradation with auto-recovery (JSON from reasoning, fallback provider, retry success) | Bell badge only, no popup |
| **INFO** | Normal operation (stage start/end, token usage summary, shadow graduation) | Scroll log only |

### 1.4 Impact Scope

| Scope | Meaning |
|:--:|------|
| MAIN_PIPELINE | Affects final analysis quality — pay attention |
| SHADOW_SYSTEM | Affects specific shadow(s) — shadow owner should check |
| INFRASTRUCTURE | API key, network, file system — needs ops fix |
| NONE | Informational only — no action needed |

### 1.5 Covered Scenarios

From RESTART_GUIDE + discussion:

| # | Scenario | Severity | Impact Scope |
|:--:|------|:--:|:--:|
| 1 | Content empty → JSON extracted from reasoning (success) | WARN | MAIN_PIPELINE |
| 2 | Content empty + reasoning empty → cannot recover | ERROR | MAIN_PIPELINE |
| 3 | Float parse failure in JSON parsing | ERROR | MAIN_PIPELINE |
| 4 | API 429 → key rotated (success) | WARN | INFRASTRUCTURE |
| 5 | API 429 → all keys exhausted → circuit OPEN → fallback | ERROR | INFRASTRUCTURE |
| 6 | Budget exhausted (Pro calls) | CRITICAL | MAIN_PIPELINE |
| 7 | Stage returns empty/None result | ERROR | MAIN_PIPELINE |
| 8 | Shadow timeout (single) | WARN | SHADOW_SYSTEM |
| 9 | Shadow timeout (multiple >30%) | ERROR | SHADOW_SYSTEM |
| 10 | File missing (config, template, data) | ERROR | INFRASTRUCTURE |
| 11 | Fallback provider routed | WARN | INFRASTRUCTURE |
| 12 | Circuit breaker state change | WARN | INFRASTRUCTURE |
| 13 | Pipeline step skipped unexpectedly | ERROR | MAIN_PIPELINE |
| 14 | ELITE shadow failed to load domain knowledge | WARN | SHADOW_SYSTEM |
| 15 | WebSocket client disconnected | INFO | NONE |
| 16 | Stage completed successfully | INFO | NONE |
| 17 | Shadow step skipped (never dispatched) | ERROR | SHADOW_SYSTEM |

### 1.6 Decorator Pattern

```python
@monitor(source="l1_narrative", impact=ImpactScope.MAIN_PIPELINE)
async def analyze_l1(data, config):
    ...
```

Auto-captures: exception, empty return (None / ""), timeout (> N seconds). Manual `emit_alert()` for internal degradation (budget, JSON fallback, fallback routing).

### 1.7 UI Components

**Notification Bell** (Dashboard header):
- Always visible, right side of header bar
- Badge: colored dot + count (red=CRITICAL, amber=ERROR, no badge for WARN/INFO)
- Click → expand dropdown: last 20 alerts, sorted by severity then time
- Each entry: icon + title + timestamp + source tag + action link

**Critical Banner** (below header):
- Red background strip, full width
- Shows active CRITICAL alert text + dismiss button
- Persists until manually dismissed or resolved

**Scroll Log** (Dashboard bottom panel):
- Collapsible, height ~120px
- All alerts in chronological order
- Color-coded severity icons
- Auto-scrolls to latest on new entry

**Toast** (upper-right corner):
- ERROR only
- Slide-in, auto-dismiss 30s
- Shows title + action_advice

---

## 2. Evolution Tracking Panel

### 2.1 Architecture

```
AlertLog / ShadowStateDB / Pipeline Archive
        │
        ▼
   EvolutionMetrics (compute: Sharpe trends, DSR/PBO, PSI, CUSUM, stagnation scores)
        │
        ▼
   /evolution API endpoints
        │
        ▼
   evolution.html (separate page, not embedded in Dashboard)
```

### 2.2 Shadow Metrics (individual + aggregate)

| Metric | Source | Update Frequency |
|------|------|:--:|
| Win Rate | ShadowStateDB trades | Daily |
| Total Return | ShadowStateDB PnL | Daily |
| Sharpe Ratio | ShadowStateDB daily returns | Daily |
| Sortino Ratio | ShadowStateDB daily returns | Daily |
| Max Drawdown | ShadowStateDB PnL | Daily |
| PSR (Probabilistic Sharpe Ratio) | ranking_stats.py | Weekly |
| GPR (Gain-to-Pain Ratio) | graduation_metrics.py | Weekly |
| Grade (Normal/Excel/ELITE/Graduated) | graduation_engine.py | Weekly |
| Stagnation Score (composite) | CUSUM + PSI + trend | Weekly |

### 2.3 Main Pipeline Metrics

| Metric | Source | Update Frequency |
|------|------|:--:|
| Direction Accuracy | Post-hoc verification vs actual market | Weekly/Monthly |
| Price Target Hit Rate | Decision archive vs actual prices | Monthly |
| Red Team "No Valid Objection" Rate | Red Team reports | Weekly |
| Degradation Frequency | AlertLog (ERROR+CRITICAL count / total stages) | Daily |
| Review Loop Closure Rate | % of Red Team findings fixed in next cycle | Weekly |
| DSR/PBO Trend | resonance.py historical | Weekly |

### 2.4 Stagnation Detection

Three signals combined:

1. **CUSUM** on rolling Sharpe — detects small sustained performance shifts
2. **PSI** (Population Stability Index) on trade distributions — detects regime drift
3. **Linear trend test** on win rate — p > 0.05 sustained = plateau

Composite Stagnation Score:
- **Green** (< 0.3): Healthy, improving or stable
- **Yellow** (0.3-0.6): Watch — one signal triggered
- **Red** (> 0.6): Stagnant — needs review and intervention

### 2.5 UI Layout

**Top Bar**: Page title + "Last Updated: ..." + Refresh button

**Section A — Shadow Evolution Overview** (top half):
- 5x5 small-multiples grid (one cell per shadow)
- Each cell: 4 mini sparklines (Sharpe, Win Rate, Grade, Stagnation) comparing baseline → last week → last month → now
- Cell border color: green (improving) / grey (stable) / red (declining)
- Click cell → expand individual shadow deep-dive

**Section B — Shadow Aggregate Trend** (middle):
- Aggregate equity curve (top panel) + drawdown overlay (bottom panel)
- Vertical bands: "Baseline", "Last Month", "Last Week", "Now"
- Delta summary row: 4 metric cards showing current vs each reference period

**Section C — Main Pipeline Evolution** (bottom half):
- Direction Accuracy trend line (rolling 30-day window)
- Degradation Frequency bar chart (daily errors per run)
- Red Team metrics: challenge count trend + closure rate gauge
- Stagnation Score traffic light (green/yellow/red) with last signal change date

**Section D — Comparison Table** (collapsible):
- Columns: Shadow Name | Baseline Sharpe | Last Week | Last Month | Now | Δ% | Stagnation
- Heat-encoded Δ% column (red-white-green diverging scale)
- Sortable by any column

### 2.6 Data Storage

- **AlertLog**: SQLite table in `data/alerts.db`, shared with AlertManager
- **Pipeline Metrics**: New SQLite table in `data/evolution.db` — weekly snapshots
- **Historical Baselines**: First-week snapshots stored as permanent baseline records

---

## 3. max_token Fix

### 3.1 Strategy

Remove explicit `max_tokens=` overrides from Pro calls where the value is < 8192. Let `chat_pro()` default (32768) apply instead. For Flash calls where output is genuinely short (classification, topic naming), keep explicit low values since Flash has no thinking overhead.

### 3.2 Fix Priority

| Priority | File | Line(s) | Current | Action |
|:--:|------|:--:|:--:|------|
| **P0** | `pipeline/l2_interactive.py` | 401, 420 | 512 | Remove override OR raise to 2048 + disable reasoning |
| **P0** | `pipeline/l3_interactive.py` | 126 | 512 | Same as above |
| **P1** | `pipeline/causal_decomposition.py` | 203 | 1024 | Remove override |
| **P1** | `pipeline/flow_decomposition.py` | 165 | 1024 | Remove override |
| **P1** | `pipeline/hvr_cycle.py` | 132 | 1536 | Remove override |
| **P1** | `pipeline/causal_review.py` | 82 | 2048 | Remove override |
| **P1** | `pipeline/reflection_agent.py` | 143 | 2048 | Remove override |
| **P2** | `integrity/fact_checker.py` | 58 | 4096 | Remove override |
| **P2** | `pipeline/investigation_loop.py` | 270, 345 | 4096 | Remove override |
| **P2** | `pipeline/scenario_forecaster.py` | 211, 274 | 4096 | Remove override |

### 3.3 Non-Fix (Keep)

| File | Line | Reason to Keep |
|------|:--:|------|
| `figure_signal.py` | 306 (128) | Flash binary classification — no thinking |
| `cluster_synthesis.py` | 130 (256) | Flash topic naming — short output |
| `causal_chains.py` | 70 (1024) | Flash cross-cluster detection |
| `l1_data_mining.py` | 43 (1024) | Flash data mining |
| `methodology_attribution.py` | 72 (1024) | Flash attribution |
| `reflection_agent.py` | 124 (1024) | Flash success reflection |
| `flash_preprocessor.py` | 88, 113 | Flash preprocessing |
| `investigation_loop.py` | 149 (4096) | Flash narrative |

---

## 4. Implementation Order

| Phase | What | Est. Effort |
|:--:|------|:--:|
| 1 | AlertManager core (schema, emit, dedup, route) | 1 module |
| 2 | `@monitor` decorator | 1 module |
| 3 | Alert API endpoints + WebSocket integration | api/ changes |
| 4 | Dashboard UI: bell, toast, banner, scroll log | dashboard.html + static |
| 5 | max_token fixes (13 lines changed) | existing files |
| 6 | Evolution data model + snapshot storage | 1 module + db |
| 7 | Evolution metrics compute (CUSUM, PSI, trend) | 1 module |
| 8 | Evolution API endpoints | api/ changes |
| 9 | Evolution UI page | new evolution.html |
| 10 | Integration test + regression verification | tests/ |

---

## 5. Design Decisions (from discussion)

1. **Severity: 4-level** (INFO/WARN/ERROR/CRITICAL) — user confirmed
2. **Impact scope on every alert** — user confirmed (MAIN_PIPELINE/SHADOW_SYSTEM/INFRASTRUCTURE/NONE)
3. **Action advice required** — user confirmed ("需要修复" / "仅通知" / etc.)
4. **Alert + Evolution = separate systems, separate pages** — user confirmed
5. **Notification granularity: mid-level** (stage/shadow) with deep info in detail field — user confirmed
6. **Red Team review: 1 agent** (medium complexity, single reviewer sufficient) — self-determined
7. **Decorator + manual emit hybrid** — self-determined, user agreed the approach
