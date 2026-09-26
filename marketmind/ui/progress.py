"""Determinate and indeterminate progress indicators for pipeline stages."""
from __future__ import annotations
import time
import math


class ProgressTracker:
    """Tracks progress of a multi-stage pipeline with ETA estimation."""

    def __init__(self, total_stages: int = 8):
        self.total_stages = total_stages
        self.current_stage = 0
        self.stage_name = "Initializing..."
        self.stage_start: float | None = None
        self.stage_elapsed: float = 0.0
        self.overall_start = time.time()
        self._stage_times: list[float] = []

    def advance(self, name: str) -> None:
        now = time.time()
        if self.stage_start is not None:
            self._stage_times.append(now - self.stage_start)
        self.current_stage += 1
        self.stage_name = name
        self.stage_start = now
        self.stage_elapsed = 0.0

    def tick(self) -> float:
        """Call periodically. Returns fraction complete (0.0-1.0)."""
        if self.stage_start is not None:
            self.stage_elapsed = time.time() - self.stage_start
        return self.fraction

    @property
    def fraction(self) -> float:
        return min(self.current_stage / self.total_stages, 1.0)

    @property
    def pct(self) -> int:
        return int(self.fraction * 100)

    @property
    def eta_seconds(self) -> float | None:
        if not self._stage_times:
            return None
        avg_stage = sum(self._stage_times) / len(self._stage_times)
        remaining = self.total_stages - self.current_stage
        return avg_stage * remaining

    @property
    def eta_str(self) -> str:
        eta = self.eta_seconds
        if eta is None:
            return "calculating..."
        if eta < 60:
            return f"{int(eta)}s"
        if eta < 3600:
            return f"{int(eta / 60)}m {int(eta % 60)}s"
        return f"{int(eta / 3600)}h {int((eta % 3600) / 60)}m"

    @property
    def is_complete(self) -> bool:
        return self.current_stage >= self.total_stages


class IndeterminateSpinner:
    """Decelerating spinner for Pro calls (long-running, unpredictable)."""

    def __init__(self, base_interval: float = 0.3, decel_factor: float = 1.5):
        self._ticks = 0
        self._base = base_interval
        self._decel = decel_factor
        self._chars = ["|", "/", "-", "\\"]

    def next(self) -> str:
        self._ticks += 1
        return self._chars[self._ticks % len(self._chars)]

    @property
    def interval(self) -> float:
        """Grows over time so the spinner appears to decelerate."""
        return min(self._base * (self._decel ** (self._ticks / 20)), 5.0)
