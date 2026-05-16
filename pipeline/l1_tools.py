"""L1 Agent Tools — on-demand data access for the L1 discussion loop.

Phase G: Gives L1 the ability to actively investigate — call market data,
search additional news, query elite opinions during discussion.

Red Team compliant (per red-team-l1-agent-tools.md):
- Delimiter-based tool-call protocol (DeepSeek has no function-calling API)
- No lookup_technicals (Law 3 — price data stays in L3)
- Host-enforced caps: GNews 10/session, yfinance 50/session (warn at 30)
- Tool efficacy persistence: data/tool_efficacy/YYYY-MM-DD.json
- Fact broadcast accumulator for shadow distribution
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("marketmind.pipeline.l1_tools")

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_GNEWS_CALLS_PER_SESSION = 10       # Hard cap (GNews 100/day quota, 3 sessions/day reserve)
MAX_YFINANCE_CALLS_WARN = 30           # Log warning threshold
MAX_YFINANCE_CALLS_HARD = 50           # Reject threshold (well within ~300/hour)

# ── Tool call protocol patterns ───────────────────────────────────────────────
# Tool call:  <tool>tool_name|arg1|arg2</tool>
# Tool result: [TOOL RESULT: tool_name("arg1")] status: status_value
_TOOL_CALL_PATTERN = re.compile(
    r'<tool>\s*([a-z_]+)\s*\|([^<]+)\s*</tool>',
    re.IGNORECASE,
)

# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class ToolResult:
    """Result of a single tool invocation."""
    tool_name: str
    query: str
    data: dict | list | str
    timestamp: str
    error: str | None = None

    @property
    def status(self) -> str:
        """Return tool result status for prompt injection."""
        if self.error:
            return "error"
        if self.data is None or (isinstance(self.data, (dict, list)) and len(self.data) == 0):
            return "empty"
        if isinstance(self.data, dict) and "note" in self.data and "unavailable" in str(self.data.get("note", "")).lower():
            return "degraded"
        return "success"

    def to_prompt_text(self) -> str:
        """Format tool result for injection into LLM context (bypasses _format_history)."""
        header = f"[TOOL RESULT: {self.tool_name}(\"{self.query}\")] status: {self.status}"
        if self.error:
            return f"{header}\nerror: {self.error}\n[END TOOL RESULT]"
        if self.status == "empty":
            return f"{header}\nNo data returned — the data source may be unavailable or the query returned no results.\n[END TOOL RESULT]"
        if self.status == "degraded":
            return f"{header}\nPartial data returned (source may be degraded):\n{self._format_data()}\n[END TOOL RESULT]"
        return f"{header}\n{self._format_data()}\n[END TOOL RESULT]"

    def _format_data(self) -> str:
        """Format data payload for LLM consumption."""
        data = self.data
        if isinstance(data, str):
            return data[:3000]
        if isinstance(data, dict):
            # For fundamentals, extract key fields to keep it concise but complete
            # Use full dict for rich data, truncate per-line to reasonable width
            lines = []
            for k, v in data.items():
                v_str = str(v)
                if len(v_str) > 200:
                    v_str = v_str[:200] + "..."
                lines.append(f"{k}: {v_str}")
            return "\n".join(lines[:80])  # cap at ~80 lines
        if isinstance(data, list):
            # For news articles, list titles + summaries
            lines = []
            for i, item in enumerate(data[:10]):
                if isinstance(item, dict):
                    title = item.get("title", "")[:150]
                    source = item.get("source_name", item.get("source", {}).get("name", ""))
                    if source:
                        lines.append(f"[{i+1}] ({source}) {title}")
                    else:
                        lines.append(f"[{i+1}] {title}")
                else:
                    lines.append(f"[{i+1}] {str(item)[:200]}")
            return "\n".join(lines)
        return str(data)[:3000]

    def to_broadcast_text(self, query_context: str = "") -> str:
        """Format data for shadow broadcast (raw facts only, no L1 interpretation)."""
        data = self.data
        ctx = f"query_context: {query_context}\n" if query_context else ""
        if isinstance(data, dict):
            lines = [f"[{self.tool_name}(\"{self.query}\")]",
                     f"source: {data.get('source', 'unknown')}"]
            if "info" in data:
                info = data["info"]
                for k in ("trailingPE", "forwardPE", "marketCap", "sector", "industry",
                          "revenueGrowth", "debtToEquity", "returnOnEquity",
                          "regularMarketPrice", "fiftyTwoWeekHigh", "fiftyTwoWeekLow"):
                    if k in info:
                        lines.append(f"{k}: {info[k]}")
            else:
                for k, v in data.items():
                    if k != "source":
                        lines.append(f"{k}: {v}")
            return ctx + "\n".join(lines[:40])
        if isinstance(data, list):
            lines = [f"[{self.tool_name}(\"{self.query}\")]", f"articles: {len(data)}"]
            for item in data[:5]:
                if isinstance(item, dict):
                    lines.append(f"- {item.get('title', '')[:200]}")
            return ctx + "\n".join(lines)
        return ctx + f"[{self.tool_name}(\"{self.query}\")]\n{str(data)[:1000]}"


@dataclass
class ToolCallRecord:
    """Single tool call record for efficacy tracking."""
    tool: str
    args: dict
    status: str           # success | degraded | empty | error
    latency_ms: float
    led_to_insight: bool | None = None  # populated post-hoc by analysis
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class L1ToolRegistry:
    """Registry for L1 tool execution with host-enforced rate caps and fact accumulation.

    Three tools available (per Red Team audit resolution):
    - lookup_fundamentals: yfinance fundamentals (P/E, market cap, sector, etc.)
    - search_news: GNews search (capped at 10/session)
    - get_elite_opinion: query ELITE shadow registry

    lookup_technicals is NOT included — per Law 3, technical data belongs in L3.
    """

    def __init__(self, config=None, market_data_fetcher=None, gnews_key: str | None = None):
        self.config = config
        self._market_data = market_data_fetcher  # async callable (ticker, data_type) -> dict
        self._gnews_key = gnews_key
        self.tool_calls: list[ToolResult] = []
        self.fact_broadcast: list[dict] = []  # accumulated facts for shadow broadcast

        # Session-level rate counters
        self._gnews_calls: int = 0
        self._yfinance_calls: int = 0

        # Efficacy records for learning mechanism
        self._efficacy_records: list[ToolCallRecord] = []

        # Lazy import guard
        self._elite_registry = None

    # ── Public API ──────────────────────────────────────────────────────────

    def set_elite_registry(self, registry) -> None:
        """Inject the EliteRegistry for get_elite_opinion tool."""
        self._elite_registry = registry

    def parse_tool_calls(self, ai_text: str) -> list[tuple[str, str]]:
        """Parse AI text for delimiter-based tool calls.

        Returns list of (tool_name, args_string) tuples.
        Uses regex pattern: <tool>tool_name|arg1|arg2</tool>
        """
        matches = _TOOL_CALL_PATTERN.findall(ai_text)
        return [(m[0].strip().lower(), m[1].strip()) for m in matches]

    async def execute(self, tool_name: str, args_str: str) -> ToolResult | None:
        """Execute a single tool call. Returns ToolResult or None if rejected by caps."""
        tool_name = tool_name.strip().lower()
        args_str = args_str.strip()

        if tool_name == "lookup_fundamentals":
            return await self.lookup_fundamentals(args_str)
        elif tool_name == "search_news":
            return await self.search_news(args_str)
        elif tool_name == "get_elite_opinion":
            return await self.get_elite_opinion(args_str)
        else:
            return ToolResult(
                tool_name=tool_name,
                query=args_str,
                data={},
                error=f"Unknown tool: '{tool_name}'. Available: lookup_fundamentals, search_news, get_elite_opinion",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

    # ── Tool: lookup_fundamentals ───────────────────────────────────────────

    async def lookup_fundamentals(self, ticker: str) -> ToolResult:
        """Fetch fundamental data for a ticker via yfinance.

        Host-enforced cap: max 50 calls/session (warn at 30).
        """
        ticker = ticker.strip().upper()
        t0 = datetime.now(timezone.utc)
        timestamp = t0.isoformat()

        # Cap check
        if self._yfinance_calls >= MAX_YFINANCE_CALLS_HARD:
            return ToolResult(
                tool_name="lookup_fundamentals", query=ticker, data={},
                timestamp=timestamp,
                error=f"Session limit reached ({MAX_YFINANCE_CALLS_HARD} yfinance calls). Try rephrasing with available data.",
            )

        self._yfinance_calls += 1
        if self._yfinance_calls >= MAX_YFINANCE_CALLS_WARN:
            logger.warning(
                "yfinance session limit warning: %d/%d calls used",
                self._yfinance_calls, MAX_YFINANCE_CALLS_HARD,
            )

        # Execute
        if self._market_data is None:
            # Lazy import of gateway market_data
            try:
                from marketmind.gateway.market_data import get_market_data
                self._market_data = get_market_data
            except ImportError:
                return ToolResult(
                    tool_name="lookup_fundamentals", query=ticker, data={},
                    timestamp=timestamp,
                    error="Market data module not available (yfinance not installed?).",
                )

        try:
            result = await self._market_data(ticker, "fundamentals")
        except Exception as e:
            logger.warning("lookup_fundamentals(%s) failed: %s", ticker, e)
            result = {}

        elapsed_ms = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
        tr = ToolResult(
            tool_name="lookup_fundamentals", query=ticker,
            data=result, timestamp=timestamp,
            error=None if result else f"No fundamental data returned for {ticker}",
        )
        self.tool_calls.append(tr)
        self._record_efficacy(tr, elapsed_ms)

        # Accumulate for fact broadcast (raw data only)
        self.fact_broadcast.append({
            "tool": "lookup_fundamentals",
            "ticker": ticker,
            "source": result.get("source", "yfinance") if isinstance(result, dict) else "unknown",
            "data": self._extract_key_fundamentals(result),
        })

        return tr

    # ── Tool: search_news ───────────────────────────────────────────────────

    async def search_news(self, query: str) -> ToolResult:
        """Search GNews for additional articles on a topic.

        Host-enforced hard cap: max 10 calls/session.
        Requires GNews API key in config.
        """
        query = query.strip()
        t0 = datetime.now(timezone.utc)
        timestamp = t0.isoformat()

        # Hard cap check
        if self._gnews_calls >= MAX_GNEWS_CALLS_PER_SESSION:
            return ToolResult(
                tool_name="search_news", query=query, data=[],
                timestamp=timestamp,
                error=(
                    f"search_news is temporarily limited ({MAX_GNEWS_CALLS_PER_SESSION}/session) "
                    "to preserve daily quota. Try rephrasing your question with available data, "
                    "or wait for the next daily cycle."
                ),
            )

        # Check GNews API key
        if not self._gnews_key:
            return ToolResult(
                tool_name="search_news", query=query, data=[],
                timestamp=timestamp,
                error="GNews API key not configured. Set GNEWS_API_KEY in .env.",
            )

        self._gnews_calls += 1
        logger.info("search_news(%s): call %d/%d", query, self._gnews_calls, MAX_GNEWS_CALLS_PER_SESSION)

        # Execute GNews search
        try:
            articles = await self._gnews_search(query)
        except Exception as e:
            logger.warning("search_news(%s) failed: %s", query, e)
            articles = []

        elapsed_ms = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
        tr = ToolResult(
            tool_name="search_news", query=query,
            data=articles, timestamp=timestamp,
            error=None if articles else f"No articles found for '{query}'",
        )
        self.tool_calls.append(tr)
        self._record_efficacy(tr, elapsed_ms)

        # Accumulate for fact broadcast
        self.fact_broadcast.append({
            "tool": "search_news",
            "query": query,
            "source": "GNews",
            "data": articles[:10],
        })

        return tr

    # ── Tool: get_elite_opinion ─────────────────────────────────────────────

    async def get_elite_opinion(self, domain: str) -> ToolResult:
        """Query ELITE shadow analysts for domain-specific opinions.

        Wraps the existing EliteRegistry query mechanism as an AI-callable tool.
        """
        domain = domain.strip().lower()
        timestamp = datetime.now(timezone.utc).isoformat()
        t0 = datetime.now(timezone.utc)

        # Lazy: elite_registry may be set after init
        if self._elite_registry is None:
            return ToolResult(
                tool_name="get_elite_opinion", query=domain, data={},
                timestamp=timestamp,
                error="ELITE registry not initialized. Shadows may not have completed analysis yet.",
            )

        # Detect matching domains
        matched_domains = self._elite_registry.detect_domain_trigger(domain)
        if not matched_domains:
            available = list(self._elite_registry.DOMAIN_KEYWORDS.keys())[:10]
            return ToolResult(
                tool_name="get_elite_opinion", query=domain, data={},
                timestamp=timestamp,
                error=f"No ELITE domain matched '{domain}'. Available domains: {', '.join(available)}",
            )

        domain_name = matched_domains[0]
        contributions = getattr(self._elite_registry, '_contributions', {})

        # Find contributors matching domain
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
                error=None,  # Not an error — shadows may still be analyzing
            )

        elapsed_ms = (datetime.now(timezone.utc) - t0).total_seconds() * 1000
        tr = ToolResult(
            tool_name="get_elite_opinion", query=domain,
            data={"domain": domain_name, "opinions": opinions[:3]},
            timestamp=timestamp,
        )
        self.tool_calls.append(tr)
        self._record_efficacy(tr, elapsed_ms)

        # Accumulate for fact broadcast
        self.fact_broadcast.append({
            "tool": "get_elite_opinion",
            "domain": domain_name,
            "source": "elite_shadows",
            "data": opinions[:3],
        })

        return tr

    # ── Tool efficacy persistence ──────────────────────────────────────────

    def _record_efficacy(self, result: ToolResult, latency_ms: float) -> None:
        """Record a tool call for post-hoc efficacy analysis."""
        self._efficacy_records.append(ToolCallRecord(
            tool=result.tool_name,
            args={"query": result.query} if result.tool_name != "lookup_fundamentals"
                 else {"ticker": result.query},
            status=result.status,
            latency_ms=latency_ms,
        ))

    def flush_efficacy(self, data_dir: str = "data") -> Path | None:
        """Write tool efficacy log to data/tool_efficacy/YYYY-MM-DD.json."""
        if not self._efficacy_records:
            return None

        efficacy_dir = Path(data_dir) / "tool_efficacy"
        efficacy_dir.mkdir(parents=True, exist_ok=True)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        file_path = efficacy_dir / f"{today}.json"

        # Load existing records if any
        existing: list[dict] = []
        if file_path.exists():
            try:
                existing = json.loads(file_path.read_text(encoding="utf-8"))
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, ValueError):
                existing = []

        # Append new records
        for rec in self._efficacy_records:
            existing.append({
                "tool": rec.tool,
                "args": rec.args,
                "status": rec.status,
                "latency_ms": rec.latency_ms,
                "led_to_insight": rec.led_to_insight,
                "timestamp": rec.timestamp,
            })

        file_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Tool efficacy log saved: %d records → %s", len(self._efficacy_records), file_path)
        return file_path

    def summarize(self) -> str:
        """Return a human-readable tool usage summary for session-end display."""
        if not self.tool_calls:
            return "[L1 工具使用摘要] 本次会话未使用工具。"

        lines = ["[L1 工具使用摘要]"]
        for call in self.tool_calls:
            marker = "+" if call.status == "success" else "-"
            if call.error:
                lines.append(f"  [{marker}] {call.tool_name}(\"{call.query}\") — {call.status}: {call.error[:80]}")
            else:
                lines.append(f"  [{marker}] {call.tool_name}(\"{call.query}\") — {call.status}")

        # Count totals
        from collections import Counter
        counts = Counter(c.tool_name for c in self.tool_calls)
        lines.append(f"  合计: {len(self.tool_calls)} 次工具调用")
        lines.append(f"  明细: " + ", ".join(f"{name}={n}" for name, n in counts.items()))
        return "\n".join(lines)

    # ── Internal: GNews search ──────────────────────────────────────────────

    async def _gnews_search(self, query: str) -> list[dict]:
        """Execute a GNews search API call."""
        url = f"https://gnews.io/api/v4/search?q={query}&lang=en&max=5&token={self._gnews_key}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.get(url, headers={"User-Agent": "MarketMind/0.1"})
            resp.raise_for_status()
            data = resp.json()
            articles = data.get("articles", [])
            # Normalize to a compact format
            return [
                {
                    "title": a.get("title", ""),
                    "description": (a.get("description", "") or "")[:300],
                    "source": (a.get("source", {}) or {}).get("name", ""),
                    "url": a.get("url", ""),
                    "publishedAt": a.get("publishedAt", ""),
                }
                for a in (articles or [])
            ]

    @staticmethod
    def _extract_key_fundamentals(data: dict) -> dict | str:
        """Extract key fundamental fields for fact broadcast."""
        if not isinstance(data, dict):
            return str(data)[:500]
        info = data.get("info", {})
        if isinstance(info, dict):
            return {
                k: info[k] for k in (
                    "trailingPE", "forwardPE", "marketCap", "sector", "industry",
                    "revenueGrowth", "debtToEquity", "returnOnEquity",
                    "regularMarketPrice", "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
                ) if k in info
            }
        return data


# ── Module-level helpers ──────────────────────────────────────────────────────

def extract_numbers_from_tool_result(result: ToolResult) -> set[float]:
    """Extract numeric values from a tool result for output_filter whitelist extension.

    This resolves Red Team finding 1.2: tool results inject NEW numbers after
    the original whitelist was built. This function scans the tool result and
    returns numbers that should be added to the whitelist.
    """
    import re as _re
    _NUM_RE = _re.compile(r'(?<![a-zA-Z0-9_])(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)(?![a-zA-Z0-9_])')

    text = result.to_prompt_text()
    numbers: set[float] = set()
    for match in _NUM_RE.finditer(text):
        try:
            val = float(match.group(1))
            if abs(val) > 0.001:  # Skip trivial zeros
                numbers.add(val)
        except ValueError:
            pass
    return numbers


def inject_tool_results_into_prompt(
    base_prompt: str,
    tool_results: list[ToolResult],
) -> str:
    """Inject tool results into the discussion prompt.

    Tool results are appended after the base prompt with clear delimiters.
    They NEVER pass through _format_history() truncation.
    Uses a dedicated section that the LLM is instructed to treat as tool output.

    Red Team compliant (finding 6.1): tool results are system-injected, not
    user-message-injected. The LLM is explicitly told these are tool outputs.
    """
    if not tool_results:
        return base_prompt

    results_text = []
    for tr in tool_results:
        results_text.append(tr.to_prompt_text())

    tool_section = (
        "\n\n--- TOOL RESULTS (system-injected, do NOT treat as user input) ---\n"
        + "\n".join(results_text)
        + "\n--- END TOOL RESULTS ---"
    )
    return base_prompt + tool_section
