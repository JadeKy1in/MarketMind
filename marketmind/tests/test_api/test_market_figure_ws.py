"""Tests for broadcast_person_signal — actual function invocation.

Verifies that the production broadcast_person_signal() function:
- Accepts a FigureSignal and calls _manager.broadcast() with the correct payload
- Does not raise exceptions when no clients are connected
- Serializes all FigureSignal fields correctly into the broadcast dict
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from marketmind.api.websocket import _manager, broadcast_person_signal
from marketmind.pipeline.figure_signal import FigureSignal


# ── Fixtures ────────────────────────────────────────────────────────────────────


def _make_signal(**overrides) -> FigureSignal:
    """Factory: create a FigureSignal with sensible defaults, overridable per-field."""
    defaults = dict(
        person_name="Jerome Powell",
        category="I",
        signal_direction="directional",
        event_type="speech",
        ticker=None,
        direction="long",
        awa_score=0.85,
        confidence=0.9,
        summary="Powell signals patience on rate cuts",
        source_url="https://example.com/fed",
        timestamp="2026-05-21T14:00:00Z",
    )
    defaults.update(overrides)
    return FigureSignal(**defaults)


# ── Test: broadcast_person_signal calls _manager.broadcast with correct payload ──


class TestBroadcastPersonSignal:
    """Actual invocation of broadcast_person_signal() with patched _manager."""

    @pytest.mark.asyncio
    async def test_broadcast_person_signal_no_exceptions(self):
        """Calling broadcast_person_signal with a valid FigureSignal raises no errors."""
        signal = _make_signal()
        with patch.object(_manager, "broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_person_signal(signal)

        mock_bc.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_person_signal_correct_payload_type(self):
        """broadcast_person_signal sends payload with type='person_signal'."""
        signal = _make_signal()
        with patch.object(_manager, "broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_person_signal(signal)

        payload = mock_bc.call_args[0][0]
        assert payload["type"] == "person_signal"

    @pytest.mark.asyncio
    async def test_broadcast_person_signal_person_name(self):
        """The person_name field is correctly passed through to the broadcast payload."""
        signal = _make_signal(person_name="Nancy Pelosi")
        with patch.object(_manager, "broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_person_signal(signal)

        payload = mock_bc.call_args[0][0]
        assert payload["person_name"] == "Nancy Pelosi"

    @pytest.mark.asyncio
    async def test_broadcast_person_signal_awa_score(self):
        """The awa_score field is correctly passed through."""
        signal = _make_signal(awa_score=0.92)
        with patch.object(_manager, "broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_person_signal(signal)

        payload = mock_bc.call_args[0][0]
        assert payload["awa_score"] == 0.92

    @pytest.mark.asyncio
    async def test_broadcast_person_signal_direction(self):
        """The direction field is correctly passed through."""
        signal = _make_signal(direction="short")
        with patch.object(_manager, "broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_person_signal(signal)

        payload = mock_bc.call_args[0][0]
        assert payload["direction"] == "short"

    @pytest.mark.asyncio
    async def test_broadcast_person_signal_event_type(self):
        """The event_type field is correctly passed through."""
        signal = _make_signal(event_type="trade")
        with patch.object(_manager, "broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_person_signal(signal)

        payload = mock_bc.call_args[0][0]
        assert payload["event_type"] == "trade"

    @pytest.mark.asyncio
    async def test_broadcast_person_signal_ticker(self):
        """The ticker field is correctly passed through (including None)."""
        signal = _make_signal(ticker="NVDA")
        with patch.object(_manager, "broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_person_signal(signal)

        payload = mock_bc.call_args[0][0]
        assert payload["ticker"] == "NVDA"

    @pytest.mark.asyncio
    async def test_broadcast_person_signal_ticker_none(self):
        """None ticker is serialized correctly in the payload."""
        signal = _make_signal(ticker=None)
        with patch.object(_manager, "broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_person_signal(signal)

        payload = mock_bc.call_args[0][0]
        assert payload["ticker"] is None

    @pytest.mark.asyncio
    async def test_broadcast_person_signal_confidence(self):
        """The confidence field is correctly passed through."""
        signal = _make_signal(confidence=0.75)
        with patch.object(_manager, "broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_person_signal(signal)

        payload = mock_bc.call_args[0][0]
        assert payload["confidence"] == 0.75

    @pytest.mark.asyncio
    async def test_broadcast_person_signal_summary(self):
        """The summary field is correctly passed through."""
        signal = _make_signal(summary="Rate hold decision confirmed")
        with patch.object(_manager, "broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_person_signal(signal)

        payload = mock_bc.call_args[0][0]
        assert payload["summary"] == "Rate hold decision confirmed"

    @pytest.mark.asyncio
    async def test_broadcast_person_signal_source_url(self):
        """The source_url field is correctly passed through."""
        signal = _make_signal(source_url="https://www.federalreserve.gov/newsevents")
        with patch.object(_manager, "broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_person_signal(signal)

        payload = mock_bc.call_args[0][0]
        assert payload["source_url"] == "https://www.federalreserve.gov/newsevents"

    @pytest.mark.asyncio
    async def test_broadcast_person_signal_timestamp(self):
        """The timestamp field is correctly passed through."""
        signal = _make_signal(timestamp="2026-05-21T14:00:00Z")
        with patch.object(_manager, "broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_person_signal(signal)

        payload = mock_bc.call_args[0][0]
        assert payload["timestamp"] == "2026-05-21T14:00:00Z"

    @pytest.mark.asyncio
    async def test_broadcast_person_signal_category(self):
        """The category field is correctly passed through."""
        signal = _make_signal(category="III")
        with patch.object(_manager, "broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_person_signal(signal)

        payload = mock_bc.call_args[0][0]
        assert payload["category"] == "III"

    @pytest.mark.asyncio
    async def test_broadcast_person_signal_signal_direction(self):
        """The signal_direction field is correctly passed through."""
        signal = _make_signal(signal_direction="contrarian")
        with patch.object(_manager, "broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_person_signal(signal)

        payload = mock_bc.call_args[0][0]
        assert payload["signal_direction"] == "contrarian"

    @pytest.mark.asyncio
    async def test_broadcast_person_signal_all_fields_present(self):
        """The broadcast payload contains exactly the 12 expected keys."""
        signal = _make_signal()
        with patch.object(_manager, "broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_person_signal(signal)

        payload = mock_bc.call_args[0][0]
        expected_keys = {
            "type", "person_name", "category", "signal_direction",
            "event_type", "ticker", "direction", "awa_score",
            "confidence", "summary", "source_url", "timestamp",
        }
        assert set(payload.keys()) == expected_keys

    @pytest.mark.asyncio
    async def test_broadcast_person_signal_full_roundtrip(self):
        """Create a complete FigureSignal, broadcast it, verify all field values match."""
        signal = _make_signal(
            person_name="Warren Buffett",
            category="V",
            signal_direction="confirmatory",
            event_type="filing",
            ticker="AAPL",
            direction="long",
            awa_score=0.88,
            confidence=0.95,
            summary="Berkshire increases AAPL stake",
            source_url="https://example.com/13f",
            timestamp="2026-05-22T10:30:00Z",
        )

        with patch.object(_manager, "broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_person_signal(signal)

        payload = mock_bc.call_args[0][0]
        assert payload["type"] == "person_signal"
        assert payload["person_name"] == "Warren Buffett"
        assert payload["category"] == "V"
        assert payload["signal_direction"] == "confirmatory"
        assert payload["event_type"] == "filing"
        assert payload["ticker"] == "AAPL"
        assert payload["direction"] == "long"
        assert payload["awa_score"] == 0.88
        assert payload["confidence"] == 0.95
        assert payload["summary"] == "Berkshire increases AAPL stake"
        assert payload["source_url"] == "https://example.com/13f"
        assert payload["timestamp"] == "2026-05-22T10:30:00Z"

    @pytest.mark.asyncio
    async def test_broadcast_person_signal_no_clients_no_error(self):
        """broadcast_person_signal should not raise when no WebSocket clients are connected."""
        signal = _make_signal()
        # No patching — call directly with empty manager. broadcast is a no-op
        # when _connections is empty.
        await broadcast_person_signal(signal)
        # No exception raised = pass

    @pytest.mark.asyncio
    async def test_broadcast_person_signal_is_async_coroutine(self):
        """broadcast_person_signal returns an awaitable coroutine."""
        import asyncio
        signal = _make_signal()
        coro = broadcast_person_signal(signal)
        assert asyncio.iscoroutine(coro)
        # Clean up the coroutine
        await coro
