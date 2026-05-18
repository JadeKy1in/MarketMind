"""Ecosystem Auditor — blind-spot detection across the shadow ecosystem (Phase 0).

# ECOSYSTEM AUDITOR — NOT A SHADOW. Reads shadow output, does not produce votes.

Replaces CatfishAgent. This is a MECHANISM, not a shadow. It scans all shadow
votes daily for structural blind spots: direction concentration, asset class
neglect, methodology convergence, uncovered tickers. Pure Python compute with
Pro interpretation only when thresholds are breached.

Input: all shadow votes + positions
Output: <=5 blind-spot alerts surfaced in Gate 2.
Detection categories: direction concentration, asset class neglect,
  methodology convergence, uncovered tickers
Python computes metrics -> Pro interprets ONLY when threshold triggered.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("marketmind.shadows.ecosystem_auditor")


@dataclass
class EcosystemAlert:
    alert_id: str
    category: str           # "direction_concentration" | "asset_class_neglect"
                            # | "methodology_convergence" | "uncovered_tickers"
    severity: str           # "info" | "warning" | "critical"
    title: str
    detail: str
    affected_shadows: list[str] = field(default_factory=list)
    date: str = ""


class EcosystemAuditor:
    """Daily blind-spot scanner over all shadow votes."""

    # Direction concentration: alert if >= threshold of all votes lean one way
    DIRECTION_CONCENTRATION_THRESHOLD = 0.80
    MIN_VOTES_FOR_CHECK = 8

    # Asset class neglect: alert if a major class has zero coverage
    ASSET_CLASS_MAP = {
        "equity_us": ["SPY", "QQQ", "IWM", "DIA", "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"],
        "equity_sector": ["XLF", "XLK", "XLV", "XLE", "XLI", "XLP", "XLU", "XLB"],
        "bonds": ["TLT", "IEF", "SHY", "HYG", "LQD"],
        "commodities": ["GLD", "IAU", "SLV", "USO", "DBC"],
        "crypto": ["IBIT", "FBTC", "ETHA"],
        "leveraged": ["TQQQ", "SQQQ", "SOXL", "SOXS", "UCO", "SCO"],
        "safe_haven": ["UUP", "FXE", "SHV", "BIL"],
    }

    # Top market-cap tickers to check for coverage gaps
    TOP_COVERAGE_TICKERS = [
        "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA",
        "BRK.B", "JPM", "V", "JNJ", "WMT", "PG", "MA", "UNH",
        "HD", "BAC", "DIS", "NFLX", "ADBE",
    ]
    COVERAGE_MIN_VOTES = 1

    def __init__(self):
        self._daily_alerts: list[EcosystemAlert] = []

    def run_audit(self, votes: list, date: str | None = None) -> list[EcosystemAlert]:
        """Run all blind-spot checks over today's votes. Returns alerts."""
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        self._daily_alerts = []

        if not votes:
            return []

        # 1. Direction concentration
        self._check_direction_concentration(votes, date)

        # 2. Asset class neglect
        self._check_asset_class_neglect(votes, date)

        # 3. Methodology convergence (lightweight: ticker overlap)
        self._check_ticker_convergence(votes, date)

        # 4. Uncovered major tickers
        self._check_uncovered_tickers(votes, date)

        return self._daily_alerts

    # ── Check implementations ───────────────────────────────────────────

    def _check_direction_concentration(self, votes: list, date: str) -> None:
        """Alert if most votes lean in one direction."""
        if len(votes) < self.MIN_VOTES_FOR_CHECK:
            return

        counts = Counter(v.direction for v in votes if v.direction != "abstain")
        total = sum(counts.values())
        if total == 0:
            return

        max_dir, max_count = counts.most_common(1)[0]
        ratio = max_count / total

        if ratio >= self.DIRECTION_CONCENTRATION_THRESHOLD:
            severity = "critical" if ratio >= 0.95 else "warning"
            self._daily_alerts.append(EcosystemAlert(
                alert_id=f"direction_{date}",
                category="direction_concentration",
                severity=severity,
                title=f"Direction Concentration: {ratio:.0%} {max_dir}",
                detail=(
                    f"{max_count}/{total} votes ({ratio:.1%}) lean {max_dir}. "
                    f"No meaningful counter-balance in the ecosystem. "
                    f"If this persists, shadows may be herding rather than reasoning independently."
                ),
                date=date,
            ))

    def _check_asset_class_neglect(self, votes: list, date: str) -> None:
        """Alert if a major asset class has no votes."""
        voted_tickers = {v.ticker for v in votes if v.ticker}
        neglected = []

        for class_name, tickers in self.ASSET_CLASS_MAP.items():
            if not voted_tickers & set(tickers):
                neglected.append(class_name)

        if neglected:
            self._daily_alerts.append(EcosystemAlert(
                alert_id=f"asset_neglect_{date}",
                category="asset_class_neglect",
                severity="warning",
                title=f"Asset Class Neglect: {len(neglected)} classes uncovered",
                detail=(
                    f"No shadow voted on: {', '.join(neglected)}. "
                    f"These asset classes may have signals the ecosystem is missing."
                ),
                date=date,
            ))

    def _check_ticker_convergence(self, votes: list, date: str) -> None:
        """Alert if too many shadows converge on same narrow set of tickers."""
        ticker_counts = Counter(v.ticker for v in votes if v.ticker)
        if not ticker_counts:
            return

        # Top 3 tickers capture what fraction of all votes?
        top3 = sum(c for _, c in ticker_counts.most_common(3))
        total = sum(ticker_counts.values())
        top3_ratio = top3 / total if total > 0 else 0

        if top3_ratio >= 0.60:
            top_tickers = [t for t, _ in ticker_counts.most_common(3)]
            self._daily_alerts.append(EcosystemAlert(
                alert_id=f"convergence_{date}",
                category="methodology_convergence",
                severity="info",
                title=f"Ticker Concentration: {top3_ratio:.0%} on {', '.join(top_tickers)}",
                detail=(
                    f"Top 3 tickers ({', '.join(top_tickers)}) capture "
                    f"{top3}/{total} votes ({top3_ratio:.1%}). "
                    f"Shadows may be anchoring on the same obvious plays."
                ),
                date=date,
            ))

    def _check_uncovered_tickers(self, votes: list, date: str) -> None:
        """Alert if major market-cap tickers have zero shadow attention."""
        voted_tickers = {v.ticker for v in votes if v.ticker}
        uncovered = [
            t for t in self.TOP_COVERAGE_TICKERS
            if t not in voted_tickers
        ]

        if len(uncovered) >= 5:
            self._daily_alerts.append(EcosystemAlert(
                alert_id=f"uncovered_{date}",
                category="uncovered_tickers",
                severity="info",
                title=f"Uncovered Tickers: {len(uncovered)} major stocks ignored",
                detail=(
                    f"No shadow voted on: {', '.join(uncovered[:8])}"
                    f"{'...' if len(uncovered) > 8 else ''}. "
                    f"These are top market-cap stocks. Are shadows missing signals?"
                ),
                date=date,
            ))

    # ── Pro interpretation (called externally when alerts present) ──────

    async def interpret_alerts(
        self, alerts: list[EcosystemAlert], market_data: dict | None = None
    ) -> str:
        """Use Pro to interpret alerts and provide actionable insight.
        Only called when alerts are present (threshold breached).
        """
        from marketmind.gateway.async_client import chat_with_integrity

        alert_text = "\n".join(
            f"- [{a.severity}] {a.category}: {a.title}\n  {a.detail}"
            for a in alerts[:5]
        )

        system_prompt = (
            "You are the Ecosystem Auditor for a multi-shadow investment analysis system. "
            "Your role: interpret blind-spot alerts and provide CONCISE, ACTIONABLE insight. "
            "Focus on: (1) Is this a genuine structural blind spot or normal market behavior? "
            "(2) What specific action should the user take? "
            "Keep output under 150 words. Be direct."
        )

        user_prompt = (
            f"Today's ecosystem alerts:\n{alert_text}\n\n"
            f"Market context: {market_data or 'Not provided'}\n\n"
            f"Provide a brief interpretation and recommended action."
        )

        try:
            result = await chat_with_integrity(
                model="pro",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                caller_agent="ecosystem_auditor",
                temperature=0.3,
                reasoning_effort="low",
            )
            return result.get("content", "")
        except Exception as e:
            logger.error("Pro interpretation failed: %s", e)
            return ""
