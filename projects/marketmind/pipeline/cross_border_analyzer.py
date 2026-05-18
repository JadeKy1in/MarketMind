"""Cross-border capital flow analyzer — heuristics over LLM, HTTP-only (free data sources).

Analyzes TIC flows, BIS banking flows, and cross-currency basis for unusual patterns.
Graceful degradation: UNAVAILABLE → PARTIAL → DEGRADED → FULL quality spectrum.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import mean, stdev

from marketmind.gateway.cross_border import (
    TICFlowData,
    BISBankingFlow,
    CrossCurrencyBasis,
    fetch_tic_data,
    fetch_bis_banking_flows,
    fetch_cross_currency_basis,
)

logger = logging.getLogger("marketmind.pipeline.cross_border_analyzer")

# Heuristic thresholds
_CAYMAN_FLOW_THRESHOLD_USD_BN = 10.0       # Large single-month Cayman flow (absolute)
_BASIS_2SIGMA_MULTIPLIER = 2.0             # Basis widening beyond 2σ triggers alert
_TREASURY_SUDDEN_STOP_THRESHOLD = -20.0    # Month-over-month drop > $20B in official purchases

# Countries commonly associated with hedge fund domicile flows
_HEDGE_FUND_DOMICILES = {
    "cayman islands", "bermuda", "british virgin islands", "bvi",
    "ireland", "luxembourg", "jersey", "guernsey",
}

# Countries associated with official/reserve Treasury holdings
_OFFICIAL_HOLDERS = {
    "china", "japan", "united kingdom", "brazil", "switzerland",
    "saudi arabia", "india", "taiwan", "hong kong", "singapore",
    "south korea", "norway",
}


@dataclass
class CrossBorderFlowReport:
    flows: list = field(default_factory=list)
    ccb_alerts: list[str] = field(default_factory=list)
    unusual_patterns: list[str] = field(default_factory=list)
    fima_usage: dict = field(default_factory=dict)
    summary: str = ""
    data_quality: str = "UNAVAILABLE"


async def analyze_cross_border_flows(
    hypothesis_text: str,
    affected_countries: list[str] | None = None,
) -> CrossBorderFlowReport:
    """Analyze cross-border capital flows for hypothesis-relevant patterns.

    Args:
        hypothesis_text: The investment hypothesis being evaluated.
        affected_countries: Countries relevant to the hypothesis (used for CCB check).

    Returns:
        CrossBorderFlowReport with flows, alerts, patterns, and data quality.
    """
    report = CrossBorderFlowReport()
    sources_available = 0
    sources_attempted = 0

    # 1. Fetch TIC data
    sources_attempted += 1
    try:
        tic_data = await fetch_tic_data()
        if tic_data:
            sources_available += 1
            report.flows.extend(tic_data)
            _check_tic_patterns(tic_data, report)
            _check_fima_usage(tic_data, report)
    except Exception as e:
        logger.warning("TIC fetch exception in analyzer: %s", e)

    # 2. Fetch BIS banking flows
    sources_attempted += 1
    try:
        bis_data = await fetch_bis_banking_flows()
        if bis_data:
            sources_available += 1
            report.flows.extend(bis_data)
    except Exception as e:
        logger.warning("BIS fetch exception in analyzer: %s", e)

    # 3. Cross-currency basis for affected countries
    ccb_pairs = _pairs_for_countries(affected_countries or [])
    for pair in ccb_pairs:
        sources_attempted += 1
        try:
            basis = await fetch_cross_currency_basis(pair)
            if basis is not None:
                sources_available += 1
                _check_basis_anomaly(basis, report)
        except Exception as e:
            logger.warning("CCB fetch exception for %s: %s", pair, e)

    # 4. Determine data quality
    if sources_available == 0:
        report.data_quality = "UNAVAILABLE"
        report.summary = "All cross-border data sources unavailable. Analysis deferred."
    elif sources_available < sources_attempted:
        report.data_quality = "PARTIAL"
        missing = sources_attempted - sources_available
        report.summary = f"Partial cross-border data: {sources_available}/{sources_attempted} sources available ({missing} missing)."
    elif sources_attempted == 0:
        report.data_quality = "UNAVAILABLE"
        report.summary = "No cross-border data sources queried."
    else:
        report.data_quality = "FULL"
        alerts = len(report.ccb_alerts) + len(report.unusual_patterns)
        report.summary = f"Full cross-border data: {alerts} alert(s) detected across TIC, BIS, and CCB sources."

    return report


# ---------------------------------------------------------------------------
# TIC pattern detection
# ---------------------------------------------------------------------------


def _check_tic_patterns(tic_data: list[TICFlowData], report: CrossBorderFlowReport) -> None:
    """Identify unusual patterns in TIC flow data."""
    # Check for large Cayman Islands / hedge fund domicile flows
    for flow in tic_data:
        if flow.country.lower() in _HEDGE_FUND_DOMICILES:
            if abs(flow.net_flow_usd_bn) > _CAYMAN_FLOW_THRESHOLD_USD_BN:
                direction = "增持" if flow.net_flow_usd_bn > 0 else "减持"
                report.unusual_patterns.append(
                    f"{flow.country} {direction}加速 ({flow.net_flow_usd_bn:+.1f}B, "
                    f"{flow.asset_type}, {flow.period}) → 对冲基金活跃"
                )

    # Check for sudden stops in official Treasury purchases
    official_flows = [f for f in tic_data if f.country.lower() in _OFFICIAL_HOLDERS
                      and f.asset_type == "treasury"]
    if len(official_flows) >= 2:
        sorted_flows = sorted(official_flows, key=lambda f: f.period, reverse=True)
        latest = sorted_flows[0]
        # Find previous period for same country
        prev = None
        for f in sorted_flows[1:]:
            if f.country.lower() == latest.country.lower():
                prev = f
                break
        if prev and latest.net_flow_usd_bn - prev.net_flow_usd_bn < _TREASURY_SUDDEN_STOP_THRESHOLD:
            report.unusual_patterns.append(
                f"{latest.country} 官方国债购买骤停: "
                f"{prev.net_flow_usd_bn:+.1f}B → {latest.net_flow_usd_bn:+.1f}B "
                f"({prev.period} → {latest.period})"
            )


# ---------------------------------------------------------------------------
# FIMA usage estimation
# ---------------------------------------------------------------------------


def _check_fima_usage(tic_data: list[TICFlowData], report: CrossBorderFlowReport) -> None:
    """Estimate FIMA repo facility usage from TIC patterns.

    Large Treasury outflows from official holders + rising short-term rates
    may indicate FIMA repo usage (dollar liquidity backstop).
    """
    outflow_countries: list[str] = []
    total_outflow = 0.0

    for flow in tic_data:
        if (flow.country.lower() in _OFFICIAL_HOLDERS
                and flow.asset_type == "treasury"
                and flow.net_flow_usd_bn < -5.0):
            outflow_countries.append(flow.country)
            total_outflow += abs(flow.net_flow_usd_bn)

    if outflow_countries:
        report.fima_usage = {
            "estimated_active": len(outflow_countries) >= 2,
            "selling_countries": outflow_countries,
            "total_treasury_outflow_usd_bn": round(total_outflow, 1),
            "note": "Official Treasury selling may indicate FIMA repo usage (dollar liquidity stress)",
        }


# ---------------------------------------------------------------------------
# Cross-currency basis analysis
# ---------------------------------------------------------------------------


def _check_basis_anomaly(basis: CrossCurrencyBasis, report: CrossBorderFlowReport) -> None:
    """Check if cross-currency basis is anomalous.

    Basis < -50 bp = significant USD funding premium (dollar shortage).
    Basis > 0 bp = USD discount (rare, dollar glut).
    """
    if basis.basis_bp < -50:
        report.ccb_alerts.append(
            f"{basis.pair} basis {basis.basis_bp:+.1f} bp — 显著的美元融资溢价，"
            f"市场美元短缺压力 ({basis.date})"
        )
    elif basis.basis_bp < -30:
        report.ccb_alerts.append(
            f"{basis.pair} basis {basis.basis_bp:+.1f} bp — 温和的美元融资溢价 ({basis.date})"
        )
    elif basis.basis_bp > 10:
        report.ccb_alerts.append(
            f"{basis.pair} basis {basis.basis_bp:+.1f} bp — 美元折价 (dollar glut), 异常信号 ({basis.date})"
        )


# ---------------------------------------------------------------------------
# Country → CCB pair mapping
# ---------------------------------------------------------------------------

_COUNTRY_TO_PAIR: dict[str, str] = {
    "china": "USD/CNH",
    "japan": "USD/JPY",
    "united kingdom": "EUR/USD",
    "germany": "EUR/USD",
    "france": "EUR/USD",
    "italy": "EUR/USD",
    "spain": "EUR/USD",
    "switzerland": "EUR/CHF",
    "australia": "AUD/USD",
    "canada": "USD/CAD",
    "south korea": "USD/KRW",
    "india": "USD/INR",
    "brazil": "USD/BRL",
    "mexico": "USD/MXN",
}


def _pairs_for_countries(countries: list[str]) -> list[str]:
    """Map affected countries to cross-currency basis pairs for checking."""
    pairs: set[str] = set()
    for country in countries:
        pair = _COUNTRY_TO_PAIR.get(country.lower())
        if pair:
            pairs.add(pair)
        else:
            # For countries without a direct mapping, check USD/JPY as global liquidity proxy
            pairs.add("EUR/USD")
    return list(pairs)
