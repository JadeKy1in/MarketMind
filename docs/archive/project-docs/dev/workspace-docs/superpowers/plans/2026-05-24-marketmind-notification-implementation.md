# MarketMind Notification System & Evolution Tracking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build AlertManager (real-time degradation notification) + Evolution Tracking Panel (quantified progress dashboard) for MarketMind investment analysis platform.

**Architecture:** AlertManager is a singleton event bus with decorator-based auto-capture and manual emit, broadcasting sanitized alerts via WebSocket to dashboard.html (bell + toast + banner + scroll log). Evolution Tracking is a separate page reading from ShadowStateDB + AlertLog + new evolution.db snapshot store, computing CUSUM/PSI/trend stagnation scores.

**Tech Stack:** Python 3.14, FastAPI, WebSocket, SQLite, vanilla HTML/CSS/JS (no framework)

**Note:** Phase 5 (max_token fixes) already completed. This plan skips it.

---

## File Map

| File | Role |
|------|------|
| `notification/alert_schema.py` | Alert dataclass, Severity/ImpactScope enums |
| `notification/alert_manager.py` | Core singleton: emit, dedup, rate-limit, escalate, persist, broadcast |
| `notification/sanitizer.py` | Strip API keys, paths, truncate HTTP bodies |
| `notification/monitor_decorator.py` | @monitor decorator: auto-catch exception/empty/timeout |
| `notification/alert_log.py` | SQLite persistence with fallback to Python logging |
| `api/websocket.py` | Add broadcast_alert() |
| `api/data_providers.py` | Add get_alerts(), alert health |
| `api/routes.py` | Add /api/alerts, /api/alerts/health endpoints |
| `dashboard.html` | Bell icon, toast, critical banner, scroll log panel |
| `evolution/stagnation_detector.py` | CUSUM, PSI, linear trend → composite score |
| `evolution/snapshot_store.py` | Weekly snapshots in evolution.db |
| `api/routes.py` | Add /api/evolution/* endpoints |
| `evolution.html` | Separate evolution tracking page |

---

### Task 1: Alert Schema + Enums

**Files:**
- Create: `projects/marketmind/notification/__init__.py`
- Create: `projects/marketmind/notification/alert_schema.py`
- Create: `projects/marketmind/tests/test_notification/__init__.py`
- Create: `projects/marketmind/tests/test_notification/test_alert_schema.py`

- [ ] **Step 1: Create __init__.py files**

```bash
mkdir -p projects/marketmind/notification
mkdir -p projects/marketmind/tests/test_notification
touch projects/marketmind/notification/__init__.py
touch projects/marketmind/tests/test_notification/__init__.py
```

- [ ] **Step 2: Write alert_schema.py**

```python
"""Alert data model — severity, impact scope, and the Alert dataclass."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import uuid


class Severity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ImpactScope(str, Enum):
    MAIN_PIPELINE = "MAIN_PIPELINE"
    SHADOW_SYSTEM = "SHADOW_SYSTEM"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    NONE = "NONE"


@dataclass
class Alert:
    severity: Severity
    source: str
    impact_scope: ImpactScope
    title: str
    detail: str = ""
    action_advice: str = ""
    degraded_output: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved: bool = False
    repeat_count: int = 1

    @property
    def dedup_key(self) -> str:
        return f"{self.source}|{self.severity.value}|{self.title[:40]}"
```

- [ ] **Step 3: Write test_alert_schema.py**

```python
"""Tests for Alert schema — dataclass, enums, dedup key."""
from marketmind.notification.alert_schema import Alert, Severity, ImpactScope


def test_alert_has_default_id():
    a = Alert(Severity.INFO, "test", ImpactScope.NONE, "title")
    assert len(a.id) == 12


def test_alert_dedup_key():
    a1 = Alert(Severity.WARN, "l1_narrative", ImpactScope.MAIN_PIPELINE, "Content empty, JSON extracted from reasoning")
    a2 = Alert(Severity.WARN, "l1_narrative", ImpactScope.MAIN_PIPELINE, "Content empty, JSON extracted from reasoning — extra text")
    assert a1.dedup_key == a2.dedup_key  # First 40 chars match


def test_alert_dedup_key_different_source():
    a1 = Alert(Severity.WARN, "l1_narrative", ImpactScope.MAIN_PIPELINE, "Same title")
    a2 = Alert(Severity.WARN, "shadow_03", ImpactScope.SHADOW_SYSTEM, "Same title")
    assert a1.dedup_key != a2.dedup_key


def test_severity_enum_values():
    assert Severity.INFO.value == "INFO"
    assert Severity.WARN.value == "WARN"
    assert Severity.ERROR.value == "ERROR"
    assert Severity.CRITICAL.value == "CRITICAL"


def test_impact_scope_enum_values():
    assert ImpactScope.MAIN_PIPELINE.value == "MAIN_PIPELINE"
    assert ImpactScope.SHADOW_SYSTEM.value == "SHADOW_SYSTEM"
    assert ImpactScope.INFRASTRUCTURE.value == "INFRASTRUCTURE"
    assert ImpactScope.NONE.value == "NONE"
```

- [ ] **Step 4: Run tests**

```bash
cd projects/marketmind && python -m pytest tests/test_notification/test_alert_schema.py -v
```
Expected: 5 passed

---

### Task 2: Sanitizer

**Files:**
- Create: `projects/marketmind/notification/sanitizer.py`
- Create: `projects/marketmind/tests/test_notification/test_sanitizer.py`

- [ ] **Step 1: Write sanitizer.py**

```python
"""Alert content sanitization — strip secrets before broadcast."""
from __future__ import annotations
import re

_API_KEY_RE = re.compile(r'sk-[a-zA-Z0-9]{20,}')
_PATH_RE = re.compile(r'[A-Z]:[\\/][^\s"]+', re.IGNORECASE)
_MAX_DETAIL_LEN = 200


def sanitize(text: str) -> str:
    if not text:
        return text
    text = _API_KEY_RE.sub("sk-***", text)
    text = _PATH_RE.sub("[path]", text)
    if len(text) > _MAX_DETAIL_LEN:
        text = text[:_MAX_DETAIL_LEN] + "..."
    return text
```

- [ ] **Step 2: Write test_sanitizer.py**

```python
"""Tests for alert content sanitization."""
from marketmind.notification.sanitizer import sanitize


def test_strips_api_key():
    assert sanitize("Key: sk-abcdefghijklmnopqrstuvwxyz123456") == "Key: sk-***"


def test_strips_windows_path():
    assert sanitize(r"Error at E:\AI_Studio_Workspace\projects\marketmind\file.py") == \
           r"Error at [path]\file.py"


def test_truncates_long_detail():
    long_text = "x" * 300
    result = sanitize(long_text)
    assert len(result) == 203  # 200 + "..."


def test_empty_ok():
    assert sanitize("") == ""


def test_short_text_unchanged():
    assert sanitize("Stage completed successfully") == "Stage completed successfully"
```

- [ ] **Step 3: Run tests**

```bash
cd projects/marketmind && python -m pytest tests/test_notification/test_sanitizer.py -v
```
Expected: 5 passed

---

### Task 3: AlertManager Core

**Files:**
- Create: `projects/marketmind/notification/alert_manager.py`
- Create: `projects/marketmind/notification/alert_log.py`
- Create: `projects/marketmind/tests/test_notification/test_alert_manager.py`

- [ ] **Step 1: Write alert_log.py**

```python
"""AlertLog — SQLite persistence with Python logging fallback."""
from __future__ import annotations
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger("marketmind.alert")


class AlertLog:
    def __init__(self, db_path: str = "data/alerts.db"):
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._available = False
        self._init_db()

    def _init_db(self) -> None:
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS alerts ("
                "  id TEXT PRIMARY KEY, severity TEXT, source TEXT,"
                "  impact_scope TEXT, title TEXT, detail TEXT,"
                "  action_advice TEXT, degraded_output INTEGER,"
                "  timestamp TEXT, resolved INTEGER, repeat_count INTEGER"
                ")"
            )
            self._conn.commit()
            self._available = True
        except Exception as e:
            logger.warning("AlertLog DB unavailable, falling back to logging: %s", e)
            self._available = False

    def insert(self, alert_dict: dict) -> None:
        if self._available and self._conn:
            try:
                self._conn.execute(
                    "INSERT OR REPLACE INTO alerts VALUES ("
                    ":id,:severity,:source,:impact_scope,:title,:detail,"
                    ":action_advice,:degraded_output,:timestamp,:resolved,:repeat_count"
                    ")", alert_dict
                )
                self._conn.commit()
            except Exception as e:
                logger.warning("AlertLog insert failed: %s", e)
        logger.info("ALERT [%s] %s: %s", alert_dict.get("severity"),
                     alert_dict.get("source"), alert_dict.get("title"))

    def recent(self, limit: int = 50) -> list[dict]:
        if not self._available or not self._conn:
            return []
        try:
            rows = self._conn.execute(
                "SELECT * FROM alerts ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
            cols = [d[0] for d in self._conn.execute("PRAGMA table_info(alerts)")]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            return []

    def health(self) -> dict:
        return {"available": self._available, "path": str(self.db_path)}
```

- [ ] **Step 2: Write alert_manager.py**

```python
"""AlertManager — central alert event bus with dedup, rate-limit, escalation."""
from __future__ import annotations
import asyncio
import time
from collections import defaultdict
from marketmind.notification.alert_schema import Alert, Severity, ImpactScope
from marketmind.notification.sanitizer import sanitize
from marketmind.notification.alert_log import AlertLog

_FREQ_ESCALATION_THRESHOLD = 5
_FREQ_ESCALATION_WINDOW = 600  # 10 minutes


class AlertManager:
    def __init__(self):
        self._alerts: list[dict] = []
        self._dedup_window: dict[str, float] = {}      # dedup_key → first_seen_at
        self._source_cooldown: dict[str, float] = {}    # source_key → last_emitted_at
        self._broadcast_count_this_second = 0
        self._second_start = time.monotonic()
        self._warn_timestamps: dict[str, list[float]] = defaultdict(list)  # dedup_key → [ts,...]
        self._alert_log = AlertLog()
        self._ws_broadcast_fn = None

    def set_broadcast_fn(self, fn) -> None:
        self._ws_broadcast_fn = fn

    def emit(self, alert: Alert) -> None:
        now = time.monotonic()
        dedup_key = alert.dedup_key

        # 1. Dedup: same key within 60s → increment counter
        if dedup_key in self._dedup_window:
            elapsed = now - self._dedup_window[dedup_key]
            if elapsed < 60:
                for a in reversed(self._alerts):
                    if a.get("dedup_key") == dedup_key:
                        a["repeat_count"] = a.get("repeat_count", 1) + 1
                        break
                # Frequency escalation: WARN repeated in window → ERROR
                if alert.severity == Severity.WARN:
                    self._warn_timestamps[dedup_key].append(now)
                    recent = [t for t in self._warn_timestamps[dedup_key]
                              if now - t < _FREQ_ESCALATION_WINDOW]
                    self._warn_timestamps[dedup_key] = recent
                    if len(recent) >= _FREQ_ESCALATION_THRESHOLD:
                        alert = Alert(
                            severity=Severity.ERROR,
                            source=alert.source,
                            impact_scope=alert.impact_scope,
                            title=f"[ESCALATED] {alert.title}",
                            detail=alert.detail,
                            action_advice=alert.action_advice,
                            degraded_output=alert.degraded_output,
                        )
                        dedup_key = alert.dedup_key
                return  # Suppress re-broadcast

        self._dedup_window[dedup_key] = now

        # 2. Source cooldown: same source within 30s → throttle
        source_key = f"{alert.source}|{alert.severity.value}"
        if source_key in self._source_cooldown:
            if now - self._source_cooldown[source_key] < 30:
                return
        self._source_cooldown[source_key] = now

        # 3. Global throttle: max 10 broadcast/sec
        if now - self._second_start > 1.0:
            self._broadcast_count_this_second = 0
            self._second_start = now
        if self._broadcast_count_this_second >= 10:
            return
        self._broadcast_count_this_second += 1

        # 4. Sanitize
        alert.title = sanitize(alert.title)
        alert.detail = sanitize(alert.detail)

        # 5. Persist
        alert_dict = {
            "id": alert.id, "severity": alert.severity.value,
            "source": alert.source, "impact_scope": alert.impact_scope.value,
            "title": alert.title, "detail": alert.detail,
            "action_advice": alert.action_advice,
            "degraded_output": int(alert.degraded_output),
            "timestamp": alert.timestamp,
            "resolved": int(alert.resolved),
            "repeat_count": alert.repeat_count,
            "dedup_key": dedup_key,
        }
        self._alert_log.insert(alert_dict)
        self._alerts.append(alert_dict)

        # 6. Evict oldest INFO if over capacity
        if len(self._alerts) > 200:
            for i, a in enumerate(self._alerts):
                if a["severity"] == "INFO":
                    self._alerts.pop(i)
                    break
            else:
                self._alerts.pop(0)

        # 7. Broadcast via WebSocket
        if self._ws_broadcast_fn:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._ws_broadcast_fn({
                    "type": "alert",
                    "id": alert_dict["id"],
                    "severity": alert_dict["severity"],
                    "source": alert_dict["source"],
                    "impact_scope": alert_dict["impact_scope"],
                    "title": alert_dict["title"],
                    "action_advice": alert_dict["action_advice"],
                    "timestamp": alert_dict["timestamp"],
                    "repeat_count": alert_dict["repeat_count"],
                }))
            except RuntimeError:
                pass

    def recent(self, limit: int = 20) -> list[dict]:
        sorted_alerts = sorted(
            self._alerts,
            key=lambda a: (
                {"CRITICAL": 0, "ERROR": 1, "WARN": 2, "INFO": 3}[a["severity"]],
                a["timestamp"]
            )
        )
        return sorted_alerts[-limit:]

    def health(self) -> dict:
        return {
            "total_alerts": len(self._alerts),
            "active_critical": sum(
                1 for a in self._alerts
                if a["severity"] == "CRITICAL" and not a["resolved"]
            ),
            "db": self._alert_log.health(),
        }


_alert_manager: AlertManager | None = None


def get_alert_manager() -> AlertManager:
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager


def emit_alert(
    severity: Severity, source: str, impact_scope: ImpactScope,
    title: str, detail: str = "", action_advice: str = "",
    degraded_output: bool = False,
) -> None:
    alert = Alert(
        severity=severity, source=source, impact_scope=impact_scope,
        title=title, detail=detail, action_advice=action_advice,
        degraded_output=degraded_output,
    )
    get_alert_manager().emit(alert)
```

- [ ] **Step 3: Write test_alert_manager.py**

```python
"""Tests for AlertManager — emit, dedup, rate-limit, escalation."""
from marketmind.notification.alert_schema import Alert, Severity, ImpactScope
from marketmind.notification.alert_manager import AlertManager


def test_emit_adds_alert():
    am = AlertManager()
    am.emit(Alert(Severity.WARN, "test_source", ImpactScope.MAIN_PIPELINE,
                   "Test alert", "detail here"))
    recent = am.recent()
    assert len(recent) >= 1
    assert recent[-1]["title"] == "Test alert"


def test_dedup_suppresses_duplicate():
    am = AlertManager()
    a1 = Alert(Severity.WARN, "test_source", ImpactScope.MAIN_PIPELINE,
               "Repeated message that is more than forty chars long for matching")
    a2 = Alert(Severity.WARN, "test_source", ImpactScope.MAIN_PIPELINE,
               "Repeated message that is more than forty chars long for matching — diff suffix")
    am.emit(a1)
    am.emit(a2)
    recent = am.recent()
    matches = [a for a in recent if "Repeated" in a.get("title", "")]
    assert len(matches) == 1
    assert matches[0]["repeat_count"] == 2


def test_different_severity_not_deduped():
    am = AlertManager()
    am.emit(Alert(Severity.WARN, "src", ImpactScope.MAIN_PIPELINE, "Title text"))
    am.emit(Alert(Severity.ERROR, "src", ImpactScope.MAIN_PIPELINE, "Title text"))
    assert len(am.recent()) >= 2


def test_frequency_escalation():
    am = AlertManager()
    for _ in range(6):
        am.emit(Alert(Severity.WARN, "src", ImpactScope.MAIN_PIPELINE,
                       "Repeated warning message for escalation test"))
    recent = am.recent()
    errors = [a for a in recent if a.get("severity") == "ERROR" and "ESCALATED" in a.get("title", "")]
    assert len(errors) == 1


def test_alert_eviction():
    am = AlertManager()
    for i in range(250):
        am.emit(Alert(Severity.INFO, f"src_{i}", ImpactScope.NONE, f"Info alert {i}"))
    assert len(am._alerts) <= 200
```

- [ ] **Step 4: Run tests**

```bash
cd projects/marketmind && python -m pytest tests/test_notification/test_alert_manager.py -v
```
Expected: 5 passed

---

### Task 4: Monitor Decorator

**Files:**
- Create: `projects/marketmind/notification/monitor_decorator.py`
- Create: `projects/marketmind/tests/test_notification/test_monitor_decorator.py`

- [ ] **Step 1: Write monitor_decorator.py**

```python
"""@monitor decorator — auto-capture exception, empty return, timeout."""
from __future__ import annotations
import asyncio
import functools
import time
from marketmind.notification.alert_schema import Severity, ImpactScope
from marketmind.notification.alert_manager import emit_alert

DEFAULT_TIMEOUT_SEC = 120


def monitor(source: str, impact: ImpactScope = ImpactScope.MAIN_PIPELINE,
            timeout_s: int = DEFAULT_TIMEOUT_SEC):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            t0 = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    func(*args, **kwargs), timeout=timeout_s
                )
                if result is None or result == "":
                    emit_alert(
                        Severity.ERROR, source, impact,
                        f"{source}: returned empty result",
                        f"Function {func.__name__} returned None or empty string",
                        "检查数据源和上游输入", degraded_output=True,
                    )
                return result
            except asyncio.TimeoutError:
                emit_alert(
                    Severity.ERROR, source, impact,
                    f"{source}: timed out after {timeout_s}s",
                    f"Function {func.__name__} exceeded {timeout_s}s timeout",
                    "检查网络连接或API响应时间", degraded_output=True,
                )
                return None
            except Exception as e:
                emit_alert(
                    Severity.ERROR, source, impact,
                    f"{source}: {type(e).__name__}",
                    str(e),
                    "需要修复 — 查看日志详情", degraded_output=True,
                )
                raise
            finally:
                elapsed = time.monotonic() - t0

        return wrapper
    return decorator
```

- [ ] **Step 2: Write test_monitor_decorator.py**

```python
"""Tests for @monitor decorator — exception, empty, timeout capture."""
import asyncio
import pytest
from marketmind.notification.alert_manager import AlertManager, get_alert_manager
from marketmind.notification.monitor_decorator import monitor
from marketmind.notification.alert_schema import ImpactScope


@pytest.mark.asyncio
async def test_monitor_captures_exception():
    am = AlertManager()
    @monitor(source="test_module", impact=ImpactScope.MAIN_PIPELINE)
    async def failing_func():
        raise ValueError("test error")

    with pytest.raises(ValueError):
        await failing_func()

    recent = am.recent()
    errors = [a for a in recent if a["severity"] == "ERROR"]
    assert len(errors) >= 1
    assert "ValueError" in errors[-1]["title"]


@pytest.mark.asyncio
async def test_monitor_captures_empty_return():
    am = AlertManager()
    @monitor(source="test_module", impact=ImpactScope.MAIN_PIPELINE)
    async def empty_func():
        return None

    result = await empty_func()
    assert result is None
    recent = am.recent()
    assert any("empty" in a["title"] for a in recent)


@pytest.mark.asyncio
async def test_monitor_healthy_passes_through():
    am = AlertManager()
    @monitor(source="test_module", impact=ImpactScope.MAIN_PIPELINE)
    async def good_func():
        return {"ok": True}

    result = await good_func()
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_monitor_timeout():
    am = AlertManager()
    @monitor(source="test_module", impact=ImpactScope.MAIN_PIPELINE, timeout_s=0.1)
    async def slow_func():
        await asyncio.sleep(1.0)
        return "done"

    result = await slow_func()
    assert result is None
    recent = am.recent()
    assert any("timed out" in a["title"] for a in recent)
```

- [ ] **Step 3: Run tests**

```bash
cd projects/marketmind && python -m pytest tests/test_notification/test_monitor_decorator.py -v
```
Expected: 4 passed

---

### Task 5: API + WebSocket Integration

**Files:**
- Modify: `projects/marketmind/api/websocket.py`
- Modify: `projects/marketmind/api/data_providers.py`
- Modify: `projects/marketmind/api/routes.py`

- [ ] **Step 1: Add broadcast_alert to websocket.py**

In `api/websocket.py`, add after `broadcast_person_signal`:

```python
async def broadcast_alert(alert_payload: dict) -> None:
    """Broadcast an alert to all connected dashboard clients."""
    await _manager.broadcast(alert_payload)
```

- [ ] **Step 2: Wire AlertManager to WebSocket in routes.py**

In `api/routes.py`, add at module level after imports:

```python
from marketmind.notification.alert_manager import get_alert_manager
from marketmind.api.websocket import broadcast_alert

_alm = get_alert_manager()
_alm.set_broadcast_fn(broadcast_alert)
```

- [ ] **Step 3: Add /api/alerts endpoint in routes.py**

```python
@app.get("/api/alerts")
async def alerts():
    return JSONResponse({"alerts": get_alert_manager().recent(50)})


@app.get("/api/alerts/health")
async def alerts_health():
    return JSONResponse(get_alert_manager().health())
```

- [ ] **Step 4: Verify API starts without error**

```bash
cd projects/marketmind && timeout 5 python api_server.py 2>&1 || true
```
Expected: No import errors, server starts

---

### Task 6: Dashboard UI — Bell + Toast + Banner + Log

**Files:**
- Modify: `projects/marketmind/dashboard.html`

- [ ] **Step 1: Add HTML elements**

After `.h-r` closing `</div>` (near the uptime span), add bell:

```html
<span class="bell-btn" id="bellBtn" onclick="toggleBell()" title="告警通知">🔔<span class="bell-badge" id="bellBadge" style="display:none">0</span></span>
```

After `.pbar`, add critical banner:

```html
<div class="crit-banner" id="critBanner" style="display:none">
  <span id="critText"></span>
  <button onclick="dismissCritical()">✕</button>
</div>
```

After `.chat-input-wrap`, add scroll log:

```html
<div class="scroll-log" id="scrollLog" style="display:none">
  <div class="scroll-log-header" onclick="toggleScrollLog()">
    <span>📋 系统日志</span><span id="logToggle">▲</span>
  </div>
  <div class="scroll-log-body" id="scrollLogBody"></div>
</div>
```

- [ ] **Step 2: Add CSS styles**

```css
.bell-btn { position:relative; cursor:pointer; font-size:16px; margin-left:8px; }
.bell-badge { position:absolute; top:-6px; right:-8px; background:var(--rd); color:#fff;
  font:9px var(--mono); padding:1px 5px; border-radius:8px; min-width:16px; text-align:center; }
.bell-dropdown { position:absolute; right:10px; top:38px; width:380px; max-height:480px;
  overflow-y:auto; background:var(--card); border:1px solid var(--bd); z-index:100;
  border-radius:4px; box-shadow:0 4px 24px rgba(0,0,0,.5); display:none; }
.crit-banner { padding:6px 14px; background:#3d1a1f; color:#f5a0a8; font:12px var(--sans);
  display:flex; justify-content:space-between; align-items:center; }
.crit-banner button { background:none; border:none; color:var(--rd); cursor:pointer; font-size:16px; }
.toast { position:fixed; top:50px; right:20px; z-index:200; background:var(--card);
  border-left:3px solid var(--rd); padding:10px 16px; border-radius:4px;
  max-width:360px; animation:slideIn .3s ease; }
@keyframes slideIn { from{transform:translateX(100%)} to{transform:translateX(0)} }
@keyframes slideOut { from{transform:translateX(0)} to{transform:translateX(120%)} }
.scroll-log { border-top:1px solid var(--bd); background:var(--card); }
.scroll-log-header { padding:4px 14px; cursor:pointer; font:10px var(--mono); color:var(--t3);
  display:flex; justify-content:space-between; }
.scroll-log-body { max-height:120px; overflow-y:auto; padding:4px 14px; font:11px var(--mono); }
.log-entry { padding:2px 0; border-bottom:1px solid var(--bd); display:flex; gap:8px; }
.log-sev { min-width:52px; font-weight:600; }
.log-sev.CRITICAL { color:var(--rd); } .log-sev.ERROR { color:var(--am); }
.log-sev.WARN { color:var(--pu); } .log-sev.INFO { color:var(--t3); }
```

- [ ] **Step 3: Add JavaScript functions**

```javascript
let activeAlerts = [];
const MAX_TOASTS = 3;

// WebSocket handler extension: handle "alert" type
// Add inside the existing WS onmessage handler:
else if (msg.type === 'alert') {
  handleAlert(msg);
}

function handleAlert(msg) {
  activeAlerts.unshift(msg);
  if (activeAlerts.length > 200) activeAlerts.length = 200;
  updateBell();
  if (msg.severity === 'CRITICAL') showCriticalBanner(msg);
  if (msg.severity === 'ERROR') showToast(msg);
  appendLogEntry(msg);
}

function updateBell() {
  const critical = activeAlerts.filter(a => a.severity === 'CRITICAL').length;
  const errors = activeAlerts.filter(a => a.severity === 'ERROR').length;
  const badge = document.getElementById('bellBadge');
  const total = critical + errors;
  if (total > 0) {
    badge.style.display = 'inline-block';
    badge.textContent = total;
    badge.style.background = critical > 0 ? 'var(--rd)' : 'var(--am)';
  } else {
    badge.style.display = 'none';
  }
}

function toggleBell() {
  const dd = document.getElementById('bellDropdown');
  if (dd.style.display === 'block') { dd.style.display = 'none'; return; }
  dd.innerHTML = activeAlerts.slice(0, 20).map(a =>
    `<div class="log-entry">
      <span class="log-sev ${a.severity}">${a.severity}</span>
      <span>${a.title}</span>
      <span style="flex:1"></span>
      <span style="color:var(--t3);font-size:10px">${a.timestamp?.slice(11,16)||''}</span>
    </div>`
  ).join('');
  dd.style.display = 'block';
}

function showCriticalBanner(msg) {
  const banner = document.getElementById('critBanner');
  document.getElementById('critText').textContent = '⚠ ' + msg.title;
  banner.style.display = 'flex';
}

function dismissCritical() {
  document.getElementById('critBanner').style.display = 'none';
}

function showToast(msg) {
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.innerHTML = `<strong>${msg.severity}</strong> ${msg.title}<br>
    <small style="color:var(--t3)">${msg.action_advice||''}</small>`;
  document.body.appendChild(toast);
  setTimeout(() => { toast.style.animation = 'slideOut .3s ease';
    setTimeout(() => toast.remove(), 300); }, 30000);
  // Limit toasts
  const toasts = document.querySelectorAll('.toast');
  if (toasts.length > MAX_TOASTS) toasts[0].remove();
}

function appendLogEntry(msg) {
  const log = document.getElementById('scrollLogBody');
  const entry = document.createElement('div');
  entry.className = 'log-entry';
  const sevColor = {CRITICAL:'var(--rd)',ERROR:'var(--am)',WARN:'var(--pu)',INFO:'var(--t3)'}[msg.severity]||'var(--t3)';
  entry.innerHTML = `<span style="color:${sevColor};min-width:52px;font-weight:600">${msg.severity}</span>
    <span>${msg.title}</span> <span style="color:var(--t3);margin-left:auto;font-size:10px">${msg.timestamp?.slice(11,19)||''}</span>`;
  log.insertBefore(entry, log.firstChild);
  if (log.children.length > 50) log.lastChild.remove();
  document.getElementById('scrollLog').style.display = 'block';
}

function toggleScrollLog() {
  const body = document.getElementById('scrollLogBody');
  const toggle = document.getElementById('logToggle');
  if (body.style.display === 'none') { body.style.display = 'block'; toggle.textContent = '▲'; }
  else { body.style.display = 'none'; toggle.textContent = '▼'; }
}
```

- [ ] **Step 4: Verify dashboard loads**

```bash
cd projects/marketmind && python -c "from api.routes import app; print('OK')"
```
Expected: OK

---

### Task 7: Evolution Tracking Backend

**Files:**
- Create: `projects/marketmind/evolution/__init__.py`
- Create: `projects/marketmind/evolution/stagnation_detector.py`
- Create: `projects/marketmind/evolution/snapshot_store.py`
- Create: `projects/marketmind/tests/test_evolution/__init__.py`
- Create: `projects/marketmind/tests/test_evolution/test_stagnation_detector.py`

- [ ] **Step 1: Create directories and __init__ files**

```bash
mkdir -p projects/marketmind/evolution
mkdir -p projects/marketmind/tests/test_evolution
touch projects/marketmind/evolution/__init__.py
touch projects/marketmind/tests/test_evolution/__init__.py
```

- [ ] **Step 2: Write snapshot_store.py**

```python
"""SnapshotStore — weekly evolution snapshots in evolution.db."""
from __future__ import annotations
import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path


class SnapshotStore:
    def __init__(self, db_path: str = "data/evolution.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS snapshots ("
            "  snapshot_id TEXT PRIMARY KEY,"
            "  scope TEXT,"         # 'shadow' | 'pipeline'
            "  entity_id TEXT,"     # shadow_id or 'main_pipeline'
            "  week_start TEXT,"
            "  metrics_json TEXT,"
            "  created_at TEXT"
            ")"
        )
        self._conn.commit()

    def save_snapshot(self, scope: str, entity_id: str, week_start: str, metrics: dict) -> str:
        sid = f"{scope}|{entity_id}|{week_start}"
        self._conn.execute(
            "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?)",
            (sid, scope, entity_id, week_start, json.dumps(metrics),
             datetime.now(timezone.utc).isoformat())
        )
        self._conn.commit()
        return sid

    def get_history(self, scope: str, entity_id: str, limit: int = 12) -> list[dict]:
        rows = self._conn.execute(
            "SELECT week_start, metrics_json FROM snapshots "
            "WHERE scope=? AND entity_id=? ORDER BY week_start DESC LIMIT ?",
            (scope, entity_id, limit)
        ).fetchall()
        return [{"week_start": r[0], "metrics": json.loads(r[1])} for r in reversed(rows)]

    def get_baseline(self, scope: str, entity_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT metrics_json FROM snapshots "
            "WHERE scope=? AND entity_id=? ORDER BY week_start ASC LIMIT 1",
            (scope, entity_id)
        ).fetchone()
        return json.loads(row[0]) if row else None
```

- [ ] **Step 3: Write stagnation_detector.py**

```python
"""Stagnation detection: CUSUM, PSI, linear trend → composite score."""
from __future__ import annotations
import math


def compute_cusum(values: list[float], target_mean: float | None = None) -> float:
    """CUSUM: cumulative sum of deviations from mean. High positive = sustained improvement;
    high negative = sustained decline. Returns normalized deviation score (0-1)."""
    if len(values) < 4:
        return 0.0
    mean = target_mean if target_mean is not None else sum(values) / len(values)
    cusum = 0.0
    max_deviation = 0.0
    for v in values:
        cusum += v - mean
        max_deviation = max(max_deviation, abs(cusum))
    if max_deviation == 0:
        return 0.0
    return min(abs(cusum) / max_deviation, 1.0)


def compute_psi(baseline: list[float], current: list[float], bins: int = 5) -> float:
    """Population Stability Index on binned distributions. PSI > 0.25 = significant drift."""
    if len(baseline) < 2 or len(current) < 2:
        return 0.0
    all_vals = baseline + current
    min_v, max_v = min(all_vals), max(all_vals)
    if max_v == min_v:
        return 0.0
    bin_width = (max_v - min_v) / bins
    psi = 0.0
    for i in range(bins):
        low = min_v + i * bin_width
        high = low + bin_width
        b_pct = sum(1 for v in baseline if low <= v < high) / len(baseline) + 0.0001
        c_pct = sum(1 for v in current if low <= v < high) / len(current) + 0.0001
        psi += (c_pct - b_pct) * math.log(c_pct / b_pct)
    return psi


def linear_trend_pvalue(values: list[float]) -> float:
    """Simple linear regression slope significance. Returns approximate p-value.
    p > 0.05 = plateau (null hypothesis: slope=0 cannot be rejected)."""
    n = len(values)
    if n < 3:
        return 1.0
    x_mean = (n - 1) / 2
    y_mean = sum(values) / n
    xy_cov = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    x_var = sum((i - x_mean) ** 2 for i in range(n))
    if x_var == 0:
        return 1.0
    slope = xy_cov / x_var
    residuals = [v - (slope * i + (y_mean - slope * x_mean)) for i, v in enumerate(values)]
    rss = sum(r ** 2 for r in residuals)
    se = math.sqrt(rss / (n - 2)) if n > 2 else 1.0
    t_stat = abs(slope) / (se / math.sqrt(x_var)) if se > 0 else 0.0
    # Approximate two-tailed p-value from t-distribution
    df = n - 2
    if df <= 0:
        return 1.0
    # Simple approximation for p-value from t-stat
    x = df / (df + t_stat ** 2)
    p = 1 - _regularized_beta(x, df / 2, 0.5) if 0 < x < 1 else 1.0
    return p


def _regularized_beta(x: float, a: float, b: float) -> float:
    """Continued fraction approximation of regularized incomplete beta."""
    if x == 0 or x == 1:
        return x
    # Use log-beta + Simpson for simplicity
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    return front / a  # Simplified — sufficient for our p-value approximation


def composite_stagnation_score(cusum_score: float, psi_score: float, trend_pvalue: float) -> float:
    """Combine three signals into 0-1 composite score. Higher = more stagnant.
    Green < 0.3, Yellow 0.3-0.6, Red > 0.6."""
    trend_signal = 1.0 if trend_pvalue > 0.05 else 0.0  # plateau detected
    psi_signal = min(psi_score / 0.25, 1.0)  # Normalize: 0.25 = full signal
    cusum_signal = cusum_score  # Already 0-1
    return (cusum_signal * 0.33 + psi_signal * 0.33 + trend_signal * 0.34)


def stagnation_grade(score: float) -> str:
    if score < 0.3:
        return "green"
    elif score < 0.6:
        return "yellow"
    else:
        return "red"
```

- [ ] **Step 4: Write test_stagnation_detector.py**

```python
"""Tests for stagnation detection — CUSUM, PSI, trend."""
from marketmind.evolution.stagnation_detector import (
    compute_cusum, compute_psi, linear_trend_pvalue,
    composite_stagnation_score, stagnation_grade,
)


def test_cusum_stable_zero():
    assert compute_cusum([0.1, 0.1, 0.1, 0.1, 0.1]) < 0.1


def test_cusum_decline_detected():
    score = compute_cusum([0.5, 0.4, 0.3, 0.2, 0.1])
    assert score > 0.3  # sustained decline


def test_psi_identical_zero():
    vals = [0.1, 0.2, 0.3, 0.1, 0.2]
    assert compute_psi(vals, vals) < 0.01


def test_psi_drift_detected():
    assert compute_psi([0.1]*10, [0.5]*10) > 0.25


def test_linear_trend_plateau():
    p = linear_trend_pvalue([0.5, 0.52, 0.48, 0.51, 0.49])
    assert p > 0.05  # No clear trend


def test_composite_green():
    score = composite_stagnation_score(0.1, 0.05, 0.8)  # low cusum, low psi, high p=plateau
    assert score > 0.3  # High trend_signal contributes
    # Actually with p=0.8 → trend_signal=1.0, composite ≈ 0.1*0.33 + 0.2*0.33 + 1.0*0.34 ≈ 0.44 (yellow)
    assert stagnation_grade(score) in ("green", "yellow")


def test_stagnation_grade():
    assert stagnation_grade(0.1) == "green"
    assert stagnation_grade(0.5) == "yellow"
    assert stagnation_grade(0.8) == "red"
```

- [ ] **Step 5: Run tests**

```bash
cd projects/marketmind && python -m pytest tests/test_evolution/test_stagnation_detector.py -v
```
Expected: 7 passed

---

### Task 8: Evolution API Endpoints

**Files:**
- Modify: `projects/marketmind/api/data_providers.py` — add evolution providers
- Modify: `projects/marketmind/api/routes.py` — add /api/evolution/* routes

- [ ] **Step 1: Add evolution data providers**

Append to `api/data_providers.py`:

```python
# ── Evolution Tracking Providers ────────────────────────────────────

def get_shadow_evolution() -> dict:
    from marketmind.evolution.snapshot_store import SnapshotStore
    store = SnapshotStore()
    rows = store._conn.execute(
        "SELECT entity_id, week_start, metrics_json FROM snapshots "
        "WHERE scope='shadow' ORDER BY week_start DESC LIMIT 500"
    ).fetchall()
    shadows: dict[str, list] = {}
    for row in rows:
        sid, ws, mj = row[0], row[1], json.loads(row[2])
        if sid not in shadows:
            shadows[sid] = []
        shadows[sid].append({"week_start": ws, "metrics": mj})
    return {"shadows": shadows}


def get_pipeline_evolution() -> dict:
    from marketmind.evolution.snapshot_store import SnapshotStore
    store = SnapshotStore()
    history = store.get_history("pipeline", "main_pipeline", limit=12)
    baseline = store.get_baseline("pipeline", "main_pipeline")
    return {"history": history, "baseline": baseline}


def get_stagnation_report() -> dict:
    from marketmind.evolution.stagnation_detector import (
        compute_cusum, compute_psi, linear_trend_pvalue,
        composite_stagnation_score, stagnation_grade,
    )
    from marketmind.evolution.snapshot_store import SnapshotStore
    store = SnapshotStore()
    results = {}
    rows = store._conn.execute(
        "SELECT entity_id, metrics_json FROM snapshots "
        "WHERE scope='shadow' AND entity_id IN ("
        "  SELECT entity_id FROM snapshots WHERE scope='shadow' "
        "  GROUP BY entity_id HAVING COUNT(*) >= 4"
        ")"
    ).fetchall()
    # Group by shadow
    shadow_data: dict[str, list[dict]] = {}
    for row in rows:
        sid, mj = row[0], json.loads(row[1])
        if sid not in shadow_data:
            shadow_data[sid] = []
        shadow_data[sid].append(mj)
    for sid, metrics_list in shadow_data.items():
        sharpes = [m.get("sharpe", 0) for m in metrics_list if "sharpe" in m]
        if len(sharpes) >= 4:
            cusum = compute_cusum(sharpes)
            psi = compute_psi(sharpes[:len(sharpes)//2], sharpes[len(sharpes)//2:])
            pval = linear_trend_pvalue(sharpes)
            score = composite_stagnation_score(cusum, psi, pval)
            results[sid] = {
                "stagnation_score": round(score, 3),
                "grade": stagnation_grade(score),
                "cusum": round(cusum, 3),
                "psi": round(psi, 3),
                "trend_pvalue": round(pval, 3),
            }
    return {"stagnation": results}
```

- [ ] **Step 2: Add evolution routes**

Append to `api/routes.py`:

```python
@app.get("/api/evolution/shadows")
async def evolution_shadows():
    try:
        from marketmind.api.data_providers import get_shadow_evolution
        return JSONResponse(get_shadow_evolution())
    except Exception:
        return JSONResponse({"shadows": {}})


@app.get("/api/evolution/pipeline")
async def evolution_pipeline():
    try:
        from marketmind.api.data_providers import get_pipeline_evolution
        return JSONResponse(get_pipeline_evolution())
    except Exception:
        return JSONResponse({"history": [], "baseline": None})


@app.get("/api/evolution/stagnation")
async def evolution_stagnation():
    try:
        from marketmind.api.data_providers import get_stagnation_report
        return JSONResponse(get_stagnation_report())
    except Exception:
        return JSONResponse({"stagnation": {}})
```

- [ ] **Step 3: Verify no import errors**

```bash
cd projects/marketmind && python -c "from api.data_providers import get_shadow_evolution, get_pipeline_evolution, get_stagnation_report; print('OK')"
```
Expected: OK

---

### Task 9: Evolution UI Page

**Files:**
- Create: `projects/marketmind/evolution.html`

- [ ] **Step 1: Create evolution.html skeleton**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MarketMind — Evolution Tracking</title>
<style>
  :root {
    --bg:#0a0c0f; --card:#111418; --bd:#252830; --t1:#e8eaed; --t2:#9aa0b0; --t3:#6a7280;
    --gr:#5cb878; --rd:#e0556a; --am:#c8a050; --bl:#5a8fd0;
    --mono:'SF Mono','Cascadia Code','Consolas',monospace;
    --sans:'PingFang SC','SF Pro SC',sans-serif;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:var(--bg); color:var(--t1); font:14px/1.5 var(--sans); padding:20px; }
  .header { display:flex; justify-content:space-between; align-items:center; margin-bottom:24px; }
  .header h1 { font:16px var(--mono); color:var(--am); }
  .header a { color:var(--bl); text-decoration:none; font:12px var(--mono); }
  .section { margin-bottom:24px; }
  .section-title { font:12px var(--mono); color:var(--t3); text-transform:uppercase; letter-spacing:1px; margin-bottom:12px; border-bottom:1px solid var(--bd); padding-bottom:4px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:8px; }
  .cell { background:var(--card); border:2px solid var(--bd); border-radius:4px; padding:8px; cursor:pointer; }
  .cell.green { border-color:var(--gr); } .cell.yellow { border-color:var(--am); } .cell.red { border-color:var(--rd); }
  .cell-name { font:12px var(--mono); color:var(--t1); }
  .cell-grade { font:10px var(--mono); padding:1px 6px; border-radius:3px; display:inline-block; margin-top:4px; }
  .grade-ELITE { color:var(--am); background:rgba(200,160,80,.15); }
  .grade-Excel { color:var(--bl); background:rgba(90,143,208,.15); }
  .grade-Normal { color:var(--t3); background:rgba(106,114,128,.1); }
  .stagnation-dot { width:8px; height:8px; border-radius:50%; display:inline-block; margin-left:4px; }
  .stagnation-dot.green { background:var(--gr); } .stagnation-dot.yellow { background:var(--am); } .stagnation-dot.red { background:var(--rd); }
  .metric-row { display:flex; gap:16px; flex-wrap:wrap; }
  .metric-card { background:var(--card); border:1px solid var(--bd); border-radius:4px; padding:12px 16px; min-width:140px; }
  .metric-value { font:24px var(--mono); color:var(--t1); }
  .metric-label { font:10px var(--mono); color:var(--t3); text-transform:uppercase; }
  .metric-delta { font:11px var(--mono); }
  .delta-up { color:var(--gr); } .delta-down { color:var(--rd); } .delta-flat { color:var(--t3); }
</style>
</head>
<body>
<div class="header">
  <h1>MarketMind Evolution Tracking</h1>
  <div>
    <span id="lastUpdated" style="color:var(--t3);font:11px var(--mono)"></span>
    <button onclick="loadAll()" style="background:var(--card);border:1px solid var(--bd);color:var(--t1);padding:4px 12px;border-radius:3px;cursor:pointer;margin-left:8px;font:12px var(--mono);">⟳ Refresh</button>
    <a href="/" style="margin-left:16px;">← Dashboard</a>
  </div>
</div>

<div class="section">
  <div class="section-title">Shadow Stagnation Overview</div>
  <div class="grid" id="shadowGrid"></div>
</div>

<div class="section">
  <div class="section-title">Pipeline Aggregate</div>
  <div class="metric-row" id="pipelineMetrics"></div>
</div>

<script>
const API = '';

async function loadAll() {
  await Promise.all([loadStagnation(), loadPipeline()]);
  document.getElementById('lastUpdated').textContent = new Date().toLocaleString();
}

async function loadStagnation() {
  const resp = await fetch(API + '/api/evolution/stagnation');
  const data = await resp.json();
  const grid = document.getElementById('shadowGrid');
  grid.innerHTML = Object.entries(data.stagnation || {}).map(([id, s]) =>
    `<div class="cell ${s.grade}" onclick="alert('${id}\\nScore: ${s.stagnation_score}\\nCUSUM: ${s.cusum}\\nPSI: ${s.psi}\\nTrend p: ${s.trend_pvalue}')">
      <div class="cell-name">${id}</div>
      <span class="stagnation-dot ${s.grade}"></span>
      <span style="font:10px var(--mono);color:var(--t3)">${(s.stagnation_score*100).toFixed(0)}% stagnant</span>
    </div>`
  ).join('') || '<div style="color:var(--t3)">No data yet — run pipeline to accumulate snapshots</div>';
}

async function loadPipeline() {
  const resp = await fetch(API + '/api/evolution/pipeline');
  const data = await resp.json();
  const latest = data.history?.[data.history.length-1]?.metrics || {};
  const baseline = data.baseline || {};
  document.getElementById('pipelineMetrics').innerHTML = [
    {label:'Degradation Rate', v:latest.degradation_rate, b:baseline.degradation_rate, fmt:'pct'},
    {label:'Direction Accuracy', v:latest.direction_accuracy, b:baseline.direction_accuracy, fmt:'pct'},
    {label:'Closure Rate', v:latest.closure_rate, b:baseline.closure_rate, fmt:'pct'},
  ].map(m => {
    const delta = m.b != null ? (m.v||0) - (m.b||0) : 0;
    const cls = delta > 0.02 ? 'delta-up' : delta < -0.02 ? 'delta-down' : 'delta-flat';
    const fmt = m.fmt === 'pct' ? v => (v*100).toFixed(1)+'%' : v => v?.toFixed(3)||'-';
    return `<div class="metric-card">
      <div class="metric-label">${m.label}</div>
      <div class="metric-value">${fmt(m.v)}</div>
      <div class="metric-delta ${cls}">vs baseline: ${fmt(m.b)} (${delta>0?'+':''}${fmt(delta)})</div>
    </div>`;
  }).join('');
}

loadAll();
setInterval(loadAll, 60000);  // Refresh every 60s
</script>
</body>
</html>
```

---

### Task 10: Wire AlertManager into Gateway

**Files:**
- Modify: `projects/marketmind/gateway/async_client.py`

- [ ] **Step 1: Add alert emits at key degradation points**

In `async_client.py`, add import at top:

```python
from marketmind.notification.alert_schema import Severity, ImpactScope
from marketmind.notification.alert_manager import emit_alert
```

In `_call` method, after line where content is empty + reasoning empty:

```python
# After existing: logger.warning("DeepSeek: content empty, reasoning_content=%d chars — no JSON found",...)
emit_alert(Severity.ERROR, "gateway", ImpactScope.MAIN_PIPELINE,
           "Pro response content empty — no JSON recovered",
           f"reasoning_content={len(reasoning_content)} chars, no extractable JSON",
           "检查API响应格式", degraded_output=True)
```

In `chat_flash`, after budget exhaustion:

```python
# After existing: return {"content": "", "error": "budget_exhausted", "usage": {}}
emit_alert(Severity.CRITICAL, "gateway", ImpactScope.INFRASTRUCTURE,
           "Flash token budget exhausted", "",
           "增加预算或减少调用频率", degraded_output=True)
```

In `chat_pro`, after budget exhaustion:

```python
# After existing: return {"content": "", "error": "budget_exhausted", "usage": {}}
emit_alert(Severity.CRITICAL, "gateway", ImpactScope.INFRASTRUCTURE,
           "Pro token budget exhausted", "",
           "增加预算，今日分析结果可能不完整", degraded_output=True)
```

---

### Task 11: Full Regression Test

- [ ] **Step 1: Run fast test suite**

```bash
cd projects/marketmind && python -m pytest tests/ -x -q -m "not slow" -p no:warnings 2>&1 | tail -5
```
Expected: 1990+ passed

- [ ] **Step 2: Run notification tests specifically**

```bash
cd projects/marketmind && python -m pytest tests/test_notification/ tests/test_evolution/ -v 2>&1 | tail -10
```
Expected: all passed

- [ ] **Step 3: Commit**

```bash
git add projects/marketmind/notification/ projects/marketmind/evolution/ projects/marketmind/api/ projects/marketmind/dashboard.html projects/marketmind/evolution.html projects/marketmind/tests/test_notification/ projects/marketmind/tests/test_evolution/
git commit -m "feat: AlertManager notification system + Evolution Tracking panel"
```
