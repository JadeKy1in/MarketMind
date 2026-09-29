"""S1: fragility is fed real inputs and reports what it could not evaluate."""
from datetime import datetime, timezone
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


NOW = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)


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
        "RRPONTSYD": {"value": 45.0, "date": "2026-09-25"},
        "WTREGEN": {"value": 850_000.0, "date": "2026-09-23"},
        "WRESBAL": {"value": 2_930_193.0, "date": "2026-09-23"},
        "BAMLH0A3HYC": {"value": 9.5, "date": "2026-09-24"},
        # Recorded shape of FRED 2026-09-24 observations (percent units)
        "BAMLH0A0HYM2": {"value": 2.80, "date": "2026-09-24"},
        "BAMLC0A0CM": {"value": 0.79, "date": "2026-09-24"},
    }
    yf = {"^VIX": (18.0, "2026-09-25"), "^TNX": (4.8, "2026-09-25"),
          "DX-Y.NYB": (101.0, "2026-09-25")}
    with patch.object(fi, "get_fred_series", AsyncMock(side_effect=lambda k: fred[k])),          patch.object(fi, "_yf_last", AsyncMock(side_effect=lambda s: yf[s])):
        out = await fi.fetch_fragility_inputs(now=NOW)
    v = out.values
    assert v["us10y_yield"] == 4.8 and out.sources["us10y_yield"].startswith("yfinance:^TNX")
    assert "2026-09-25" in out.sources["us10y_yield"]
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
        out = await fi.fetch_fragility_inputs(now=NOW)
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
            out = await fi.fetch_fragility_inputs(now=NOW)
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


# ── Non-finite, stale and undated inputs (red-team fix 2026-09-29) ──────────

def _fred(**over):
    base = {k: {"value": 1.0, "date": "2026-09-25"} for k in (
        "DGS10", "RRPONTSYD", "WTREGEN", "WRESBAL", "BAMLH0A3HYC", "BAMLH0A0HYM2", "BAMLC0A0CM")}
    base.update(over)
    return base


async def _fetch(fred, yf=None, now=NOW):
    yf = yf or {}
    with patch.object(fi, "get_fred_series", AsyncMock(side_effect=lambda k: fred[k])), \
         patch.object(fi, "_yf_last", AsyncMock(side_effect=lambda s: yf.get(s))):
        return await fi.fetch_fragility_inputs(now=now)


@pytest.mark.asyncio
async def test_nan_input_is_unavailable_not_a_value():
    out = await _fetch(_fred(RRPONTSYD={"value": float("nan"), "date": "2026-09-25"}),
                       yf={"^VIX": (float("nan"), "2026-09-25")})
    for m in ("on_rrp", "vix"):
        assert m not in out.values and "non-finite" in out.unavailable[m]


@pytest.mark.asyncio
async def test_stale_values_become_unavailable_with_their_date():
    out = await _fetch(_fred(RRPONTSYD={"value": 45.0, "date": "2026-09-18"},     # 10d > 7
                             WTREGEN={"value": 850_000.0, "date": "2026-09-01"}),  # 27d > 21
                       yf={"DX-Y.NYB": (101.0, "2026-09-10")})
    assert out.unavailable["on_rrp"] == "stale (2026-09-18)"
    assert out.unavailable["tga"] == "stale (2026-09-01)"
    assert out.unavailable["dollar_index"] == "stale (2026-09-10)"
    assert "on_rrp" not in out.values and "tga" not in out.values


@pytest.mark.asyncio
async def test_undated_value_is_unavailable():
    out = await _fetch(_fred(RRPONTSYD={"value": 45.0}))
    assert "on_rrp" not in out.values and out.unavailable["on_rrp"] == "no observation date"


@pytest.mark.asyncio
async def test_every_source_string_carries_its_observation_date():
    out = await _fetch(_fred(), yf={"^VIX": (18.0, "2026-09-25"),
                                    "DX-Y.NYB": (101.0, "2026-09-25")})
    assert out.values
    for m, src in out.sources.items():
        assert "2026-" in src, (m, src)


def test_stale_reason_uses_period_end_for_monthly_and_quarterly():
    now = datetime(2026, 9, 28, tzinfo=timezone.utc)
    assert fi.stale_reason("2026-09-21", "daily", now) is None           # 7d
    assert fi.stale_reason("2026-09-20", "daily", now) == "stale (2026-09-20)"
    assert fi.stale_reason("2026-09-07", "weekly", now) is None          # 21d
    # FRED monthly 2026-07-01 = July (ends 07-31, 59d); June ends 06-30 (90d > 75)
    assert fi.stale_reason("2026-07-01", "monthly", now) is None
    assert fi.stale_reason("2026-06-01", "monthly", now) == "stale (2026-06-01)"
    # FRED quarterly 2026-01-01 = Q1 (ends 03-31, 181d <= 200); 2025-10-01 = Q4 (272d)
    assert fi.stale_reason("2026-01-01", "quarterly", now) is None
    assert fi.stale_reason("2025-10-01", "quarterly", now) == "stale (2025-10-01)"
    assert fi.stale_reason(None, "daily", now) == "no observation date"
    assert "unparseable" in fi.stale_reason("n/a", "daily", now)


@pytest.mark.asyncio
async def test_bank_reserves_needs_fresh_gdp_too():
    async def fred_obs(series_id, limit=5):
        return {"GDP": [("2025-07-01", 30_000.0)]}.get(series_id, "FRED unavailable (test)")

    with patch.object(fi, "_fred_observations", fred_obs):
        out = await _fetch(_fred(WRESBAL={"value": 2_930_193.0, "date": "2026-09-23"}))
    assert "bank_reserves" not in out.values
    assert out.unavailable["bank_reserves"] == "stale (2025-07-01)"


@pytest.mark.asyncio
async def test_yf_last_uses_last_complete_bar(monkeypatch):
    import pandas as pd

    idx = pd.DatetimeIndex(["2026-09-24", "2026-09-25"])
    df = pd.DataFrame({"Open": [17.0, 30.0], "High": [19.0, 31.0], "Low": [16.0, 29.0],
                       "Close": [18.0, 30.5], "Volume": [0, 0]}, index=idx)

    class _T:
        def __init__(self, sym):
            pass

        def history(self, **kw):
            return df

    import sys
    import types
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=_T))
    from marketmind.gateway import price_history as ph
    real = ph.complete_bars
    during = datetime(2026, 9, 25, 18, 0, tzinfo=timezone.utc)            # 14:00 ET
    monkeypatch.setattr(ph, "complete_bars", lambda t, d, now=None: real(t, d, during))
    assert await fi._yf_last("^VIX") == (18.0, "2026-09-24")               # partial dropped
    after = datetime(2026, 9, 25, 21, 0, tzinfo=timezone.utc)              # 17:00 ET
    monkeypatch.setattr(ph, "complete_bars", lambda t, d, now=None: real(t, d, after))
    assert await fi._yf_last("^VIX") == (30.5, "2026-09-25")
