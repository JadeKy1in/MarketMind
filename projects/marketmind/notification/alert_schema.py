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
