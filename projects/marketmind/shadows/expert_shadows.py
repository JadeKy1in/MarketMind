"""Expert shadows — 16 domain-specific analysts with structured vote output + factory.

Each expert uses indicator confirmation thresholds from the canonical design.
See .claude/research/shadow-ecosystem-full-design.md §1.1 for the source of truth.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from marketmind.shadows.shadow_agent import (
    ShadowAgent, ShadowAnalysisOutput, ShadowVote
)
from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.config.settings import ShadowSettings
from marketmind.config import load_shadow_prompts

logger = logging.getLogger("marketmind.shadows.expert_shadows")


def _load_prompts() -> dict:
    """Load expert prompts from JSON config. Falls back to macro-only if loading fails."""
    prompts = load_shadow_prompts()
    return prompts.get("expert", {"macro": "You are the Cycle Reader, a macro/cross-asset expert."})


_EXPERT_PROMPTS = _load_prompts()


class ExpertShadow(ShadowAgent):
    """Shadow with domain-specific methodology and independent analysis."""

    def __init__(self, config: ShadowConfig, state_db: ShadowStateDB,
                 settings: ShadowSettings):
        super().__init__(config, state_db, settings)
        self.methodology = _EXPERT_PROMPTS.get(
            config.domain or "macro",
            _EXPERT_PROMPTS["macro"]
        )

    @staticmethod
    def _safe_headline(item) -> str:
        """Extract headline from dict or object safely."""
        if hasattr(item, "get"):
            return str(item.get("headline", "") or item.get("title", ""))
        return str(getattr(item, "headline", None) or getattr(item, "title", None) or "")

    def _filter_news_by_domain(self, news_items: list) -> list:
        """Filter news headlines for domain relevance."""
        domain_keywords = {
            "gold": ["gold", "silver", "precious", "bullion", "GLD", "SLV", "GDX", "COMEX"],
            "crypto": ["bitcoin", "crypto", "blockchain", "ethereum", "BTC", "ETH", "DeFi"],
            "energy": ["oil", "crude", "OPEC", "energy", "gas", "petroleum", "USO", "XLE"],
            "bonds": ["treasury", "bond", "yield", "fed", "rate", "TLT", "credit"],
            "volatility": ["VIX", "vol", "volatility", "VXX", "SVOL", "implied"],
            "emerging": ["emerging", "EM", "China", "India", "Brazil", "EEM", "FXI"],
            "tech": ["tech", "AI", "software", "chip", "semiconductor", "QQQ", "SMH"],
            "financials": ["bank", "financial", "loan", "credit", "XLF", "KRE"],
            "healthcare": ["FDA", "drug", "trial", "health", "pharma", "XLV", "IBB"],
            "consumer": ["retail", "consumer", "sales", "sentiment", "XLY", "XRT"],
            "industrials": ["PMI", "manufacturing", "industrial", "factory", "XLI", "ITA"],
            "metals": ["steel", "copper", "iron", "LME", "mining", "DBB", "XME"],
            "real_estate": ["REIT", "real estate", "housing", "mortgage", "VNQ"],
            "fx": ["forex", "FX", "dollar", "euro", "yen", "carry", "UUP", "FXE"],
            "agriculture": ["agriculture", "grain", "wheat", "corn", "soybean",
                          "livestock", "fertilizer", "harvest", "DBA", "CORN",
                          "WEAT", "SOYB", "USDA", "crop", "coffee", "sugar",
                          "cotton", "cocoa", "农产品", "粮食", "农业"],
            "macro": [],  # Macro sees everything
        }
        keywords = domain_keywords.get(self.config.domain or "macro", [])
        if not keywords:
            return news_items
        filtered = []
        for item in news_items:
            headline = self._safe_headline(item).lower()
            if any(kw.lower() in headline for kw in keywords):
                filtered.append(item)
        # Return top 20 or all if fewer
        return filtered[:20] if filtered else news_items[:5]

    async def _analyze(self, news_items: list[dict],
                        market_data: dict) -> ShadowAnalysisOutput:
        """Domain-filtered analysis using the base LLM call."""
        filtered = self._filter_news_by_domain(news_items)
        return await super()._analyze(filtered, market_data)

    def _build_user_prompt(self, news_items: list[dict], market_data: dict) -> str:
        """Expert-specific prompt: domain context, structured vote expectations."""
        filtered = self._filter_news_by_domain(news_items)
        headlines = []
        for item in filtered[:20]:
            h = self._safe_headline(item)
            if h and h not in headlines:
                headlines.append(h[:200])
        news_context = "\n".join(f"- {h}" for h in headlines[:15]) if headlines else "No domain-relevant news"

        return (
            f"You are analyzing the {self.config.domain or 'macro'} domain.\n"
            f"Domain-relevant news ({len(filtered)} items from {len(news_items)} total):\n"
            f"{news_context}\n\n"
            f"Market context: {json.dumps(market_data) if market_data else 'None'}\n\n"
            f"Output your expert analysis using VOTE_START/VOTE_END blocks. "
            f"For each vote include: ticker, direction (long/short/abstain), "
            f"confidence (0.0-1.0), thesis (1 sentence), risk_note (1 sentence)."
        )

# _parse_votes() and _extract_field() inherited from ShadowAgent base class


# ── Pre-built expert shadow configurations ──────────────────────────────────

EXPERT_SHADOW_CONFIGS: list[ShadowConfig] = [
    ShadowConfig(shadow_id="expert:gold:bullion_broker", shadow_type="expert",
                 display_name="Bullion Broker", methodology_prompt=_EXPERT_PROMPTS["gold"],
                 virtual_capital=50000.0, domain="gold", temperature=0.3),
    ShadowConfig(shadow_id="expert:crypto:chain_oracle", shadow_type="expert",
                 display_name="Chain Oracle", methodology_prompt=_EXPERT_PROMPTS["crypto"],
                 virtual_capital=45000.0, domain="crypto", temperature=0.35),
    ShadowConfig(shadow_id="expert:energy:oil_geologist", shadow_type="expert",
                 display_name="Oil Geologist", methodology_prompt=_EXPERT_PROMPTS["energy"],
                 virtual_capital=50000.0, domain="energy", temperature=0.3),
    ShadowConfig(shadow_id="expert:bonds:yield_whisperer", shadow_type="expert",
                 display_name="Yield Whisperer", methodology_prompt=_EXPERT_PROMPTS["bonds"],
                 virtual_capital=55000.0, domain="bonds", temperature=0.3),
    ShadowConfig(shadow_id="expert:vol:vega_trader", shadow_type="expert",
                 display_name="Vega Trader", methodology_prompt=_EXPERT_PROMPTS["volatility"],
                 virtual_capital=40000.0, domain="volatility", temperature=0.4),
    ShadowConfig(shadow_id="expert:em:frontier_scout", shadow_type="expert",
                 display_name="Frontier Scout", methodology_prompt=_EXPERT_PROMPTS["emerging"],
                 virtual_capital=45000.0, domain="emerging", temperature=0.35),
    ShadowConfig(shadow_id="expert:tech:silicon_oracle", shadow_type="expert",
                 display_name="Silicon Oracle", methodology_prompt=_EXPERT_PROMPTS["tech"],
                 virtual_capital=50000.0, domain="tech", temperature=0.3),
    ShadowConfig(shadow_id="expert:financials:bank_examiner", shadow_type="expert",
                 display_name="Bank Examiner", methodology_prompt=_EXPERT_PROMPTS["financials"],
                 virtual_capital=48000.0, domain="financials", temperature=0.3),
    ShadowConfig(shadow_id="expert:healthcare:trial_reviewer", shadow_type="expert",
                 display_name="Trial Reviewer", methodology_prompt=_EXPERT_PROMPTS["healthcare"],
                 virtual_capital=48000.0, domain="healthcare", temperature=0.3),
    ShadowConfig(shadow_id="expert:consumer:wallet_watcher", shadow_type="expert",
                 display_name="Wallet Watcher", methodology_prompt=_EXPERT_PROMPTS["consumer"],
                 virtual_capital=46000.0, domain="consumer", temperature=0.3),
    ShadowConfig(shadow_id="expert:industrials:factory_floor", shadow_type="expert",
                 display_name="Factory Floor", methodology_prompt=_EXPERT_PROMPTS["industrials"],
                 virtual_capital=48000.0, domain="industrials", temperature=0.3),
    ShadowConfig(shadow_id="expert:metals:steel_trader", shadow_type="expert",
                 display_name="Steel Trader", methodology_prompt=_EXPERT_PROMPTS["metals"],
                 virtual_capital=42000.0, domain="metals", temperature=0.35),
    ShadowConfig(shadow_id="expert:agriculture:harvest_seer", shadow_type="expert",
                 display_name="Harvest Seer", methodology_prompt=_EXPERT_PROMPTS["agriculture"],
                 virtual_capital=42000.0, domain="agriculture", temperature=0.35),
    ShadowConfig(shadow_id="expert:realestate:reit_analyst", shadow_type="expert",
                 display_name="REIT Analyst", methodology_prompt=_EXPERT_PROMPTS["real_estate"],
                 virtual_capital=48000.0, domain="real_estate", temperature=0.3),
    ShadowConfig(shadow_id="expert:fx:currency_dealer", shadow_type="expert",
                 display_name="Currency Dealer", methodology_prompt=_EXPERT_PROMPTS["fx"],
                 virtual_capital=44000.0, domain="fx", temperature=0.35),
    ShadowConfig(shadow_id="expert:macro:cycle_reader", shadow_type="expert",
                 display_name="Cycle Reader", methodology_prompt=_EXPERT_PROMPTS["macro"],
                 virtual_capital=60000.0, domain="macro", temperature=0.3),
]


def create_expert_shadows(state_db: ShadowStateDB,
                           settings: ShadowSettings) -> list[ExpertShadow]:
    """Instantiate all 16 expert shadows from configs."""
    shadows = []
    for config in EXPERT_SHADOW_CONFIGS:
        # Register in DB if not exists
        if state_db.get_shadow(config.shadow_id) is None:
            state_db.create_shadow(config)
        shadows.append(ExpertShadow(config, state_db, settings))
    return shadows
