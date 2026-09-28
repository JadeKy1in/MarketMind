"""Offline tests for the 2026-09-28 gateway data fixes."""
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from marketmind.markets import yahoo_symbol


def test_yahoo_symbol_uses_four_digit_hk_codes():
    assert yahoo_symbol("09866.HK") == "9866.HK"
    assert yahoo_symbol("0700.HK") == "0700.HK"
    assert yahoo_symbol("00700.HK") == "0700.HK"
    assert yahoo_symbol("700.HK") == "0700.HK"
    assert yahoo_symbol("600519.SS") == "600519.SS"
    assert yahoo_symbol("AAPL") == "AAPL"


def test_yf_history_requests_yahoo_symbol_but_keeps_ledger_ticker():
    from marketmind.gateway import price_history as ph
    df = pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0], "Volume": [10]},
                      index=pd.to_datetime(["2026-09-25"]))
    fake_yf = MagicMock()
    fake_yf.Ticker.return_value.history.return_value = df
    with patch.object(ph, "yf", fake_yf):
        hist = ph._yf_sync("09866.HK", 5)
    fake_yf.Ticker.assert_called_once_with("9866.HK")
    assert hist.ticker == "09866.HK"


@pytest.mark.asyncio
async def test_finnhub_has_no_ohlcv_fallback():
    from marketmind.gateway import market_data as md
    with patch.object(md, "_FINNHUB_KEY", "k"), \
            patch("httpx.AsyncClient") as client_cls:
        assert await md._fetch_finnhub("AAPL", "ohlcv") == {}
        assert await md._fetch_finnhub("AAPL", "technical") == {}
    client_cls.assert_not_called()
    assert not hasattr(md, "_finnhub_ohlcv")


@pytest.mark.parametrize("fred_var,eia_var", [("FRED_KEY", "EIA_KEY"),
                                              ("FRED_API_KEY", "EIA_API_KEY")])
def test_provider_key_check_accepts_both_env_names(monkeypatch, fred_var, eia_var):
    from marketmind.api import data_providers
    for v in ("FRED_KEY", "FRED_API_KEY", "EIA_KEY", "EIA_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv(fred_var, "x")
    monkeypatch.setenv(eia_var, "x")
    monkeypatch.setattr("marketmind.config.source_authority.SOURCES", [])
    by = {s["name"]: s["ok"] for s in data_providers.get_source_status()}
    assert by["FRED"] is True and by["EIA"] is True


@pytest.mark.asyncio
async def test_failed_fragility_scan_score_is_none_not_zero():
    from marketmind.pipeline import orchestration
    with patch("marketmind.gateway.fragility_inputs.fetch_fragility_inputs",
               AsyncMock(side_effect=RuntimeError("down"))):
        report = await orchestration._do_fragility_scan(MagicMock())
    assert report.overall_fragility_score is None
    assert "not evaluated" in report.summary


@pytest.mark.asyncio
async def test_decision_note_handles_unevaluated_fragility_score():
    from types import SimpleNamespace
    from marketmind.pipeline.decision import generate_decision
    fragility = SimpleNamespace(overall_fragility_score=None, crossed=[1, 2, 3])
    l3 = SimpleNamespace(green_lights=[], results=[])
    with patch("marketmind.pipeline.decision._pick_paper_trade", return_value=None), \
            patch("marketmind.pipeline.decision._l3_evidence", return_value="e"):
        out = await generate_decision(MagicMock(), MagicMock(), l3, MagicMock(), fragility=fragility)
    assert "score=n/a" in out.no_trade_card.thesis
