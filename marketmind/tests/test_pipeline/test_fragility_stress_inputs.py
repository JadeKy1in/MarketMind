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
    "SOFR": {"observations": [{"date": "2026-09-25", "value": "4.33"},
                              {"date": "2026-09-24", "value": "4.32"},
                              {"date": "2026-09-23", "value": "4.35"}]},
    "IORB": {"observations": [{"date": "2026-09-26", "value": "4.30"},
                              {"date": "2026-09-25", "value": "4.30"},
                              {"date": "2026-09-24", "value": "4.30"},
                              {"date": "2026-09-23", "value": "4.30"}]},
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
    assert v["sofr_iorb_spread"] == pytest.approx(2.0)     # min(3, 2, 5) bp
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
              "em_import_cover", "crypto_exchange_reserves", "sofr_iorb_spread",
              "bank_reserves"):
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
    report = await scan_fragility({"stlfsi": 1.5, "ofr_fsi": 5.0, "bbb_oas": 320.0,
                                   "margin_debt_gdp": 2.7, "em_import_cover": 2.5,
                                   "crypto_exchange_reserves": -12.0})
    crossed = {a.threshold.metric for a in report.crossed}
    # crypto_exchange_reserves is MONITOR-only since 2026-09-28: shown, never crossed
    assert crossed == {"stlfsi", "ofr_fsi", "bbb_oas", "margin_debt_gdp", "em_import_cover"}
    calm = await scan_fragility({"stlfsi": -0.9, "ofr_fsi": -2.7, "bbb_oas": 97.0,
                                 "margin_debt_gdp": 2.29, "em_import_cover": 9.9,
                                 "crypto_exchange_reserves": -1.6})
    assert not calm.crossed


def test_new_thresholds_carry_units_and_review_date():
    lib = {t.metric: t for t in ft.THRESHOLD_LIBRARY}
    assert lib["bbb_oas"].unit == "basis_points"
    assert lib["crypto_exchange_reserves"].unit == "percent_7d_change"
    assert lib["copper_gold_ratio"].crossable is False
    assert lib["crypto_exchange_reserves"].crossable is False
    for m in ("margin_debt_gdp", "copper_gold_ratio", "em_import_cover",
              "crypto_exchange_reserves", "stlfsi", "ofr_fsi", "bbb_oas"):
        assert lib[m].last_validated == ft.THRESHOLDS_REVIEWED_2026_09_28


# -- 2026-09-28 threshold revision (owner decision) --

def test_revised_threshold_values_and_sources():
    lib = {t.metric: t for t in ft.THRESHOLD_LIBRARY}
    assert lib["hyg_lqd_spread"].threshold_value == 450
    assert lib["ccc_treasury_spread"].threshold_value == 1300
    s = lib["sofr_iorb_spread"]
    assert (s.threshold_value, s.direction, s.unit) == (10, "above", "basis_points")
    r = lib["bank_reserves"]
    assert (r.threshold_value, r.warning_value, r.unit, r.direction) == (
        8.0, 9.0, "percent_of_GDP", "below")
    assert "WRESBAL" in r.data_source and "WRBWFRBL" not in r.data_source
    b = lib["bbb_oas"]
    assert (b.threshold_value, b.warning_value) == (300, 200)
    for m in ("on_rrp", "us10y_yield", "crypto_exchange_reserves", "copper_gold_ratio"):
        assert lib[m].crossable is False, m
    for m in ("hyg_lqd_spread", "on_rrp", "bank_reserves", "sofr_iorb_spread",
              "ccc_treasury_spread", "bbb_oas"):
        assert "2026-09-28" in lib[m].source_document and "http" in lib[m].source_document, m
        assert lib[m].last_validated == ft.THRESHOLDS_REVIEWED_2026_09_28
    assert "secondary" in lib["ccc_treasury_spread"].source_document
    # TGA: the rebuild drains liquidity, the drawdown does not
    assert "rebuild" in lib["tga"].mechanism and "drains" in lib["tga"].mechanism


def test_sofr_iorb_needs_three_consecutive_observations_above_10bp():
    iorb = [("2026-09-25", 4.30), ("2026-09-24", 4.30), ("2026-09-23", 4.30)]
    persistent = [("2026-09-25", 4.45), ("2026-09-24", 4.44), ("2026-09-23", 4.41)]
    value, src, why = fi._sofr_iorb_persistent(persistent, iorb)
    assert value == pytest.approx(11.0) and "2026-09-23..2026-09-25" in src and not why
    # one day back below 10bp -> the persistent value is that low day
    blip = [("2026-09-25", 4.46), ("2026-09-24", 4.36), ("2026-09-23", 4.45)]
    assert fi._sofr_iorb_persistent(blip, iorb)[0] == pytest.approx(6.0)
    # exactly 10bp is not "> 10bp" (float noise is rounded away)
    assert fi._sofr_iorb_persistent([(d, 4.40) for d, _ in iorb], iorb)[0] == 10.0
    # too few observations, or IORB missing on a SOFR date -> unavailable, never a number
    assert fi._sofr_iorb_persistent(persistent[:2], iorb)[0] is None
    value, _, why = fi._sofr_iorb_persistent(persistent, iorb[:2])
    assert value is None and "2026-09-23" in why
    assert fi._sofr_iorb_persistent("FRED SOFR unavailable (x)", iorb) == (
        None, "", "FRED SOFR unavailable (x)")


@pytest.mark.asyncio
async def test_sofr_iorb_persistence_crosses_in_scanner():
    report = await scan_fragility({"sofr_iorb_spread": 11.0})
    assert [a.threshold.metric for a in report.crossed] == ["sofr_iorb_spread"]
    at_line = await scan_fragility({"sofr_iorb_spread": 10.0})
    assert not at_line.crossed and at_line.alerts[0].severity == "WARNING"


def test_reserves_to_gdp_ratio_and_failures():
    gdp = [("2026-04-01", 32_486.066)]
    value, src, why = fi._reserves_to_gdp(2_930_193.0, "2026-09-23", gdp, "fred down")
    assert value == pytest.approx(9.0199, abs=1e-4) and "GDP 2026-04-01" in src
    assert fi._reserves_to_gdp(None, None, gdp, "fred down") == (None, "", "fred down")
    assert fi._reserves_to_gdp(2_930_193.0, "d", "FRED GDP unavailable (x)", "")[0] is None
    assert fi._reserves_to_gdp(2_930_193.0, "d", [], "")[0] is None


@pytest.mark.asyncio
async def test_two_tier_thresholds_warning_then_stress():
    cases = {  # metric: [(value, severity, crossed), ...]
        "bbb_oas": [(97.0, "CLEAR", False), (195.0, "WARNING", False),
                    (250.0, "WARNING", False), (320.0, "CRITICAL", True)],
        "bank_reserves": [(11.0, "CLEAR", False), (9.8, "MONITOR", False),
                          (9.02, "WARNING", False), (8.5, "WARNING", False),
                          (7.9, "CRITICAL", True)],
    }
    for metric, rows in cases.items():
        for value, severity, crossed in rows:
            report = await scan_fragility({metric: value})
            a = report.alerts[0]
            assert (a.severity, a.crossed) == (severity, crossed), (metric, value)
            assert (a.distance_pct < 0) == crossed      # distance is to the stress line


@pytest.mark.asyncio
async def test_monitor_only_metrics_are_shown_but_never_scored():
    report = await scan_fragility({"on_rrp": 0.58, "us10y_yield": 5.2,
                                   "crypto_exchange_reserves": -25.0})
    assert {a.threshold.metric for a in report.alerts} == {
        "on_rrp", "us10y_yield", "crypto_exchange_reserves"}
    assert all(a.severity == "MONITOR" and a.distance_pct is None and not a.crossed
               for a in report.alerts)
    assert report.overall_fragility_score is None and not report.crossed


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
