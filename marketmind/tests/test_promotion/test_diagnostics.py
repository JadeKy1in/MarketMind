"""Promotion diagnostics (docs/S7_DESIGN.md §三 / §四): factor data, factor regression,
style drift, paper-to-live gap, runner storage. Offline."""
from __future__ import annotations

import io
import json
import math
import zipfile
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from marketmind.gateway import factor_data as FD
from marketmind.gateway.price_history import Bar
from marketmind.ledger.prices import StaticPriceSource
from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.promotion import factors as FA
from marketmind.promotion import paper_live as PL
from marketmind.promotion.runner import read_diagnostics, run_promotion
from marketmind.shadows.v3.roster import RosterEntry

DAYS = [str(d) for d in np.arange(np.datetime64("2025-01-06"), np.datetime64("2026-06-30"),
                                  dtype="datetime64[D]") if np.is_busday(d)]


# ── Factor data ─────────────────────────────────────────────────────────

FF5_CSV = """This file was created by using the 202608 CRSP database.
Some header text

,Mkt-RF,SMB,HML,RMW,CMA,RF
20250106,   1.00,   -0.50,    0.20,    0.00,    0.10,    0.02
20250107,  -0.25,    0.30,  -99.99,    0.00,    0.10,    0.02
20250108,   0.40,    0.10,    0.00,   -0.10,    0.00,    0.02

 Annual Factors: January-December
,Mkt-RF,SMB,HML,RMW,CMA,RF
  2025,  10.00,  1.00, 1.00, 1.00, 1.00, 4.00

Copyright 2026 Eugene F. Fama and Kenneth R. French
"""
MOM_CSV = """Momentum header

,Mom
20250106,   0.50
20250107,  -0.10
20250108,   0.20
Copyright
"""


def _zip(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("x.csv", text)
    return buf.getvalue()


def test_parse_french_csv_daily_block_only():
    rows = FD.parse_french_csv(FF5_CSV)
    assert sorted(rows) == ["2025-01-06", "2025-01-08"]          # -99.99 row skipped, annual block ignored
    assert rows["2025-01-06"]["MKT"] == pytest.approx(0.01)
    assert rows["2025-01-06"]["RF"] == pytest.approx(0.0002)
    assert FD.parse_french_csv(MOM_CSV)["2025-01-07"]["MOM"] == pytest.approx(-0.001)


def test_french_factors_cache_refresh_and_stale_fallback(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        return _zip(FF5_CSV if "5_Factors" in url else MOM_CSV)

    now = datetime(2026, 9, 29, tzinfo=timezone.utc)
    t = FD.french_factors(tmp_path, fetch=fetch, now=now)
    assert t.source == "french" and t.names == FD.FRENCH_NAMES and t.days == ["2025-01-06", "2025-01-08"]
    assert t.values[0].tolist() == pytest.approx([0.01, -0.005, 0.002, 0.0, 0.001, 0.005])
    assert t.rf.tolist() == pytest.approx([0.0002, 0.0002])
    assert len(calls) == 2 and (tmp_path / "french_ff5.csv").exists()
    FD.french_factors(tmp_path, fetch=fetch, now=now + timedelta(days=1))
    assert len(calls) == 2                                         # fresh cache: no download

    def broken(url):
        raise OSError("offline")
    stale = FD.french_factors(tmp_path, fetch=broken, now=now + timedelta(days=30))
    assert stale is not None and stale.days == t.days             # stale cache still used
    assert FD.french_factors(tmp_path / "empty", fetch=broken, now=now) is None


def _bars_from_returns(rets, days, start=100.0, volume=1e6, rng=0.02):
    """Bars whose close-to-close returns are `rets` (first bar at `start`); open = previous close."""
    out, prev = [], start
    out.append(Bar(days[0], start, start * (1 + rng / 2), start * (1 - rng / 2), start, volume))
    for d, r in zip(days[1:], rets):
        c = prev * (1 + r)
        out.append(Bar(d, prev, max(prev, c) * (1 + rng / 2), min(prev, c) * (1 - rng / 2), c, volume))
        prev = c
    return out


def test_etf_proxy_factors_definitions():
    rng = np.random.default_rng(0)
    days = DAYS[:30]
    rets = {t: rng.normal(0, 0.01, 29) for t in FD.PROXY_TICKERS}
    bars = {t: _bars_from_returns(r, days) for t, r in rets.items()}
    t = FD.etf_proxy_factors(bars)
    assert t.source == "etf_proxy" and t.names == ("MKT", "SMB", "HML", "MOM") and t.days == days[1:]
    np.testing.assert_allclose(t.values[:, 0], rets["SPY"] - rets["BIL"], atol=1e-12)
    np.testing.assert_allclose(t.values[:, 1], rets["IWM"] - rets["SPY"], atol=1e-12)
    np.testing.assert_allclose(t.values[:, 2], rets["IWD"] - rets["IWF"], atol=1e-12)
    np.testing.assert_allclose(t.values[:, 3], rets["MTUM"] - rets["SPY"], atol=1e-12)
    np.testing.assert_allclose(t.rf, rets["BIL"], atol=1e-12)
    assert FD.etf_proxy_factors({**bars, "MTUM": None}) is None


def test_aligned_returns_compound_weekends():
    cal_days = [str(d) for d in np.arange(np.datetime64("2025-01-01"), np.datetime64("2025-01-15"),
                                          dtype="datetime64[D]")]
    bars = [Bar(d, 0, 0, 0, 100.0 + i, 1) for i, d in enumerate(cal_days)]
    r = FD.aligned_returns(bars, ["2025-01-03", "2025-01-06", "2025-01-07"])   # Fri, Mon, Tue
    assert r.tolist() == pytest.approx([105 / 102 - 1, 106 / 105 - 1])
    assert FD.aligned_returns(bars, ["2025-01-03", "2025-01-30"]) is None      # stale bar


# ── Regression ──────────────────────────────────────────────────────────

def test_ols_hac_hand_value_and_recovery():
    rng = np.random.default_rng(1)
    n = 300
    F = rng.normal(0, 0.01, (n, 2))
    y = 0.0005 + 0.8 * F[:, 0] - 0.3 * F[:, 1] + rng.normal(0, 0.002, n)
    X = np.column_stack([np.ones(n), F])
    fit = FA.ols_hac(y, X, 0)
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    inv = np.linalg.inv(X.T @ X)
    white = inv @ (X.T * e ** 2) @ X @ inv * n / (n - 3)
    np.testing.assert_allclose(fit["coef"], b, rtol=1e-9)
    np.testing.assert_allclose(fit["se"], np.sqrt(np.diag(white)), rtol=1e-9)
    assert fit["coef"][1] == pytest.approx(0.8, abs=0.05) and fit["coef"][2] == pytest.approx(-0.3, abs=0.05)
    assert 0.9 < fit["r2"] <= 1 and fit["adj_r2"] < fit["r2"]
    # Bartlett weights with lag 2 on the score cross-products
    u = X * e[:, None]
    S = u.T @ u + sum((1 - l / 3) * (u[l:].T @ u[:-l] + u[:-l].T @ u[l:]) for l in (1, 2))
    np.testing.assert_allclose(FA.ols_hac(y, X, 2)["se"],
                               np.sqrt(np.diag(inv @ S @ inv * n / (n - 3))), rtol=1e-9)
    assert FA.hac_lag(40) == 3 and FA.hac_lag(100) == 4 and FA.hac_lag(1) == 1


# ── Mark-to-market ──────────────────────────────────────────────────────

def _trade(ticker, entry, exit_, entry_price, exit_price, position=1000.0, direction="long",
           pnl=None, sid="S", **kw):
    sign = 1 if direction == "long" else -1
    gross = sign * (exit_price / entry_price - 1)
    net = gross - kw.pop("cost", 0.0)
    return LedgerEntry("shadow", sid, ticker, direction, 1, 0.6, position, "x", status="settled",
                       created_at=kw.pop("created_at", entry + "T00:00:00Z"),
                       entry_date=entry, exit_date=exit_, entry_price=entry_price,
                       exit_price=exit_price, net_return=net,
                       pnl_usd=pnl if pnl is not None else position * net, **kw)


def test_mark_to_market_sums_to_ledger_pnl():
    bars = [Bar("2025-01-06", 100, 0, 0, 102, 1), Bar("2025-01-07", 102, 0, 0, 99, 1),
            Bar("2025-01-08", 99, 0, 0, 101, 1)]
    e = _trade("AAA", "2025-01-06", "2025-01-08", 100.0, 103.0, position=1000.0, cost=0.001)
    s = _trade("BBB", "2025-01-06", "2025-01-08", 50.0, 49.0, position=500.0, direction="short")
    m = FA.mark_to_market([e, s], {"AAA": bars}, notional=10_000)
    assert m["marked"] == 1 and m["spread"] == 1
    assert m["pnl"]["2025-01-06"] == pytest.approx((10 * 2 + e_spread(s)) / 10_000)
    assert m["pnl"]["2025-01-07"] == pytest.approx((10 * -3 + e_spread(s)) / 10_000)
    # exit day: 10 shares x (103 - 101) plus the ledger cost (-$1) booked on exit
    assert m["pnl"]["2025-01-08"] == pytest.approx((10 * 4 - 1 + e_spread(s)) / 10_000)
    assert sum(m["pnl"].values()) == pytest.approx((e.pnl_usd + s.pnl_usd) / 10_000)
    assert m["net"]["2025-01-07"] == pytest.approx((1000 - 500) / 10_000)
    assert m["gross"]["2025-01-07"] == pytest.approx(1500 / 10_000)


def e_spread(s):
    return s.pnl_usd / 3


def test_align_sums_weekends_into_monday():
    series, after = FA.align({"2025-01-03": 1.0, "2025-01-04": 2.0, "2025-01-05": 3.0,
                              "2025-01-06": 4.0, "2025-01-08": 5.0},
                             ["2025-01-03", "2025-01-06", "2025-01-07"])
    assert series.tolist() == [1.0, 9.0, 0.0] and after == 5.0


# ── Per-shadow analysis ─────────────────────────────────────────────────

class _Provider(FA.FactorProvider):
    def __init__(self, bars, french=None):
        super().__init__(lambda ts: {t: bars.get(t) for t in ts}, None, french=french)


def _world(n=120, beta=(0.8, 0.3), alpha=0.0004, seed=2, beta_after=None, split=None):
    """Proxy ETFs with random returns and a ticker X whose daily return is
    rf + alpha + b1 MKT + b2 SMB + noise; the shadow buys $10k of X at every open and
    sells at the close (entry = exit day), so its daily P&L / notional is X's return."""
    rng = np.random.default_rng(seed)
    days = DAYS[:n + 1]
    rets = {t: rng.normal(0.0003, 0.01, n) for t in FD.PROXY_TICKERS}
    rets["BIL"] = np.full(n, 0.00015)
    mkt, smb = rets["SPY"] - rets["BIL"], rets["IWM"] - rets["SPY"]
    b1 = np.full(n, beta[0])
    if beta_after is not None:
        b1[split:] = beta_after
    x = rets["BIL"] + alpha + b1 * mkt + beta[1] * smb + rng.normal(0, 0.001, n)
    bars = {t: _bars_from_returns(r, days) for t, r in rets.items()}
    bars["X"] = _bars_from_returns(x, days)
    trades = [_trade("X", b.date, b.date, b.open, b.close, position=10_000.0)
              for b in bars["X"][1:]]
    return bars, trades, x


def test_analyze_recovers_alpha_and_betas_on_proxies():
    bars, trades, _ = _world()
    res = FA.analyze(trades, _Provider(bars))
    assert res["status"] == "ok" and res["source"] == "etf_proxy" and res["obs"] == 120
    assert res["factors"] == ["MKT", "SMB", "HML", "MOM"] and res["meaningful"]
    assert res["betas"]["MKT"]["beta"] == pytest.approx(0.8, abs=0.06)
    assert res["betas"]["SMB"]["beta"] == pytest.approx(0.3, abs=0.08)
    assert abs(res["betas"]["HML"]["beta"]) < 0.1
    assert res["alpha_daily"] == pytest.approx(0.0004, abs=0.0003)
    assert res["alpha_annual"] == pytest.approx(res["alpha_daily"] * 252)
    assert res["alpha_t"] > 1 and res["hac_lag"] == FA.hac_lag(120)
    assert res["mtm"] == {"marked": 120, "spread": 0, "skipped": 0, "pnl_after_window": 0.0}
    assert res["mean_gross_exposure"] == pytest.approx(1.0)
    assert res["rolling"]["window"] == 40 and res["rolling"]["days"][-1] == DAYS[120]
    assert res["drift"]["status"] == "ok"


def test_style_drift_flags_a_beta_shift_only():
    bars, trades, _ = _world(n=160, beta_after=2.0, split=120, seed=5)
    res = FA.analyze(trades, _Provider(bars))
    assert "MKT" in res["drift"]["flags"]
    assert res["drift"]["detail"]["MKT"]["recent"] == pytest.approx(2.0, abs=0.2)
    assert res["drift"]["prior_days"] == 120
    bars, trades, _ = _world(n=160, seed=5)
    assert "MKT" not in FA.analyze(trades, _Provider(bars))["drift"]["flags"]
    bars, trades, _ = _world(n=60)
    assert FA.analyze(trades, _Provider(bars))["drift"]["status"] == "insufficient"


def test_insufficient_sample_fetches_nothing():
    def boom(_):
        raise AssertionError("no data should be loaded")
    p = FA.FactorProvider(boom, None, french=None)
    trades = [_trade("X", DAYS[i], DAYS[i], 100, 101) for i in range(39)]
    res = FA.analyze(trades, p)
    assert res["status"] == "insufficient" and res["obs"] == 39
    assert FA.analyze([], p)["status"] == "insufficient"


def test_french_used_when_it_covers_the_window_else_proxies():
    bars, trades, _ = _world()
    n = len(DAYS)
    rng = np.random.default_rng(9)
    french = FD.FactorTable("french", FD.FRENCH_NAMES, DAYS, rng.normal(0, 0.01, (n, 6)),
                            np.full(n, 0.0001))
    res = FA.analyze(trades, _Provider(bars, french=french))
    assert res["source"] == "french" and res["factors"] == list(FD.FRENCH_NAMES)
    short = FD.FactorTable("french", FD.FRENCH_NAMES, DAYS[:60], french.values[:60], french.rf[:60])
    assert FA.analyze(trades, _Provider(bars, french=short))["source"] == "etf_proxy"
    assert FA.analyze(trades, _Provider({}, french=None))["status"] == "unavailable"


def test_crypto_heavy_shadow_gets_btc_factor_and_is_not_meaningful():
    bars, _, _ = _world()
    rng = np.random.default_rng(3)
    cal = [str(d) for d in np.arange(np.datetime64(DAYS[0]) - 5, np.datetime64(DAYS[130]) + 1,
                                     dtype="datetime64[D]")]
    btc_r = rng.normal(0, 0.03, len(cal) - 1)
    bars["BTC-USD"] = _bars_from_returns(btc_r, cal, start=50_000.0)
    trades = [_trade("BTC-USD", b.date, b.date, b.open, b.close, position=5_000.0)
              for b in bars["BTC-USD"][6:] if b.date <= DAYS[120]]
    res = FA.analyze(trades, _Provider(bars))
    assert res["status"] == "ok" and res["factors"][-1] == "BTC"
    assert res["crypto_share"] == pytest.approx(1.0) and res["meaningful"] is False
    # weekend P&L lands on Monday; BTC is the whole return: beta ~ exposure (0.5)
    assert res["betas"]["BTC"]["beta"] == pytest.approx(0.5, abs=0.05)
    assert any("crypto" in n for n in res["notes"])


# ── Paper-to-live gap ───────────────────────────────────────────────────

def _flat_bars(days, price=100.0, rng=2.0, volume=1e6):
    return [Bar(d, price, price + rng / 2, price - rng / 2, price, volume) for d in days]


def test_extra_cost_hand_value_liquid_and_illiquid():
    days = DAYS[:40]
    e = _trade("AAA", DAYS[30], DAYS[32], 100.0, 101.0, position=1000.0)
    liquid = _flat_bars(days, volume=1e6)                          # ADV $100M, ATR 2%
    inp = PL.trade_inputs(e, liquid)
    assert inp["tier"] == "liquid" and inp["atr_pct"] == pytest.approx(0.02)
    assert inp["adv"] == pytest.approx(1e8) and inp["sigma"] == pytest.approx(0.0)
    x, unknown = PL.extra_cost(e, inp)
    assert not unknown and x == pytest.approx(2 * 0.05 * 0.02)      # 20 bp round trip
    thin = _flat_bars(days, volume=1e4)                             # ADV $1M -> x4
    inp = PL.trade_inputs(e, thin)
    assert inp["tier"] == "illiquid" and PL.extra_cost(e, inp)[0] == pytest.approx(2 * 0.05 * 0.02 * 4)
    # the review's ATR wins; sqrt impact with sigma
    e.review = {"atr_pct": 0.03}
    inp = {"atr_pct": 0.03, "sigma": 0.02, "adv": 4e6, "tier": "illiquid", "multiplier": 4.0}
    assert PL.extra_cost(e, inp)[0] == pytest.approx(2 * (0.05 * 0.03 * 4 + 0.02 * math.sqrt(1000 / 4e6)))
    assert PL.trade_inputs(e, liquid)["atr_pct"] == 0.03
    # no bars: unknown fallback; FX without volume is x1
    e.review = None
    assert PL.extra_cost(e, PL.trade_inputs(e, None)) == (2 * PL.UNKNOWN_SIDE_COST, True)
    fx = _trade("EURUSD=X", DAYS[30], DAYS[32], 1.0, 1.01)
    assert PL.trade_inputs(fx, _flat_bars(days, 1.0, 0.02, volume=0))["tier"] == "fx"
    # futures (contracts) and non-US listings (local currency): no dollar ADV, x2
    for t, tier in (("GC=F", "future"), ("7203.T", "non_usd")):
        f = _trade(t, DAYS[30], DAYS[32], 100.0, 101.0)
        inp = PL.trade_inputs(f, liquid)
        assert (inp["tier"], inp["multiplier"], inp["adv"]) == (tier, 2.0, None)
        assert PL.extra_cost(f, inp)[0] == pytest.approx(2 * 0.05 * 0.02 * 2)


def test_paper_live_analysis_and_live_ready():
    days = DAYS[:120]
    bars = {"AAA": _flat_bars(days, volume=1e6), "THIN": _flat_bars(days, volume=2e3)}
    rows = []
    for i in range(40):
        t = _trade("AAA", DAYS[30 + i], DAYS[31 + i], 100.0, 100.5, position=1000.0,
                   excess_domain=0.004)
        rows.append(t)
    res = PL.analyze(rows, bars, record_days=40)
    assert res["status"] == "ok" and res["trades"] == 40
    assert res["extra_cost_mean"] == pytest.approx(0.002)
    assert res["live_mean_net"] == pytest.approx(res["paper_mean_net"] - 0.002)
    assert res["live_mean_excess_domain"] == pytest.approx(0.002)
    assert res["live_pnl_usd"] == pytest.approx(res["paper_pnl_usd"] - 40 * 1000 * 0.002)
    assert res["capacity"]["breaches"] == 0 and res["live_ready"]
    # a loss stays a (larger) loss: no proportional discount
    loss = [_trade("AAA", DAYS[30], DAYS[31], 100.0, 99.0, excess_domain=-0.01)]
    out = PL.analyze(loss, bars, record_days=1)
    assert out["live_mean_net"] < out["paper_mean_net"] < 0 and out["status"] == "insufficient"
    assert not out["live_ready"] and not out["live_ready_checks"]["sample"]
    # edge above the domain benchmark smaller than the haircut -> not live-ready
    thin_edge = [_trade("AAA", DAYS[30 + i], DAYS[31 + i], 100.0, 100.5, excess_domain=0.001)
                 for i in range(40)]
    r = PL.analyze(thin_edge, bars, record_days=40)
    assert r["paper_mean_excess_domain"] > 0 and not r["live_ready_checks"]["beats_domain_after_costs"]
    # capacity: $5000 > 1% of a $200k ADV on every trade
    thin = [_trade("THIN", DAYS[30 + i], DAYS[31 + i], 100.0, 100.5, position=5000.0,
                   excess_domain=0.05)
            for i in range(40)]
    r = PL.analyze(thin, bars, record_days=40)
    assert r["capacity"]["breaches"] == 40 and r["capacity"]["capacity_usd_p10"] == pytest.approx(2000)
    assert not r["live_ready"] and r["tiers"] == {"illiquid": 40}
    assert PL.analyze([], bars, 0)["status"] == "empty"


# ── Runner ──────────────────────────────────────────────────────────────

def _roster(*ids):
    return [RosterEntry(s, s, s, "fundamental", "d", ("X",), "SPY", "active") for s in ids]


def test_run_promotion_stores_diagnostics(tmp_path):
    bars, trades, _ = _world()
    store = LedgerStore(tmp_path / "ledger.db")
    for e in trades:
        store.add(e, created_at=e.created_at)
    kw = dict(data_dir=tmp_path, roster=_roster("S", "T"), active_ids={"S", "T"},
              price_source=StaticPriceSource(bars))
    run_promotion(store, today=DAYS[125], factor_provider=_Provider(bars), **kw)
    diag = read_diagnostics(tmp_path)
    assert diag["updated_at"] == DAYS[125] and diag["meta"]["sources_used"] == ["etf_proxy"]
    s = read_diagnostics(tmp_path, "S")
    assert s["factors"]["status"] == "ok" and s["paper_live"]["trades"] == 120
    assert read_diagnostics(tmp_path, "T")["factors"]["status"] == "insufficient"
    assert read_diagnostics(tmp_path, "nobody") == {}
    # a failing diagnostics provider never fails the promotion run
    class Broken(_Provider):
        def table_for(self, lo, hi):
            raise RuntimeError("boom")
    out = run_promotion(store, today=DAYS[126], factor_provider=Broken(bars), **kw)
    assert out["stages"]
    state = json.loads((tmp_path / "promotion" / "state.json").read_text(encoding="utf-8"))
    assert state["updated_at"] == DAYS[126]
