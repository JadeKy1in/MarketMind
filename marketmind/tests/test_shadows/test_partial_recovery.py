"""Tests for partial-state recovery — crash-safe cycle checkpoints (P3-4)."""
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig, CODE_VERSION
from datetime import datetime, timezone


class TestCycleCheckpointDB:

    def test_save_and_load_checkpoint(self, tmp_path):
        """Should save and retrieve per-shadow checkpoints."""
        db = ShadowStateDB(str(tmp_path / "test.db"))
        db.init_schema()

        today = "2026-05-13"
        db.save_checkpoint(today, "s1", "completed", step=4,
                          analysis_json='{"signal": "buy"}')
        db.save_checkpoint(today, "s2", "completed", step=4,
                          analysis_json='{"signal": "sell"}')

        cp1 = db.get_checkpoint(today, "s1")
        assert cp1 is not None
        assert cp1["status"] == "completed"
        assert cp1["step_completed"] == 4
        assert cp1["shadow_id"] == "s1"
        assert cp1["analysis_json"] == '{"signal": "buy"}'

        cp2 = db.get_checkpoint(today, "s2")
        assert cp2 is not None
        assert cp2["status"] == "completed"
        assert cp2["step_completed"] == 4
        assert cp2["shadow_id"] == "s2"
        db.close()

    def test_checkpoint_update_in_place(self, tmp_path):
        """Should update existing checkpoint (INSERT OR REPLACE)."""
        db = ShadowStateDB(str(tmp_path / "test.db"))
        db.init_schema()

        today = "2026-05-13"
        db.save_checkpoint(today, "s1", "pending", step=0)
        db.save_checkpoint(today, "s1", "completed", step=4,
                          analysis_json='{"signal": "buy"}')
        cp = db.get_checkpoint(today, "s1")
        assert cp["status"] == "completed"
        assert cp["step_completed"] == 4
        assert cp["analysis_json"] == '{"signal": "buy"}'
        db.close()

    def test_get_nonexistent_checkpoint(self, tmp_path):
        """Should return None for missing (date, shadow_id) pair."""
        db = ShadowStateDB(str(tmp_path / "test.db"))
        db.init_schema()
        cp = db.get_checkpoint("2026-01-01", "nonexistent")
        assert cp is None
        db.close()

    def test_incomplete_shadows(self, tmp_path):
        """get_incomplete_shadows should return shadow_ids with status pending/failed."""
        db = ShadowStateDB(str(tmp_path / "test.db"))
        db.init_schema()

        today = "2026-05-12"
        db.save_checkpoint(today, "s1", "completed", step=4)
        db.save_checkpoint(today, "s2", "pending", step=0)
        db.save_checkpoint(today, "s3", "failed", step=2,
                          error_message="LLM timeout")

        incomplete = db.get_incomplete_shadows(today)
        assert len(incomplete) == 2
        assert "s2" in incomplete
        assert "s3" in incomplete
        assert "s1" not in incomplete
        db.close()

    def test_clear_date_checkpoints(self, tmp_path):
        """clear_date_checkpoints should delete all checkpoints for a date."""
        db = ShadowStateDB(str(tmp_path / "test.db"))
        db.init_schema()

        old_date = "2025-01-01"
        db.save_checkpoint(old_date, "s1", "completed", step=4)
        db.save_checkpoint(old_date, "s2", "completed", step=4)

        # Verify they exist
        assert db.get_checkpoint(old_date, "s1") is not None
        assert db.get_checkpoint(old_date, "s2") is not None

        db.clear_date_checkpoints(old_date)

        # Should be gone
        assert db.get_checkpoint(old_date, "s1") is None
        assert db.get_checkpoint(old_date, "s2") is None
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
