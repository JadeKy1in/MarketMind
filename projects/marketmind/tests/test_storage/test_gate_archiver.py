"""Tests for GateArchiver — JSONL + Markdown dual-format conversation archive."""
import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from marketmind.storage.archivist import MarketMindArchive
from marketmind.storage.gate_archiver import GateArchiver, GateTurn


def test_gate_turn_dataclass():
    """GateTurn should have required fields with correct defaults."""
    t = GateTurn(
        turn=1,
        speaker="AI",
        type="hypothesis_card",
        content_type="structured_data",
    )
    assert t.turn == 1
    assert t.speaker == "AI"
    assert t.type == "hypothesis_card"
    assert t.content_type == "structured_data"
    assert t.text is None
    assert t.data is None
    assert t.warnings is None
    assert t.timestamp == ""

    # With optional fields
    t2 = GateTurn(
        turn=2,
        speaker="USER",
        type="question",
        content_type="user_free_text",
        text="What about risk?",
        data={"key": "val"},
        warnings=["test_warning"],
        timestamp="2026-05-18T14:30:00Z",
    )
    assert t2.text == "What about risk?"
    assert t2.data == {"key": "val"}
    assert t2.warnings == ["test_warning"]
    assert t2.timestamp == "2026-05-18T14:30:00Z"


@pytest.mark.asyncio
async def test_start_session_creates_files():
    """start_session should create JSONL and MD files with correct paths."""
    with tempfile.TemporaryDirectory() as td:
        archive = MarketMindArchive(Path(td))
        archiver = GateArchiver(archive)

        jsonl_path = await archiver.start_session(1, "test-session-001")

        assert jsonl_path.exists()
        assert jsonl_path.suffix == ".jsonl"

        md_path = jsonl_path.with_suffix(".md")
        assert md_path.exists()

        md_content = md_path.read_text(encoding="utf-8")
        assert md_content.startswith("# Gate 1 — ")
        assert "UTC" in md_content

        archive.close()


@pytest.mark.asyncio
async def test_log_turn_appends_to_jsonl():
    """log_turn should append one line to JSONL and one section to MD."""
    with tempfile.TemporaryDirectory() as td:
        archive = MarketMindArchive(Path(td))
        archiver = GateArchiver(archive)

        jsonl_path = await archiver.start_session(1, "test-session-002")

        turn = GateTurn(
            turn=1,
            speaker="AI",
            type="hypothesis_card",
            content_type="structured_data",
            data={"direction": "tech_long", "confidence": 0.81},
            timestamp="2026-05-18T14:30:00Z",
        )
        await archiver.log_turn(turn)

        # JSONL should have exactly 1 line
        lines = jsonl_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["turn"] == 1
        assert parsed["speaker"] == "AI"
        assert parsed["direction"] == "tech_long"
        assert parsed["confidence"] == 0.81

        # MD should have the turn section with system decision wrapping
        md_path = jsonl_path.with_suffix(".md")
        md_content = md_path.read_text(encoding="utf-8")
        assert "## Turn 1 — AI (hypothesis_card)" in md_content
        assert "**direction**" in md_content
        assert "tech_long" in md_content

        archive.close()


@pytest.mark.asyncio
async def test_user_text_wrapped_in_html_comments():
    """User text in MD should be wrapped in USER_TEXT_START/END comments."""
    with tempfile.TemporaryDirectory() as td:
        archive = MarketMindArchive(Path(td))
        archiver = GateArchiver(archive)

        jsonl_path = await archiver.start_session(1, "test-session-003")

        turn = GateTurn(
            turn=2,
            speaker="USER",
            type="question",
            content_type="user_free_text",
            text="反对意见为什么只有0.45？",
            timestamp="2026-05-18T14:30:45Z",
        )
        await archiver.log_turn(turn)

        md_path = jsonl_path.with_suffix(".md")
        md_content = md_path.read_text(encoding="utf-8")

        assert "<!-- USER_TEXT_START -->" in md_content
        assert "<!-- USER_TEXT_END -->" in md_content
        assert "反对意见为什么只有0.45？" in md_content

        # Verify wrapping is BEFORE and AFTER the text
        start_idx = md_content.index("<!-- USER_TEXT_START -->")
        end_idx = md_content.index("<!-- USER_TEXT_END -->")
        text_idx = md_content.index("反对意见为什么只有0.45？")
        assert start_idx < text_idx < end_idx

        archive.close()


@pytest.mark.asyncio
async def test_decision_atomic_write():
    """log_decision should write gate_decision.json atomically (no .tmp leftover)."""
    with tempfile.TemporaryDirectory() as td:
        archive = MarketMindArchive(Path(td))
        archiver = GateArchiver(archive)

        await archiver.start_session(2, "test-session-004")

        decision_data = {
            "direction": "tech",
            "confidence": 0.81,
            "rejected_directions": ["gold", "bonds"],
        }
        await archiver.log_decision(decision_data)

        # Decision file should exist (via atomic write)
        decision_path = archive.today_path() / "gates" / "gate2_decision.json"
        assert decision_path.exists()

        # No .tmp leftover — atomic write (temp → rename) cleans up
        tmp_files = list(decision_path.parent.glob("*.tmp"))
        assert len(tmp_files) == 0, f"Orphaned .tmp files: {tmp_files}"

        # Content is correct
        loaded = json.loads(decision_path.read_text(encoding="utf-8"))
        assert loaded["gate"] == 2
        assert loaded["direction"] == "tech"
        assert loaded["confidence"] == 0.81
        assert loaded["session_id"] == "test-session-004"
        assert "rejected_directions" in loaded
        assert "timestamp" in loaded

        archive.close()


@pytest.mark.asyncio
async def test_close_session_integrity_footer():
    """close_session should append integrity footer with hash and event count."""
    with tempfile.TemporaryDirectory() as td:
        archive = MarketMindArchive(Path(td))
        archiver = GateArchiver(archive)

        jsonl_path = await archiver.start_session(1, "test-session-005")

        await archiver.log_turn(GateTurn(
            turn=1, speaker="AI", type="hypothesis_card",
            content_type="structured_data",
            data={"direction": "EUR_long", "confidence": 0.81},
            timestamp="2026-05-18T14:30:00Z",
        ))
        await archiver.log_turn(GateTurn(
            turn=2, speaker="USER", type="question",
            content_type="user_free_text",
            text="反对意见为什么只有0.45？",
            timestamp="2026-05-18T14:30:45Z",
        ))

        result = await archiver.close_session()

        assert result["turn_count"] == 2
        assert "jsonl_hash" in result
        assert len(result["jsonl_hash"]) > 0
        assert result["jsonl_path"] == str(jsonl_path)
        assert "md_path" in result

        # MD should have integrity footer
        md_path = jsonl_path.with_suffix(".md")
        md_content = md_path.read_text(encoding="utf-8")
        assert "Archive integrity" in md_content
        assert "JSONL hash" in md_content
        assert "2 events" in md_content
        assert "Canonical source" in md_content
        assert "rendered view for human reading only" in md_content
        assert result["jsonl_hash"] in md_content

        archive.close()


@pytest.mark.asyncio
async def test_jsonl_content_type_field_present():
    """Every JSONL line must have content_type field."""
    with tempfile.TemporaryDirectory() as td:
        archive = MarketMindArchive(Path(td))
        archiver = GateArchiver(archive)

        jsonl_path = await archiver.start_session(1, "test-session-006")

        turns = [
            GateTurn(turn=1, speaker="AI", type="hypothesis_card",
                     content_type="structured_data",
                     data={"direction": "tech"}, timestamp="2026-05-18T14:30:00Z"),
            GateTurn(turn=2, speaker="USER", type="question",
                     content_type="user_free_text",
                     text="Why?", timestamp="2026-05-18T14:31:00Z"),
            GateTurn(turn=3, speaker="AI", type="confirmation",
                     content_type="system_decision",
                     text="Confirmed.", timestamp="2026-05-18T14:32:00Z"),
            GateTurn(turn=4, speaker="AI", type="bear_case_detail",
                     content_type="ai_response",
                     text="Here is the bear case.", timestamp="2026-05-18T14:33:00Z"),
        ]

        for t in turns:
            await archiver.log_turn(t)

        lines = jsonl_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 4

        for i, line in enumerate(lines):
            parsed = json.loads(line)
            assert "content_type" in parsed, (
                f"Line {i + 1} missing content_type: {line}"
            )
            assert parsed["content_type"], f"Line {i + 1} has empty content_type"

        archive.close()


@pytest.mark.asyncio
async def test_timestamps_use_utc():
    """All timestamps must be UTC ISO format (end with Z or +00:00 offset)."""
    with tempfile.TemporaryDirectory() as td:
        archive = MarketMindArchive(Path(td))
        archiver = GateArchiver(archive)

        jsonl_path = await archiver.start_session(1, "test-session-007")

        # Turn with explicit timestamp
        await archiver.log_turn(GateTurn(
            turn=1, speaker="AI", type="system",
            content_type="system_decision",
            timestamp="2026-05-18T14:30:00Z",
        ))

        # Turn without timestamp — should be auto-filled with UTC
        await archiver.log_turn(GateTurn(
            turn=2, speaker="USER", type="question",
            content_type="user_free_text",
            text="Test question",
        ))

        lines = jsonl_path.read_text(encoding="utf-8").strip().split("\n")

        for i, line in enumerate(lines):
            parsed = json.loads(line)
            ts = parsed["timestamp"]
            # ISO 8601 UTC: must end with Z or +00:00
            assert ts.endswith("Z") or ts.endswith("+00:00"), (
                f"Line {i + 1} timestamp not UTC: {ts}"
            )
            # Must parse as ISO-8601
            normalized = ts.replace("Z", "+00:00")
            datetime.fromisoformat(normalized)

        # Decision timestamp should also be UTC
        await archiver.log_decision({"direction": "tech"})
        decision_path = archive.today_path() / "gates" / "gate1_decision.json"
        loaded = json.loads(decision_path.read_text(encoding="utf-8"))
        decision_ts = loaded["timestamp"]
        assert decision_ts.endswith("Z") or decision_ts.endswith("+00:00")

        archive.close()
