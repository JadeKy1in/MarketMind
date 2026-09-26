"""Main AI Domain Benchmark — track main AI recommendations by domain (Phase 1).

Classifies every main AI investment recommendation into a domain, tracks its
outcome, and builds a per-domain performance baseline. Expert shadows must
statistically outperform main AI in their domain to qualify for promotion.

Minimum N records required per domain before comparison.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("marketmind.shadows.main_ai_benchmark")


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class DomainRecommendation:
    """A single main AI recommendation, filed by domain."""
    rec_id: str
    date: str
    ticker: str
    direction: str           # "long" | "short"
    domain: str              # assigned domain classification
    recommended_price: float
    target_price: float | None = None
    outcome_pnl_pct: float | None = None    # resolved PnL (None if still tracking)
    resolved_date: str | None = None
    adopted: bool = False    # did user actually follow this recommendation?
    notes: str = ""


@dataclass
class DomainPerformance:
    """Aggregate main AI performance in one domain."""
    domain: str
    total_recommendations: int = 0
    adopted_recommendations: int = 0
    profitable_recommendations: int = 0
    cumulative_pnl_pct: float = 0.0
    win_rate: float = 0.0
    avg_return: float = 0.0
    last_updated: str = ""


# ── Domain classification ───────────────────────────────────────────────────

# Map tickers and keywords to domains
DOMAIN_CLASSIFIER: dict[str, list[str]] = {
    "tech": ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "QQQ", "SMH", "SOXX",
             "chip", "semiconductor", "AI", "software", "cloud", "SaaS", "tech"],
    "gold": ["GLD", "IAU", "SLV", "GDX", "GDXJ", "gold", "silver", "precious", "bullion", "COMEX"],
    "crypto": ["IBIT", "FBTC", "ETHA", "BTC", "ETH", "bitcoin", "crypto", "blockchain", "DeFi"],
    "energy": ["XLE", "USO", "DBC", "XOP", "oil", "crude", "OPEC", "energy", "gas", "petroleum"],
    "bonds": ["TLT", "IEF", "SHY", "HYG", "LQD", "treasury", "bond", "yield", "fed", "rate"],
    "financials": ["XLF", "KRE", "JPM", "BAC", "GS", "MS", "bank", "financial", "loan", "credit"],
    "healthcare": ["XLV", "IBB", "JNJ", "PFE", "UNH", "FDA", "drug", "trial", "pharma"],
    "consumer": ["XLY", "XRT", "WMT", "retail", "consumer", "sales", "sentiment"],
    "industrials": ["XLI", "ITA", "CAT", "DE", "PMI", "manufacturing", "industrial", "factory"],
    "real_estate": ["VNQ", "REIT", "real estate", "housing", "mortgage"],
    "emerging": ["EEM", "FXI", "emerging", "EM", "China", "India", "Brazil"],
    "volatility": ["VIX", "VXX", "SVOL", "UVXY", "vol", "volatility", "implied"],
    "macro": ["SPY", "DIA", "IWM", "UUP", "FXE", "macro", "GDP", "CPI", "inflation"],
}


class MainAIBenchmark:
    """Tracks and compares main AI performance by domain."""

    MIN_COMPARISON_RECORDS = 10  # minimum records before shadow can challenge

    def __init__(self):
        self._recommendations: list[DomainRecommendation] = []

    def classify_domain(self, ticker: str, context: str = "") -> str:
        """Assign a recommendation to the best-matching domain."""
        scores = defaultdict(int)
        ticker_up = ticker.upper()
        context_lower = context.lower() if context else ""

        for domain, keywords in DOMAIN_CLASSIFIER.items():
            if ticker_up in keywords:
                scores[domain] += 3
            for kw in keywords:
                if kw in context_lower:
                    scores[domain] += 1

        # Tie-breaking: prefer the domain with stronger keyword evidence,
        # then fall back to ordering in DOMAIN_CLASSIFIER
        if scores:
            best_domain = max(scores, key=lambda k: (scores[k], -list(DOMAIN_CLASSIFIER.keys()).index(k)))
            return best_domain
        return "macro"  # default fallback

    def record_recommendation(
        self,
        ticker: str,
        direction: str,
        price: float,
        target_price: float | None = None,
        context: str = "",
        adopted: bool = False,
    ) -> DomainRecommendation:
        """Record a main AI recommendation for future tracking."""
        domain = self.classify_domain(ticker, context)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rec = DomainRecommendation(
            rec_id=f"main_ai:{domain}:{ticker}:{today}",
            date=today,
            ticker=ticker,
            direction=direction,
            domain=domain,
            recommended_price=price,
            target_price=target_price,
            adopted=adopted,
            notes=context[:200],
        )
        self._recommendations.append(rec)
        logger.info("Main AI benchmark: recorded %s %s → %s", ticker, direction, domain)
        return rec

    def resolve_recommendation(
        self, rec_id: str, current_price: float, resolved_date: str | None = None
    ) -> float | None:
        """Resolve a recommendation's PnL based on current price.

        Returns the PnL percentage, or None if recommendation not found.
        """
        for rec in self._recommendations:
            if rec.rec_id == rec_id:
                if rec.direction == "long":
                    pnl = (current_price - rec.recommended_price) / rec.recommended_price
                else:
                    pnl = (rec.recommended_price - current_price) / rec.recommended_price
                rec.outcome_pnl_pct = pnl
                rec.resolved_date = resolved_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
                return pnl
        return None

    def get_domain_performance(self) -> dict[str, DomainPerformance]:
        """Compute per-domain performance from resolved recommendations."""
        perf_map: dict[str, DomainPerformance] = {}

        for rec in self._recommendations:
            if rec.outcome_pnl_pct is None:
                continue  # skip unresolved

            if rec.domain not in perf_map:
                perf_map[rec.domain] = DomainPerformance(domain=rec.domain)

            dp = perf_map[rec.domain]
            dp.total_recommendations += 1
            if rec.adopted:
                dp.adopted_recommendations += 1
            if rec.outcome_pnl_pct > 0:
                dp.profitable_recommendations += 1
            dp.cumulative_pnl_pct += rec.outcome_pnl_pct

        for dp in perf_map.values():
            dp.win_rate = dp.profitable_recommendations / max(dp.total_recommendations, 1)
            dp.avg_return = dp.cumulative_pnl_pct / max(dp.total_recommendations, 1)
            dp.last_updated = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        return perf_map

    def can_compare(self, domain: str) -> bool:
        """Check if main AI has enough records in a domain for comparison."""
        perf = self.get_domain_performance()
        if domain not in perf:
            return False
        return perf[domain].total_recommendations >= self.MIN_COMPARISON_RECORDS

    def compare_shadow_to_main_ai(
        self, domain: str, shadow_win_rate: float, shadow_total_trades: int
    ) -> dict:
        """Compare a shadow's performance to main AI in the same domain.

        Returns a dict with comparison results for promotion gating.
        """
        perf = self.get_domain_performance()
        if domain not in perf:
            return {"eligible": False, "reason": f"No main AI data for domain '{domain}'",
                    "main_ai_wr": 0.0, "main_ai_trades": 0}

        dp = perf[domain]
        if dp.total_recommendations < self.MIN_COMPARISON_RECORDS:
            return {"eligible": False,
                    "reason": f"Main AI has only {dp.total_recommendations} records "
                              f"(need {self.MIN_COMPARISON_RECORDS})",
                    "main_ai_wr": dp.win_rate, "main_ai_trades": dp.total_recommendations}

        wr_diff = shadow_win_rate - dp.win_rate
        eligible = shadow_win_rate > dp.win_rate and shadow_total_trades >= self.MIN_COMPARISON_RECORDS

        return {
            "eligible": eligible,
            "reason": (f"Shadow WR {shadow_win_rate:.1%} {'>' if eligible else '<='} "
                       f"Main AI {dp.win_rate:.1%}") if not eligible or True else "",
            "main_ai_wr": dp.win_rate,
            "main_ai_trades": dp.total_recommendations,
            "wr_difference": wr_diff,
            "main_ai_cumulative_pnl": dp.cumulative_pnl_pct,
        }
