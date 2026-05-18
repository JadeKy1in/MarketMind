"""L1 Agent Market Data Tools — yfinance fundamentals, macro, CoT, EIA inventory.

Extracted from l1_tools.py per modular architecture rules (CLAUDE.md §3.1).
Each tool preserves ToolResult wrapping and rate cap logic.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from marketmind.pipeline.l1_tools import (
    ToolResult,
    MAX_YFINANCE_CALLS_HARD,
    MAX_YFINANCE_CALLS_WARN,
    MAX_MACRO_CALLS_WARN,
)

if TYPE_CHECKING:
    from marketmind.pipeline.l1_tools import L1ToolRegistry

logger = logging.getLogger("marketmind.pipeline.l1_market_tools")


async def _tool_lookup_fundamentals(registry: "L1ToolRegistry", ticker: str) -> ToolResult:
    """Fetch fundamental data for a ticker via yfinance.

    Host-enforced cap: max 50 calls/session (warn at 30).
    """
    ticker = ticker.strip().upper()
    t0 = datetime.now(timezone.utc)
    timestamp = t0.isoformat()

    if registry._yfinance_calls >= MAX_YFINANCE_CALLS_HARD:
        return ToolResult(
            tool_name="lookup_fundamentals", query=ticker, data={},
            timestamp=timestamp,
            error=f"Session limit reached ({MAX_YFINANCE_CALLS_HARD} yfinance calls). Try rephrasing with available data.",
        )

    registry._yfinance_calls += 1
    if registry._yfinance_calls >= MAX_YFINANCE_CALLS_WARN:
        logger.warning(
            "yfinance session limit warning: %d/%d calls used",
            registry._yfinance_calls, MAX_YFINANCE_CALLS_HARD,
        )

    if registry._market_data is None:
        try:
            from marketmind.gateway.market_data import get_market_data
            registry._market_data = get_market_data
        except ImportError:
            return ToolResult(
                tool_name="lookup_fundamentals", query=ticker, data={},
                timestamp=timestamp,
                error="Market data module not available (yfinance not installed?).",
            )

    try:
        result = await registry._market_data(ticker, "fundamentals")
    except Exception as e:
        logger.warning("lookup_fundamentals(%s) failed: %s", ticker, e)
        result = {}

    elapsed_ms = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
    tr = ToolResult(
        tool_name="lookup_fundamentals", query=ticker,
        data=result, timestamp=timestamp,
        error=None if result else f"No fundamental data returned for {ticker}",
    )
    registry.tool_calls.append(tr)
    registry._record_efficacy(tr, elapsed_ms)

    registry.fact_broadcast.append({
        "tool": "lookup_fundamentals",
        "ticker": ticker,
        "source": result.get("source", "yfinance") if isinstance(result, dict) else "unknown",
        "data": registry._extract_key_fundamentals(result),
    })

    return tr


async def _tool_get_macro_indicator(registry: "L1ToolRegistry", indicator: str) -> ToolResult:
    """Fetch a macro indicator from FRED (BDI or GSCPI).

    Uses FRED API (free key, env FRED_KEY). No hard cap — warn at 10/session.
    """
    indicator = indicator.strip()
    t0 = datetime.now(timezone.utc)
    timestamp = t0.isoformat()

    registry._macro_indicator_calls += 1
    if registry._macro_indicator_calls >= MAX_MACRO_CALLS_WARN:
        logger.warning(
            "get_macro_indicator session call warning: %d calls",
            registry._macro_indicator_calls,
        )

    valid = {"BDI", "GSCPI"}
    indicator_upper = indicator.upper()
    if indicator_upper not in valid:
        return ToolResult(
            tool_name="get_macro_indicator", query=indicator, data={},
            timestamp=timestamp,
            error=f"Unknown indicator: '{indicator}'. Supported: {', '.join(sorted(valid))}",
        )

    try:
        from marketmind.gateway.macro_data import get_macro_indicator as _gmi
        result = await _gmi(indicator_upper)
    except ImportError:
        return ToolResult(
            tool_name="get_macro_indicator", query=indicator, data={},
            timestamp=timestamp,
            error="Macro data module not available.",
        )
    except Exception as e:
        logger.warning("get_macro_indicator(%s) failed: %s", indicator, e)
        result = {"error": "source_unavailable"}

    elapsed_ms = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
    tr = ToolResult(
        tool_name="get_macro_indicator", query=indicator,
        data=result if isinstance(result, dict) else {},
        timestamp=timestamp,
        error=None if isinstance(result, dict) and "error" not in result
               else result.get("error", f"No data for {indicator}") if isinstance(result, dict)
               else f"Unexpected response for {indicator}",
    )
    registry.tool_calls.append(tr)
    registry._record_efficacy(tr, elapsed_ms)

    if isinstance(result, dict) and "error" not in result:
        registry.fact_broadcast.append({
            "tool": "get_macro_indicator",
            "indicator": indicator_upper,
            "source": result.get("source", "fred"),
            "data": result,
        })

    return tr


async def _tool_get_cot_data(registry: "L1ToolRegistry", asset: str) -> ToolResult:
    """Fetch Commitments of Traders data for a futures asset.

    Uses CFTC SODA API (free, no key). No hard cap — warn at 10/session.
    """
    asset = asset.strip().upper()
    t0 = datetime.now(timezone.utc)
    timestamp = t0.isoformat()

    registry._cot_calls += 1
    if registry._cot_calls >= MAX_MACRO_CALLS_WARN:
        logger.warning(
            "get_cot_data session call warning: %d calls",
            registry._cot_calls,
        )

    valid = {"ES", "CL", "GC", "NG"}
    if asset not in valid:
        return ToolResult(
            tool_name="get_cot_data", query=asset, data={},
            timestamp=timestamp,
            error=f"Unknown asset: '{asset}'. Supported: {', '.join(sorted(valid))}",
        )

    try:
        from marketmind.gateway.macro_data import get_cot_data as _gcot
        result = await _gcot(asset)
    except ImportError:
        return ToolResult(
            tool_name="get_cot_data", query=asset, data={},
            timestamp=timestamp,
            error="Macro data module not available.",
        )
    except Exception as e:
        logger.warning("get_cot_data(%s) failed: %s", asset, e)
        result = {"error": "source_unavailable"}

    elapsed_ms = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
    tr = ToolResult(
        tool_name="get_cot_data", query=asset,
        data=result if isinstance(result, dict) else {},
        timestamp=timestamp,
        error=None if isinstance(result, dict) and "error" not in result
               else result.get("error", f"No data for {asset}") if isinstance(result, dict)
               else f"Unexpected response for {asset}",
    )
    registry.tool_calls.append(tr)
    registry._record_efficacy(tr, elapsed_ms)

    if isinstance(result, dict) and "error" not in result:
        registry.fact_broadcast.append({
            "tool": "get_cot_data",
            "asset": asset,
            "source": result.get("source", "cftc"),
            "data": result,
        })

    return tr


async def _tool_get_eia_inventory(registry: "L1ToolRegistry", product: str) -> ToolResult:
    """Fetch EIA petroleum inventory data.

    Uses EIA API v2 (free key, env EIA_KEY). No hard cap — warn at 10/session.
    """
    product = product.strip().lower()
    t0 = datetime.now(timezone.utc)
    timestamp = t0.isoformat()

    registry._eia_calls += 1
    if registry._eia_calls >= MAX_MACRO_CALLS_WARN:
        logger.warning(
            "get_eia_inventory session call warning: %d calls",
            registry._eia_calls,
        )

    valid = {"crude", "gasoline", "distillate"}
    if product not in valid:
        return ToolResult(
            tool_name="get_eia_inventory", query=product, data={},
            timestamp=timestamp,
            error=f"Unknown product: '{product}'. Supported: {', '.join(sorted(valid))}",
        )

    try:
        from marketmind.gateway.macro_data import get_eia_inventory as _geia
        result = await _geia(product)
    except ImportError:
        return ToolResult(
            tool_name="get_eia_inventory", query=product, data={},
            timestamp=timestamp,
            error="Macro data module not available.",
        )
    except Exception as e:
        logger.warning("get_eia_inventory(%s) failed: %s", product, e)
        result = {"error": "source_unavailable"}

    elapsed_ms = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
    tr = ToolResult(
        tool_name="get_eia_inventory", query=product,
        data=result if isinstance(result, dict) else {},
        timestamp=timestamp,
        error=None if isinstance(result, dict) and "error" not in result
               else result.get("error", f"No data for {product}") if isinstance(result, dict)
               else f"Unexpected response for {product}",
    )
    registry.tool_calls.append(tr)
    registry._record_efficacy(tr, elapsed_ms)

    if isinstance(result, dict) and "error" not in result:
        registry.fact_broadcast.append({
            "tool": "get_eia_inventory",
            "product": product,
            "source": result.get("source", "eia"),
            "data": result,
        })

    return tr
