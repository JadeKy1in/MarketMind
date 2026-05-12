"""Expert shadows — domain-specific methodologies, structured vote output, factory."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from marketmind.shadows.shadow_agent import (
    ShadowAgent, ShadowAnalysisOutput, ShadowVote
)
from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.config.settings import ShadowSettings

logger = logging.getLogger("marketmind.shadows.expert_shadows")

# ── Expert methodology prompts (abbreviated; full prompts in .claude/methodology/B3_expert_prompts.md) ──

_DOMAIN_PROMPTS = {
    "gold": (
        "You are the Bullion Broker, an expert in precious metals. Analyze real rates, USD, "
        "central bank buying, COT positioning, ETF flows, physical premiums, mining costs, "
        "and silver industrial demand. Output VOTE_START/VOTE_END blocks for GLD, SLV, GDX."
    ),
    "crypto": (
        "You are the Chain Oracle, a cryptocurrency expert. Analyze on-chain metrics (hash rate, "
        "active addresses, exchange reserves), ETF flows, regulatory developments, halving cycles, "
        "stablecoin market caps, and DeFi TVL. Output votes for BTC, ETH, and major crypto assets."
    ),
    "energy": (
        "You are the Oil Geologist, an energy markets expert. Analyze OPEC+ decisions, crude "
        "inventories, rig counts, demand forecasts, refining spreads (crack spreads), VLCC rates, "
        "and natural gas storage. Output votes for USO, XLE, UNG."
    ),
    "bonds": (
        "You are the Yield Whisperer, a fixed income expert. Analyze yield curve shape (2s10s, 3m10y), "
        "breakeven inflation rates, Fed rhetoric/futures pricing, Treasury auction demand (bid-to-cover, "
        "tail), MOVE index, and corporate credit spreads. Output votes for TLT, IEF, LQD."
    ),
    "volatility": (
        "You are the Vega Trader, a volatility expert. Analyze VIX term structure (contango vs backwardation), "
        "SKEW index, VVIX (vol of vol), realized vs implied volatility gap, event premium, and "
        "volatility risk premium. Output votes for VXX, SVOL, or abstain when vol surface is fair."
    ),
    "emerging": (
        "You are the Frontier Scout, an emerging markets expert. Analyze DXY, EM bond spreads (EMBI), "
        "capital flow data (IIF), political risk indicators, current account balances, and "
        "commodity export/import profiles. Output votes for EEM, FXI, INDA."
    ),
    "tech": (
        "You are the Silicon Oracle, a technology sector expert. Analyze earnings momentum, "
        "AI capex trends, semiconductor supply chains, regulatory/antitrust developments, "
        "cloud spending growth, and ad market health. Output votes for QQQ, SMH, individual mega-cap tech."
    ),
    "financials": (
        "You are the Bank Examiner, a financial sector expert. Analyze yield curve steepness, "
        "loan growth trends, credit quality (NCO rates, provisions), regulatory capital requirements, "
        "and M&A activity. Output votes for XLF, KRE, individual money-center banks."
    ),
    "healthcare": (
        "You are the Trial Reviewer, a healthcare sector expert. Analyze FDA approval calendar, "
        "clinical trial results, drug pricing policy developments, demographic trends, and "
        "healthcare utilization rates. Output votes for XLV, IBB, major pharma tickers."
    ),
    "consumer": (
        "You are the Wallet Watcher, a consumer sector expert. Analyze retail sales trends, "
        "consumer confidence/sentiment, credit card spending data, wage growth, savings rate, "
        "and housing affordability. Output votes for XLY, XRT, consumer discretionary names."
    ),
    "industrials": (
        "You are the Factory Floor foreman, an industrials expert. Analyze PMI (ISM/global), "
        "durable goods orders, infrastructure spending bills, trade policy/tariffs, and "
        "transportation indices (Dow Transport, Cass Freight). Output votes for XLI, ITA, CAT."
    ),
    "metals": (
        "You are the Steel Trader, an industrial metals expert. Analyze China demand indicators, "
        "infrastructure spending, EV adoption rates, supply disruption events, LME inventory levels, "
        "and iron ore prices. Output votes for DBB, XME, FCX."
    ),
    "real_estate": (
        "You are the REIT Analyst, a real estate expert. Analyze interest rates, occupancy rates "
        "by sector, cap rate spreads, CMBS issuance, housing starts/existing home sales, and "
        "mortgage rates. Output votes for VNQ, XLRE, individual REITs."
    ),
    "fx": (
        "You are the Currency Dealer, an FX/carry trade expert. Analyze rate differentials, "
        "carry-to-risk ratios, purchasing power parity deviations, central bank intervention risk, "
        "and current account balances. Output votes for UUP, FXE, FXY carry pairs."
    ),
    "macro": (
        "You are the Cycle Reader, a macro/cross-asset expert. Analyze the growth-inflation quadrant, "
        "regime detection, risk appetite indicators, global PMI momentum, financial conditions indices, "
        "and central bank policy divergence. Output multi-asset allocation votes."
    ),
}


class ExpertShadow(ShadowAgent):
    """Shadow with domain-specific methodology and independent analysis."""

    def __init__(self, config: ShadowConfig, state_db: ShadowStateDB,
                 settings: ShadowSettings):
        super().__init__(config, state_db, settings)
        self.methodology = _DOMAIN_PROMPTS.get(
            config.domain or "macro",
            _DOMAIN_PROMPTS["macro"]
        )

    def _filter_news_by_domain(self, news_items: list[dict]) -> list[dict]:
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
            "macro": [],  # Macro sees everything
        }
        keywords = domain_keywords.get(self.config.domain or "macro", [])
        if not keywords:
            return news_items
        filtered = []
        for item in news_items:
            headline = str(item.get("headline", "")).lower()
            if any(kw.lower() in headline for kw in keywords):
                filtered.append(item)
        # Return top 20 or all if fewer
        return filtered[:20] if filtered else news_items[:5]

    async def _analyze(self, news_items: list[dict],
                        market_data: dict) -> ShadowAnalysisOutput:
        """Filter news by domain relevance, call Flash with methodology prompt,
        parse structured output into votes."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filtered = self._filter_news_by_domain(news_items)

        # In production, this would call the LLM gateway (flash client)
        # For now, produce a well-formed no-vote output
        headlines = [item.get("headline", "")[:120] for item in filtered[:10]]
        news_context = "\n".join(f"- {h}" for h in headlines) if headlines else "No domain-relevant news"

        # Parse VOTE_START/VOTE_END blocks from analysis (simulated)
        votes = self._parse_votes(
            f"Domain: {self.config.domain}. News: {news_context}. "
            f"No actionable signal detected for today."
        )

        return ShadowAnalysisOutput(
            shadow_id=self.shadow_id,
            date=today,
            votes=votes,
            insights=[f"Domain scan: {len(filtered)} relevant items from {len(news_items)} total"],
            methodology_notes=self.methodology[:200],
            quota_used=1,
        )

    @staticmethod
    def _parse_votes(text: str) -> list[ShadowVote]:
        """Parse VOTE_START/VOTE_END blocks from LLM output."""
        votes = []
        pattern = re.compile(
            r'VOTE_START\s*\n(.*?)\nVOTE_END',
            re.DOTALL
        )
        for match in pattern.finditer(text):
            block = match.group(1)
            ticker = _extract_field(block, "ticker")
            direction = _extract_field(block, "direction")
            confidence = float(_extract_field(block, "confidence") or 0.5)
            thesis = _extract_field(block, "thesis") or ""
            risk = _extract_field(block, "risk_note") or ""
            if ticker and direction:
                votes.append(ShadowVote(
                    shadow_id="", shadow_type="expert",
                    date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    ticker=ticker, direction=direction,
                    confidence=min(max(confidence, 0.0), 1.0),
                    thesis=thesis[:200], risk_note=risk[:200],
                    emergency_flag=confidence >= 0.8,
                ))
        return votes


def _extract_field(block: str, field: str) -> str | None:
    match = re.search(rf'{field}:\s*(.+)', block, re.IGNORECASE)
    return match.group(1).strip() if match else None


# ── Pre-built expert shadow configurations ──────────────────────────────────

EXPERT_SHADOW_CONFIGS: list[ShadowConfig] = [
    ShadowConfig(shadow_id="expert:gold:bullion_broker", shadow_type="expert",
                 display_name="Bullion Broker", methodology_prompt=_DOMAIN_PROMPTS["gold"],
                 virtual_capital=50000.0, domain="gold", temperature=0.3),
    ShadowConfig(shadow_id="expert:crypto:chain_oracle", shadow_type="expert",
                 display_name="Chain Oracle", methodology_prompt=_DOMAIN_PROMPTS["crypto"],
                 virtual_capital=45000.0, domain="crypto", temperature=0.35),
    ShadowConfig(shadow_id="expert:energy:oil_geologist", shadow_type="expert",
                 display_name="Oil Geologist", methodology_prompt=_DOMAIN_PROMPTS["energy"],
                 virtual_capital=50000.0, domain="energy", temperature=0.3),
    ShadowConfig(shadow_id="expert:bonds:yield_whisperer", shadow_type="expert",
                 display_name="Yield Whisperer", methodology_prompt=_DOMAIN_PROMPTS["bonds"],
                 virtual_capital=55000.0, domain="bonds", temperature=0.3),
    ShadowConfig(shadow_id="expert:vol:vega_trader", shadow_type="expert",
                 display_name="Vega Trader", methodology_prompt=_DOMAIN_PROMPTS["volatility"],
                 virtual_capital=40000.0, domain="volatility", temperature=0.4),
    ShadowConfig(shadow_id="expert:em:frontier_scout", shadow_type="expert",
                 display_name="Frontier Scout", methodology_prompt=_DOMAIN_PROMPTS["emerging"],
                 virtual_capital=45000.0, domain="emerging", temperature=0.35),
    ShadowConfig(shadow_id="expert:tech:silicon_oracle", shadow_type="expert",
                 display_name="Silicon Oracle", methodology_prompt=_DOMAIN_PROMPTS["tech"],
                 virtual_capital=50000.0, domain="tech", temperature=0.3),
    ShadowConfig(shadow_id="expert:financials:bank_examiner", shadow_type="expert",
                 display_name="Bank Examiner", methodology_prompt=_DOMAIN_PROMPTS["financials"],
                 virtual_capital=48000.0, domain="financials", temperature=0.3),
    ShadowConfig(shadow_id="expert:healthcare:trial_reviewer", shadow_type="expert",
                 display_name="Trial Reviewer", methodology_prompt=_DOMAIN_PROMPTS["healthcare"],
                 virtual_capital=48000.0, domain="healthcare", temperature=0.3),
    ShadowConfig(shadow_id="expert:consumer:wallet_watcher", shadow_type="expert",
                 display_name="Wallet Watcher", methodology_prompt=_DOMAIN_PROMPTS["consumer"],
                 virtual_capital=46000.0, domain="consumer", temperature=0.3),
    ShadowConfig(shadow_id="expert:industrials:factory_floor", shadow_type="expert",
                 display_name="Factory Floor", methodology_prompt=_DOMAIN_PROMPTS["industrials"],
                 virtual_capital=48000.0, domain="industrials", temperature=0.3),
    ShadowConfig(shadow_id="expert:metals:steel_trader", shadow_type="expert",
                 display_name="Steel Trader", methodology_prompt=_DOMAIN_PROMPTS["metals"],
                 virtual_capital=42000.0, domain="metals", temperature=0.35),
    ShadowConfig(shadow_id="expert:realestate:reit_analyst", shadow_type="expert",
                 display_name="REIT Analyst", methodology_prompt=_DOMAIN_PROMPTS["real_estate"],
                 virtual_capital=48000.0, domain="real_estate", temperature=0.3),
    ShadowConfig(shadow_id="expert:fx:currency_dealer", shadow_type="expert",
                 display_name="Currency Dealer", methodology_prompt=_DOMAIN_PROMPTS["fx"],
                 virtual_capital=44000.0, domain="fx", temperature=0.35),
    ShadowConfig(shadow_id="expert:macro:cycle_reader", shadow_type="expert",
                 display_name="Cycle Reader", methodology_prompt=_DOMAIN_PROMPTS["macro"],
                 virtual_capital=60000.0, domain="macro", temperature=0.3),
]


def create_expert_shadows(state_db: ShadowStateDB,
                           settings: ShadowSettings) -> list[ExpertShadow]:
    """Instantiate all 15 expert shadows from configs."""
    shadows = []
    for config in EXPERT_SHADOW_CONFIGS:
        # Register in DB if not exists
        if state_db.get_shadow(config.shadow_id) is None:
            state_db.create_shadow(config)
        shadows.append(ExpertShadow(config, state_db, settings))
    return shadows
