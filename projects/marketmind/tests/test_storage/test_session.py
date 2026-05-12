"""Tests for session checkpoint persistence."""
import tempfile
from pathlib import Path
from marketmind.storage.session import (
    SessionState, SessionManager, GateCheckpoint,
)


def test_gate_checkpoint_defaults():
    gc = GateCheckpoint(gate_number=1, completed=True)
    assert gc.gate_number == 1
    assert gc.completed is True
    assert gc.timestamp
    assert gc.data == {}


def test_session_state_progress():
    state = SessionState(
        session_id="test-session-1",
        mode="full",
        current_gate=2,
        gate1=GateCheckpoint(1, True),
        gate2=GateCheckpoint(2, True),
    )
    assert not state.is_complete
    assert "Gate 2 complete" in state.progress_summary
    state.gate3 = GateCheckpoint(3, True)
    assert state.is_complete
    assert "complete" in state.progress_summary


def test_session_state_new():
    state = SessionState(session_id="new", mode="quick", current_gate=1)
    assert not state.is_complete
    assert "Gate 1 pending" in state.progress_summary


def test_session_manager_save_load():
    with tempfile.TemporaryDirectory() as td:
        sm = SessionManager(Path(td))
        state = SessionState(
            session_id="test-session",
            mode="full",
            current_gate=1,
            gate1=GateCheckpoint(1, True, data={"selected_direction": "tech"}),
        )
        filepath = sm.save(state)
        assert filepath.exists()
        loaded = sm.load("test-session")
        assert loaded is not None
        assert loaded.session_id == "test-session"
        assert loaded.mode == "full"
        assert loaded.gate1 is not None
        assert loaded.gate1.completed
        assert loaded.gate1.data["selected_direction"] == "tech"


def test_session_manager_load_nonexistent():
    with tempfile.TemporaryDirectory() as td:
        sm = SessionManager(Path(td))
        assert sm.load("nonexistent") is None


def test_session_manager_list_and_delete():
    with tempfile.TemporaryDirectory() as td:
        sm = SessionManager(Path(td))
        sm.save(SessionState(session_id="sess-1", mode="full", current_gate=1))
        sm.save(SessionState(session_id="sess-2", mode="quick", current_gate=2))
        sessions = sm.list_sessions()
        assert len(sessions) >= 2
        assert sm.delete("sess-1")
        assert sm.load("sess-1") is None
        assert len(sm.list_sessions()) == 1
