"""S1: fragility is fed real inputs and reports what it could not evaluate."""
from unittest.mock import AsyncMock, patch

import pytest

from marketmind.config import fragility_thresholds as ft
from marketmind.gateway import fragility_inputs as fi
from marketmind.pipeline.fragility_scanner import scan_fragility


@pytest.fixture(autouse=True)
def _no_network_for_new_sources(monkeypatch):
    """Keep these tests offline: the non-catalog sources report unavailable by default."""
    async def fred_obs(series_id, limit=5):
        return "FRED unavailable (test)"

    async def unavailable():
        return None, "", "unavailable (test)"

    async def gold():
        return "yfinance GC=F unavailable (test)"

    monkeypatch.setattr(fi, "_fred_observations", fred_obs)
    monkeypatch.setattr(fi, "_ofr_fsi_latest", unavailable)
    monkeypatch.setattr(fi, "_worldbank_em_import_cover", unavailable)
    monkeypatch.setattr(fi, "_defillama_cex_7d_change", unavailable)
    monkeypatch.setattr(fi, "_gold_monthly_avg", gold)


@pytest.mark.asyncio
async def test_missing_metrics_are_listed_not_treated_as_safe():
    report = await scan_fragility({"vix": 20.0}, unavailable={"on_rrp": "FRED unavailable"})
    assert len(report.alerts) == 1
    assert report.unavailable["on_rrp"] == "FRED unavailable"
    assert "us10y_yield" in report.unavailable            # no value supplied -> listed
    assert "not evaluated" in report.summary


def test_thresholds_have_real_validation_date_so_staleness_can_fire():
    allowed = {ft.THRESHOLDS_RESEARCHED_ON, ft.THRESHOLDS_REVIEWED_2026_09_28}
    assert all(t.last_validated in allowed for t in ft.THRESHOLD_LIBRARY)
    assert any("STALE" in w for w in ft.validate_thresholds())   # 2026-05-18 is > 90 days ago


# Recorded shape of FRED observations (newest first), percent units.
OBS = {
    "SOFR": [("2026-09-25", 4.52), ("2026-09-24", 4.45), ("2026-09-23", 4.41),
             ("2026-09-22", 4.30)],
    "IORB": [("2026-09-26", 4.30), ("2026-09-25", 4.30), ("2026-09-24", 4.30),
             ("2026-09-23", 4.30), ("2026-09-22", 4.30)],
    "GDP": [("2026-04-01", 32_486.066), ("2026-01-01", 31_865.721)],
}


@pytest.mark.asyncio
async def test_inputs_convert_units_and_fall_back_to_yfinance(monkeypatch):
    async def fred_obs(series_id, limit=5):
        return OBS.get(series_id, f"FRED {series_id} unavailable (test)")

    monkeypatch.setattr(fi, "_fred_observations", fred_obs)
    fred = {
        "DGS10": {"error": "source_unavailable"},
        "RRPONTSYD": {"value": 45.0}, "WTREGEN": {"value": 850_000.0},
        "WRESBAL": {"value": 2_930_193.0, "date": "2026-09-23"},
        "BAMLH0A3HYC": {"value": 9.5},
        # Recorded shape of FRED 2026-09-24 observations (percent units)
        "BAMLH0A0HYM2": {"value": 2.80, "date": "2026-09-24"},
        "BAMLC0A0CM": {"value": 0.79, "date": "2026-09-24"},
    }
    yf = {"^VIX": 18.0, "^TNX": 4.8, "DX-Y.NYB": 101.0}
    with patch.object(fi, "get_fred_series", AsyncMock(side_effect=lambda k: fred[k])), \
         patch.object(fi, "_yf_last", AsyncMock(side_effect=lambda s: yf[s])):
        out = await fi.fetch_fragility_inputs()
    v = out.values
    assert v["us10y_yield"] == 4.8 and out.sources["us10y_yield"] == "yfinance:^TNX"
    assert v["on_rrp"] == 45.0
    assert v["tga"] == 850.0                    # M -> B USD
    # 2,930,193 M USD / (32,486.066 B USD * 1000) * 100 = 9.0199 % of GDP
    assert v["bank_reserves"] == pytest.approx(9.0199, abs=1e-4)
    assert "WRESBAL 2026-09-23" in out.sources["bank_reserves"]
    assert "GDP 2026-04-01" in out.sources["bank_reserves"]
    # min of the last 3 SOFR obs: 22, 15, 11 bp -> 11 (% -> bp)
    assert v["sofr_iorb_spread"] == pytest.approx(11.0)
    assert v["ccc_treasury_spread"] == 950.0
    assert v["hyg_lqd_spread"] == pytest.approx(201.0)   # (HY OAS - IG OAS) % -> bp
    assert "hyg_lqd_spread" not in out.unavailable
    assert "copper_gold_ratio" in out.unavailable and "copper_gold_ratio" not in v


@pytest.mark.asyncio
async def test_inputs_without_fred_mark_fred_metrics_unavailable():
    with patch.object(fi, "get_fred_series", AsyncMock(return_value={"error": "source_unavailable"})), \
         patch.object(fi, "_yf_last", AsyncMock(return_value=None)):
        out = await fi.fetch_fragility_inputs()
    assert out.values == {}
    for m in ("on_rrp", "tga", "bank_reserves", "sofr_iorb_spread", "ccc_treasury_spread",
              "hyg_lqd_spread", "vix"):
        assert m in out.unavailable


@pytest.mark.asyncio
async def test_hy_ig_spread_unavailable_when_one_leg_missing_or_dates_differ():
    base = {"value": 1.0, "date": "2026-09-24"}
    for hy, ig, reason in (
        ({"value": 2.8, "date": "2026-09-24"}, {"error": "source_unavailable"}, "FRED unavailable"),
        ({"value": 2.8, "date": "2026-09-24"}, {"value": 0.79, "date": "2026-09-23"}, "dates differ"),
    ):
        fred = {"BAMLH0A0HYM2": hy, "BAMLC0A0CM": ig}
        with patch.object(fi, "get_fred_series", AsyncMock(side_effect=lambda k: fred.get(k, base))),              patch.object(fi, "_yf_last", AsyncMock(return_value=None)):
            out = await fi.fetch_fragility_inputs()
        assert "hyg_lqd_spread" not in out.values
        assert reason in out.unavailable["hyg_lqd_spread"]


@pytest.mark.asyncio
async def test_hy_ig_spread_crosses_threshold_in_scanner():
    report = await scan_fragility({"hyg_lqd_spread": 500.0})
    assert any(a.threshold.metric == "hyg_lqd_spread" and a.crossed for a in report.crossed)
    # 201bp (Sep 2026, tight market) no longer fires against the 450bp line
    calm = await scan_fragility({"hyg_lqd_spread": 201.0})
    assert not calm.crossed and calm.alerts[0].severity == "CLEAR"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_live_fred_hy_ig_spread_is_plausible_bp():
    from marketmind.gateway import fred_client
    fred_client._clear_cache()
    out = await fi.fetch_fragility_inputs()
    assert 50 < out.values["hyg_lqd_spread"] < 2000
