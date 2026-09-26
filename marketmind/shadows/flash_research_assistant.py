"""Flash Research Assistant — shadow research proxy with quota management.

Shadows call Flash (not Pro) for research tasks. Flash has tools:
- fetch_market_snapshot: latest OHLCV for a ticker
- scan_archive: semantic search over Gate 1-3 archives
- check_peer_consensus: anonymized aggregate direction (N>=5 required)
- retrieve_cached_analysis: from shadow_analysis_repo

Phase 2: Gate 2 mode provides unlimited Flash for invited graduated shadows.
Budget-ratio conditioning: remaining quota injected into prompts.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("marketmind.shadows.flash_research_assistant")

PEER_CONSENSUS_MIN_PEERS = 5  # Gate 2 de-anonymization protection


@dataclass
class FlashResearchRequest:
    """A research request from a shadow to Flash."""
    shadow_id: str
    topic: str
    tool: str  # "fetch_market_snapshot" | "scan_archive" | "check_peer_consensus" | "retrieve_cached_analysis"
    params: dict = field(default_factory=dict)
    depth: str = "standard"  # "quick" | "standard" | "deep"
    requested_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class FlashResearchResult:
    """Structured findings returned from Flash to shadow."""
    request_id: str
    tool: str
    status: str  # "ok" | "insufficient_peers" | "error"
    data: dict = field(default_factory=dict)
    summary: str = ""
    error: str = ""


class FlashResearchAssistant:
    """Manages shadow→Flash research calls with quota tracking and tool dispatch.

    In Gate 2 mode (is_gate2_discussion=True), quota is NOT consumed.
    """

    def __init__(self, model: str = "flash", gate2_mode: bool = False):
        self.model = model
        self.gate2_mode = gate2_mode
        self._call_log: list[dict] = []

    # ── Public API ──────────────────────────────────────────────────────────

    async def research(self, shadow_id: str, request: FlashResearchRequest,
                       quota_used: int = 0, quota_total: int = 10) -> FlashResearchResult:
        """Execute a research request via Flash.

        In Gate 2 mode, quota is not consumed. In training mode, each call
        counts against the shadow's daily quota.
        """
        request_id = hashlib.sha256(
            f"{shadow_id}:{request.tool}:{request.topic}:{request.requested_at}".encode()
        ).hexdigest()[:12]

        if not self.gate2_mode and quota_used >= quota_total:
            return FlashResearchResult(
                request_id=request_id, tool=request.tool,
                status="error", error="Quota exhausted"
            )

        try:
            result = await self._dispatch(request)
            self._call_log.append({
                "shadow_id": shadow_id, "tool": request.tool,
                "topic": request.topic, "status": result.status,
                "gate2_mode": self.gate2_mode,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return result
        except Exception as e:
            logger.error("Flash research failed for %s: %s", shadow_id, e)
            return FlashResearchResult(
                request_id=request_id, tool=request.tool,
                status="error", error=str(e)[:200]
            )

    async def _dispatch(self, request: FlashResearchRequest) -> FlashResearchResult:
        """Route to the appropriate tool handler."""
        request_id = hashlib.sha256(
            f"{request.shadow_id}:{request.tool}:{request.topic}".encode()
        ).hexdigest()[:12]

        if request.tool == "fetch_market_snapshot":
            return await self._fetch_market_snapshot(request_id, request.params)
        elif request.tool == "scan_archive":
            return await self._scan_archive(request_id, request.params)
        elif request.tool == "check_peer_consensus":
            return await self._check_peer_consensus(request_id, request.params)
        elif request.tool == "retrieve_cached_analysis":
            return await self._retrieve_cached_analysis(request_id, request.params)
        else:
            return FlashResearchResult(
                request_id=request_id, tool=request.tool,
                status="error", error=f"Unknown tool: {request.tool}"
            )

    # ── Tool Implementations ────────────────────────────────────────────────

    async def _fetch_market_snapshot(self, request_id: str,
                                      params: dict) -> FlashResearchResult:
        """Fetch latest OHLCV for a ticker from market_data_fetcher."""
        ticker = params.get("ticker", "")
        if not ticker:
            return FlashResearchResult(
                request_id=request_id, tool="fetch_market_snapshot",
                status="error", error="Missing ticker parameter"
            )
        try:
            from marketmind.shadows.market_data_fetcher import MarketDataFetcher
            fetcher = MarketDataFetcher()
            prices = await fetcher.get_recent_prices(ticker, days=params.get("days", 5))
            return FlashResearchResult(
                request_id=request_id, tool="fetch_market_snapshot",
                status="ok", data={"ticker": ticker, "prices": prices},
                summary=f"Fetched {len(prices)} days of price data for {ticker}"
            )
        except Exception as e:
            return FlashResearchResult(
                request_id=request_id, tool="fetch_market_snapshot",
                status="error", error=str(e)[:200]
            )

    async def _scan_archive(self, request_id: str,
                             params: dict) -> FlashResearchResult:
        """Semantic search over Gate 1-3 archives."""
        query = params.get("query", "")
        days = params.get("days", 30)
        if not query:
            return FlashResearchResult(
                request_id=request_id, tool="scan_archive",
                status="error", error="Missing query parameter"
            )
        try:
            from marketmind.storage.archivist import MarketMindArchive
            archive = MarketMindArchive()
            results = archive.search(query, limit=params.get("limit", 5),
                                      days_back=days)
            return FlashResearchResult(
                request_id=request_id, tool="scan_archive",
                status="ok", data={"results": results[:5]},
                summary=f"Found {len(results)} archive matches for '{query[:60]}'"
            )
        except Exception as e:
            return FlashResearchResult(
                request_id=request_id, tool="scan_archive",
                status="error", error=str(e)[:200]
            )

    async def _check_peer_consensus(self, request_id: str,
                                     params: dict) -> FlashResearchResult:
        """Get anonymized aggregate direction for a ticker. N>=5 required."""
        ticker = params.get("ticker", "")
        if not ticker:
            return FlashResearchResult(
                request_id=request_id, tool="check_peer_consensus",
                status="error", error="Missing ticker parameter"
            )
        try:
            from marketmind.shadows.shadow_state import ShadowStateDB
            state_db = ShadowStateDB()
            todays_votes = state_db.get_todays_votes(ticker) or []
            non_abstain = [v for v in todays_votes if v.get("direction") != "abstain"]

            if len(non_abstain) < PEER_CONSENSUS_MIN_PEERS:
                return FlashResearchResult(
                    request_id=request_id, tool="check_peer_consensus",
                    status="insufficient_peers",
                    data={"min_required": PEER_CONSENSUS_MIN_PEERS,
                          "available": len(non_abstain)},
                    summary=f"Need {PEER_CONSENSUS_MIN_PEERS} peers, only {len(non_abstain)} voted"
                )

            long_pct = sum(1 for v in non_abstain if v.get("direction") == "long") / len(non_abstain)
            consensus_strength = 2 * abs(long_pct - 0.5)
            dominant = "long" if long_pct > 0.5 else "short" if long_pct < 0.5 else "split"

            return FlashResearchResult(
                request_id=request_id, tool="check_peer_consensus",
                status="ok",
                data={"ticker": ticker, "total_votes": len(non_abstain),
                      "consensus_strength": round(consensus_strength, 2),
                      "dominant_direction": dominant},
                summary=f"Consensus {consensus_strength:.2f} {dominant} ({len(non_abstain)} peers)"
            )
        except Exception as e:
            return FlashResearchResult(
                request_id=request_id, tool="check_peer_consensus",
                status="error", error=str(e)[:200]
            )

    async def _retrieve_cached_analysis(self, request_id: str,
                                         params: dict) -> FlashResearchResult:
        """Retrieve cached analysis from shadow_analysis_repo."""
        ticker = params.get("ticker", "")
        date = params.get("date", "")
        try:
            from marketmind.shadows.shadow_analysis_repo import get_analyses
            analyses = get_analyses(ticker=ticker, date=date, limit=3)
            return FlashResearchResult(
                request_id=request_id, tool="retrieve_cached_analysis",
                status="ok", data={"analyses": analyses[:3]},
                summary=f"Retrieved {len(analyses)} cached analyses for {ticker}"
            )
        except Exception as e:
            return FlashResearchResult(
                request_id=request_id, tool="retrieve_cached_analysis",
                status="error", error=str(e)[:200]
            )

    # ── Quota Helpers ───────────────────────────────────────────────────────

    def get_call_log(self) -> list[dict]:
        return list(self._call_log)

    def get_call_count(self, shadow_id: str | None = None) -> int:
        if shadow_id:
            return sum(1 for c in self._call_log if c["shadow_id"] == shadow_id)
        return len(self._call_log)
