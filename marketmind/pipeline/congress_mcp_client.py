"""MCP stdio client for @anguslin/mcp-capitol-trades.

Spawns the Node.js MCP server as a subprocess and communicates via
JSON-RPC 2.0 over stdin/stdout. Converts results to NewsItem objects
for the main pipeline.

The MCP server scrapes capitoltrades.com/trades in real-time — no API
key, no cache, always fetches fresh Congressional disclosure data.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("marketmind.pipeline.congress_mcp_client")

MCP_SERVER_PATH = os.path.expandvars(
    r"C:\Users\Administrator\AppData\Roaming\npm\node_modules\@anguslin\mcp-capitol-trades\build\src\index.js"
)


class McpClientError(Exception):
    """MCP communication or tool call failure."""


async def _mcp_rpc(proc: asyncio.subprocess.Process, request: dict) -> dict:
    """Send a JSON-RPC request and read the matching response."""
    payload = (json.dumps(request) + "\n").encode()
    proc.stdin.write(payload)
    await proc.stdin.drain()
    while True:
        line = await asyncio.wait_for(proc.stdout.readline(), timeout=60.0)
        if not line:
            raise McpClientError("MCP server closed stdout unexpectedly")
        if isinstance(line, bytes):
            line = line.decode()
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == request["id"]:
            if "error" in msg:
                raise McpClientError(
                    f"MCP error {msg['error'].get('code', '?')}: "
                    f"{msg['error'].get('message', str(msg['error']))}"
                )
            return msg.get("result", {})


async def _start_mcp_server() -> asyncio.subprocess.Process:
    """Start the capitol-trades MCP server and complete initialization."""
    proc = await asyncio.create_subprocess_exec(
        "node", MCP_SERVER_PATH,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        init_result = await _mcp_rpc(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "marketmind", "version": "1.0"},
            },
        })
        server_info = init_result.get("serverInfo", {})
        logger.info("MCP Capitol Trades server v%s initialized",
                     server_info.get("version", "?"))
        # Send initialized notification
        notification = (json.dumps({
            "jsonrpc": "2.0", "method": "notifications/initialized",
        }) + "\n").encode()
        proc.stdin.write(notification)
        await proc.stdin.drain()
        return proc
    except Exception:
        proc.kill()
        try:
            stderr_data = await asyncio.wait_for(proc.stderr.read(), timeout=3.0)
            if stderr_data:
                text = stderr_data.decode() if isinstance(stderr_data, bytes) else str(stderr_data)
                logger.error("MCP stderr: %s", text[:500])
        except Exception:
            pass
        raise


async def _call_tool(proc: asyncio.subprocess.Process,
                     tool_name: str, arguments: dict) -> dict:
    """Call a named tool on the MCP server and return parsed result."""
    result = await _mcp_rpc(proc, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    })
    content = result.get("content", [])
    if not content:
        return {}
    text = content[0].get("text", "{}") if isinstance(content, list) else str(content)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("MCP tool %s returned non-JSON: %s", tool_name, text[:200])
        return {"raw": text}


async def fetch_congress_trades_via_mcp(days: int = 90) -> list[dict]:
    """Fetch recent Congressional trades via MCP server.

    Returns a list of trade dicts with keys:
        politician, ticker, type, amount, date, party, chamber
    """
    proc = await _start_mcp_server()
    try:
        data = await _call_tool(proc, "get_politician_trades", {
            "days": days,
            "type": ["BUY", "SELL", "RECEIVE", "EXCHANGE"],
        })
        trades = data.get("trades", [])
        logger.info("Congress MCP: %d trades fetched (%d-day window)",
                     len(trades), days)
        return trades
    finally:
        proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except Exception:
            pass


def congress_trades_to_newsitems(trades: list[dict]) -> list[Any]:
    """Convert raw MCP trade dicts to NewsItem objects.

    Handles the capitoltrades.com data structure:
        politician: {name, party, chamber, state}
        issuer: {name, ticker}
        transaction: {type, size, price}
        dates: {disclosure, trade, reportingGap}
    """
    from marketmind.config.source_authority import SourceTier
    from marketmind.pipeline.scout import NewsItem

    items = []
    for t in trades:
        pol = t.get("politician", {}) or {}
        politician = pol.get("name", "Unknown")
        party = pol.get("party", "")
        chamber = pol.get("chamber", "")

        issuer = t.get("issuer", {}) or {}
        raw_ticker = (issuer.get("ticker", "") or "").upper()
        ticker = raw_ticker.split(":")[0] if ":" in raw_ticker else raw_ticker
        if not ticker or ticker in ("N/A", ""):
            continue

        txn = t.get("transaction", {}) or {}
        tx_type = txn.get("type", "?").upper()
        amount = txn.get("size", "unknown")

        dates = t.get("dates", {}) or {}
        date_str = dates.get("trade", dates.get("disclosure", ""))

        is_buy = tx_type in ("BUY", "RECEIVE", "PURCHASE")
        direction = "Buy" if is_buy else tx_type.capitalize()

        title = f"[Congress] {politician} ({direction} ${ticker})"
        summary = (
            f"{politician}" + (f" ({party})" if party else "") +
            (f", {chamber}" if chamber else "") +
            f" reported {direction} of ${ticker}. "
            f"Amount: {amount}. STOCK Act disclosure."
        )
        item_id = hashlib.sha256(
            f"congress_mcp:{politician}:{ticker}:{date_str}".encode()
        ).hexdigest()[:16]

        items.append(NewsItem(
            id=item_id,
            title=title,
            url="https://www.capitoltrades.com/trades",
            source_name="Congress Trades",
            source_tier=int(SourceTier.BEST_EFFORT),
            published_at=date_str or datetime.now(timezone.utc).isoformat(),
            summary=summary[:500],
            source_reliability=0.20,
            content_type="insider_signal",
        ))
    return items
