"""Tests for async_bridge — daemon-thread asyncio + tkinter bridge."""
import time
import asyncio
import pytest
from unittest.mock import MagicMock


class FakeRoot:
    """Minimal tkinter root stand-in for tests."""
    def __init__(self):
        self._after_calls = []

    def after(self, ms, callback):
        self._after_calls.append((ms, callback))
        return f"after_{len(self._after_calls)}"


@pytest.fixture
def fake_root():
    return FakeRoot()


@pytest.fixture
def bridge(fake_root):
    from projects.marketmind.ui.async_bridge import AsyncBridge
    b = AsyncBridge(fake_root)
    b.start()
    yield b
    b.stop()


def test_start_creates_event_loop(bridge):
    assert bridge._loop is not None
    assert bridge._running


def test_pending_count_zero_initially(bridge):
    assert bridge.pending_count == 0


def test_submit_increments_pending(bridge):
    async def dummy():
        await asyncio.sleep(0.01)
        return 42

    callback = MagicMock()
    bridge.submit("test-1", dummy(), callback)
    time.sleep(0.2)
    assert bridge.pending_count <= 1


def test_submit_completes_and_calls_callback(bridge):
    received = []

    async def dummy():
        await asyncio.sleep(0.01)
        return "result_value"

    def cb(value):
        received.append(value)

    bridge.submit("test-2", dummy(), cb)
    time.sleep(0.3)

    bridge.poll(50)
    time.sleep(0.1)

    assert "result_value" in received


def test_submit_error_calls_callback_with_exception(bridge):
    errors = []

    async def failing():
        await asyncio.sleep(0.01)
        raise ValueError("boom")

    def cb(value):
        errors.append(value)

    bridge.submit("test-3", failing(), cb)
    time.sleep(0.3)

    bridge.poll(50)
    time.sleep(0.1)

    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)
    assert "boom" in str(errors[0])


def test_poll_registers_after_callback(bridge, fake_root):
    bridge.poll(100)
    assert len(fake_root._after_calls) >= 1
    ms, cb = fake_root._after_calls[-1]
    assert ms == 100


def test_stop_stops_running(bridge):
    bridge.stop()
    assert not bridge._running


def test_multiple_submits_run_concurrently(bridge):
    results = []

    async def work(n):
        await asyncio.sleep(0.02)
        return n * 10

    def make_cb():
        def cb(val):
            if not isinstance(val, Exception):
                results.append(val)
        return cb

    for i in range(5):
        bridge.submit(f"multi-{i}", work(i), make_cb())

    time.sleep(0.3)
    bridge.poll(50)
    time.sleep(0.1)

    assert len(results) == 5
    assert sorted(results) == [0, 10, 20, 30, 40]
