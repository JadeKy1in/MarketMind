"""Tests for pipeline/cross_border_analyzer.py — flow analysis, patterns, data quality."""
from unittest.mock import AsyncMock, patch

import pytest

from marketmind.gateway.cross_border import (
    TICFlowData,
    BISBankingFlow,
    CrossCurrencyBasis,
)
from marketmind.pipeline.cross_border_analyzer import (
    CrossBorderFlowReport,
    analyze_cross_border_flows,
    _check_tic_patterns,
    _check_basis_anomaly,
    _pairs_for_countries,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tic_flow(country: str, net_flow: float, asset_type: str = "treasury",
                   period: str = "2026-04") -> TICFlowData:
    return TICFlowData(country=country, net_flow_usd_bn=net_flow,
                       asset_type=asset_type, period=period)


def _make_bis_flow(reporting: str, counterparty: str, flow: float,
                   period: str = "2026-Q1") -> BISBankingFlow:
    return BISBankingFlow(reporting_country=reporting, counterparty_country=counterparty,
                          flow_usd_bn=flow, period=period)


# ---------------------------------------------------------------------------
# 1. Data quality — all sources fail → UNAVAILABLE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_data_quality_unavailable_when_all_fail():
    """All sources fail → data_quality = UNAVAILABLE."""
    with patch(
        "marketmind.pipeline.cross_border_analyzer.fetch_tic_data",
        new_callable=AsyncMock,
    ) as mock_tic, patch(
        "marketmind.pipeline.cross_border_analyzer.fetch_bis_banking_flows",
        new_callable=AsyncMock,
    ) as mock_bis, patch(
        "marketmind.pipeline.cross_border_analyzer.fetch_cross_currency_basis",
        new_callable=AsyncMock,
    ) as mock_ccb:
        mock_tic.return_value = []
        mock_bis.return_value = []
        mock_ccb.return_value = None

        report = await analyze_cross_border_flows(
            hypothesis_text="USD strengthening",
            affected_countries=["japan"],
        )

        assert report.data_quality == "UNAVAILABLE"
        assert len(report.flows) == 0


# ---------------------------------------------------------------------------
# 2. Unusual pattern detection — large Cayman flows
# ---------------------------------------------------------------------------


def test_unusual_pattern_detection_large_cayman_flow():
    """Large Cayman Islands flow → unusual pattern flag."""
    report = CrossBorderFlowReport()
    tic_data = [
        _make_tic_flow("United Kingdom", 5.0),
        _make_tic_flow("Cayman Islands", 15.0),
        _make_tic_flow("Japan", -3.0),
    ]
    _check_tic_patterns(tic_data, report)

    assert len(report.unusual_patterns) >= 1
    cayman_patterns = [p for p in report.unusual_patterns if "Cayman Islands" in p]
    assert len(cayman_patterns) >= 1
    assert "对冲基金活跃" in cayman_patterns[0]


def test_unusual_pattern_detection_small_flow_no_flag():
    """Small Cayman flow below threshold → no pattern flag."""
    report = CrossBorderFlowReport()
    tic_data = [
        _make_tic_flow("Cayman Islands", 5.0),
    ]
    _check_tic_patterns(tic_data, report)
    cayman_patterns = [p for p in report.unusual_patterns if "Cayman Islands" in p]
    assert len(cayman_patterns) == 0


def test_sudden_stop_in_official_treasury_purchases():
    """Large drop in official Treasury purchases → sudden stop flag."""
    report = CrossBorderFlowReport()
    tic_data = [
        _make_tic_flow("Japan", -25.0, period="2026-04"),
        _make_tic_flow("Japan", 5.0, period="2026-03"),
    ]
    _check_tic_patterns(tic_data, report)
    stop_patterns = [p for p in report.unusual_patterns if "骤停" in p]
    assert len(stop_patterns) >= 1


# ---------------------------------------------------------------------------
# 3. Partial data quality
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_partial_data_quality_when_some_available():
    """Some sources available → PARTIAL quality."""
    with patch(
        "marketmind.pipeline.cross_border_analyzer.fetch_tic_data",
        new_callable=AsyncMock,
    ) as mock_tic, patch(
        "marketmind.pipeline.cross_border_analyzer.fetch_bis_banking_flows",
        new_callable=AsyncMock,
    ) as mock_bis, patch(
        "marketmind.pipeline.cross_border_analyzer.fetch_cross_currency_basis",
        new_callable=AsyncMock,
    ) as mock_ccb:
        mock_tic.return_value = [_make_tic_flow("Japan", 5.0)]
        mock_bis.return_value = []  # BIS fails
        mock_ccb.return_value = None  # CCB fails

        report = await analyze_cross_border_flows(
            hypothesis_text="BOJ policy shift",
            affected_countries=["japan"],
        )

        assert report.data_quality == "PARTIAL"
        assert len(report.flows) == 1


# ---------------------------------------------------------------------------
# 4. Full data quality
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_data_quality_when_all_sources_available():
    """All sources return data → FULL quality."""
    with patch(
        "marketmind.pipeline.cross_border_analyzer.fetch_tic_data",
        new_callable=AsyncMock,
    ) as mock_tic, patch(
        "marketmind.pipeline.cross_border_analyzer.fetch_bis_banking_flows",
        new_callable=AsyncMock,
    ) as mock_bis, patch(
        "marketmind.pipeline.cross_border_analyzer.fetch_cross_currency_basis",
        new_callable=AsyncMock,
    ) as mock_ccb:
        mock_tic.return_value = [_make_tic_flow("Japan", 5.0)]
        mock_bis.return_value = [_make_bis_flow("JP", "US", 10.0)]
        mock_ccb.return_value = CrossCurrencyBasis(
            pair="USD/JPY", basis_bp=-25.0, date="2026-05-15",
        )

        report = await analyze_cross_border_flows(
            hypothesis_text="BOJ policy shift",
            affected_countries=["japan"],
        )

        assert report.data_quality == "FULL"
        assert len(report.flows) == 2  # TIC + BIS


# ---------------------------------------------------------------------------
# 5. Cross-currency basis alerts
# ---------------------------------------------------------------------------


def test_basis_anomaly_severe_usd_premium():
    """Basis < -50 bp → significant USD funding premium alert."""
    report = CrossBorderFlowReport()
    basis = CrossCurrencyBasis(pair="EUR/USD", basis_bp=-65.0, date="2026-05-15")
    _check_basis_anomaly(basis, report)

    assert len(report.ccb_alerts) >= 1
    assert "显著" in report.ccb_alerts[0]


def test_basis_anomaly_moderate_usd_premium():
    """Basis between -50 and -30 bp → moderate USD premium alert."""
    report = CrossBorderFlowReport()
    basis = CrossCurrencyBasis(pair="EUR/USD", basis_bp=-35.0, date="2026-05-15")
    _check_basis_anomaly(basis, report)

    assert len(report.ccb_alerts) >= 1
    assert "温和" in report.ccb_alerts[0]


def test_basis_anomaly_dollar_glut():
    """Basis > 10 bp → dollar glut alert."""
    report = CrossBorderFlowReport()
    basis = CrossCurrencyBasis(pair="EUR/USD", basis_bp=15.0, date="2026-05-15")
    _check_basis_anomaly(basis, report)

    assert len(report.ccb_alerts) >= 1
    assert "dollar glut" in report.ccb_alerts[0].lower()


def test_basis_normal_no_alert():
    """Basis in normal range → no alert."""
    report = CrossBorderFlowReport()
    basis = CrossCurrencyBasis(pair="EUR/USD", basis_bp=-10.0, date="2026-05-15")
    _check_basis_anomaly(basis, report)

    assert len(report.ccb_alerts) == 0


# ---------------------------------------------------------------------------
# 6. Country → CCB pair mapping
# ---------------------------------------------------------------------------


def test_pairs_for_countries_maps_correctly():
    pairs = _pairs_for_countries(["japan", "germany"])
    assert "USD/JPY" in pairs
    assert "EUR/USD" in pairs


def test_pairs_for_countries_unknown_fallback():
    pairs = _pairs_for_countries(["mars"])
    assert "EUR/USD" in pairs
