"""ActivityMonitor — detect shadow activity level changes and emit alerts."""
from __future__ import annotations
from marketmind.notification.alert_schema import Severity, ImpactScope
from marketmind.notification.alert_manager import emit_alert


class ActivityMonitor:
    """Track shadow activity grades and emit alerts on level changes only."""

    def __init__(self):
        self._previous_grades: dict[str, str] = {}

    def check_and_alert(self, shadow_id: str, current_grade: str,
                        activity_score: float) -> str | None:
        """Emit alert if grade changed. Returns new grade or None."""
        prev = self._previous_grades.get(shadow_id)
        if prev == current_grade:
            return None  # No change, no alert

        self._previous_grades[shadow_id] = current_grade

        if prev is None:
            return None  # First time seeing this shadow, no alert

        # Grade change detected — emit appropriate alert
        grade_labels = {"green": "Active · 活跃", "yellow": "Watch · 关注", "red": "Stagnant · 停滞"}

        if current_grade == "red":
            emit_alert(Severity.WARN, f"shadow:{shadow_id}", ImpactScope.SHADOW_SYSTEM,
                       f"{shadow_id}: 进化活跃度降为停滞 (Stagnant)",
                       f"从 {grade_labels.get(prev, prev)} → Stagnant · 停滞，活动分={activity_score:.2f}",
                       "检查影子策略是否需要调整或退役", degraded_output=False)
        elif current_grade == "yellow" and prev == "green":
            emit_alert(Severity.INFO, f"shadow:{shadow_id}", ImpactScope.SHADOW_SYSTEM,
                       f"{shadow_id}: 进化活跃度降为关注 (Watch)",
                       f"从 Active · 活跃 → Watch · 关注，活动分={activity_score:.2f}",
                       "持续观察，如进一步下降需关注", degraded_output=False)
        elif current_grade == "green" and prev in ("yellow", "red"):
            emit_alert(Severity.INFO, f"shadow:{shadow_id}", ImpactScope.SHADOW_SYSTEM,
                       f"{shadow_id}: 进化活跃度恢复为活跃 (Active)",
                       f"从 {grade_labels.get(prev, prev)} → Active · 活跃，活动分={activity_score:.2f}",
                       "影子已恢复活力，仅通知无需操作", degraded_output=False)

        return current_grade


_activity_monitor: ActivityMonitor | None = None


def get_activity_monitor() -> ActivityMonitor:
    global _activity_monitor
    if _activity_monitor is None:
        _activity_monitor = ActivityMonitor()
    return _activity_monitor
