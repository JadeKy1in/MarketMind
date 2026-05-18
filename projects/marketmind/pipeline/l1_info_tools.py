"""L1 Agent Information Tools — news search, elite opinions, calendar, earnings.

Extracted from l1_tools.py per modular architecture rules (CLAUDE.md §3.1).
Each tool preserves ToolResult wrapping and rate cap logic.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from marketmind.pipeline.l1_tools import (
    ToolResult,
    MAX_GNEWS_CALLS_PER_SESSION,
)

if TYPE_CHECKING:
    from marketmind.pipeline.l1_tools import L1ToolRegistry

logger = logging.getLogger("marketmind.pipeline.l1_info_tools")


async def _tool_search_news(registry: "L1ToolRegistry", query: str) -> ToolResult:
    """Search GNews for additional articles on a topic.

    Host-enforced hard cap: max 10 calls/session.
    Requires GNews API key in config.
    """
    query = query.strip()
    t0 = datetime.now(timezone.utc)
    timestamp = t0.isoformat()

    if registry._gnews_calls >= MAX_GNEWS_CALLS_PER_SESSION:
        return ToolResult(
            tool_name="search_news", query=query, data=[],
            timestamp=timestamp,
            error=(
                f"search_news is temporarily limited ({MAX_GNEWS_CALLS_PER_SESSION}/session) "
                "to preserve daily quota. Try rephrasing your question with available data, "
                "or wait for the next daily cycle."
            ),
        )

    if not registry._gnews_key:
        return ToolResult(
            tool_name="search_news", query=query, data=[],
            timestamp=timestamp,
            error="GNews API key not configured. Set GNEWS_API_KEY in .env.",
        )

    registry._gnews_calls += 1
    logger.info("search_news(%s): call %d/%d", query, registry._gnews_calls, MAX_GNEWS_CALLS_PER_SESSION)

    try:
        articles = await registry._gnews_search(query)
    except Exception as e:
        logger.warning("search_news(%s) failed: %s", query, e)
        articles = []

    elapsed_ms = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
    tr = ToolResult(
        tool_name="search_news", query=query,
        data=articles, timestamp=timestamp,
        error=None if articles else f"No articles found for '{query}'",
    )
    registry.tool_calls.append(tr)
    registry._record_efficacy(tr, elapsed_ms)

    registry.fact_broadcast.append({
        "tool": "search_news",
        "query": query,
        "source": "GNews",
        "data": articles[:10],
    })

    return tr


async def _tool_get_elite_opinion(registry: "L1ToolRegistry", domain: str) -> ToolResult:
    """Query ELITE shadow analysts for domain-specific opinions.

    Wraps the existing EliteRegistry query mechanism as an AI-callable tool.
    """
    domain = domain.strip().lower()
    timestamp = datetime.now(timezone.utc).isoformat()
    t0 = datetime.now(timezone.utc)

    if registry._elite_registry is None:
        return ToolResult(
            tool_name="get_elite_opinion", query=domain, data={},
            timestamp=timestamp,
            error="ELITE registry not initialized. Shadows may not have completed analysis yet.",
        )

    matched_domains = registry._elite_registry.detect_domain_trigger(domain)
    if not matched_domains:
        available = list(registry._elite_registry.DOMAIN_KEYWORDS.keys())[:10]
        return ToolResult(
            tool_name="get_elite_opinion", query=domain, data={},
            timestamp=timestamp,
            error=f"No ELITE domain matched '{domain}'. Available domains: {', '.join(available)}",
        )

    domain_name = matched_domains[0]
    contributions = getattr(registry._elite_registry, '_contributions', {})

    opinions = []
    for sid, contrib in contributions.items():
        if contrib.domain == domain_name or domain_name in contrib.domain:
            opinions.append({
                "shadow_name": getattr(contrib, 'shadow_name', sid),
                "opinion": getattr(contrib, 'opinion', '')[:500],
                "confidence": getattr(contrib, 'confidence', 0.5),
            })

    if not opinions:
        return ToolResult(
            tool_name="get_elite_opinion", query=domain,
            data={"domain": domain_name, "status": "pending"},
            timestamp=timestamp,
            error=None,
        )

    elapsed_ms = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
    tr = ToolResult(
        tool_name="get_elite_opinion", query=domain,
        data={"domain": domain_name, "opinions": opinions[:3]},
        timestamp=timestamp,
    )
    registry.tool_calls.append(tr)
    registry._record_efficacy(tr, elapsed_ms)

    registry.fact_broadcast.append({
        "tool": "get_elite_opinion",
        "domain": domain_name,
        "source": "elite_shadows",
        "data": opinions[:3],
    })

    return tr


async def _tool_get_economic_calendar(registry: "L1ToolRegistry", _unused: str = "") -> ToolResult:
    """Query upcoming economic events (FOMC, CPI, NFP, GDP) from the pre-pipeline check.

    Returns events already cached in the economic calendar check (stage 0.5).
    No remote API call — data is fetched once per session.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    t0 = datetime.now(timezone.utc)

    try:
        from marketmind.pipeline.economic_calendar import (
            check_economic_calendar,
            get_event_confidence_discount,
        )
    except ImportError:
        return ToolResult(
            tool_name="get_economic_calendar", query="",
            data={}, timestamp=timestamp,
            error="Economic calendar module not available.",
        )

    fred_key = getattr(registry.config, "fred_key", "") if registry.config else ""
    try:
        events = await check_economic_calendar(lookahead_hours=48, fred_key=fred_key)
    except Exception as e:
        logger.warning("get_economic_calendar failed: %s", e)
        events = {"has_high_impact": False, "pipeline_annotation": "calendar check failed"}

    discount = get_event_confidence_discount(events) if events.get("has_high_impact") else 1.0

    high_events = events.get("high_impact_events", [])
    medium_events = events.get("medium_impact_events", [])
    summary_lines = [events.get("pipeline_annotation", "")]
    for e in high_events:
        summary_lines.append(
            f"HIGH: {e['name']} on {e['date']} ({e.get('hours_until', '?')}h away)"
        )
    for e in medium_events[:5]:
        summary_lines.append(
            f"MEDIUM: {e['name']} on {e['date']} ({e.get('hours_until', '?')}h away)"
        )
    if discount < 1.0:
        summary_lines.append(f"Confidence discount: {discount:.0%}")

    data = {
        "has_high_impact": events.get("has_high_impact", False),
        "high_impact_count": len(high_events),
        "medium_impact_count": len(medium_events),
        "confidence_discount": discount,
        "summary": "\n".join(summary_lines),
        "events": high_events + medium_events[:5],
        "source": "economic_calendar",
    }

    elapsed_ms = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
    tr = ToolResult(
        tool_name="get_economic_calendar", query="upcoming events",
        data=data, timestamp=timestamp,
    )
    registry.tool_calls.append(tr)
    registry._record_efficacy(tr, elapsed_ms)

    registry.fact_broadcast.append({
        "tool": "get_economic_calendar",
        "source": "fomc+fred",
        "data": data,
    })

    return tr


async def _tool_get_earnings_date(registry: "L1ToolRegistry", ticker: str) -> ToolResult:
    """Query upcoming earnings dates for a ticker.

    Uses session-level in-memory cache. Graceful degradation if data unavailable.
    """
    ticker = ticker.strip().upper()
    t0 = datetime.now(timezone.utc)
    timestamp = t0.isoformat()

    if not ticker:
        return ToolResult(
            tool_name="get_earnings_date", query=ticker, data={},
            timestamp=timestamp,
            error="Ticker is required. Usage: get_earnings_date|AAPL",
        )

    try:
        from marketmind.pipeline.earnings_dates import get_earnings_date as _ged
    except ImportError:
        return ToolResult(
            tool_name="get_earnings_date", query=ticker, data={},
            timestamp=timestamp,
            error="Earnings dates module not available.",
        )

    try:
        earnings = await _ged(ticker)
    except Exception as e:
        logger.warning("get_earnings_date(%s) failed: %s", ticker, e)
        earnings = [{"ticker": ticker, "note": "earnings_data_unavailable"}]

    elapsed_ms = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
    has_data = any("date" in e for e in earnings)
    tr = ToolResult(
        tool_name="get_earnings_date", query=ticker,
        data={"ticker": ticker, "earnings": earnings, "source": "yfinance_calendar"},
        timestamp=timestamp,
        error=None if has_data else f"No earnings dates found for {ticker}",
    )
    registry.tool_calls.append(tr)
    registry._record_efficacy(tr, elapsed_ms)

    registry.fact_broadcast.append({
        "tool": "get_earnings_date",
        "ticker": ticker,
        "source": "yfinance_calendar",
        "data": earnings,
    })

    return tr
