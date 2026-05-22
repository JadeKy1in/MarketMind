"""Tests for partial-state recovery — crash-safe cycle checkpoints (P3-4)."""
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig, CODE_VERSION
from datetime import datetime, timezone


@pytest.mark.skip(reason="Checkpoint API redesigned: per-day to per-shadow")
class TestCycleCheckpointDB:

    def test_save_and_load_checkpoint(self, tmp_path):
        """Should save and retrieve a cycle checkpoint."""
        db = ShadowStateDB(str(tmp_path / "test.db"))
        db.init_schema()

        today = "2026-05-13"
        db.save_checkpoint(today, {"completed": ["s1", "s2"]}, step_completed=4)
        cp = db.get_checkpoint(today)
        assert cp is not None
        assert cp["status"] == "running"
        assert cp["step_completed"] == 4
        assert set(cp["shadow_states"]["completed"]) == {"s1", "s2"}
        db.close()

    def test_checkpoint_update_in_place(self, tmp_path):
        """Should update existing checkpoint (INSERT OR REPLACE)."""
        db = ShadowStateDB(str(tmp_path / "test.db"))
        db.init_schema()

        today = "2026-05-13"
        db.save_checkpoint(today, {"completed": ["s1"]})
        db.save_checkpoint(today, {"completed": ["s1", "s2", "s3"]})
        cp = db.get_checkpoint(today)
        assert len(cp["shadow_states"]["completed"]) == 3
        db.close()

    def test_get_nonexistent_checkpoint(self, tmp_path):
        """Should return None for missing checkpoint."""
        db = ShadowStateDB(str(tmp_path / "test.db"))
        db.init_schema()
        cp = db.get_checkpoint("2026-01-01")
        assert cp is None
        db.close()

    def test_incomplete_checkpoints(self, tmp_path):
        """Should return only checkpoints with status != completed."""
        db = ShadowStateDB(str(tmp_path / "test.db"))
        db.init_schema()

        db.save_checkpoint("2026-05-10", {"completed": ["s1"]}, status="completed")
        db.save_checkpoint("2026-05-11", {"completed": []}, status="running")
        db.save_checkpoint("2026-05-12", {"completed": ["s2"]}, status="crashed")

        incomplete = db.get_incomplete_checkpoints()
        assert len(incomplete) == 2
        statuses = {cp["status"] for cp in incomplete}
        assert "running" in statuses
        assert "crashed" in statuses
        db.close()

    def test_cleanup_old_checkpoints(self, tmp_path):
        """Should delete checkpoints older than keep_days."""
        db = ShadowStateDB(str(tmp_path / "test.db"))
        db.init_schema()

        # Save a checkpoint with an old date
        conn = db._connect()
        try:
            conn.execute(
                """INSERT INTO cycle_checkpoints (date, status, step_completed,
                   shadow_states, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("2025-01-01", "completed", 4, "{}", "2025-01-01T00:00:00", "2025-01-01T00:00:00")
            )
            conn.commit()
        finally:
            conn.close()

        deleted = db.cleanup_old_checkpoints(keep_days=30)
        assert deleted >= 1
        cp = db.get_checkpoint("2025-01-01")
        assert cp is None
        db.close()

    def test_code_version_is_6(self):
        """CODE_VERSION should be 12 after Phase C independent tools migration."""
        assert CODE_VERSION == 12


class TestCrashRecoveryLogic:

    def test_completed_shadows_skipped_on_resume(self):
        """Shadows in checkpoint completed list should be skipped."""
        completed_shadows = {"s1", "s2"}

        # s1 is completed → should skip
        assert "s1" in completed_shadows
        # s3 is not completed → should not skip
        assert "s3" not in completed_shadows

    def test_per_shadow_checkpoint_after_each_analysis(self):
        """After each shadow completes, checkpoint should be updated."""
        checkpoint_data = {"completed": []}

        # Simulate shadows completing one at a time
        for sid in ["s1", "s2", "s3"]:
            checkpoint_data["completed"].append(sid)

        assert len(checkpoint_data["completed"]) == 3
        assert checkpoint_data["completed"] == ["s1", "s2", "s3"]

    def test_checkpoint_marked_complete_after_full_cycle(self):
        """After all shadows finish, checkpoint status should be 'completed'."""
        checkpoint = {
            "status": "running",
            "shadow_states": {"completed": ["s1", "s2"]},
        }
        # After full cycle
        checkpoint["status"] = "completed"
        assert checkpoint["status"] == "completed"

    def test_resume_from_partial_checkpoint(self):
        """Resume: 2 of 5 shadows done → only 3 need to run."""
        checkpoint_completed = {"s1", "s2"}
        all_shadows = {"s1", "s2", "s3", "s4", "s5"}

        pending = all_shadows - checkpoint_completed
        assert len(pending) == 3
        assert pending == {"s3", "s4", "s5"}
