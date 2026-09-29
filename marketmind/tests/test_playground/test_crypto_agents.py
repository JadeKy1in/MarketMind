"""Crypto pure-code Playground agents onchain_valuation and crypto_tsmom
(docs/PLAYGROUND_AGENTS.md §8): rules on synthetic data, records through the ledger
bridge. No network, no LLM."""
import importlib
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from marketmind.gateway import crypto_signals as cs
from marketmind.gateway.price_history import Bar, PriceHistory
from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.playground import ledger_bridge as lb
from marketmind.playground.agent_manifest import load_manifest

ov = importlib.import_module("marketmind.playground.agents.onchain_valuation.adapter")
ct = importlib.import_module("marketmind.playground.agents.crypto_tsmom.adapter")
AGENTS_DIR = Path(lb.__file__).resolve().parent / "agents"

LAST = date(2026, 9, 20)                                   # last complete bar / data day
NOW = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)       # ISO week 2026-W39


def bars(closes, last=LAST, wiggle=0.01):
    start = last - timedelta(days=len(closes) - 1)
    return [Bar((start + timedelta(days=i)).isoformat(), c, c * (1 + wiggle), c * (1 - wiggle), c, 1e6)
            for i, c in enumerate(closes)]


def trend(n, daily, start=100.0, noise=0.01):
    return [start * (1 + daily) ** i * (1 + (noise if i % 2 else -noise)) for i in range(n)]


# ── onchain_valuation ───────────────────────────────────────────────────────

def mvrv_series(n=1500, last_mvrv=0.5, last=LAST, name="coinmetrics_btc"):
    """MVRV 2 (Z far above 6) for years, then a final day deep under realized value."""
    start = last - timedelta(days=n - 1)
    pts = [cs.MvrvPoint((start + timedelta(days=i)).isoformat(), 2.0, 100.0 + i % 20) for i in range(n - 1)]
    pts.append(cs.MvrvPoint(last.isoformat(), last_mvrv, 100.0))
    return cs.Series(name, tuple(pts), last.isoformat(), "live")


def fng_series(value, label, day=LAST):
    return cs.Series("fear_greed", (cs.FngPoint(day.isoformat(), value, label),), day.isoformat(), "live")


def loaders(fng=(20, "Extreme Fear"), fng_day=LAST, eth_fails=True, btc=None):
    async def load_mvrv(asset):
        if asset == "eth" and eth_fails:
            raise cs.CryptoDataUnavailable("eth down")
        return btc or mvrv_series()

    async def load_fng():
        return fng_series(*fng, day=fng_day)
    return load_mvrv, load_fng


def price_stub(h):
    async def fetch(tickers):
        return {t: h.get(t) for t in tickers}
    return fetch


def test_valuation_replays_the_regime(monkeypatch):
    band = ov.Band("mvrv_z", -0.2, 6.0, "test")
    pts = [cs.MvrvPoint(f"2026-01-{i + 1:02d}", 1.5, 100.0) for i in range(7)]
    path = [None, 1.0, -0.5, 3.0, 6.5, 2.0]
    for tail, zone in ((2.0, "out_of_cycle"), (-0.3, "deep_value"), (7.0, "overheated")):
        monkeypatch.setattr(ov, "metric_series", lambda p, b, t=tail: path + [t])
        v = ov.valuation(pts, band)
        assert v["zone"] == zone and v["regime_last_exit"] == "2026-01-05"
    monkeypatch.setattr(ov, "metric_series", lambda p, b: [None, 1.0, -0.5, 3.0, 2.0, 5.9, 4.0])
    v = ov.valuation(pts, band)
    assert v["zone"] == "in_cycle" and v["regime_entered"] == "2026-01-03" and v["regime_on"]


def test_decide_table():
    assert ov.decide("deep_value", 20) == ("long", 60, 0.65, "deep value band")
    assert ov.decide("deep_value", 50)[:3] == ("long", 60, 0.60)
    assert ov.decide("deep_value", 76)[0] is None                    # Extreme Greed veto
    assert ov.decide("in_cycle", 25)[:3] == ("long", 20, 0.55)
    assert ov.decide("in_cycle", 26)[0] is None
    assert ov.decide("overheated", 5)[0] is None and ov.decide("out_of_cycle", 5)[0] is None


def test_eth_percentile_band_ignores_the_first_year():
    pts = [cs.MvrvPoint(f"d{i}", 1.0 + i / 1000, 1.0) for i in range(400)]
    vals = ov.metric_series(pts, ov.BANDS["eth"])
    assert vals[363] is None and vals[364] == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_onchain_deep_value_long_with_stop_and_week_key(tmp_path):
    load_mvrv, load_fng = loaders()
    h = {"BTC-USD": bars([100.0] * 60)}
    out = await ov.analyze({}, now=NOW, store=LedgerStore(tmp_path / "l.db"),
                           fetch_prices=price_stub(h), load_mvrv=load_mvrv, load_fng=load_fng)
    [c] = out["directional_calls"]
    assert c["ticker"] == "BTC-USD" and c["direction"] == "long" and c["hold_bars"] == 60
    assert c["confidence"] == 0.65 and c["signal_key"] == "BTC-USD:2026-W39"
    assert c["falsifier_rule"] == {"type": "close_below", "price": pytest.approx(94.0)}
    s = c["signal"]
    assert s["zone"] == "deep_value" and s["mvrv_z"] < -0.2 and s["fear_greed"]["value"] == 20
    assert out["unavailable"]["ETH-USD"].startswith("MVRV unavailable")


@pytest.mark.asyncio
async def test_onchain_greed_veto_stale_inputs_and_held_guard(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    h = price_stub({"BTC-USD": bars([100.0] * 60)})
    load_mvrv, load_fng = loaders(fng=(80, "Extreme Greed"))
    out = await ov.analyze({}, now=NOW, store=store, fetch_prices=h, load_mvrv=load_mvrv, load_fng=load_fng)
    assert out["directional_calls"] == [] and "Extreme Greed" in out["no_calls_reason"]
    load_mvrv, load_fng = loaders(fng_day=LAST - timedelta(days=3))
    out = await ov.analyze({}, now=NOW, store=store, fetch_prices=h, load_mvrv=load_mvrv, load_fng=load_fng)
    assert "stale" in out["no_calls_reason"]
    load_mvrv, load_fng = loaders(btc=mvrv_series(last=LAST - timedelta(days=5)))
    out = await ov.analyze({}, now=NOW, store=store, fetch_prices=h, load_mvrv=load_mvrv, load_fng=load_fng)
    assert out["unavailable"]["BTC-USD"].startswith("MVRV stale")
    load_mvrv, load_fng = loaders(btc=mvrv_series(n=500))
    out = await ov.analyze({}, now=NOW, store=store, fetch_prices=h, load_mvrv=load_mvrv, load_fng=load_fng)
    assert out["unavailable"]["BTC-USD"].startswith("insufficient MVRV history")
    store.add(LedgerEntry(source_type="playground", source_id="playground:onchain_valuation",
                          ticker="BTC-USD", direction="long", hold_bars=60, confidence=0.6,
                          position_usd=280, falsifier="x", thesis="x"))
    load_mvrv, load_fng = loaders()
    out = await ov.analyze({}, now=NOW, store=store, fetch_prices=h, load_mvrv=load_mvrv, load_fng=load_fng)
    assert out["directional_calls"] == [] and "BTC-USD" in out["skipped"]
    out = await ov.analyze({}, now=NOW, store=store, fetch_prices=price_stub({}),
                           load_mvrv=load_mvrv, load_fng=load_fng)
    assert out["directional_calls"] == []                          # held guard before prices


@pytest.mark.asyncio
async def test_onchain_without_candles_is_unavailable(tmp_path):
    load_mvrv, load_fng = loaders()
    out = await ov.analyze({}, now=NOW, store=LedgerStore(tmp_path / "l.db"),
                           fetch_prices=price_stub({}), load_mvrv=load_mvrv, load_fng=load_fng)
    assert out["directional_calls"] == [] and out["unavailable"]["BTC-USD"].startswith("no price history")


# ── crypto_tsmom ────────────────────────────────────────────────────────────

def tsmom_histories():
    h = {t: bars(trend(300, 0.004)) for t in ct.UNIVERSE}
    h["ETH-USD"] = bars(trend(300, -0.004))                        # falling: flat
    h["XRP-USD"] = bars(trend(100, 0.004))                         # too short
    h["DOGE-USD"] = None                                           # no data
    h["ADA-USD"] = bars(trend(300, 0.004), last=LAST - timedelta(days=9))   # stale
    return h


def test_tsmom_strength_is_the_mean_vol_scaled_return():
    h = tsmom_histories()
    rows, missing = ct.signals(h, LAST)
    assert rows["ETH-USD"]["direction"] is None and rows["BTC-USD"]["direction"] == "long"
    assert set(missing) == {"XRP-USD", "DOGE-USD", "ADA-USD"}
    assert missing["XRP-USD"].startswith("insufficient") and missing["ADA-USD"].startswith("stale")
    b, s = h["BTC-USD"], rows["BTC-USD"]
    from marketmind.playground.agents import _quant as q
    vol = q.ewma_vol(b, "BTC-USD")
    expect = sum((b[-1].close / b[-1 - k].close - 1) / (vol * math.sqrt(k / 365))
                 for k in ct.LOOKBACKS) / 4
    assert s["strength"] == pytest.approx(expect, abs=1e-4) and s["vol_ann"] == pytest.approx(vol, abs=1e-4)


@pytest.mark.asyncio
async def test_tsmom_calls_and_bridge_records_once_per_week(tmp_path):
    h = tsmom_histories()
    out = await ct.analyze({}, fetch=price_stub(h), now=NOW)
    calls = {c["ticker"]: c for c in out["directional_calls"]}
    assert set(calls) == {"BTC-USD", "SOL-USD", "LINK-USD", "LTC-USD", "BCH-USD", "AVAX-USD"}
    c = calls["BTC-USD"]
    assert c["hold_bars"] == 7 and c["signal_key"] == "BTC-USD:2026-W39"
    assert 0.5 <= c["confidence"] <= 0.65 and c["falsifier_rule"]["type"] == "close_below"
    store = LedgerStore(tmp_path / "l.db")
    manifests = {"crypto_tsmom": load_manifest(AGENTS_DIR / "crypto_tsmom")}
    res = SimpleNamespace(decisions=[SimpleNamespace(agent_id="crypto_tsmom", run_id="r",
                                                     directional_calls=out["directional_calls"],
                                                     metadata={"mock_mode": False})])

    async def hist_fn(tickers):
        return {t: PriceHistory(t, "static", h[t], []) for t in tickers if h.get(t)}
    s = await lb.record_run(store, res, manifests, today="2026-09-21", tradable=lambda t: True,
                            histories_fn=hist_fn)
    rows = {e.ticker: e for e in store.list(source_type="playground")}
    assert set(rows) == set(calls) and s["dropped"] == []
    e = rows["BTC-USD"]
    assert e.source_id == "playground:crypto_tsmom" and e.hold_bars == 7
    assert e.falsifier_rule["type"] == "close_below" and e.meta["signal_key"] == "BTC-USD:2026-W39"
    assert e.meta["signal"]["strength"] == out["signals"]["BTC-USD"]["strength"]
    assert e.domain_benchmark == "BTC-USD"
    s = await lb.record_run(store, res, manifests, today="2026-09-22", tradable=lambda t: True,
                            histories_fn=hist_fn)
    assert s["recorded"] == {} and len(s["dropped"]) == len(calls)


@pytest.mark.asyncio
async def test_onchain_records_through_the_bridge(tmp_path):
    load_mvrv, load_fng = loaders()
    h = {"BTC-USD": bars([100.0] * 60)}
    store = LedgerStore(tmp_path / "l.db")
    out = await ov.analyze({}, now=NOW, store=store, fetch_prices=price_stub(h),
                           load_mvrv=load_mvrv, load_fng=load_fng)
    res = SimpleNamespace(decisions=[SimpleNamespace(agent_id="onchain_valuation", run_id="r",
                                                     directional_calls=out["directional_calls"],
                                                     metadata={"mock_mode": False})])

    async def hist_fn(tickers):
        return {t: PriceHistory(t, "static", h[t], []) for t in tickers if h.get(t)}
    await lb.record_run(store, res, {"onchain_valuation": load_manifest(AGENTS_DIR / "onchain_valuation")},
                        today="2026-09-21", tradable=lambda t: True, histories_fn=hist_fn)
    [e] = store.list(source_type="playground")
    assert e.hold_bars == 60 and e.meta["signal"]["zone"] == "deep_value"
    assert e.meta["model"] == ov.MODEL and e.falsifier_rule["price"] == pytest.approx(94.0)


# ── manifests / contract ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_manifests_mock_mode_and_no_llm():
    cites = {"onchain_valuation": "Grobys", "crypto_tsmom": "Tsyvinski"}
    for aid, mod in (("onchain_valuation", ov), ("crypto_tsmom", ct)):
        m = load_manifest(AGENTS_DIR / aid)
        assert m is not None and m.agent_id == aid and m.domain_benchmark == "BTC-USD"
        assert cites[aid] in m.description and "zero-llm" in m.tags
        assert (await mod.analyze({}, mock=True))["directional_calls"] == []
        src = (AGENTS_DIR / aid / "adapter.py").read_text(encoding="utf-8")
        assert "async_client" not in src and "chat_" not in src
    assert set(load_manifest(AGENTS_DIR / "crypto_tsmom").domain_universe) == set(ct.UNIVERSE)
