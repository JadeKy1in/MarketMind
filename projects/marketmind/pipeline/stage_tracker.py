"""Pipeline stage tracker — progress reporting with elapsed-time annotations.

Extracted from pipeline/orchestration.py for modular compliance (grandfather reduction).
"""
from __future__ import annotations

import time


class StageTracker:
    """Tracks pipeline stage progress with optional verbose console output.

    Used by all pipeline modes (daily, daily_legacy, interactive, shadows_only)
    to report stage-advancement messages with elapsed-time annotations.
    """

    def __init__(self, verbose: bool):
        self.verbose = verbose
        self.total_start: float = time.time()
        self.start_times: dict[int, float] = {}
        self._stage_msgs: dict[int, str] = {}

    def advance(self, stage: int, msg: str, stage_times: dict[str, float] | None = None) -> None:
        now = time.time()

        # Record elapsed for the most recent previous stage
        prev_stages = sorted(self.start_times.keys())
        if prev_stages and stage_times is not None:
            prev_stage = prev_stages[-1]
            prev_elapsed = now - self.start_times[prev_stage]
            prev_key = self._stage_msgs.get(prev_stage, f"stage_{prev_stage}")
            stage_times[prev_key] = prev_elapsed

        self.start_times[stage] = now
        self._stage_msgs[stage] = msg

        if self.verbose:
            timing = ""
            if prev_stages:
                prev_stage = prev_stages[-1]
                prev_elapsed = now - self.start_times[prev_stage]
                total_elapsed = now - self.total_start
                prev_label = self._stage_msgs.get(prev_stage, "").split(":")[0].strip()
                timing = f" ({prev_label}: {self._fmt(prev_elapsed)} | total: {self._fmt(total_elapsed)})"
            print(f"[{stage}/9] {msg}{timing}")

    def result(self, msg: str) -> None:
        if self.verbose:
            now = time.time()
            stage_keys = sorted(self.start_times.keys())
            if stage_keys:
                elapsed = now - self.start_times[stage_keys[-1]]
                print(f"       {msg} ({self._fmt(elapsed)})")
            else:
                print(f"       {msg}")

    @staticmethod
    def _fmt(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f}s"
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}m{s}s"
