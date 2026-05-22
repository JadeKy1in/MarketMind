"""WebSocket support — pipeline progress + log broadcast to dashboard clients."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import WebSocket

logger = logging.getLogger("marketmind.api.websocket")


class _ConnectionManager:
    """Track connected WebSocket clients and broadcast to all."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)
        logger.debug("WS client connected, total=%d", len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)
        logger.debug("WS client disconnected, total=%d", len(self._connections))

    async def broadcast(self, payload: dict) -> None:
        if not self._connections:
            return
        msg = json.dumps(payload, ensure_ascii=False)
        dead: set[WebSocket] = set()
        for ws in self._connections:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        self._connections -= dead


_manager = _ConnectionManager()


async def broadcast_stage(stage: str, pct: float, status: str = "running") -> None:
    """Broadcast pipeline stage progress to all connected dashboard clients."""
    await _manager.broadcast({
        "type": "stage",
        "stage": stage,
        "pct": round(pct, 1),
        "status": status,
    })


async def broadcast_log(level: str, message: str) -> None:
    """Broadcast a log entry to all connected dashboard clients."""
    await _manager.broadcast({
        "type": "log",
        "level": level,
        "message": message,
        "ts": datetime.now(timezone.utc).strftime("%H:%M:%S"),
    })


async def ws_endpoint(websocket: WebSocket) -> None:
    """Handle one dashboard WebSocket connection — keep-alive with ping/pong."""
    await _manager.connect(websocket)
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                await websocket.send_text('{"type":"ping"}')
    except Exception:
        pass
    finally:
        await _manager.disconnect(websocket)
