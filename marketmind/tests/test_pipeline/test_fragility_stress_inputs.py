"""Fragility gap-fill (2026-09-28): margin debt/GDP, copper/gold, EM import cover,
CEX reserves proxy and the financial-stress indices. Offline, recorded-shape payloads."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from marketmind.config import fragility_thresholds as ft
from marketmind.gateway import fragility_inputs as fi
from marketmind.pipeline.fragility_scanner import scan_fragility

# Recorded shape of the FRED observations endpoint (sort_order=desc), 2026-09-28.
FRED_OBS = {
    "BOGZ1FL663067003Q": {"observations": [
        {"date": "2026-04-01", "value": "742321"}, {"date": "2026-01-01", "value": "622199.0"}]},
    "GDP": {"observations": [
        {"date": "2026-04-01", "value": "32486.066"}, {"date": "2026-01-01", "value": "31865.721"}]},
    "PCOPPUSDM": {"observations": [{"date": "2026-07-01", "value": "13542.82086956522"}]},
    "STLFSI4": {"observations": [{"date": "2026-09-18", "value": "-0.9075"}]},
    "BAMLC0A4CBBB": {"observations": [{"date": "2026-09-25", "value": "."},
                                      {"date": "2026-09-24", "value": "0.97"}]},
}
OFR_CSV = (
    "Date,OFR FSI,Credit,Equity valuation,Safe assets,Funding,Volatility,United States,"
    "Other advanced economies,Emerging markets\n"
    "2026-09-22,-2.773,-1.149,-0.577,-0.296,-0.145,-0.606,-1.371,-0.842,-0.56\n"
    "2026-09-23,-2.663,-1.148,-0.567,-0.294,-0.166,-0.488,-1.33,-0.772,-0.562\n"
)
WB_PAYLOAD = [
    {"page": 1, "pages": 1, "per_page": 50, "total": 2},
    [{"countryiso3code": "LMY", "date": "2025", "value": 9.90084977002796},
     {"countryiso3code": "LMY", "date": "2024", "value": 8.98564156730719}],
]
CEX_PAYLOAD = [
    {"name": "Binance CEX", "category": "CEX", "tvl": 180e9, "change_7d": -2.0},
    {"name": "OKX", "category": "CEX", "tvl": 30e9, "change_7d": 1.0},
    {"name": "Uniswap", "category": "Dexs", "tvl": 5e9, "change_7d": -50.0},  # not CEX
]


async def _fred_obs_from_payload(series_id, limit=5):
    return fi._parse_fred_observations(FRED_OBS[series_id])


def _patch_all(**overrides):
    base = {
        "_fred_observations": _fred_obs_from_payload,
        "_ofr_fsi_latest": AsyncMock(return_value=fi._parse_ofr_fsi(OFR_CSV)),
        "_worldbank_em_import_cover": AsyncMock(return_value=fi._parse_worldbank(
            WB_PAYLOAD, now=datetime(2026, 9, 28, tzinfo=timezone.utc))),
        "_defillama_cex_7d_change": AsyncMock(return_value=fi._parse_cex_change(CEX_PAYLOAD)),
        "_gold_monthly_avg": AsyncMock(return_value={"2026-07": 4078.7409, "2026-08": 4468.87}),
        "get_fred_series": AsyncMock(return_value={"error": "source_unavailable"}),
        "_yf_last": AsyncMock(return_value=None),
    }
    base.update(overrides)
    return patch.multiple(fi, **base)


@pytest.mark.asyncio
async def test_new_inputs_computed_with_explicit_units():
    with _patch_all():
        out = await fi.fetch_fragility_inputs()
    v = out.values
    # 742,321 M USD / (32,486.066 B USD * 1000) * 100 = 2.285 % of GDP
    assert v["margin_debt_gdp"] == pytest.approx(2.285, abs=1e-3)
    # (13,542.82 USD/t / 2204.62262 lb/t) / 4078.74 USD/oz * 1000 = 1.506
    assert v["copper_gold_ratio"] == pytest.approx(1.506, abs=1e-3)
    assert v["stlfsi"] == -0.9075
    assert v["ofr_fsi"] == -2.663
    assert v["bbb_oas"] == pytest.approx(97.0)          # 0.97 % -> bp, skips "."
    assert v["em_import_cover"] == pytest.approx(9.9008, abs=1e-4)
    # prev = 180/0.98 + 30/1.01 ; (210/prev - 1)*100
    prev = 180 / 0.98 + 30 / 1.01
    assert v["crypto_exchange_reserves"] == pytest.approx((210 / prev - 1) * 100, abs=1e-4)
    for m in ("margin_debt_gdp", "copper_gold_ratio", "stlfsi", "ofr_fsi", "bbb_oas",
              "em_import_cover", "crypto_exchange_reserves"):
        assert m not in out.unavailable and out.sources[m]


@pytest.mark.asyncio
async def test_failed_sources_stay_unavailable_never_a_number():
    async def fred_fail(series_id, limit=5):
        return f"FRED {series_id} unavailable (ConnectTimeout)"

    fail = AsyncMock(return_value=(None, "", "down (test)"))
    with _patch_all(_fred_observations=fred_fail, _ofr_fsi_latest=fail,
                    _worldbank_em_import_cover=fail, _defillama_cex_7d_change=fail,
                    _gold_monthly_avg=AsyncMock(return_value="yfinance GC=F unavailable")):
        out = await fi.fetch_fragility_inputs()
    for m in ("margin_debt_gdp", "copper_gold_ratio", "stlfsi", "ofr_fsi", "bbb_oas",
              "em_import_cover", "crypto_exchange_reserves"):
        assert m not in out.values
        assert out.unavailable[m]


@pytest.mark.asyncio
async def test_copper_gold_needs_gold_for_the_same_month():
    with _patch_all(_gold_monthly_avg=AsyncMock(return_value={"2026-08": 4468.87})):
        out = await fi.fetch_fragility_inputs()
    assert "copper_gold_ratio" not in out.values
    assert "2026-07" in out.unavailable["copper_gold_ratio"]


def test_margin_ratio_uses_same_quarter_only():
    margin = [("2026-07-01", 800_000.0), ("2026-04-01", 742_321.0)]
    gdp = [("2026-04-01", 32_486.066)]
    value, date, why = fi._same_date_ratio(margin, gdp)
    assert date == "2026-04-01" and value == pytest.approx(742_321 / 32_486.066)
    assert fi._same_date_ratio([("2026-07-01", 1.0)], gdp)[0] is None


def test_parsers_reject_bad_payloads():
    assert fi._parse_ofr_fsi("a,b\n1,2\n")[0] is None
    assert fi._parse_worldbank([{"message": "error"}])[0] is None
    old = [{}, [{"date": "2019", "value": 7.0}]]
    value, _, why = fi._parse_worldbank(old, now=datetime(2026, 9, 28, tzinfo=timezone.utc))
    assert value is None and "too old" in why
    # CEX coverage below 90% of TVL -> unavailable
    thin = [{"category": "CEX", "tvl": 100.0, "change_7d": 1.0},
            {"category": "CEX", "tvl": 900.0, "change_7d": None}]
    assert fi._parse_cex_change(thin)[0] is None
    assert fi._parse_cex_change({"error": "x"})[0] is None


@pytest.mark.asyncio
async def test_copper_gold_is_monitor_only_never_crossed():
    report = await scan_fragility({"copper_gold_ratio": 1.5})
    alert = next(a for a in report.alerts if a.threshold.metric == "copper_gold_ratio")
    assert not alert.crossed and alert.severity == "MONITOR" and alert.distance_pct is None
    assert report.overall_fragility_score is None           # not scored
    assert not report.crossed


@pytest.mark.asyncio
async def test_new_thresholds_cross_in_the_right_direction():
    report = await scan_fragility({"stlfsi": 1.5, "ofr_fsi": 5.0, "bbb_oas": 250.0,
                                   "margin_debt_gdp": 2.7, "em_import_cover": 2.5,
                                   "crypto_exchange_reserves": -12.0})
    crossed = {a.threshold.metric for a in report.crossed}
    assert crossed == {"stlfsi", "ofr_fsi", "bbb_oas", "margin_debt_gdp",
                       "em_import_cover", "crypto_exchange_reserves"}
    calm = await scan_fragility({"stlfsi": -0.9, "ofr_fsi": -2.7, "bbb_oas": 97.0,
                                 "margin_debt_gdp": 2.29, "em_import_cover": 9.9,
                                 "crypto_exchange_reserves": -1.6})
    assert not calm.crossed


def test_new_thresholds_carry_units_and_review_date():
    lib = {t.metric: t for t in ft.THRESHOLD_LIBRARY}
    assert lib["bbb_oas"].unit == "basis_points"
    assert lib["crypto_exchange_reserves"].unit == "percent_7d_change"
    assert lib["copper_gold_ratio"].crossable is False
    for m in ("margin_debt_gdp", "copper_gold_ratio", "em_import_cover",
              "crypto_exchange_reserves", "stlfsi", "ofr_fsi", "bbb_oas"):
        assert lib[m].last_validated == ft.THRESHOLDS_REVIEWED_2026_09_28


@pytest.mark.slow
@pytest.mark.asyncio
async def test_live_new_inputs_are_plausible():
    out = await fi.fetch_fragility_inputs()
    v = out.values
    assert 0.5 < v["margin_debt_gdp"] < 5
    assert 0.5 < v["copper_gold_ratio"] < 10
    assert -5 < v["stlfsi"] < 15 and -10 < v["ofr_fsi"] < 40
    assert 30 < v["bbb_oas"] < 1500
    assert 1 < v["em_import_cover"] < 30
    assert -100 < v["crypto_exchange_reserves"] < 100
