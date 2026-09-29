"""shadow_feeds.crypto_onchain: lines computed from gateway.crypto_signals series. Offline."""
import pytest

import marketmind.shadow_feeds as sf
from marketmind.gateway import crypto_signals as cs
from marketmind.shadow_feeds import crypto_onchain as co


def _mvrv(n=400, last_mvrv=1.2):
    pts = [cs.MvrvPoint(f"D{i:04d}", 1.0 + (i % 10) / 10, 1000.0 + i) for i in range(n - 1)]
    # real ISO dates for the first / last points (only those are printed)
    pts[0] = cs.MvrvPoint("2016-01-01", pts[0].mvrv, pts[0].market_cap)
    pts.append(cs.MvrvPoint("2026-09-28", last_mvrv, 1.5e12))
    return cs.Series("coinmetrics_btc", tuple(pts), "2026-09-29", "live")


def _fng():
    pts = (cs.FngPoint("2026-09-22", 78, "Extreme Greed"), cs.FngPoint("2026-09-28", 74, "Greed"),
           cs.FngPoint("2026-09-29", 73, "Greed"))
    return cs.Series("fear_greed", pts, "2026-09-29", "live")


def _etf(origin="live"):
    pts = tuple(cs.EtfFlowDay(f"2026-09-{d:02d}", f * 1e6, None)
                for d, f in ((19, 999), (22, 715), (23, 347), (24, 191), (25, 134), (28, -31)))
    return cs.Series("btc_etf_flows", pts, "2026-09-28", origin, {"attribution": cs.ETF_ATTRIBUTION})


def test_lines_are_dated_and_computed():
    line = co.mvrv_line("BTC", _mvrv())
    assert "BTC MVRV 1.20 on 2026-09-28" in line and "since 2016-01-01" in line
    assert "percentile" in line and "MVRV Z" in line and "realized cap $1,250B" in line
    fng = co.fng_line(_fng())
    assert "73/100 (Greed) on 2026-09-29" in fng and "2026-09-22: 78 (Extreme Greed), 7-day change -5" in fng
    etf = co.etf_line(_etf("stale-cache"))
    assert "5 trading days 2026-09-22 to 2026-09-28: +1,356M USD" in etf
    assert "CC BY 4.0" in etf and "stale cache fetched 2026-09-28" in etf


def test_fng_without_a_value_seven_days_earlier():
    s = cs.Series("fear_greed", (cs.FngPoint("2026-09-29", 10, "Extreme Fear"),), "2026-09-29", "live")
    assert "7-day change unavailable" in co.fng_line(s)


@pytest.mark.asyncio
async def test_fetch_partial_and_total_failure(monkeypatch):
    async def mv(asset, today=None):
        if asset == "eth":
            raise cs.CryptoDataUnavailable("eth down")
        return _mvrv()

    async def fng(today=None):
        return _fng()

    async def etf(today=None):
        raise cs.CryptoDataUnavailable("tftc down")
    monkeypatch.setattr(cs, "mvrv_history", mv)
    monkeypatch.setattr(cs, "fear_greed_history", fng)
    monkeypatch.setattr(cs, "etf_flow_history", etf)
    lines = await co.fetch("2026-09-29")
    assert len(lines) == 4 and lines[0].startswith("- BTC MVRV 1.20")
    assert lines[1] == "- ETH MVRV (Coin Metrics): unavailable (CryptoDataUnavailable)"
    assert "unavailable" in lines[3]

    async def down(*a, **k):
        raise cs.CryptoDataUnavailable("down")
    for name in ("mvrv_history", "fear_greed_history", "etf_flow_history"):
        monkeypatch.setattr(cs, name, down)
    with pytest.raises(cs.CryptoDataUnavailable):
        await co.fetch("2026-09-29")


def test_feed_serves_the_crypto_shadows():
    from marketmind.shadows.v3 import roster
    feed = {f.name: f for f in sf.discover()}["crypto_onchain"]
    assert set(feed.shadows) == {"chain_oracle", "defi_scout"}
    assert set(feed.shadows) <= {e.name for e in roster.ROSTER}
    assert sf.serves(feed, "trial_chain_oracle_ab12") and not sf.serves(feed, "vega_trader")
