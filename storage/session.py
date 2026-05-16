"""Session checkpoint persistence — auto-save after each gate, resume on restart."""
from __future__ import annotations
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class GateCheckpoint:
    gate_number: int              # 1, 2, or 3
    completed: bool
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionState:
    session_id: str
    mode: str                      # full | quick | catchup
    current_gate: int              # which gate we're at (1-3)
    gate1: GateCheckpoint | None = None
    gate2: GateCheckpoint | None = None
    gate3: GateCheckpoint | None = None
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_activity: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def is_complete(self) -> bool:
        return self.gate3 is not None and self.gate3.completed

    @property
    def progress_summary(self) -> str:
        if self.gate3 and self.gate3.completed:
            return "Session complete — all 3 gates passed."
        if self.gate2 and self.gate2.completed:
            return "Gate 2 complete. Phase 1+2 analysis done. Gate 3 pending."
        if self.gate1 and self.gate1.completed:
            return "Gate 1 complete. Direction selected. Phase 1+2 in progress."
        return "Session started. Gate 1 pending."


class SessionManager:
    def __init__(self, checkpoint_dir: str | Path = "data/sessions"):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def save(self, state: SessionState) -> Path:
        filepath = self.checkpoint_dir / f"{state.session_id}.json"
        data = _serialize_state(state)
        filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return filepath

    def load(self, session_id: str) -> SessionState | None:
        filepath = self.checkpoint_dir / f"{session_id}.json"
        if not filepath.exists():
            return None
        data = json.loads(filepath.read_text(encoding="utf-8"))
        return _deserialize_state(data)

    def list_sessions(self) -> list[dict]:
        sessions = []
        for f in sorted(self.checkpoint_dir.glob("*.json"), key=os.path.getmtime, reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id": data.get("session_id", f.stem),
                    "mode": data.get("mode", "full"),
                    "started_at": data.get("started_at", ""),
                    "complete": (data.get("gate3") or {}).get("completed", False),
                })
            except Exception:
                logger.warning("Skipping corrupt session file: %s", f.name)
        return sessions

    def delete(self, session_id: str) -> bool:
        filepath = self.checkpoint_dir / f"{session_id}.json"
        if filepath.exists():
            filepath.unlink()
            return True
        return False


def _serialize_state(state: SessionState) -> dict:
    return {
        "session_id": state.session_id,
        "mode": state.mode,
        "current_gate": state.current_gate,
        "gate1": {"completed": state.gate1.completed, "timestamp": state.gate1.timestamp, "data": state.gate1.data} if state.gate1 else None,
        "gate2": {"completed": state.gate2.completed, "timestamp": state.gate2.timestamp, "data": state.gate2.data} if state.gate2 else None,
        "gate3": {"completed": state.gate3.completed, "timestamp": state.gate3.timestamp, "data": state.gate3.data} if state.gate3 else None,
        "started_at": state.started_at,
        "last_activity": state.last_activity,
    }


def _deserialize_state(data: dict) -> SessionState:
    g1 = data.get("gate1")
    g2 = data.get("gate2")
    g3 = data.get("gate3")
    return SessionState(
        session_id=data["session_id"],
        mode=data.get("mode", "full"),
        current_gate=data.get("current_gate", 1),
        gate1=GateCheckpoint(1, g1["completed"], g1.get("timestamp", ""), g1.get("data", {})) if g1 else None,
        gate2=GateCheckpoint(2, g2["completed"], g2.get("timestamp", ""), g2.get("data", {})) if g2 else None,
        gate3=GateCheckpoint(3, g3["completed"], g3.get("timestamp", ""), g3.get("data", {})) if g3 else None,
        started_at=data.get("started_at", ""),
        last_activity=data.get("last_activity", ""),
    )
