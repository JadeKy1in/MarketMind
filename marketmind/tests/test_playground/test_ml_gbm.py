"""ml_gbm Playground agent (docs/PLAYGROUND_AGENTS.md §7): no-leakage features and
training windows, determinism, call caps, weekly model cache. Synthetic bars only;
no network, no LLM."""
import importlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from marketmind.gateway.price_history import Bar
from marketmind.ledger.store import LedgerStore
from marketmind.playground import ledger_bridge as lb
from marketmind.playground.agent_manifest import load_manifest
from marketmind.playground.agents.ml_gbm import features as F
from marketmind.playground.agents.ml_gbm import model as M

ad = importlib.import_module("marketmind.playground.agents.ml_gbm.adapter")
AGENT_DIR = Path(lb.__file__).resolve().parent / "agents" / "ml_gbm"
LAST = date(2026, 9, 28)                      # a Monday; last complete synthetic bar
NOW = datetime(2026, 9, 29, 14, tzinfo=timezone.utc)
TICKERS = ("SPY", "QQQ", "XLK", "XLE", "GLD", "BTC-USD")
N = 800


def walk(seed, n=N, last=LAST, drift=0.0003, vol=0.012):
    rng = np.random.default_rng(seed)
    r = drift + vol * rng.standard_normal(n)
    c = 100 * np.exp(np.cumsum(r))
    start = last - timedelta(days=n - 1)
    return [Bar((start + timedelta(days=i)).isoformat(), float(c[i]), float(c[i] * 1.01),
                float(c[i] * 0.99), float(c[i]), float(1e6 * (1 + rng.random())))
            for i in range(n)]


@pytest.fixture(scope="module")
def hist():
    return {t: walk(i) for i, t in enumerate(TICKERS)}


@pytest.fixture(scope="module")
def panel(hist):
    return F.build_panel(hist)


def fetch_stub(histories):
    async def fetch(tickers):
        return ({t: histories.get(t) for t in tickers},
                {t: "static" for t in tickers if histories.get(t)})
    return fetch


# ── features and labels ─────────────────────────────────────────────────────

def test_features_use_only_bars_up_to_the_row_date(hist, panel):
    k = 600
    cut = hist["XLK"][k].date
    truncated = {t: [b for b in bars if b.date <= cut] for t, bars in hist.items()}
    small = F.build_panel(truncated)
    for p in (panel, small):
        assert p.features == F.FEATURES and p.X.shape[1] == len(F.FEATURES)
    d = np.datetime64(cut)
    full_rows = panel.X[panel.date == d]
    trunc_rows = small.X[small.date == d]
    assert full_rows.shape == trunc_rows.shape == (len(TICKERS), len(F.FEATURES))
    np.testing.assert_array_equal(full_rows, trunc_rows)   # nothing after d changes row d
    # the label, which does look ahead, is unknown in the truncated panel
    assert np.isnan(small.label[small.date == d]).all()


def test_label_is_the_forward_return_net_of_round_trip_cost(hist):
    f = F.instrument_features("BTC-USD", hist["BTC-USD"])
    assert F.round_trip_cost("BTC-USD") == pytest.approx(0.02)
    assert F.round_trip_cost("XLK") == pytest.approx(0.001)
    i = 500
    fwd = hist["BTC-USD"][i + 10].close / hist["BTC-USD"][i].close - 1
    assert f["fwd_ret"][i] == pytest.approx(fwd) and f["label"][i] == float(fwd > 0.02)
    assert str(f["label_end"][i]) == hist["BTC-USD"][i + 10].date
    assert np.isnan(f["label"][-10:]).all() and np.isnat(f["label_end"][-10:]).all()
    assert np.isnan(f["ret_252"][:252]).all() and not np.isnan(f["ret_252"][252])


def test_cross_sectional_ranks_are_percentiles(panel):
    col = panel.features.index("rank_ret_20")
    d = panel.date.max()
    r = np.sort(panel.X[panel.date == d, col])
    np.testing.assert_allclose(r, np.linspace(0, 1, len(TICKERS)))


# ── training window, determinism ────────────────────────────────────────────

def test_training_window_ends_before_the_purge_gap(panel):
    asof = LAST - timedelta(days=100)
    mask = M.training_mask(panel, asof)
    cal = panel.calendar
    i = int(np.searchsorted(cal, np.datetime64(asof), side="right")) - 1
    assert mask.sum() > 0
    assert panel.date[mask].max() <= cal[i - M.HORIZON - M.EMBARGO]
    assert panel.label_end[mask].max() <= cal[i - M.EMBARGO] < np.datetime64(asof)
    assert M.EMBARGO >= 5 and M.HORIZON == 10
    b = M.fit(panel, asof, importance=False)
    assert b["train_last"] <= b["row_cutoff"] and b["train_label_end_max"] <= b["label_cutoff"]
    assert b["label_cutoff"] < asof.isoformat()
    assert b["calib_start"] > b["train_first"] and b["n_fit"] >= M.MIN_TRAIN_ROWS // 2


def test_fit_is_deterministic_with_the_fixed_seed(panel):
    a, b = M.fit(panel, LAST), M.fit(panel, LAST)
    X = panel.X[-50:]
    np.testing.assert_array_equal(M.predict(a, X)[1], M.predict(b, X)[1])
    assert a["importance"] == b["importance"] and set(a["importance"]) == set(F.FEATURES)
    assert M.PARAMS["random_state"] == M.SEED and M.PARAMS["max_depth"] <= 3


def test_too_little_history_gives_no_model(hist):
    short = {t: bars[-300:] for t, bars in hist.items()}
    assert M.fit(F.build_panel(short), LAST) is None


# ── daily calls ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_calls_respect_caps(hist, tmp_path, monkeypatch):
    monkeypatch.setattr(ad, "THRESHOLD", 0.0)                 # force every instrument eligible
    out = await ad.analyze({}, fetch=fetch_stub(hist), now=NOW, data_dir=tmp_path)
    calls = out["directional_calls"]
    assert len(calls) == ad.MAX_CALLS == 2 and out["retrained"] is True
    probs = sorted(out["scores"].values(), reverse=True)
    assert [c["signal"]["p_calibrated"] for c in calls] == probs[:2]
    for c in calls:
        assert c["direction"] == "long" and c["hold_bars"] == 10
        assert 0.5 <= c["confidence"] <= 0.7
        assert c["confidence"] == ad.confidence(c["signal"]["p_calibrated"])
        assert c["signal_key"] == f"{c['ticker']}:2026-W40"
        close = hist[c["ticker"]][-1].close
        assert c["falsifier_rule"]["type"] == "close_below" and c["falsifier_rule"]["price"] < close
        tops = c["signal"]["top_features"]
        assert 0 < len(tops) <= M.TOP_FEATURES
        assert all(isinstance(t["importance"], float) for t in tops)
        assert c["signal"]["model"]["row_cutoff"] < LAST.isoformat()
    assert (tmp_path / "playground" / "ml_gbm" / "model.joblib").exists()
    # the real threshold keeps calls only at or above 0.55
    monkeypatch.setattr(ad, "THRESHOLD", 0.55)
    out = await ad.analyze({}, fetch=fetch_stub(hist), now=NOW, data_dir=tmp_path)
    assert all(c["signal"]["p_calibrated"] >= 0.55 for c in out["directional_calls"])
    assert out["retrained"] is False                            # same ISO week -> cached


@pytest.mark.asyncio
async def test_model_retrains_at_most_weekly(hist, tmp_path):
    out = await ad.analyze({}, fetch=fetch_stub(hist), now=NOW, data_dir=tmp_path)
    assert out["retrained"] is True and out["model"]["week"] == "2026-W40"
    again = await ad.analyze({}, fetch=fetch_stub(hist), now=NOW + timedelta(days=2),
                             data_dir=tmp_path)
    assert again["retrained"] is False
    nxt = await ad.analyze({}, fetch=fetch_stub(hist), now=NOW + timedelta(days=6),
                           data_dir=tmp_path)
    assert nxt["retrained"] is True and nxt["model"]["week"] == "2026-W41"


@pytest.mark.asyncio
async def test_stale_or_missing_data(hist, tmp_path):
    out = await ad.analyze({}, fetch=fetch_stub({}), now=NOW, data_dir=tmp_path)
    assert out["directional_calls"] == [] and "SPY" in out["no_calls_reason"]
    stale = dict(hist, XLE=hist["XLE"][:-20])
    out = await ad.analyze({}, fetch=fetch_stub(stale), now=NOW, data_dir=tmp_path)
    assert "stale" in out["unavailable"]["XLE"] and "XLE" not in out["scores"]
    assert (await ad.analyze({}, mock=True))["directional_calls"] == []


@pytest.mark.asyncio
async def test_bridge_records_once_per_ticker_week(hist, tmp_path, monkeypatch):
    monkeypatch.setattr(ad, "THRESHOLD", 0.0)
    out = await ad.analyze({}, fetch=fetch_stub(hist), now=NOW, data_dir=tmp_path)

    async def histories_fn(tickers):
        return {t: SimpleNamespace(daily=hist.get(t), source="static") for t in tickers}
    store = LedgerStore(tmp_path / "l.db")
    manifests = {"ml_gbm": load_manifest(AGENT_DIR)}
    res = SimpleNamespace(decisions=[SimpleNamespace(
        agent_id="ml_gbm", run_id="r", directional_calls=out["directional_calls"],
        metadata={"mock_mode": False})])
    s = await lb.record_run(store, res, manifests, today="2026-09-29", tradable=lambda t: True,
                            histories_fn=histories_fn)
    rows = store.list(source_type="playground")
    assert len(rows) == 2 and all(e.hold_bars == 10 and e.falsifier_rule for e in rows)
    s = await lb.record_run(store, res, manifests, today="2026-09-30", tradable=lambda t: True,
                            histories_fn=histories_fn)
    assert s["recorded"] == {} and len(s["dropped"]) == 2


def test_walk_forward_scores_only_after_each_purged_fit(panel):
    from marketmind.playground.agents.ml_gbm import backtest as B
    wf = B.walk_forward(panel, step=40)
    assert wf["fits"]
    for f in wf["fits"]:
        assert f["train_last"] <= f["row_cutoff"] < f["asof"]
        assert f["train_label_end_max"] <= f["label_cutoff"] < f["asof"]
    first_fit = np.datetime64(wf["fits"][0]["asof"])
    scored = ~np.isnan(wf["pred"])
    assert scored.any() and panel.date[scored].min() >= first_fit
    rep = B.evaluate(panel, wf)
    assert rep["overall"]["n"] > 0 and 0 <= rep["overall"]["auc"] <= 1
    assert rep["strategy"]["equal_weight"]["periods"] > 0


def test_manifest_and_zero_llm():
    m = load_manifest(AGENT_DIR)
    assert m.agent_id == ad.AGENT_ID and set(m.domain_universe) == set(F.UNIVERSE)
    for name in ("adapter.py", "features.py", "model.py", "backtest.py"):
        src = (AGENT_DIR / name).read_text(encoding="utf-8")
        assert "async_client" not in src and "chat_" not in src
