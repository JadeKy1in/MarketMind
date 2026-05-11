"""Tests for progress tracker and indeterminate spinner."""
import time
from projects.marketmind.ui.progress import ProgressTracker, IndeterminateSpinner


def test_progress_tracker_initial_state():
    pt = ProgressTracker(total_stages=8)
    assert pt.current_stage == 0
    assert pt.fraction == 0.0
    assert pt.pct == 0
    assert not pt.is_complete


def test_progress_tracker_advance():
    pt = ProgressTracker(total_stages=4)
    pt.advance("Stage 1")
    assert pt.current_stage == 1
    assert pt.stage_name == "Stage 1"
    assert pt.fraction == 0.25
    assert pt.pct == 25


def test_progress_tracker_complete():
    pt = ProgressTracker(total_stages=3)
    pt.advance("S1")
    pt.advance("S2")
    pt.advance("S3")
    assert pt.current_stage == 3
    assert pt.is_complete


def test_progress_tracker_fraction_capped():
    pt = ProgressTracker(total_stages=2)
    pt.advance("S1")
    pt.advance("S2")
    pt.advance("S3")
    assert pt.fraction == 1.0


def test_progress_tracker_eta():
    pt = ProgressTracker(total_stages=5)
    pt.advance("S1")
    time.sleep(0.1)
    pt.advance("S2")
    eta = pt.eta_seconds
    assert eta is not None
    assert eta > 0


def test_progress_tracker_tick():
    pt = ProgressTracker(total_stages=5)
    pt.advance("S1")
    f = pt.tick()
    assert 0.0 <= f <= 1.0


def test_indeterminate_spinner_next():
    spinner = IndeterminateSpinner()
    chars = {spinner.next() for _ in range(20)}
    assert len(chars) >= 2


def test_indeterminate_spinner_interval_grows():
    spinner = IndeterminateSpinner(base_interval=0.1, decel_factor=2.0)
    initial = spinner.interval
    for _ in range(100):
        spinner.next()
    grown = spinner.interval
    assert grown > initial
