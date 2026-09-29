"""S9 step 0: provenance (meta.llm / meta.prompt_version) and review facts (docs/S9_DESIGN.md)."""
import asyncio
import json
import sqlite3

import pytest

from marketmind.gateway import async_client, llm_trace
from marketmind.gateway.price_history import Bar
from marketmind.ledger.prices import StaticPriceSource
from marketmind.ledger.recorder import record_main_decision
from marketmind.ledger.settlement import compute_review, settle_all
from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.pipeline.decision import DecisionOutput, PaperTrade
from marketmind.pipeline.layer3_technical import Layer3BatchResult
from marketmind.shadows.v3 import runner
from marketmind.tests.test_shadows_v3.test_runner import entries, good, no_fred, prices, reply  # noqa: F401

CREATED = "2026-09-01T21:00:00Z"


# ── llm_trace ────────────────────────────────────────────────────────────

def test_trace_collects_answering_models_in_nested_tasks():
    async def one(model):
        llm_trace.note({"content": "x", "model": model})

    async def main():
        with llm_trace.trace() as calls:
            await asyncio.wait_for(one("claude-sonnet"), timeout=1)
            await one("deepseek-flash")
            await one("claude-sonnet")
            llm_trace.note({"content": "", "model": "empty-reply"})
            llm_trace.note({"content": "x", "model": "m", "error": "boom"})
        return calls
    calls = asyncio.run(main())
    assert calls == ["claude-sonnet", "deepseek-flash", "claude-sonnet"]
    assert llm_trace.label(calls) == "claude-sonnet+deepseek-flash"
    assert llm_trace.label([]) is None
    llm_trace.note({"content": "x", "model": "outside"})     # no trace open: ignored


def test_prompt_version_is_a_stable_12_hex_fingerprint():
    v = llm_trace.prompt_version("methodology A")
    assert len(v) == 12 and int(v, 16) >= 0
    assert v == llm_trace.prompt_version("methodology A") != llm_trace.prompt_version("B")


def test_gateway_notes_claude_and_deepseek_fallback(monkeypatch):
    async def claude_ok(system, user, tier):
        return {"content": "hi", "model": "claude-sonnet-x", "usage": {}}

    async def claude_down(system, user, tier):
        return None

    async def deepseek(gw, model, *args):
        return {"content": "hi", "model": "deepseek-flash", "usage": {}}
    async_client.init_gateway("test-key")
    monkeypatch.setattr(async_client, "_call_with_retry", deepseek)

    async def run(claude):
        monkeypatch.setattr(async_client, "_try_claude", claude)
        with llm_trace.trace() as calls:
            await async_client.chat_flash("s", "u")
        return calls
    assert asyncio.run(run(claude_ok)) == ["claude-sonnet-x"]
    assert asyncio.run(run(claude_down)) == ["deepseek-flash"]


# ── provenance on ledger records ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_shadow_records_carry_llm_and_prompt_version(tmp_path, prices):
    store = LedgerStore(tmp_path / "l.db")

    async def call(system, user, stage):
        llm_trace.note({"content": "x", "model": "claude-sonnet-x"})
        return reply(good("GLD"))

    await runner.run_shadow_day(store, [], today="2026-09-28",
                                entries=entries("expert:gold:bullion_broker"),
                                call=call, fred_fetch=no_fred, report_dir=tmp_path / "runs")
    gld = next(e for e in store.list(source_type="shadow") if e.ticker == "GLD")
    entry = entries("expert:gold:bullion_broker")[0]
    assert gld.meta["llm"] == "claude-sonnet-x"
    assert gld.meta["prompt_version"] == llm_trace.prompt_version(runner.system_prompt(entry))
    bench = store.list(source_type="benchmark")[0]
    assert "llm" not in bench.meta and "prompt_version" not in bench.meta


@pytest.mark.asyncio
async def test_main_records_carry_decision_provenance(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    src = StaticPriceSource({"NVDA": [Bar("2026-09-01", 1, 1, 1, 225.0, 1)]})
    out = DecisionOutput(paper_trade=PaperTrade("NVDA", "long", 0.65, "green light", "L3"),
                         llm="claude-opus-x", prompt_version="abc123abc123")
    ids = await record_main_decision(out, Layer3BatchResult(results=[]), store, src,
                                     created_at=CREATED)
    meta = store.get(ids[0]).meta
    assert (meta["llm"], meta["prompt_version"]) == ("claude-opus-x", "abc123abc123")
    out2 = DecisionOutput(paper_trade=PaperTrade("NVDA", "long", 0.65, "green light", "L3"))
    meta2 = store.get((await record_main_decision(out2, None, store, src))[0]).meta
    assert "llm" not in meta2 and "prompt_version" not in meta2


# ── review facts ─────────────────────────────────────────────────────────

def bar(date, o, h, l, c):
    return Bar(date=date, open=o, high=h, low=l, close=c, volume=1.0)


def settled(**kw):
    base = dict(source_type="main", source_id="t", ticker="AAA", direction="long", hold_bars=3,
                confidence=0.6, position_usd=1000.0, falsifier="f", stop_loss=95.0,
                target_price=110.0, status="settled", entry_date="2026-09-02",
                entry_price=100.0, exit_date="2026-09-04", exit_price=104.0,
                gross_return=0.04, net_return=0.039, excess_market=-0.01)
    base.update(kw)
    return LedgerEntry(**base)


BARS = [bar("2026-09-01", 90, 91, 89, 90), bar("2026-09-02", 100, 103, 96, 102),
        bar("2026-09-03", 102, 108, 101, 107), bar("2026-09-04", 107, 107, 103, 104),
        bar("2026-09-05", 104, 130, 60, 104)]


def test_review_facts_long():
    r = compute_review(settled(), BARS)
    assert r == {"v": 1, "direction_correct": True, "error_class": "beta_carried",
                 "mfe": 0.08, "mae": -0.04, "bars_held": 3,
                 "touched_target": False, "touched_stop": False, "ambiguous_bar": False,
                 "target_distance": 0.1, "stop_distance": -0.05, "r_multiple": 0.8,
                 "atr_pct": None, "mfe_atr": None, "mae_atr": None,
                 "target_hit_after_exit": False, "post_exit_complete": True,
                 "regime": {"ret_20d": None, "above_ma50": None, "above_ma200": None},
                 "beat_market": False}


def test_review_facts_short_rescaled_and_missing_levels():
    r = compute_review(settled(direction="short", gross_return=-0.04, net_return=-0.041,
                               stop_loss=None, target_price=100.0, excess_market=None),
                       BARS, factor=0.97)
    assert r["direction_correct"] is False and r["mfe"] == 0.04 and r["mae"] == -0.08
    assert r["touched_target"] is True and r["target_distance"] == 0.03     # 97 vs fill 100
    assert r["touched_stop"] is None and r["stop_distance"] is None and r["r_multiple"] is None
    assert r["beat_market"] is None and r["error_class"] == "thesis_wrong"
    assert compute_review(settled(entry_price=None), BARS) is None


def test_error_classes_and_post_exit_path():
    # stopped out on 09-03, target reached on 09-05 within the original 5-bar plan
    stopped = settled(hold_bars=5, exit_date="2026-09-03", exit_price=95.0, exit_reason="stop",
                      gross_return=-0.05, net_return=-0.051)
    r = compute_review(stopped, BARS + [bar("2026-09-06", 104, 111, 103, 110)])
    assert r["error_class"] == "right_but_stopped" and r["target_hit_after_exit"] is True
    assert r["ambiguous_bar"] is False
    early = compute_review(stopped, BARS[:4])                 # plan not over yet
    assert early["post_exit_complete"] is False and early["error_class"] == "thesis_wrong"
    assert compute_review(settled(net_return=0.03, excess_market=0.01), BARS)["error_class"] == "win"
    assert compute_review(settled(gross_return=0.001, net_return=-0.001),
                          BARS)["error_class"] == "cost_flipped"
    wide = settled(exit_date="2026-09-05", target_price=120.0, stop_loss=70.0, hold_bars=4)
    assert compute_review(wide, BARS)["ambiguous_bar"] is True   # 09-05 spans 60-130


def test_regime_and_atr_normalisation():
    import itertools
    days = [f"D{i:03d}" for i in range(230)]
    closes = [100 + i * 0.1 for i in range(230)]
    bars = [bar(d, c, c + 1, c - 1, c) for d, c in zip(days, closes)]
    e = settled(entry_date="D220", exit_date="D222", entry_price=closes[220], hold_bars=3,
                stop_loss=None, target_price=None)
    r = compute_review(e, bars)
    assert r["atr_pct"] == round(2.0 / closes[219], 6)
    assert r["mfe_atr"] == round(r["mfe"] / r["atr_pct"], 4)
    assert r["regime"]["above_ma50"] is True and r["regime"]["above_ma200"] is True
    assert r["regime"]["ret_20d"] == round(closes[219] / closes[199] - 1, 6)
    assert list(itertools.islice(r, 1)) == ["v"]


@pytest.mark.asyncio
async def test_settlement_writes_and_backfills_review(tmp_path):
    store = LedgerStore(tmp_path / "l.db")
    days = [f"2026-09-{d:02d}" for d in range(1, 12)]
    src = StaticPriceSource({"AAA": [bar(d, 100, 101, 99, 100) for d in days],
                             "SPY": [bar(d, 100, 101, 99, 100) for d in days]})
    new_id = store.add(LedgerEntry(source_type="main", source_id="t", ticker="AAA",
                                   direction="long", hold_bars=3, confidence=0.6,
                                   position_usd=1000.0, falsifier="f"), created_at=CREATED)
    old_id = store.add(settled(), created_at=CREATED)          # settled before reviews existed
    stale_id = store.add(settled(review={"v": 0, "mfe": 9}), created_at=CREATED)
    rep = await settle_all(store, src, today="2026-09-12")
    assert store.get(new_id).status == "settled" and store.get(new_id).review["bars_held"] == 3
    assert store.get(old_id).review["mfe"] == 0.01 and store.get(stale_id).review["v"] == 1
    assert rep.reviews_backfilled == 2 and "reviews backfilled 2" in rep.summary()


def test_old_ledger_gets_review_column(tmp_path):
    path = tmp_path / "old.db"
    LedgerStore(path)
    with sqlite3.connect(path) as conn:                        # simulate a pre-S9 ledger
        conn.execute("ALTER TABLE ledger DROP COLUMN review")
        assert "review" not in {r[1] for r in conn.execute("PRAGMA table_info(ledger)")}
    store = LedgerStore(path)
    eid = store.add(settled(review={"mfe": 0.1}))
    assert store.get(eid).review == {"mfe": 0.1}
    with sqlite3.connect(path) as conn:
        raw = conn.execute("SELECT review FROM ledger").fetchone()[0]
    assert json.loads(raw) == {"mfe": 0.1}


def test_decision_prompt_version_ignores_the_daily_date_note(monkeypatch):
    from marketmind.pipeline import decision
    base = "rules...\n\n[TODAY: 2026年09月29日. All trading decisions ...]\n\n[LANGUAGE: zh]"
    other_day = base.replace("09月29日", "09月30日")
    assert decision.decision_prompt_version(base) == decision.decision_prompt_version(other_day)
    assert decision.decision_prompt_version(base) != decision.decision_prompt_version(base + "x")
    real = decision._get_decision_prompt()
    assert "[TODAY:" in real
    import re
    other = re.sub(r"\d{4}年\d{2}月\d{2}日", "1999年01月01日", real)
    assert other != real
    assert decision.decision_prompt_version(real) == decision.decision_prompt_version(other)
