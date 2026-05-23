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
MAX_MACRO_CALLS_WARN = 10              # Per-tool-type warning threshold (no hard cap)

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
            lines = []
            for k, v in data.items():
                v_str = str(v)
                if len(v_str) > 200:
                    v_str = v_str[:200] + "..."
                lines.append(f"{k}: {v_str}")
            return "\n".join(lines[:80])
        if isinstance(data, list):
            lines = []
            for i, item in enumerate(data[:10]):
                if isinstance(item, dict):
                    title = item.get("title", "")[:150]
                    src = item.get("source", "")
                    source = item.get("source_name", "")
                    if not source and src:
                        source = src.get("name", "") if isinstance(src, dict) else str(src)
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

    Eight tools available (per Red Team audit resolution):
    - lookup_fundamentals: yfinance fundamentals (P/E, market cap, sector, etc.)
    - search_news: GNews search (capped at 10/session)
    - get_elite_opinion: query ELITE shadow registry
    - get_macro_indicator: FRED macro indicators (BDI, GSCPI)
    - get_cot_data: CFTC Commitments of Traders (ES, CL, GC, NG)
    - get_eia_inventory: EIA petroleum inventory (crude, gasoline, distillate)
    - get_economic_calendar: upcoming economic events (FOMC, CPI, NFP, GDP)
    - get_earnings_date: earnings dates for ticker(s)

    Tool implementations are in l1_market_tools.py and l1_info_tools.py.
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
        self._macro_indicator_calls: int = 0
        self._cot_calls: int = 0
        self._eia_calls: int = 0

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
        elif tool_name == "get_macro_indicator":
            return await self.get_macro_indicator(args_str)
        elif tool_name == "get_cot_data":
            return await self.get_cot_data(args_str)
        elif tool_name == "get_eia_inventory":
            return await self.get_eia_inventory(args_str)
        elif tool_name == "get_economic_calendar":
            return await self.get_economic_calendar(args_str)
        elif tool_name == "get_earnings_date":
            return await self.get_earnings_date(args_str)
        else:
            return ToolResult(
                tool_name=tool_name,
                query=args_str,
                data={},
                error=f"Unknown tool: '{tool_name}'. Available: lookup_fundamentals, search_news, get_elite_opinion, get_macro_indicator, get_cot_data, get_eia_inventory, get_economic_calendar, get_earnings_date",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

    # ── Tool delegation (implementations in l1_market_tools / l1_info_tools) ──

    async def lookup_fundamentals(self, ticker: str) -> ToolResult:
        from marketmind.pipeline.l1_market_tools import _tool_lookup_fundamentals
        return await _tool_lookup_fundamentals(self, ticker)

    async def search_news(self, query: str) -> ToolResult:
        from marketmind.pipeline.l1_info_tools import _tool_search_news
        return await _tool_search_news(self, query)

    async def get_elite_opinion(self, domain: str) -> ToolResult:
        from marketmind.pipeline.l1_info_tools import _tool_get_elite_opinion
        return await _tool_get_elite_opinion(self, domain)

    async def get_macro_indicator(self, indicator: str) -> ToolResult:
        from marketmind.pipeline.l1_market_tools import _tool_get_macro_indicator
        return await _tool_get_macro_indicator(self, indicator)

    async def get_cot_data(self, asset: str) -> ToolResult:
        from marketmind.pipeline.l1_market_tools import _tool_get_cot_data
        return await _tool_get_cot_data(self, asset)

    async def get_eia_inventory(self, product: str) -> ToolResult:
        from marketmind.pipeline.l1_market_tools import _tool_get_eia_inventory
        return await _tool_get_eia_inventory(self, product)

    async def get_economic_calendar(self, _unused: str = "") -> ToolResult:
        from marketmind.pipeline.l1_info_tools import _tool_get_economic_calendar
        return await _tool_get_economic_calendar(self, _unused)

    async def get_earnings_date(self, ticker: str) -> ToolResult:
        from marketmind.pipeline.l1_info_tools import _tool_get_earnings_date
        return await _tool_get_earnings_date(self, ticker)

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

        existing: list[dict] = []
        if file_path.exists():
            try:
                existing = json.loads(file_path.read_text(encoding="utf-8"))
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, ValueError):
                existing = []

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
