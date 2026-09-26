"""Tests for @monitor decorator — exception, empty, timeout capture."""
import asyncio
import pytest
from marketmind.notification.alert_manager import get_alert_manager
from marketmind.notification.monitor_decorator import monitor
from marketmind.notification.alert_schema import ImpactScope


def _singleton() -> "AlertManager":
    """Return the singleton AlertManager and clear it for test isolation."""
    am = get_alert_manager()
    am._alerts.clear()
    am._dedup_window.clear()
    am._source_cooldown.clear()
    am._warn_timestamps.clear()
    return am


@pytest.mark.asyncio
async def test_monitor_captures_exception():
    am = _singleton()
    @monitor(source="test_exception", impact=ImpactScope.MAIN_PIPELINE)
    async def failing_func():
        raise ValueError("test error")

    with pytest.raises(ValueError):
        await failing_func()

    recent = am.recent()
    errors = [a for a in recent if a["severity"] == "ERROR"]
    assert len(errors) >= 1
    assert "ValueError" in errors[-1]["title"]


@pytest.mark.asyncio
async def test_monitor_captures_empty_return():
    am = _singleton()
    @monitor(source="test_empty", impact=ImpactScope.MAIN_PIPELINE)
    async def empty_func():
        return None

    result = await empty_func()
    assert result is None
    recent = am.recent()
    assert any("empty" in a["title"] for a in recent)


@pytest.mark.asyncio
async def test_monitor_healthy_passes_through():
    am = _singleton()
    @monitor(source="test_healthy", impact=ImpactScope.MAIN_PIPELINE)
    async def good_func():
        return {"ok": True}

    result = await good_func()
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_monitor_timeout():
    am = _singleton()
    @monitor(source="test_timeout", impact=ImpactScope.MAIN_PIPELINE, timeout_s=0.1)
    async def slow_func():
        await asyncio.sleep(1.0)
        return "done"

    result = await slow_func()
    assert result is None
    recent = am.recent()
    assert any("timed out" in a["title"] for a in recent)
