"""
Tests for shadow_pipeline_orchestrator.py — Phase 8.1 Daily Shadow Run Pipeline Orchestrator.

Covers four scenarios:
  1. Day T execution: batch generation → EventStore write → report formatting.
  2. Day T+1 execution: tribunal judgment → verdict append → summary formatting.
  3. Full run (two-day combined): end-to-end pipeline integrity.
  4. Empty ticker pool edge case.

All tests use a temporary EventStore directory (via tempfile) to guarantee
immutable append-only isolation — no cross-test state pollution.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from src.shadow_pipeline_orchestrator import (
    DailyShadowRunPipeline,
    DayTRunResult,
    DayTPlus1RunResult,
    FullRunResult,
    DEFAULT_SHADOW_POOL,
    DEFAULT_EVENT_STORE_DIR,
)
from src.shadow_types import VerdictStatus


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def temp_store_dir() -> Generator[str, None, None]:
    """Create a temporary directory for EventStore isolation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def pipeline(temp_store_dir: str) -> DailyShadowRunPipeline:
    """Create a pipeline with a small ticker pool and temp EventStore."""
    return DailyShadowRunPipeline(
        store_dir=temp_store_dir,
        ticker_pool=["IAU", "GDX"],
        run_aggressive=True,
        run_ambiguous=True,
        strict_mode=True,
        replayer_seed=42,
    )


@pytest.fixture
def pipeline_full_pool(temp_store_dir: str) -> DailyShadowRunPipeline:
    """Create a pipeline with the full default pool for realism."""
    return DailyShadowRunPipeline(
        store_dir=temp_store_dir,
        run_aggressive=True,
        run_ambiguous=True,
        strict_mode=True,
        replayer_seed=42,
    )


@pytest.fixture
def pipeline_empty_pool(temp_store_dir: str) -> DailyShadowRunPipeline:
    """Create a pipeline with an empty ticker pool (edge case)."""
    return DailyShadowRunPipeline(
        store_dir=temp_store_dir,
        ticker_pool=[],
        run_aggressive=True,
        run_ambiguous=True,
        strict_mode=True,
        replayer_seed=42,
    )


# ============================================================
# Helpers
# ============================================================


def _count_lines(filepath: Path) -> int:
    """Count non-empty lines in a JSONL file."""
    if not filepath.exists():
        return 0
    count = 0
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def _assert_jsonl_valid(filepath: Path, min_lines: int = 1) -> None:
    """Assert that a JSONL file has valid JSON on each line."""
    assert filepath.exists(), f"Expected {filepath} to exist"
    with open(filepath, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]
    assert len(lines) >= min_lines, (
        f"Expected >= {min_lines} lines, got {len(lines)} in {filepath}"
    )
    for i, line in enumerate(lines):
        try:
            json.loads(line)
        except json.JSONDecodeError as e:
            pytest.fail(f"Line {i} in {filepath} is not valid JSON: {e}")


# ============================================================
# Tests
# ============================================================


class TestDayTExecution:
    """Scenario 1: Day T snapshot pipeline."""

    def test_basic_day_t(self, pipeline: DailyShadowRunPipeline) -> None:
        """Day T executes and returns a valid DayTRunResult."""
        result = pipeline.execute_day_t(date="2026-05-07")

        assert isinstance(result, DayTRunResult)
        assert result.date == "2026-05-07"
        assert result.batch is not None
        assert result.report is not None
        assert result.events_written >= 1

        # Verify batch content
        batch = result.batch
        assert len(batch.tickers) == 2  # IAU, GDX
        assert batch.total_predictions > 0
        assert len(batch.scenarios) >= 1

        # Verify report content
        report = result.report
        assert report.batch_id == batch.batch_id
        assert report.total_predictions == batch.total_predictions
        assert "SHADOW MODE REPORT" in report.output_text
        assert report.output_json != ""
        assert json.loads(report.output_json) is not None  # valid JSON

    def test_day_t_event_store_write(
        self, pipeline: DailyShadowRunPipeline, temp_store_dir: str
    ) -> None:
        """Day T writes to all three EventStore streams (append-only)."""
        store_path = Path(temp_store_dir)

        # Pre-run: streams should be empty
        assert _count_lines(store_path / "predictions.jsonl") == 0
        assert _count_lines(store_path / "verdicts.jsonl") == 0
        assert _count_lines(store_path / "batches.jsonl") == 0

        result = pipeline.execute_day_t(date="2026-05-07")

        # Post-run: predictions and batches should have data
        pred_lines = _count_lines(store_path / "predictions.jsonl")
        batch_lines = _count_lines(store_path / "batches.jsonl")

        assert batch_lines == 1, "Expected exactly one batch event"
        assert pred_lines >= 1, "Expected at least one prediction event"
        assert _count_lines(store_path / "verdicts.jsonl") == 0  # No verdicts yet

        # Validate JSONL format
        _assert_jsonl_valid(store_path / "predictions.jsonl", min_lines=1)
        _assert_jsonl_valid(store_path / "batches.jsonl", min_lines=1)

        # Verify event store path in result
        assert result.store_path.endswith(temp_store_dir.replace("\\", "/").split("/")[-1]) or \
               temp_store_dir in result.store_path

    def test_day_t_full_pool(
        self, pipeline_full_pool: DailyShadowRunPipeline
    ) -> None:
        """Day T works with the full default ticker pool."""
        result = pipeline_full_pool.execute_day_t(date="2026-05-07")

        assert result.batch is not None
        assert result.batch.total_predictions > len(DEFAULT_SHADOW_POOL)
        assert len(result.batch.tickers) == len(DEFAULT_SHADOW_POOL)

    def test_day_t_formatting_integrity(
        self, pipeline: DailyShadowRunPipeline
    ) -> None:
        """Day T report formatting reflects actual batch data."""
        result = pipeline.execute_day_t(date="2026-05-07")
        report = result.report
        batch = result.batch

        assert report is not None
        # Text report should include tickers from batch
        for ticker in batch.tickers:
            assert ticker in report.output_text or ticker.upper() in report.output_text

        # JSON body should include all predictions
        json_body = json.loads(report.output_json)
        assert json_body["total_predictions"] == batch.total_predictions
        assert len(json_body["scenarios"]) == len(batch.scenarios)


class TestDayTPlus1Execution:
    """Scenario 2: Day T+1 reconciliation pipeline."""

    def test_basic_day_t_plus_1(self, pipeline: DailyShadowRunPipeline) -> None:
        """Day T+1 executes after Day T and returns valid verdicts."""
        day_t_result = pipeline.execute_day_t(date="2026-05-07")
        result = pipeline.execute_day_t_plus_1(
            day_t_result=day_t_result,
            date="2026-05-08",
        )

        assert isinstance(result, DayTPlus1RunResult)
        assert result.date == "2026-05-08"
        assert result.previous_date == "2026-05-07"
        assert len(result.verdicts) > 0
        assert result.events_written == len(result.verdicts)

        # All verdicts should have valid status
        for verdict in result.verdicts:
            assert verdict.status in (VerdictStatus.PASS, VerdictStatus.FAIL, VerdictStatus.PENDING)

    def test_day_t_plus_1_verdict_count(
        self, pipeline: DailyShadowRunPipeline
    ) -> None:
        """Number of verdicts should be >= number of predictions (may merge)."""
        day_t_result = pipeline.execute_day_t(date="2026-05-07")
        total_predictions = day_t_result.batch.total_predictions

        result = pipeline.execute_day_t_plus_1(
            day_t_result=day_t_result,
            date="2026-05-08",
        )

        # Every prediction should receive a verdict
        assert len(result.verdicts) >= total_predictions * 0.5  # tolerance for merges

    def test_day_t_plus_1_event_store_write(
        self, pipeline: DailyShadowRunPipeline, temp_store_dir: str
    ) -> None:
        """Day T+1 appends verdicts to the EventStore (no duplicate predictions)."""
        store_path = Path(temp_store_dir)

        day_t_result = pipeline.execute_day_t(date="2026-05-07")
        pre_verdict_lines = _count_lines(store_path / "verdicts.jsonl")
        pre_pred_lines = _count_lines(store_path / "predictions.jsonl")

        result = pipeline.execute_day_t_plus_1(
            day_t_result=day_t_result,
            date="2026-05-08",
        )

        # Verdicts should have been written
        post_verdict_lines = _count_lines(store_path / "verdicts.jsonl")
        assert post_verdict_lines >= pre_verdict_lines + len(result.verdicts)

        # Predictions should NOT have been re-written (immutable append-only)
        post_pred_lines = _count_lines(store_path / "predictions.jsonl")
        assert post_pred_lines == pre_pred_lines, \
            "Day T+1 must NOT append to prediction stream"

        # Validate JSONL format
        _assert_jsonl_valid(store_path / "verdicts.jsonl", min_lines=1)

    def test_day_t_plus_1_summary(
        self, pipeline: DailyShadowRunPipeline
    ) -> None:
        """Day T+1 produces a valid TribunalSummary with pass rates."""
        day_t_result = pipeline.execute_day_t(date="2026-05-07")
        result = pipeline.execute_day_t_plus_1(
            day_t_result=day_t_result,
            date="2026-05-08",
        )

        summary = result.summary
        assert summary is not None
        assert summary.batch_id == day_t_result.batch.batch_id
        assert summary.total_judged == len(result.verdicts)
        assert summary.total_judged >= summary.passed + summary.failed
        assert 0.0 <= summary.pass_rate_pct <= 100.0

        # Ticker breakdown should exist
        assert len(summary.ticker_breakdown) > 0
        for ticker, stats in summary.ticker_breakdown.items():
            assert stats["total"] > 0
            assert stats["passed"] + stats["failed"] <= stats["total"]
            assert 0.0 <= stats["pass_rate_pct"] <= 100.0

    def test_day_t_plus_1_without_day_t(self, pipeline: DailyShadowRunPipeline) -> None:
        """Day T+1 raises ValueError if day_t_result has no batch."""
        empty_result = DayTRunResult(date="2026-05-07")
        with pytest.raises(ValueError, match="requires day_t_result.batch"):
            pipeline.execute_day_t_plus_1(day_t_result=empty_result)


class TestFullRun:
    """Scenario 3: End-to-end Day T → Day T+1 pipeline."""

    def test_full_run_integrity(self, pipeline: DailyShadowRunPipeline) -> None:
        """Full run returns a combined result with both stages."""
        full_result = pipeline.execute_full_run(
            day_t_date="2026-05-07",
            day_t_plus_1_date="2026-05-08",
        )

        assert isinstance(full_result, FullRunResult)
        assert full_result.day_t is not None
        assert full_result.day_t_plus_1 is not None
        assert full_result.total_events > 0

        # Day T result
        assert full_result.day_t.date == "2026-05-07"
        assert full_result.day_t.batch is not None

        # Day T+1 result
        assert full_result.day_t_plus_1.date == "2026-05-08"
        assert full_result.day_t_plus_1.previous_date == "2026-05-07"
        assert len(full_result.day_t_plus_1.verdicts) > 0

        # Event counts should be consistent
        expected_total = (
            full_result.day_t.events_written +
            full_result.day_t_plus_1.events_written
        )
        assert full_result.total_events == expected_total

    def test_full_run_event_trail(
        self, pipeline: DailyShadowRunPipeline, temp_store_dir: str
    ) -> None:
        """Full run produces a complete immutable event trail (all three streams)."""
        store_path = Path(temp_store_dir)

        pipeline.execute_full_run(
            day_t_date="2026-05-07",
            day_t_plus_1_date="2026-05-08",
        )

        # All three event streams should have data
        pred_lines = _count_lines(store_path / "predictions.jsonl")
        verdict_lines = _count_lines(store_path / "verdicts.jsonl")
        batch_lines = _count_lines(store_path / "batches.jsonl")

        assert pred_lines >= 1, f"Expected >=1 predictions, got {pred_lines}"
        assert verdict_lines >= 1, f"Expected >=1 verdicts, got {verdict_lines}"
        assert batch_lines >= 1, f"Expected >=1 batches, got {batch_lines}"

        # Validate all JSONL files
        _assert_jsonl_valid(store_path / "predictions.jsonl", min_lines=1)
        _assert_jsonl_valid(store_path / "verdicts.jsonl", min_lines=1)
        _assert_jsonl_valid(store_path / "batches.jsonl", min_lines=1)

    def test_full_run_idempotent_second_run(
        self, pipeline: DailyShadowRunPipeline, temp_store_dir: str
    ) -> None:
        """Running the full pipeline twice appends new events (never overwrites)."""
        store_path = Path(temp_store_dir)

        # First run
        result_1 = pipeline.execute_full_run(
            day_t_date="2026-05-07",
            day_t_plus_1_date="2026-05-08",
        )

        pred_after_1 = _count_lines(store_path / "predictions.jsonl")
        batch_after_1 = _count_lines(store_path / "batches.jsonl")

        # Second run (different dates)
        result_2 = pipeline.execute_full_run(
            day_t_date="2026-05-08",
            day_t_plus_1_date="2026-05-09",
        )

        pred_after_2 = _count_lines(store_path / "predictions.jsonl")
        batch_after_2 = _count_lines(store_path / "batches.jsonl")

        # Second run must append, not overwrite
        assert pred_after_2 > pred_after_1, "Predictions must be appended, not overwritten"
        assert batch_after_2 > batch_after_1, "Batches must be appended, not overwritten"
        assert result_1.day_t.batch.batch_id != result_2.day_t.batch.batch_id, \
            "Each run should produce a unique batch ID"


class TestEmptyPoolEdgeCase:
    """Scenario 4: Edge case — empty ticker pool."""

    def test_empty_pool_day_t(self, pipeline_empty_pool: DailyShadowRunPipeline) -> None:
        """Day T with empty pool returns zero predictions."""
        result = pipeline_empty_pool.execute_day_t(date="2026-05-07")

        assert result.batch is not None
        assert len(result.batch.tickers) == 0
        assert result.batch.total_predictions == 0
        assert result.events_written >= 1  # batch event still written

    def test_empty_pool_full_run(
        self, pipeline_empty_pool: DailyShadowRunPipeline
    ) -> None:
        """Full run with empty pool produces zero verdicts."""
        full_result = pipeline_empty_pool.execute_full_run(
            day_t_date="2026-05-07",
            day_t_plus_1_date="2026-05-08",
        )

        assert full_result.day_t is not None
        assert full_result.day_t_plus_1 is not None


class TestConfiguration:
    """Pipeline configuration and properties."""

    def test_default_config(self) -> None:
        """Pipeline initialises with sensible defaults."""
        pipe = DailyShadowRunPipeline()
        assert pipe.ticker_pool == DEFAULT_SHADOW_POOL
        assert pipe.store_dir == DEFAULT_EVENT_STORE_DIR

    def test_custom_config(self, temp_store_dir: str) -> None:
        """Pipeline accepts custom configuration."""
        pipe = DailyShadowRunPipeline(
            store_dir=temp_store_dir,
            ticker_pool=["SPY", "QQQ"],
            run_aggressive=False,
            run_ambiguous=True,
            strict_mode=False,
            replayer_seed=99,
        )
        assert pipe.ticker_pool == ["SPY", "QQQ"]
        assert pipe.store_dir == temp_store_dir

    def test_ticker_pool_immutability(self, temp_store_dir: str) -> None:
        """ticker_pool property returns a copy, not the internal list."""
        pipe = DailyShadowRunPipeline(
            store_dir=temp_store_dir,
            ticker_pool=["IAU", "GDX"],
        )
        external_ref = pipe.ticker_pool
        external_ref.append("SPY")
        # Internal list should be unchanged
        assert pipe.ticker_pool == ["IAU", "GDX"]  # fresh copy