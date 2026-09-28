"""S10 wiring: discovery -> L3 tickers / decision text / ledger origin / watch items."""
from marketmind.discovery.series import Series, pricing_base_date
from marketmind.pipeline import orchestration as orch
from marketmind.pipeline.decision import DecisionOutput, WatchCard


def _report():
    def proxy(t, d, bucket):
        return {"ticker": t, "direction": d, "bucket": bucket, "move_atr": 0.2,
                "origin": {"kind": "anomaly", "series": ["fred:WRESBAL"],
                           "anomaly_id": "2026-09-28:fred:WRESBAL", "priced_in": bucket, "coverage": 0}}
    a = {"anomaly_id": "2026-09-28:fred:WRESBAL", "series": "fred:WRESBAL", "title": "Reserves",
         "cold": True, "coverage": 0, "z": -2.5, "obs_date": "2026-09-23",
         "proxies": [proxy("SPY", "short", "not_priced"), proxy("TLT", "long", "priced_in")]}
    return {"anomalies": [a], "counts": {}}


def test_discovery_helpers():
    rep = _report()
    assert orch._discovery_tickers(rep) == ["SPY"]            # priced-in TLT is not a candidate
    assert orch._discovery_origins(rep)["SPY"]["anomaly_id"] == "2026-09-28:fred:WRESBAL"
    assert orch._discovery_tickers(None) == [] and orch._discovery_text(None) == ""
    assert orch._discovery_origins(None) == {}


def test_watch_items_map_conditions_and_origins():
    card = WatchCard(ticker="SPY", direction="short", thesis="wait",
                     conditions=[{"type": "close_below", "value": 700.0},
                                 {"type": "close_below_ma", "value": 50},
                                 {"type": "volume_ratio_at_least", "value": 1.5},
                                 {"type": "after_date", "value": "2026-10-02"},
                                 {"type": "breakout_20d"}],
                     invalidation=[{"type": "close_above", "value": 760.0}], expiry_days=15)
    items = orch.watch_items(DecisionOutput(watch_cards=[card]), _report())
    main, anomaly = items
    assert main["source"] == "main_pipeline" and main["expiry_bars"] == 15
    assert main["conditions"] == [{"type": "close_below", "price": 700.0},
                                  {"type": "close_below_ma", "period": 50},
                                  {"type": "volume_ratio_at_least", "ratio": 1.5},
                                  {"type": "after_date", "date": "2026-10-02"},
                                  {"type": "breakout_20d"}]
    assert main["invalidation"] == [{"type": "close_above", "price": 760.0}]
    assert main["origin"]["kind"] == "anomaly"
    assert anomaly["source"] == "anomaly" and anomaly["ticker"] == "SPY" and "conditions" not in anomaly
    other = orch.watch_items(DecisionOutput(watch_cards=[WatchCard("XLE", "long", "t", [])]), None)
    assert other[0]["origin"] == {"kind": "news"} and len(other) == 1


def test_warm_anomalies_do_not_become_watch_items():
    rep = _report()
    rep["anomalies"][0]["cold"] = False
    assert orch.watch_items(None, rep) == []


def test_crypto_registry_is_crypto_only():
    ids = [s.id for s in orch.crypto_registry()]
    assert ids and all(i.startswith(("okx:", "defillama:")) for i in ids)


def test_pricing_base_date_follows_publication_lag():
    def s(sid, freq, lag=None):
        return Series(sid, "t", freq, "u", "src", fetch=None, release_lag_days=lag)
    assert pricing_base_date(s("fred:BAMLH0A0HYM2", "daily"), "2026-09-24") == "2026-09-24"
    assert pricing_base_date(s("fred:WRESBAL", "weekly"), "2026-09-23") == "2026-09-24"
    assert pricing_base_date(s("eia:WCESTUS1", "weekly"), "2026-09-19") == "2026-09-23"
    assert pricing_base_date(s("x:y", "weekly", lag=3), "2026-09-23") == "2026-09-26"
