"""Tests for gateway/cross_border.py — TIC, BIS, CCB data types and graceful degradation."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from marketmind.gateway.cross_border import (
    TICFlowData,
    BISBankingFlow,
    CrossCurrencyBasis,
    fetch_tic_data,
    fetch_cross_currency_basis,
    fetch_bis_banking_flows,
    _clear_cache,
    _parse_float,
)


# ---------------------------------------------------------------------------
# 1. Dataclass field validation
# ---------------------------------------------------------------------------


class TestTICFlowData:
    def test_tic_data_dataclass_has_required_fields(self):
        flow = TICFlowData(
            country="China",
            net_flow_usd_bn=-15.2,
            asset_type="treasury",
            period="2026-04",
        )
        assert flow.country == "China"
        assert flow.net_flow_usd_bn == -15.2
        assert flow.asset_type == "treasury"
        assert flow.period == "2026-04"
        assert flow.source == "TIC_SLT"

    def test_tic_data_default_source(self):
        flow = TICFlowData(country="Japan", net_flow_usd_bn=5.0, asset_type="equity", period="2026-03")
        assert flow.source == "TIC_SLT"


class TestCrossCurrencyBasis:
    def test_cross_currency_basis_negative_is_usd_premium(self):
        basis = CrossCurrencyBasis(pair="EUR/USD", basis_bp=-45.0, date="2026-05-15")
        assert basis.basis_bp < 0
        assert basis.pair == "EUR/USD"
        assert basis.source == "FRED"

    def test_basis_default_source(self):
        basis = CrossCurrencyBasis(pair="USD/JPY", basis_bp=-20.0, date="2026-05-15")
        assert basis.source == "FRED"


class TestBISBankingFlow:
    def test_bis_flow_default_source(self):
        flow = BISBankingFlow(
            reporting_country="US",
            counterparty_country="KY",
            flow_usd_bn=12.5,
            period="2026-Q1",
        )
        assert flow.source == "BIS_LBS"
        assert flow.reporting_country == "US"
        assert flow.flow_usd_bn == 12.5


# ---------------------------------------------------------------------------
# 2. Graceful degradation on fetch failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGracefulDegradation:
    async def test_tic_http_failure_returns_empty_list(self):
        _clear_cache()
        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_get.side_effect = OSError("Connection refused")

            result = await fetch_tic_data()
            assert result == []
            assert isinstance(result, list)

    async def test_tic_http_500_returns_empty_list(self):
        _clear_cache()
        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Server error",
                request=AsyncMock(),
                response=AsyncMock(status_code=500),
            )
            mock_get.return_value = mock_resp

            result = await fetch_tic_data()
            assert result == []

    async def test_bis_network_error_returns_empty_list(self):
        _clear_cache()
        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_get.side_effect = OSError("Network unreachable")

            result = await fetch_bis_banking_flows()
            assert result == []
            assert isinstance(result, list)

    async def test_ccb_fetch_failure_returns_none(self):
        _clear_cache()
        with patch(
            "marketmind.gateway.cross_border._get_fred_key",
            return_value="",
        ):
            result = await fetch_cross_currency_basis("EUR/USD")
            assert result is None

    async def test_ccb_http_error_returns_none(self):
        _clear_cache()
        with patch(
            "marketmind.gateway.cross_border._get_fred_key",
            return_value="test_key",
        ), patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
        ) as mock_get:
            mock_get.side_effect = OSError("Timeout")

            result = await fetch_cross_currency_basis("EUR/USD")
            assert result is None


# ---------------------------------------------------------------------------
# 3. Parse helper
# ---------------------------------------------------------------------------


class TestParseFloat:
    def test_parse_float_valid(self):
        assert _parse_float("1450") == 1450.0
        assert _parse_float("-15.2") == -15.2

    def test_parse_float_invalid_returns_zero(self):
        assert _parse_float(None) == 0.0
        assert _parse_float("abc") == 0.0
        assert _parse_float("") == 0.0
