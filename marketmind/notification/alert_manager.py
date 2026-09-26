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
        self._dedup_window: dict[str, float] = {}
        self._source_cooldown: dict[str, float] = {}
        self._broadcast_count_this_second = 0
        self._second_start = time.monotonic()
        self._warn_timestamps: dict[str, list[float]] = defaultdict(list)
        self._alert_log = AlertLog()
        self._ws_broadcast_fn = None

    def set_broadcast_fn(self, fn) -> None:
        self._ws_broadcast_fn = fn

    def emit(self, alert: Alert) -> None:
        now = time.monotonic()
        dedup_key = alert.dedup_key

        # 1. Track WARN timestamps for escalation (before dedup — all occurrences count)
        escalating = False
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
                escalating = True

        # 2. Dedup: same key within 60s -> increment counter, suppress re-broadcast
        if dedup_key in self._dedup_window:
            elapsed = now - self._dedup_window[dedup_key]
            if elapsed < 60:
                for a in reversed(self._alerts):
                    if a.get("dedup_key") == dedup_key:
                        a["repeat_count"] = a.get("repeat_count", 1) + 1
                        break
                if not escalating:
                    return

        self._dedup_window[dedup_key] = now

        # 3. Source cooldown: same source+severity within 30s -> throttle
        source_key = f"{alert.source}|{alert.severity.value}"
        if source_key in self._source_cooldown:
            if now - self._source_cooldown[source_key] < 30:
                return
        self._source_cooldown[source_key] = now

        # 4. Global throttle: max 10 broadcast/sec
        if now - self._second_start > 1.0:
            self._broadcast_count_this_second = 0
            self._second_start = now
        if self._broadcast_count_this_second >= 10:
            return
        self._broadcast_count_this_second += 1

        # 5. Sanitize
        alert.title = sanitize(alert.title)
        alert.detail = sanitize(alert.detail)

        # 6. Persist
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

        # 7. Evict oldest INFO if over capacity
        if len(self._alerts) > 200:
            for i, a in enumerate(self._alerts):
                if a["severity"] == "INFO":
                    self._alerts.pop(i)
                    break
            else:
                self._alerts.pop(0)

        # 8. Broadcast via WebSocket
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
