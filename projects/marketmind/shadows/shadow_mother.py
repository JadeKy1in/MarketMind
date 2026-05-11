"""Shadow Mother — event detection, temp shadow lifecycle, daily orchestration."""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from projects.marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from projects.marketmind.shadows.shadow_agent import ShadowAgent, ShadowAnalysisOutput, ShadowVote
from projects.marketmind.config.settings import ShadowSettings

logger = logging.getLogger("marketmind.shadows.shadow_mother")


@dataclass
class DetectedEvent:
    event_id: str
    event_type: str          # "cb_shock" | "geopolitical" | "vol_shock" | "personnel"
    description: str
    affected_assets: list[str]
    impact_score: float      # 0-1 normalized impact
    detected_at: str         # ISO 8601
    vix_level: float | None = None
    max_zscore: float | None = None
    news_volume: int | None = None


@dataclass
class TempShadowSpec:
    event_id: str
    shadow_name: str
    methodology_base: str    # which expert template to clone from
    domain: str
    virtual_capital: float   # $10K-$20K based on event impact
    max_lifespan_days: int = 30
    flash_quota_per_day: int = 3


@dataclass
class ShadowOrchestrationResult:
    date: str
    active_shadows: int = 0
    temp_shadows_created: int = 0
    temp_shadows_destroyed: int = 0
    votes_collected: int = 0
    shadow_analyses: dict[str, ShadowAnalysisOutput] = field(default_factory=dict)
    rankings: list = field(default_factory=list)
    collusion_flags: list = field(default_factory=list)
    challenger_actions: list[str] = field(default_factory=list)
    emergency_audits: list[str] = field(default_factory=list)


class ShadowMother:
    """Detects events, creates/destroys temporary shadows, manages event lifecycle."""

    def __init__(self, config: ShadowSettings, state_db: ShadowStateDB):
        self.config = config
        self.state_db = state_db

    # ── Event scanning ───────────────────────────────────────────────────

    async def scan_events(self, news_items: list[dict]) -> list[DetectedEvent]:
        """Scan news for trigger events. Returns detected events sorted by impact."""
        events = []
        events.extend(self.detect_cb_shock(news_items))
        events.extend(self.detect_geopolitical(news_items))
        events.extend(self.detect_vol_shock(None))  # market_data passed separately
        events.extend(self.detect_personnel_change(news_items))
        events.sort(key=lambda e: e.impact_score, reverse=True)
        return events

    def detect_cb_shock(self, news_items: list[dict]) -> list[DetectedEvent]:
        """E1: Central bank action |actual - expected| >= 50bp."""
        cb_keywords = [
            r'(?:Fed|Federal Reserve|ECB|BOJ|BOE|PBOC|RBA|RBNZ|BOC|SNB)\s',
            r'(?:rate|hike|cut|ease|tighten|basis point|bp)\s',
            r'(?:surprise|unexpected|vs\s+\d+(?:\.\d+)?%\s+expected)',
        ]
        return self._detect_by_keywords(
            news_items, "cb_shock", cb_keywords, base_impact=0.6
        )

    def detect_geopolitical(self, news_items: list[dict]) -> list[DetectedEvent]:
        """E2: VIX ratio >= 1.5 AND delta >= 5 points."""
        geo_keywords = [
            r'(?:war|conflict|sanctions|tensions?|missile|invasion|military|coup)',
            r'(?:geopolitical|crisis|escalation|attack|embargo)',
            r'(?:VIX\s+(?:surge|spike|jump|soar)s?)',
        ]
        return self._detect_by_keywords(
            news_items, "geopolitical", geo_keywords, base_impact=0.5
        )

    def detect_vol_shock(self, market_data: dict[str, float] | None = None) -> list[DetectedEvent]:
        """E3: Single-asset 24h |return| >= 5 * sigma_60d."""
        if market_data is None:
            return []
        events = []
        for ticker, zscore in market_data.items():
            abs_z = abs(zscore)
            if abs_z >= 5.0:
                event_id = hashlib.sha256(
                    f"vol_shock:{ticker}:{datetime.now(timezone.utc).date()}".encode()
                ).hexdigest()[:16]
                impact = min(abs_z / 10.0, 1.0)
                events.append(DetectedEvent(
                    event_id=event_id,
                    event_type="vol_shock",
                    description=f"{ticker} volatility shock: {abs_z:.1f} sigma move",
                    affected_assets=[ticker],
                    impact_score=impact,
                    detected_at=datetime.now(timezone.utc).isoformat(),
                    max_zscore=abs_z,
                ))
        return events

    def detect_personnel_change(self, news_items: list[dict]) -> list[DetectedEvent]:
        """E4: Key personnel change via keyword detection."""
        personnel_keywords = [
            r'(?:Treasury Secretary|Fed Chair|SEC Chair|CFTC|OCC|FDIC)\b',
            r'(?:resign|fired|replaced|appointed|nominated|confirmed)\b',
        ]
        return self._detect_by_keywords(
            news_items, "personnel", personnel_keywords, base_impact=0.4
        )

    def _detect_by_keywords(self, news_items: list[dict], event_type: str,
                             keywords: list[str], base_impact: float) -> list[DetectedEvent]:
        """Generic keyword-based event detection."""
        events = []
        seen_headlines = set()
        for item in news_items:
            headline = str(item.get("headline", ""))
            if headline in seen_headlines:
                continue
            matched = sum(1 for kw in keywords if re.search(kw, headline, re.IGNORECASE))
            if matched >= 2:  # at least 2 keyword groups match
                seen_headlines.add(headline)
                event_id = hashlib.sha256(
                    f"{event_type}:{headline}:{datetime.now(timezone.utc).date()}".encode()
                ).hexdigest()[:16]
                impact = min(base_impact + matched * 0.1, 1.0)
                # Extract ticker mentions
                tickers = re.findall(r'\b[A-Z]{1,5}\b', headline)
                events.append(DetectedEvent(
                    event_id=event_id,
                    event_type=event_type,
                    description=headline[:200],
                    affected_assets=tickers[:5],
                    impact_score=impact,
                    detected_at=datetime.now(timezone.utc).isoformat(),
                    news_volume=1,
                ))
        return events

    # ── Prioritization ───────────────────────────────────────────────────

    def prioritize_events(self, events: list[DetectedEvent],
                          max_shadows: int = 5) -> list[DetectedEvent]:
        """Top N events by impact_score get shadows."""
        sorted_events = sorted(events, key=lambda e: e.impact_score, reverse=True)
        return sorted_events[:max_shadows]

    # ── Temp shadow lifecycle ────────────────────────────────────────────

    async def create_temp_shadows(self, events: list[DetectedEvent]) -> list[str]:
        """Create temporary event shadows for prioritized events."""
        created_ids = []
        for event in events:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            shadow_id = f"temp_event:{event.event_type}:{ts}_{event.event_id[:8]}"
            capital = 10000.0 + event.impact_score * 10000.0  # $10K-$20K

            config = ShadowConfig(
                shadow_id=shadow_id,
                shadow_type="temp_event",
                display_name=f"Temp {event.event_type} {ts}",
                methodology_prompt=(
                    f"You are a temporary market analyst activated for: {event.description}. "
                    f"Focus on affected assets: {', '.join(event.affected_assets[:5])}. "
                    f"Event impact score: {event.impact_score:.2f}. "
                    f"You have 30 days max lifespan. Be aggressive with high-conviction trades."
                ),
                virtual_capital=capital,
                domain=event.affected_assets[0] if event.affected_assets else "macro",
                temperature=0.4,
            )
            try:
                self.state_db.create_shadow(config)
                created_ids.append(shadow_id)
                logger.info("Created temp shadow %s for event %s", shadow_id, event.event_type)
            except ValueError:
                logger.warning("Temp shadow %s already exists", shadow_id)

        return created_ids

    def check_destruction_conditions(self, shadow_id: str) -> bool:
        """Check if a temporary shadow should be destroyed."""
        config = self.state_db.get_shadow(shadow_id)
        if config is None:
            return False
        if config.shadow_type != "temp_event":
            return False
        # Check max lifespan
        created = datetime.fromisoformat(config.created_at.replace("Z", "+00:00"))
        days_alive = (datetime.now(timezone.utc) - created).days
        if days_alive >= 30:
            return True
        # If shadow has been inactive (no snapshots or no trades)
        snapshots = self.state_db.get_snapshot_history(shadow_id, days=5)
        if len(snapshots) < 1:
            return False  # New shadow, not yet active
        # Check for 5+ no-trade days
        if days_alive >= 5 and len(snapshots) < days_alive:
            return True
        return False

    async def destroy_temp_shadow(self, shadow_id: str) -> None:
        """Destroy shadow, archive knowledge, notify relevant expert shadows."""
        self.state_db.eliminate_shadow(shadow_id, "temp_shadow_expired")
        logger.info("Destroyed temp shadow %s", shadow_id)

    # ── Missed path shadows ──────────────────────────────────────────────

    async def create_missed_path_shadows(self, rejected_directions: list[str]) -> list[str]:
        """Gate 1: user chose direction A. Create missed_path shadows for B and C."""
        created_ids = []
        for i, direction in enumerate(rejected_directions[:self.config.missed_path_max_per_gate]):
            ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            shadow_id = f"missed_path:gate1:{ts}_{i}"
            config = ShadowConfig(
                shadow_id=shadow_id,
                shadow_type="missed_path",
                display_name=f"Missed Path {direction}",
                methodology_prompt=(
                    f"You are tracking the counterfactual path: {direction}. "
                    f"This path was rejected at Gate 1. You record what WOULD have happened "
                    f"if this direction was chosen. You do NOT generate investment votes. "
                    f"Track performance of this direction for {self.config.missed_path_report_days} days "
                    f"and report survivorship bias warning."
                ),
                virtual_capital=0.0,  # Read-only, no trading
                max_positions=0,
            )
            try:
                self.state_db.create_shadow(config)
                created_ids.append(shadow_id)
            except ValueError:
                pass
        return created_ids

    # ── Status cards ─────────────────────────────────────────────────────

    async def generate_status_cards(self, date: str) -> dict[str, dict]:
        """Generate today's status card for every active shadow."""
        cards = {}
        for shadow in self.state_db.get_visible_shadows():
            from projects.marketmind.shadows.shadow_agent import ShadowAgent
            agent = ShadowAgent(shadow, self.state_db, self.config)
            cards[shadow.shadow_id] = await agent.receive_status_card()
        return cards

    # ── Daily orchestration ──────────────────────────────────────────────

    async def orchestrate_daily_cycle(self, news_items: list[dict],
                                       market_data: dict,
                                       rejected_directions: list[str] | None = None
                                       ) -> ShadowOrchestrationResult:
        """Full daily cycle for the shadow ecosystem."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        result = ShadowOrchestrationResult(date=today)

        # 1. Scan events -> create/destroy temp shadows
        events = await self.scan_events(news_items)
        prioritized = self.prioritize_events(events)
        created = await self.create_temp_shadows(prioritized)
        result.temp_shadows_created = len(created)

        # Destroy expired temp shadows
        for shadow in self.state_db.get_active_shadows("temp_event"):
            if self.check_destruction_conditions(shadow.shadow_id):
                await self.destroy_temp_shadow(shadow.shadow_id)
                result.temp_shadows_destroyed += 1

        # 2. Create missed_path shadows
        if rejected_directions:
            await self.create_missed_path_shadows(rejected_directions)

        # 3. Count active shadows
        visible = self.state_db.get_visible_shadows()
        result.active_shadows = len(visible)

        return result

    # ── Queries ──────────────────────────────────────────────────────────

    def get_active_temp_shadows(self) -> list[str]:
        return [s.shadow_id for s in self.state_db.get_active_shadows("temp_event")]

    def get_event_status(self, event_id: str) -> str:
        """Returns "active" | "resolved" | "decayed" | "unknown"."""
        for shadow_id in self.get_active_temp_shadows():
            if event_id in shadow_id:
                shadow = self.state_db.get_shadow(shadow_id)
                if shadow is None:
                    return "resolved"
                created = datetime.fromisoformat(shadow.created_at.replace("Z", "+00:00"))
                days = (datetime.now(timezone.utc) - created).days
                if days > 20:
                    return "decayed"
                return "active"
        return "unknown"
