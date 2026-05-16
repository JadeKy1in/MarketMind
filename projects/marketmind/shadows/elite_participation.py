"""ELITE Shadow Participation — domain-triggered awakening for Gate 2 (Phase 5).

ELITE-tier shadows can contribute opinions during user-main AI discussions
when their domain is activated. They analyze daily news at the same time as
the main AI, wait to be "awakened" by user mention or domain trigger, and
contribute analysis but NO decision authority.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger("marketmind.shadows.elite_participation")


@dataclass
class EliteContribution:
    """An ELITE shadow's opinion contribution for Gate 2 display."""
    shadow_id: str
    shadow_name: str
    domain: str
    trigger_type: str       # "user_mention" | "domain_match"
    opinion: str            # the shadow's contributed analysis
    confidence: float
    timestamp: str = ""


class EliteRegistry:
    """Manages ELITE shadow availability and domain-triggered participation.

    ELITE shadows analyze news in parallel with the main AI (same daily
    cycle). After analysis, they wait passively. When a user discusses a
    topic or mentions a shadow name, the registry checks for matching
    ELITE shadows and surfaces their pre-computed opinions.

    Constraints:
    - Each ELITE shadow contributes at most ONCE per Gate 2 session
    - Contributions are clearly marked "SHADOW OPINION" (not main AI)
    - ELITE shadows have NO decision authority
    """

    # Domain keyword mapping for auto-trigger (same as expert shadow domains)
    DOMAIN_KEYWORDS = {
        "gold": ["gold", "silver", "precious", "GLD", "SLV", "bullion"],
        "crypto": ["bitcoin", "crypto", "ethereum", "BTC", "ETH", "DeFi", "blockchain"],
        "energy": ["oil", "crude", "OPEC", "energy", "gas", "XLE", "USO"],
        "bonds": ["treasury", "bond", "yield", "fed", "rate", "TLT", "credit"],
        "volatility": ["VIX", "vol", "volatility", "VXX", "implied"],
        "emerging": ["emerging", "EM", "China", "India", "Brazil", "EEM", "FXI"],
        "tech": ["tech", "AI", "software", "chip", "semiconductor", "QQQ", "SMH",
                "NVDA", "AAPL", "MSFT"],
        "financials": ["bank", "financial", "loan", "credit", "XLF"],
        "healthcare": ["FDA", "drug", "trial", "pharma", "XLV", "JNJ", "PFE"],
        "consumer": ["retail", "consumer", "sales", "XLY", "XRT"],
        "industrials": ["PMI", "manufacturing", "industrial", "XLI"],
        "macro": ["SPY", "macro", "GDP", "CPI", "inflation", "recession", "growth"],
        "metals": ["steel", "copper", "iron", "mining", "DBB", "XME"],
        "real_estate": ["REIT", "real estate", "housing", "mortgage", "VNQ"],
        "fx": ["forex", "FX", "dollar", "euro", "yen", "UUP", "FXE", "carry"],
        "short": ["short", "bear", "overvalued", "downturn", "crash", "correction",
                  "put/call", "short interest", "insider selling", "breakdown"],
    }

    def __init__(self):
        self._contributions: dict[str, EliteContribution] = {}
        self._awakened: set[str] = set()  # shadows that already contributed this session

    def register_shadow_analysis(
        self, shadow_id: str, shadow_name: str, domain: str,
        analysis_text: str, confidence: float
    ) -> None:
        """Register an ELITE shadow's pre-computed analysis for potential awakening."""
        self._contributions[shadow_id] = EliteContribution(
            shadow_id=shadow_id,
            shadow_name=shadow_name,
            domain=domain,
            trigger_type="domain_match",
            opinion=analysis_text[:500],
            confidence=confidence,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def detect_domain_trigger(self, user_text: str) -> list[str]:
        """Detect which domains are mentioned in user discussion text.

        Returns list of domain names that match.
        """
        text_lower = user_text.lower()
        matched = []
        for domain, keywords in self.DOMAIN_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in text_lower:
                    matched.append(domain)
                    break
        return matched

    def detect_shadow_mention(self, user_text: str, elite_shadows: dict[str, str]) -> str | None:
        """Check if user mentioned a specific ELITE shadow by name.

        Args:
            user_text: User's message text
            elite_shadows: {shadow_id: display_name} mapping

        Returns shadow_id if mentioned, None otherwise.
        """
        text_lower = user_text.lower()
        for sid, name in elite_shadows.items():
            if name.lower() in text_lower:
                return sid
        return None

    def get_eligible_contributors(
        self, triggered_domains: list[str], elite_shadows: dict[str, str]
    ) -> list[dict]:
        """Get list of ELITE shadows eligible to contribute based on domain match.

        Returns list of {shadow_id, shadow_name, domain} dicts.
        Shadows that already contributed this session are excluded.
        """
        eligible = []
        for domain in triggered_domains:
            for sid in elite_shadows:
                if sid in self._awakened:
                    continue
                if sid in self._contributions:
                    contrib = self._contributions[sid]
                    if contrib.domain == domain:
                        eligible.append({
                            "shadow_id": sid,
                            "shadow_name": contrib.shadow_name,
                            "domain": domain,
                        })
        return eligible

    def awaken_shadow(self, shadow_id: str) -> EliteContribution | None:
        """Awaken an ELITE shadow to contribute its pre-computed opinion.

        Marks shadow as awakened for this session (max once per session).
        Returns the contribution or None if shadow not found or already awakened.
        """
        if shadow_id in self._awakened:
            return None
        if shadow_id not in self._contributions:
            return None

        self._awakened.add(shadow_id)
        contrib = self._contributions[shadow_id]
        contrib.trigger_type = "user_mention" if shadow_id else "domain_match"
        return contrib

    def reset_session(self) -> None:
        """Reset the session — all shadows can contribute again in next session."""
        self._awakened.clear()
        self._contributions.clear()
