"""Nasdaq short interest / option chain parsing and summaries (offline fixtures)."""
from datetime import date

import httpx
import pytest

from marketmind.gateway import nasdaq_derivs as nd

SI_PAYLOAD = {"data": {"symbol": "upst", "shortInterestTable": {"rows": [
    {"settlementDate": "08/31/2026", "interest": "25,946,861", "avgDailyShareVolume": "4,168,492",
     "daysToCover": 6.22452},
    {"settlementDate": "09/15/2026", "interest": "27,649,788", "avgDailyShareVolume": "4,028,630",
     "daysToCover": 6.863323},
]}}}

CHAIN = {"data": {"lastTrade": "LAST TRADE: $100.00 (AS OF SEP 24, 2026)", "table": {"rows": [
    {"expirygroup": "September 30, 2026", "strike": None},        # 3 days out: skipped as "near"
    {"expirygroup": "", "strike": "100.00", "c_Bid": "1", "c_Ask": "1.2", "c_Volume": "500",
     "c_Openinterest": "900", "p_Bid": "1", "p_Ask": "1.2", "p_Volume": "100",
     "p_Openinterest": "100"},
    {"expirygroup": "October 16, 2026", "strike": None},
    {"expirygroup": "", "strike": "95.00", "c_Bid": "6", "c_Ask": "6.4", "c_Volume": "10",
     "c_Openinterest": "50", "p_Bid": "1.9", "p_Ask": "2.1", "p_Volume": "300",
     "p_Openinterest": "4,000"},
    {"expirygroup": "", "strike": "100.00", "c_Bid": "2.9", "c_Ask": "3.1", "c_Volume": "200",
     "c_Openinterest": "1,000", "p_Bid": "2.4", "p_Ask": "2.6", "p_Volume": "100",
     "p_Openinterest": "500"},
    {"expirygroup": "", "strike": "105.00", "c_Bid": "0.9", "c_Ask": "1.1", "c_Volume": "90",
     "c_Openinterest": "3,000", "p_Bid": "--", "p_Ask": "--", "p_Last": "5.5", "p_Volume": "--",
     "p_Openinterest": "--"},
]}}}


def test_parse_short_interest_latest_and_change():
    si = nd.parse_short_interest("UPST", SI_PAYLOAD)
    assert (si.settlement_date, si.shares_short, si.previous_date) == (
        "2026-09-15", 27649788.0, "2026-08-31")
    assert si.days_to_cover == pytest.approx(6.863, abs=1e-3)
    assert si.change_pct == pytest.approx(6.563, abs=1e-2)
    assert "days to cover 6.9" in si.line()
    assert nd.parse_short_interest("GME", {"data": None}) is None


def test_parse_chain_and_summary():
    contracts = nd.parse_chain(CHAIN)
    assert len(contracts) == 8 and contracts[0].expiry == date(2026, 9, 30)
    s = nd.summarise_chain("XYZ", contracts, 100.0, date(2026, 9, 27), "2026-09-24")
    assert s.put_call_volume == pytest.approx(500 / 800)
    assert s.put_call_oi == pytest.approx(4600 / 4950)
    assert s.near_expiry == "2026-10-16" and s.days_to_near == 19
    assert s.implied_move_pct == pytest.approx(5.5)            # (3.0 + 2.5) / 100
    assert s.otm_put_call_ratio == pytest.approx(2.0 / 1.0)    # 95 put mid / 105 call mid
    assert (s.call_wall, s.put_wall) == (105.0, 95.0)
    assert "implied move ±5.5%" in s.line()


def test_summary_handles_empty_and_symbols():
    assert nd.summarise_chain("X", [], 100, date(2026, 9, 27), "") is None
    assert nd._symbol("BTC-USD") is None and nd._symbol("BRK-B") == "BRK.B"


@pytest.mark.asyncio
async def test_fetchers_over_mock_transport():
    def handler(request):
        if request.url.path.endswith("/short-interest"):
            return httpx.Response(200, json=SI_PAYLOAD)
        if request.url.path.endswith("/option-chain"):
            return httpx.Response(200, json=CHAIN)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        si = await nd.get_short_interest("UPST", client=client)
        oc = await nd.get_option_summary("XYZ", 100.0, date(2026, 9, 27), client=client)
    assert si.shares_short == 27649788.0
    assert oc.as_of == "2026-09-24" and oc.near_expiry == "2026-10-16"

    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r: httpx.Response(500))) as client:
        assert await nd.get_short_interest("UPST", client=client) is None
        assert await nd.get_option_summary("XYZ", 100.0, client=client) is None
