"""Playground-exclusive data sources — independent of main Scout pipeline.

Three-tier usage model:
  CORE         — fetched daily for active agents
  SUPPLEMENTAL — on-demand only (agent explicitly requests, or core < threshold)
  RETIRED      — kept for audit trail, never fetched

Two fetch channels:
  WP_API  — WordPress REST API (clean JSON, full article content)
  RSS     — traditional RSS 2.0 / Atom feed (headline + summary)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum


class SourceTier(IntEnum):
    PRIMARY = 1
    RELIABLE = 2
    FRAGILE = 3
    BEST_EFFORT = 4


class UsageTier(str, Enum):
    CORE = "core"
    SUPPLEMENTAL = "supplemental"
    RETIRED = "retired"


class SourceChannel(str, Enum):
    WP_API = "wp_api"
    RSS = "rss"


@dataclass
class PlaygroundSource:
    name: str
    url: str                        # RSS URL or WP API base
    tier: SourceTier
    channel: SourceChannel = SourceChannel.RSS
    reliability: float = 0.5
    rate_limit_rps: float = 1.0
    description: str = ""
    coverage: list[str] = field(default_factory=list)
    usage_tier: UsageTier = UsageTier.CORE
    wp_api_url: str = ""            # Only for WP_API channel
    retire_reason: str = ""         # Only for RETIRED


# ── WP API helpers ────────────────────────────────────────────────────────

def wp_posts_url(base: str, per_page: int = 20) -> str:
    """Build WP REST API posts endpoint URL."""
    base = base.rstrip("/")
    return f"{base}/wp-json/wp/v2/posts?per_page={per_page}&_embed"


# ══════════════════════════════════════════════════════════════════════════
# Playground Source Registry (all 16 discovered sources)
# ══════════════════════════════════════════════════════════════════════════

PLAYGROUND_SOURCES: list[PlaygroundSource] = [

    # ── CORE: WP API — Full Article ────────────────────────────────────
    PlaygroundSource(
        name="EE Times",
        url="https://www.eetimes.com",
        wp_api_url=wp_posts_url("https://www.eetimes.com"),
        channel=SourceChannel.WP_API,
        tier=SourceTier.PRIMARY,
        reliability=0.88,
        usage_tier=UsageTier.CORE,
        description="Global electronics industry — AI chips, processors, TSMC events, Huawei. "
                    "WP API returns full article (~7,000 chars).",
        coverage=["semiconductor", "electronics", "AI_chips", "processors", "TSMC"],
    ),
    PlaygroundSource(
        name="EDN",
        url="https://www.edn.com",
        wp_api_url=wp_posts_url("https://www.edn.com"),
        channel=SourceChannel.WP_API,
        tier=SourceTier.RELIABLE,
        reliability=0.80,
        usage_tier=UsageTier.CORE,
        description="Component-level electronics design — circuit protection, SoC, medical "
                    "electronics. WP API returns full article (~15,000 chars).",
        coverage=["electronics", "components", "design", "SoC", "power_management"],
    ),
    PlaygroundSource(
        name="Semiconductor Engineering",
        url="https://semiengineering.com",
        wp_api_url=wp_posts_url("https://semiengineering.com"),
        channel=SourceChannel.WP_API,
        tier=SourceTier.PRIMARY,
        reliability=0.90,
        usage_tier=UsageTier.CORE,
        description="Deep technical analysis for chip engineers — GPU inference characterization, "
                    "technical paper roundups, research. WP API (~2,000 chars).",
        coverage=["chip_design", "manufacturing", "technical_deep_dive", "GPU", "EDA"],
    ),
    PlaygroundSource(
        name="Semiconductor Digest",
        url="https://www.semiconductor-digest.com",
        wp_api_url=wp_posts_url("https://www.semiconductor-digest.com"),
        channel=SourceChannel.WP_API,
        tier=SourceTier.RELIABLE,
        reliability=0.78,
        usage_tier=UsageTier.CORE,
        description="Semiconductor industry business/trends — SEMI Foundation, ASE packaging, "
                    "next-gen semiconductor research. WP API (~4,700 chars).",
        coverage=["semiconductor", "industry_trends", "packaging", "SEMI"],
    ),
    PlaygroundSource(
        name="Solid State Technology",
        url="https://sst.semiconductor-digest.com",
        wp_api_url=wp_posts_url("https://sst.semiconductor-digest.com"),
        channel=SourceChannel.WP_API,
        tier=SourceTier.RELIABLE,
        reliability=0.80,
        usage_tier=UsageTier.CORE,
        description="Semiconductor manufacturing process/equipment — automotive fab monitoring, "
                    "embedded NVM, measurement systems. WP API (~8,000 chars).",
        coverage=["manufacturing", "process_technology", "equipment", "automotive"],
    ),
    PlaygroundSource(
        name="ServeTheHome",
        url="https://www.servethehome.com",
        wp_api_url=wp_posts_url("https://www.servethehome.com"),
        channel=SourceChannel.WP_API,
        tier=SourceTier.RELIABLE,
        reliability=0.82,
        usage_tier=UsageTier.CORE,
        description="Server and data center hardware — Supermicro, NVIDIA DGX, PCIe Gen6, CXL. "
                    "WP API returns full review/article (~23,000 chars).",
        coverage=["AI_hardware", "data_center", "server", "NVIDIA", "networking"],
    ),

    # ── CORE: RSS — Good Excerpt ────────────────────────────────────────
    PlaygroundSource(
        name="EE Times Asia",
        url="https://www.eetasia.com/feed/",
        channel=SourceChannel.RSS,
        tier=SourceTier.RELIABLE,
        reliability=0.78,
        usage_tier=UsageTier.CORE,
        description="Asian electronics supply chain — Indonesia smartphone shipments, ASE, "
                    "EUV lithography, AI design verification. RSS excerpt (~3,200 chars).",
        coverage=["asian_semiconductor", "supply_chain", "ASE", "EUV", "smartphone"],
    ),
    PlaygroundSource(
        name="Photonics Spectra",
        url="https://www.photonics.com/rss.aspx",
        channel=SourceChannel.RSS,
        tier=SourceTier.PRIMARY,
        reliability=0.85,
        usage_tier=UsageTier.CORE,
        description="Photonics/optoelectronics — wafer-level packaging, photonic-electronic "
                    "integration, quantum computing, CPO. RSS excerpt (~720 chars).",
        coverage=["photonics", "optical_interconnect", "CPO", "silicon_photonics", "quantum"],
    ),

    # ── SUPPLEMENTAL ────────────────────────────────────────────────────
    PlaygroundSource(
        name="Google News — Semiconductor",
        url="https://news.google.com/rss/search?q=semiconductor+supply+chain&hl=en-US",
        channel=SourceChannel.RSS,
        tier=SourceTier.BEST_EFFORT,
        reliability=0.30,
        usage_tier=UsageTier.SUPPLEMENTAL,
        description="Catch-all aggregation. Triggered when core sources yield < 15 articles/day.",
        coverage=["semiconductor", "supply_chain", "aggregation"],
    ),

    # ── RETIRED ─────────────────────────────────────────────────────────
    PlaygroundSource(
        name="Tom's Hardware",
        url="https://www.tomshardware.com/feeds/all",
        channel=SourceChannel.RSS,
        tier=SourceTier.FRAGILE,
        reliability=0.65,
        usage_tier=UsageTier.RETIRED,
        retire_reason="Consumer GPU/gaming focus. RSS has no body text + no WP API. "
                      "Signal density too low for semiconductor bottleneck analysis.",
        coverage=["hardware", "GPU", "consumer"],
    ),
    PlaygroundSource(
        name="TechPowerUp",
        url="https://www.techpowerup.com/rss/news",
        channel=SourceChannel.RSS,
        tier=SourceTier.FRAGILE,
        reliability=0.60,
        usage_tier=UsageTier.RETIRED,
        retire_reason="Gaming GPU focus. No WP API. Zero supply chain relevance.",
        coverage=["GPU", "gaming"],
    ),
    PlaygroundSource(
        name="Ars Technica",
        url="https://feeds.arstechnica.com/arstechnica/index",
        channel=SourceChannel.RSS,
        tier=SourceTier.FRAGILE,
        reliability=0.55,
        usage_tier=UsageTier.RETIRED,
        retire_reason="General tech, low semiconductor signal density. "
                      "Redundant with main Scout's existing tech coverage (BBC, Reuters).",
        coverage=["technology", "general"],
    ),
    PlaygroundSource(
        name="The Register",
        url="https://www.theregister.com/headlines.atom",
        channel=SourceChannel.RSS,
        tier=SourceTier.FRAGILE,
        reliability=0.60,
        usage_tier=UsageTier.RETIRED,
        retire_reason="Atom feed returns no body content. Enterprise IT focus overlaps "
                      "with Nikkei Asia + SCMP in main Scout.",
        coverage=["enterprise_IT", "data_center"],
    ),
    PlaygroundSource(
        name="WCCFTech",
        url="https://wccftech.com/feed/",
        channel=SourceChannel.RSS,
        tier=SourceTier.BEST_EFFORT,
        reliability=0.40,
        usage_tier=UsageTier.RETIRED,
        retire_reason="Hardware rumor aggregation. Reliability 0.40 — too low even for "
                      "supplemental use.",
        coverage=["hardware", "rumors"],
    ),
    PlaygroundSource(
        name="Power Electronics News",
        url="https://www.powerelectronicsnews.com/feed/",
        channel=SourceChannel.RSS,
        tier=SourceTier.BEST_EFFORT,
        reliability=0.55,
        usage_tier=UsageTier.RETIRED,
        retire_reason="GaN/SiC power electronics — too specialized for bottleneck analysis. "
                      "No agent currently needs this domain.",
        coverage=["power_electronics", "GaN", "SiC"],
    ),
]


# ══════════════════════════════════════════════════════════════════════════
# Agent-to-source mapping
# ══════════════════════════════════════════════════════════════════════════

AGENT_SOURCE_MAP: dict[str, list[str]] = {
    "serenity_reply": [
        # CORE — all 8 semiconductor supply chain sources
        "EE Times",
        "EDN",
        "Semiconductor Engineering",
        "Semiconductor Digest",
        "Solid State Technology",
        "ServeTheHome",
        "EE Times Asia",
        "Photonics Spectra",
        # SUPPLEMENTAL — catch-all when core < threshold
        "Google News — Semiconductor",
    ],
}


# ══════════════════════════════════════════════════════════════════════════
# Query helpers
# ══════════════════════════════════════════════════════════════════════════

_name_to_source: dict[str, PlaygroundSource] | None = None


def _build_index() -> dict[str, PlaygroundSource]:
    global _name_to_source
    if _name_to_source is None:
        _name_to_source = {s.name: s for s in PLAYGROUND_SOURCES}
    return _name_to_source


def get_source(name: str) -> PlaygroundSource | None:
    return _build_index().get(name)


def get_sources_for_agent(agent_id: str) -> list[PlaygroundSource]:
    """Get all sources (any tier) declared for an agent."""
    source_names = AGENT_SOURCE_MAP.get(agent_id, [])
    index = _build_index()
    return [index[n] for n in source_names if n in index]


def get_core_sources(agent_ids: list[str]) -> list[PlaygroundSource]:
    """Get union of CORE-tier sources across agents."""
    seen: set[str] = set()
    sources: list[PlaygroundSource] = []
    for aid in agent_ids:
        for src in get_sources_for_agent(aid):
            if src.usage_tier == UsageTier.CORE and src.name not in seen:
                seen.add(src.name)
                sources.append(src)
    return sources


def get_supplemental_sources(agent_ids: list[str]) -> list[PlaygroundSource]:
    """Get union of SUPPLEMENTAL-tier sources across agents."""
    seen: set[str] = set()
    sources: list[PlaygroundSource] = []
    for aid in agent_ids:
        for src in get_sources_for_agent(aid):
            if src.usage_tier == UsageTier.SUPPLEMENTAL and src.name not in seen:
                seen.add(src.name)
                sources.append(src)
    return sources


def get_retired_sources() -> list[PlaygroundSource]:
    """Get all retired sources (for audit display)."""
    return [s for s in PLAYGROUND_SOURCES if s.usage_tier == UsageTier.RETIRED]


def get_all_active_sources(agent_ids: list[str]) -> list[PlaygroundSource]:
    """Get CORE + SUPPLEMENTAL sources for given agents."""
    return get_core_sources(agent_ids) + get_supplemental_sources(agent_ids)
