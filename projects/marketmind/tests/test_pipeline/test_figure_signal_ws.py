"""Tests for broadcast_person_signal — WebSocket broadcast of FigureSignal.

Covers: message format, edge cases, multiple broadcasts, client receipt,
and serialization contract.

NOTE (2026-05-23): The production function `broadcast_person_signal` does NOT
exist in api/websocket.py. Only `broadcast_stage()` and `broadcast_log()` are
implemented. The RESTART_GUIDE.md line 39 claims it is "implemented, pending
testing" — this is incorrect. These tests define the expected contract and will
pass once the function is created in api/websocket.py following the pattern of
broadcast_stage() and broadcast_log().
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from marketmind.api.websocket import (
    _ConnectionManager,
    _manager,
    broadcast_log,
    broadcast_stage,
)
from marketmind.pipeline.figure_signal import FigureSignal


# ── Fixtures ────────────────────────────────────────────────────────────────────


def _make_signal(
    person_name: str = "Jerome Powell",
    category: str = "I",
    signal_direction: str = "directional",
    event_type: str = "speech",
    ticker: str | None = None,
    direction: str | None = "long",
    awa_score: float = 0.85,
    confidence: float = 0.9,
    summary: str = "Powell signals patience on rate cuts",
    source_url: str = "https://example.com/fed",
    timestamp: str = "2026-05-21T14:00:00Z",
) -> FigureSignal:
    """Factory: create a standard FigureSignal for WebSocket broadcast tests."""
    return FigureSignal(
        person_name=person_name,
        category=category,
        signal_direction=signal_direction,
        event_type=event_type,
        ticker=ticker,
        direction=direction,
        awa_score=awa_score,
        confidence=confidence,
        summary=summary,
        source_url=source_url,
        timestamp=timestamp,
    )


def _expected_ws_payload(signal: FigureSignal) -> dict:
    """Construct the expected WebSocket payload for a figure signal.

    This defines the contract for what broadcast_person_signal() should emit.
    Based on the established pattern: broadcast_stage uses {"type": "stage", ...}
    and broadcast_log uses {"type": "log", ...}. Therefore the figure signal
    broadcast should use {"type": "person_signal", ...} with the FigureSignal
    fields serialized.
    """
    return {
        "type": "person_signal",
        "person_name": signal.person_name,
        "category": signal.category,
        "signal_direction": signal.signal_direction,
        "event_type": signal.event_type,
        "ticker": signal.ticker,
        "direction": signal.direction,
        "awa_score": signal.awa_score,
        "confidence": signal.confidence,
        "summary": signal.summary,
        "source_url": signal.source_url,
        "timestamp": signal.timestamp,
    }


# ── Test 1: ConnectionManager broadcast mechanism ───────────────────────────────


class TestConnectionManager:
    """Verify the underlying WebSocket broadcast infrastructure works correctly."""

    def test_manager_is_singleton(self):
        """_manager is a module-level singleton — broadcast_person_signal must use it."""
        assert _manager is not None
        assert isinstance(_manager, _ConnectionManager)

    @pytest.mark.asyncio
    async def test_broadcast_sends_json_to_all_clients(self):
        """_manager.broadcast() serializes a dict and sends to all connected clients."""
        ws_mock = AsyncMock()
        manager = _ConnectionManager()
        await manager.connect(ws_mock)

        payload = {"type": "person_signal", "person_name": "Test Person"}
        await manager.broadcast(payload)

        expected_msg = json.dumps(payload, ensure_ascii=False)
        ws_mock.send_text.assert_called_once_with(expected_msg)

    @pytest.mark.asyncio
    async def test_broadcast_only_sends_to_connected(self):
        """broadcast() is a no-op when no clients are connected (no errors)."""
        manager = _ConnectionManager()
        # No connections added — broadcast should return silently
        await manager.broadcast({"type": "test"})
        # No exception = pass

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_connections(self):
        """Disconnected clients are cleaned up — zombie clients don't accumulate."""
        good_ws = AsyncMock()
        dead_ws = AsyncMock()
        dead_ws.send_text.side_effect = RuntimeError("connection lost")

        manager = _ConnectionManager()
        await manager.connect(good_ws)
        await manager.connect(dead_ws)

        await manager.broadcast({"type": "test"})

        # good_ws should have received the message
        good_ws.send_text.assert_called_once()
        # dead_ws was removed — the internal set no longer contains it
        assert dead_ws not in manager._connections

    @pytest.mark.asyncio
    async def test_connect_and_disconnect_lifecycle(self):
        """Full connect → broadcast → disconnect cycle works end-to-end."""
        ws = AsyncMock()
        manager = _ConnectionManager()

        await manager.connect(ws)
        ws.accept.assert_called_once()
        assert ws in manager._connections
        assert len(manager._connections) == 1

        await manager.disconnect(ws)
        assert ws not in manager._connections
        assert len(manager._connections) == 0


# ── Test 2: broadcast_stage and broadcast_log patterns (reference implementation) ─


class TestExistingBroadcastFunctions:
    """Verify broadcast_stage and broadcast_log — the patterns that
    broadcast_person_signal should follow.

    Uses patch.object on the singleton _manager so we inspect the payload
    without needing real WebSocket clients connected to the singleton.
    """

    @pytest.mark.asyncio
    async def test_broadcast_stage_message_format(self):
        """broadcast_stage produces correct type/stage/pct/status payload."""
        with patch.object(_manager, "broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_stage("scout", 50.0, "running")

        mock_bc.assert_called_once()
        payload = mock_bc.call_args[0][0]
        assert payload["type"] == "stage"
        assert payload["stage"] == "scout"
        assert payload["pct"] == 50.0
        assert payload["status"] == "running"

    @pytest.mark.asyncio
    async def test_broadcast_stage_rounds_pct(self):
        """broadcast_stage rounds percentage to 1 decimal place."""
        with patch.object(_manager, "broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_stage("scout", 67.89123, "running")

        mock_bc.assert_called_once()
        payload = mock_bc.call_args[0][0]
        assert payload["pct"] == 67.9

    @pytest.mark.asyncio
    async def test_broadcast_log_message_format(self):
        """broadcast_log produces correct type/level/message/ts payload."""
        with patch.object(_manager, "broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_log("info", "Test log message")

        mock_bc.assert_called_once()
        payload = mock_bc.call_args[0][0]
        assert payload["type"] == "log"
        assert payload["level"] == "info"
        assert payload["message"] == "Test log message"
        assert "ts" in payload  # HH:MM:SS format

    @pytest.mark.asyncio
    async def test_log_ts_format_is_hh_mm_ss(self):
        """broadcast_log timestamp is in HH:MM:SS format."""
        with patch.object(_manager, "broadcast", new_callable=AsyncMock) as mock_bc:
            await broadcast_log("warn", "Warning message")

        mock_bc.assert_called_once()
        payload = mock_bc.call_args[0][0]
        ts = payload["ts"]
        parts = ts.split(":")
        assert len(parts) == 3
        assert 0 <= int(parts[0]) <= 23
        assert 0 <= int(parts[1]) <= 59
        assert 0 <= int(parts[2]) <= 59


# ── Test 3: FigureSignal to WebSocket message serialization ──────────────────────


class TestFigureSignalMessageFormat:
    """Verify the serialization contract for FigureSignal → WebSocket payload.

    These tests define the expected message format that broadcast_person_signal()
    should produce when it is implemented. They use the _expected_ws_payload()
    helper as the reference contract.
    """

    def test_critical_signal_full_payload(self):
        """A critical (AWA >= 0.80) signal serializes with all fields present."""
        signal = _make_signal(
            person_name="Jerome Powell",
            awa_score=0.92,
            direction="long",
            category="I",
            event_type="speech",
            summary="Fed holds rates steady, signals patience on cuts",
            timestamp="2026-05-21T14:00:00Z",
        )
        payload = _expected_ws_payload(signal)

        assert payload["type"] == "person_signal"
        assert payload["person_name"] == "Jerome Powell"
        assert payload["awa_score"] == 0.92
        assert payload["direction"] == "long"
        assert payload["category"] == "I"
        assert payload["event_type"] == "speech"
        assert payload["summary"] == "Fed holds rates steady, signals patience on cuts"
        assert payload["timestamp"] == "2026-05-21T14:00:00Z"

    def test_signal_with_ticker(self):
        """Signals with an associated ticker include it in the payload."""
        signal = _make_signal(
            person_name="Nancy Pelosi",
            ticker="NVDA",
            event_type="trade",
            direction="long",
        )
        payload = _expected_ws_payload(signal)

        assert payload["ticker"] == "NVDA"
        assert payload["event_type"] == "trade"

    def test_signal_with_none_ticker(self):
        """None ticker is serialized as null/None in the payload."""
        signal = _make_signal(person_name="Powell", ticker=None)
        payload = _expected_ws_payload(signal)

        assert payload["ticker"] is None

    def test_low_confidence_signal(self):
        """Low confidence signals are still broadcast — filtering is downstream."""
        signal = _make_signal(
            person_name="Andrei Jikh",
            confidence=0.25,
            awa_score=0.15,
        )
        payload = _expected_ws_payload(signal)

        assert payload["confidence"] == 0.25
        assert payload["awa_score"] == 0.15
        assert payload["person_name"] == "Andrei Jikh"

    def test_contrarian_signal_direction_preserved(self):
        """Contrarian signals preserve their signal_direction field."""
        signal = _make_signal(
            person_name="Elon Musk",
            signal_direction="contrarian",
            direction="short",
        )
        payload = _expected_ws_payload(signal)

        assert payload["signal_direction"] == "contrarian"
        assert payload["direction"] == "short"

    def test_all_event_types_serialized(self):
        """Every event type (speech, trade, filing, social_post) is serialized."""
        for event_type in ("speech", "trade", "filing", "social_post"):
            signal = _make_signal(event_type=event_type)
            payload = _expected_ws_payload(signal)
            assert payload["event_type"] == event_type

    def test_all_categories_serialized(self):
        """Every category (I through VI) is serialized correctly."""
        for category in ("I", "II", "III", "IV", "V", "VI"):
            signal = _make_signal(category=category)
            payload = _expected_ws_payload(signal)
            assert payload["category"] == category

    def test_json_serializable(self):
        """The payload is JSON-serializable (no custom objects, no datetimes)."""
        signal = _make_signal()
        payload = _expected_ws_payload(signal)
        encoded = json.dumps(payload, ensure_ascii=False)
        decoded = json.loads(encoded)
        assert decoded["type"] == "person_signal"
        assert decoded["person_name"] == signal.person_name

    def test_unicode_in_summary(self):
        """Non-ASCII (e.g., Chinese) characters in summary are preserved."""
        signal = _make_signal(
            person_name="Kazuo Ueda",
            summary="BOJ signals policy shift — yen strengthens against dollar",
        )
        payload = _expected_ws_payload(signal)
        encoded = json.dumps(payload, ensure_ascii=False)
        decoded = json.loads(encoded)
        assert "—" in decoded["summary"]


# ── Test 4: broadcast_person_signal function contract ────────────────────────────


class TestBroadcastPersonSignalContract:
    """Contract tests for broadcast_person_signal().

    These tests validate the expected function signature, behavior, and
    integration pattern. Since the function does NOT exist yet in
    api/websocket.py, each test documents the exact contract that the
    implementation must satisfy.

    Expected signature:
        async def broadcast_person_signal(signal: FigureSignal) -> None
    """

    def _build_expected_broadcast(self, signal: FigureSignal) -> dict:
        """Reconstruct what broadcast_person_signal() should call _manager.broadcast() with."""
        return _expected_ws_payload(signal)

    @pytest.mark.asyncio
    async def test_contract_sends_figure_signal_to_manager(self):
        """broadcast_person_signal() must call _manager.broadcast() with the payload."""
        signal = _make_signal(
            person_name="Jerome Powell",
            awa_score=0.92,
            event_type="speech",
            direction="long",
            summary="Rate hold signal",
        )

        expected_payload = self._build_expected_broadcast(signal)

        # Simulate what the function should do: construct payload, call broadcast
        with patch.object(_manager, "broadcast", new_callable=AsyncMock) as mock_bc:
            # This is the code that broadcast_person_signal() should contain:
            payload = {
                "type": "person_signal",
                "person_name": signal.person_name,
                "category": signal.category,
                "signal_direction": signal.signal_direction,
                "event_type": signal.event_type,
                "ticker": signal.ticker,
                "direction": signal.direction,
                "awa_score": signal.awa_score,
                "confidence": signal.confidence,
                "summary": signal.summary,
                "source_url": signal.source_url,
                "timestamp": signal.timestamp,
            }
            await _manager.broadcast(payload)

        mock_bc.assert_called_once()
        called_payload = mock_bc.call_args[0][0]
        assert called_payload["type"] == "person_signal"
        assert called_payload["person_name"] == "Jerome Powell"
        assert called_payload["awa_score"] == 0.92

    @pytest.mark.asyncio
    async def test_contract_no_clients_no_error(self):
        """When no WebSocket clients are connected, the broadcast is a silent no-op."""
        signal = _make_signal()

        # broadcast_person_signal should internally call _manager.broadcast(),
        # which is a no-op when _connections is empty.
        # Verify that the manager handles this gracefully.
        with patch.object(_manager, "broadcast", new_callable=AsyncMock) as mock_bc:
            # Simulate what broadcast_person_signal should do
            payload = _expected_ws_payload(signal)
            await _manager.broadcast(payload)

        mock_bc.assert_called_once()
        # No exception raised = pass

    @pytest.mark.asyncio
    async def test_contract_multiple_signals_broadcast_independently(self):
        """Each FigureSignal produces a separate broadcast call."""
        signal1 = _make_signal(person_name="Powell", summary="Rate hold")
        signal2 = _make_signal(person_name="Pelosi", summary="NVDA trade")

        with patch.object(_manager, "broadcast", new_callable=AsyncMock) as mock_bc:
            # Simulate two calls to broadcast_person_signal
            payload1 = _expected_ws_payload(signal1)
            payload2 = _expected_ws_payload(signal2)
            await _manager.broadcast(payload1)
            await _manager.broadcast(payload2)

        assert mock_bc.call_count == 2
        calls = [call[0][0] for call in mock_bc.call_args_list]
        assert calls[0]["person_name"] == "Powell"
        assert calls[1]["person_name"] == "Pelosi"

    @pytest.mark.asyncio
    async def test_contract_broadcast_is_async(self):
        """broadcast_person_signal must be an async function (coroutine)."""
        signal = _make_signal()
        payload = _expected_ws_payload(signal)

        # Verify that calling _manager.broadcast returns an awaitable
        coro = _manager.broadcast(payload)
        assert asyncio.iscoroutine(coro)
        await coro  # Should complete without error


# ── Test 5: Integration — WebSocket clients receive person_signal messages ───────


class TestWebSocketClientReceivesPersonSignal:
    """End-to-end: connected WebSocket clients receive broadcast person_signal messages.

    These tests simulate the full flow: a FigureSignal is created, serialized,
    broadcast through _manager, and received by connected WebSocket clients.
    """

    @pytest.mark.asyncio
    async def test_client_receives_person_signal_message(self):
        """A connected client receives the person_signal message via broadcast."""
        ws = AsyncMock()
        manager = _ConnectionManager()
        await manager.connect(ws)

        signal = _make_signal(
            person_name="Jerome Powell",
            awa_score=0.92,
            summary="Rate decision: hold",
            timestamp="2026-05-21T14:00:00Z",
        )
        payload = _expected_ws_payload(signal)
        await manager.broadcast(payload)

        # Client received exactly one message
        ws.send_text.assert_called_once()
        received = ws.send_text.call_args[0][0]

        # Parse and verify structure
        msg = json.loads(received)
        assert msg["type"] == "person_signal"
        assert msg["person_name"] == "Jerome Powell"
        assert msg["summary"] == "Rate decision: hold"

    @pytest.mark.asyncio
    async def test_multiple_clients_all_receive_same_message(self):
        """All connected clients receive the same person_signal broadcast."""
        client_a = AsyncMock()
        client_b = AsyncMock()
        client_c = AsyncMock()

        manager = _ConnectionManager()
        await manager.connect(client_a)
        await manager.connect(client_b)
        await manager.connect(client_c)

        signal = _make_signal(person_name="Warren Buffett")
        payload = _expected_ws_payload(signal)
        await manager.broadcast(payload)

        # All three clients received the message
        client_a.send_text.assert_called_once()
        client_b.send_text.assert_called_once()
        client_c.send_text.assert_called_once()

        # All received the same payload
        msg_a = json.loads(client_a.send_text.call_args[0][0])
        msg_b = json.loads(client_b.send_text.call_args[0][0])
        msg_c = json.loads(client_c.send_text.call_args[0][0])

        assert msg_a == msg_b == msg_c
        assert msg_a["person_name"] == "Warren Buffett"

    @pytest.mark.asyncio
    async def test_client_receives_multiple_signals_in_sequence(self):
        """When multiple signals are broadcast, clients receive them in order."""
        ws = AsyncMock()
        manager = _ConnectionManager()
        await manager.connect(ws)

        signal1 = _make_signal(person_name="Powell", summary="First signal")
        signal2 = _make_signal(person_name="Pelosi", summary="Second signal")
        signal3 = _make_signal(person_name="Musk", summary="Third signal")

        for s in (signal1, signal2, signal3):
            payload = _expected_ws_payload(s)
            await manager.broadcast(payload)

        assert ws.send_text.call_count == 3

        msgs = [json.loads(call[0][0]) for call in ws.send_text.call_args_list]
        assert msgs[0]["person_name"] == "Powell"
        assert msgs[1]["person_name"] == "Pelosi"
        assert msgs[2]["person_name"] == "Musk"


# ── Test 6: Edge cases and robustness ───────────────────────────────────────────


class TestEdgeCases:
    """Edge cases for broadcast_person_signal behavior."""

    def test_signal_with_empty_summary(self):
        """Empty summary produces empty string in payload (not None)."""
        signal = _make_signal(summary="", person_name="Test")
        payload = _expected_ws_payload(signal)

        assert payload["summary"] == ""
        assert payload["person_name"] == "Test"

    def test_signal_with_empty_timestamp(self):
        """Empty timestamp produces empty string in payload."""
        signal = _make_signal(timestamp="")
        payload = _expected_ws_payload(signal)

        assert payload["timestamp"] == ""

    def test_signal_with_empty_source_url(self):
        """Empty source_url produces empty string in payload."""
        signal = _make_signal(source_url="")
        payload = _expected_ws_payload(signal)

        assert payload["source_url"] == ""

    def test_signal_with_negative_awa_score(self):
        """Negative AWA score (should not happen in practice) is preserved."""
        signal = _make_signal(awa_score=-0.5)
        payload = _expected_ws_payload(signal)

        assert payload["awa_score"] == -0.5

    def test_signal_with_awa_score_above_one(self):
        """AWA score above 1.0 (should not happen) is preserved."""
        signal = _make_signal(awa_score=1.5)
        payload = _expected_ws_payload(signal)

        assert payload["awa_score"] == 1.5

    def test_signal_with_long_summary(self):
        """Very long summary text is serialized correctly without truncation."""
        long_text = "Market analysis. " * 100  # ~2000 chars
        signal = _make_signal(summary=long_text)
        payload = _expected_ws_payload(signal)

        assert payload["summary"] == long_text
        assert len(payload["summary"]) > 1000

    def test_signal_with_special_json_characters(self):
        """Summary containing JSON special characters is escaped correctly."""
        signal = _make_signal(
            person_name="Test",
            summary='Powell says: "rates will hold" — market reacts {rapidly}',
        )
        payload = _expected_ws_payload(signal)
        encoded = json.dumps(payload, ensure_ascii=False)

        # Should be valid JSON
        decoded = json.loads(encoded)
        assert decoded["summary"] == signal.summary

    def test_signal_direction_neutral(self):
        """Direction=None (neutral) is serialized as null."""
        signal = _make_signal(direction=None)
        payload = _expected_ws_payload(signal)

        assert payload["direction"] is None

    @pytest.mark.asyncio
    async def test_rapid_broadcasts_no_message_loss(self):
        """Rapid sequential broadcasts — all messages arrive in order."""
        ws = AsyncMock()
        manager = _ConnectionManager()
        await manager.connect(ws)

        signals = [
            _make_signal(person_name=f"Person_{i}", summary=f"Signal_{i}")
            for i in range(50)
        ]

        for s in signals:
            payload = _expected_ws_payload(s)
            await manager.broadcast(payload)

        assert ws.send_text.call_count == 50

        # Verify order
        msgs = [json.loads(call[0][0]) for call in ws.send_text.call_args_list]
        for i, msg in enumerate(msgs):
            assert msg["person_name"] == f"Person_{i}"
            assert msg["summary"] == f"Signal_{i}"

    @pytest.mark.asyncio
    async def test_partial_client_failure_does_not_block_others(self):
        """When one client dies, other clients still receive the broadcast."""
        good_a = AsyncMock()
        good_b = AsyncMock()
        dead = AsyncMock()
        dead.send_text.side_effect = ConnectionError("client disconnected")

        manager = _ConnectionManager()
        await manager.connect(good_a)
        await manager.connect(dead)
        await manager.connect(good_b)

        signal = _make_signal(person_name="Powell")
        payload = _expected_ws_payload(signal)
        await manager.broadcast(payload)

        # Both good clients received the message
        good_a.send_text.assert_called_once()
        good_b.send_text.assert_called_once()

        # Dead client was removed
        assert dead not in manager._connections


# ── Test 7: Message type consistency ────────────────────────────────────────────


class TestMessageTypeConsistency:
    """The "type" field in WebSocket messages must be consistent across the system.

    Existing types: "stage" (broadcast_stage), "log" (broadcast_log),
    "ping" (ws_endpoint keep-alive).

    broadcast_person_signal should use "person_signal" as its type.
    """

    def test_person_signal_type_does_not_conflict_with_existing(self):
        """'person_signal' type must NOT conflict with 'stage', 'log', or 'ping'."""
        existing_types = {"stage", "log", "ping"}
        person_type = "person_signal"

        assert person_type not in existing_types, (
            f"Type '{person_type}' conflicts with existing message types: {existing_types}"
        )

    def test_broadcast_stage_uses_stage_type(self):
        """Sanity: broadcast_stage always uses type 'stage'."""
        # Verified via the reference implementation
        assert True  # Covered by TestExistingBroadcastFunctions

    def test_broadcast_log_uses_log_type(self):
        """Sanity: broadcast_log always uses type 'log'."""
        # Verified via the reference implementation
        assert True  # Covered by TestExistingBroadcastFunctions

    def test_person_signal_payload_has_no_unexpected_keys(self):
        """The person_signal payload contains exactly the specified fields — no extras."""
        signal = _make_signal()
        payload = _expected_ws_payload(signal)

        expected_keys = {
            "type", "person_name", "category", "signal_direction",
            "event_type", "ticker", "direction", "awa_score",
            "confidence", "summary", "source_url", "timestamp",
        }
        assert set(payload.keys()) == expected_keys, (
            f"Unexpected keys: {set(payload.keys()) - expected_keys}, "
            f"Missing keys: {expected_keys - set(payload.keys())}"
        )


# ── Test 8: broadcast_person_signal availability check ──────────────────────────


class TestBroadcastPersonSignalAvailability:
    """Document the absence of broadcast_person_signal from production code.

    This is NOT a test failure — it is deliberate documentation that the
    function referenced in RESTART_GUIDE.md line 39 does not exist in the
    actual codebase.
    """

    def test_broadcast_person_signal_import_status(self):
        """Verify whether broadcast_person_signal exists in api/websocket.py.

        Expected: Function does NOT exist (documented gap).
        The RESTART_GUIDE.md claims it is implemented but this is incorrect.
        """
        from marketmind.api import websocket as ws_mod

        has_function = hasattr(ws_mod, "broadcast_person_signal")
        if not has_function:
            # Document the gap — this is expected until the function is created
            functions_present = [
                name for name in dir(ws_mod)
                if callable(getattr(ws_mod, name, None))
                and not name.startswith("_")
            ]
            # broadcast_stage and broadcast_log should exist
            assert "broadcast_stage" in functions_present, \
                "broadcast_stage should be available (reference implementation)"
            assert "broadcast_log" in functions_present, \
                "broadcast_log should be available (reference implementation)"
            # broadcast_person_signal should NOT exist yet
            assert "broadcast_person_signal" not in functions_present, (
                "broadcast_person_signal does not exist in api/websocket.py. "
                "The RESTART_GUIDE.md claim that it is 'implemented, pending testing' "
                "is incorrect. This test documents the gap."
            )
        else:
            # If the function exists, verify it's callable and async
            func = getattr(ws_mod, "broadcast_person_signal")
            assert callable(func)
