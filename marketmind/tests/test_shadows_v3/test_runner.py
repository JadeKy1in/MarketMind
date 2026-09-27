"""Daily shadow run into the ledger with a fake LLM (docs/S3_DESIGN.md §3, §4)."""
import json

import pytest

from marketmind.ledger.store import LedgerStore
from marketmind.shadows.v3 import roster, runner
from marketmind.tests.test_shadows_v3.test_roster_context import history

TODAY = "2026-09-28"


@pytest.fixture
def prices(monkeypatch):
    async def fake_histories(tickers, years=5):
        return {t: history(t) for t in tickers if t not in ("SLV",)}
    monkeypatch.setattr(runner, "get_price_histories", fake_histories)


async def no_fred(shadow_id):
    return {}


def reply(*decisions):
    return json.dumps({"decisions": list(decisions)})


def good(ticker, **kw):
    d = {"ticker": ticker, "direction": "long", "hold_days": 10, "confidence": 0.62,
         "thesis": "测试理由", "falsifier": "跌破支撑说明我错了"}
    d.update(kw)
    return d


def entries(*ids):
    by = roster.by_id()
    return [by[i] for i in ids]


@pytest.mark.asyncio
async def test_submitted_decisions_and_benchmark_are_recorded(tmp_path, prices):
    store = LedgerStore(tmp_path / "l.db")
    seen = {}

    async def call(system, user, stage):
        seen[stage] = (system, user)
        return reply(good("GLD"), good("GDX", direction="short", hold_days=3, confidence=0.4))

    report = await runner.run_shadow_day(
        store, [], today=TODAY, entries=entries("expert:gold:bullion_broker"),
        call=call, fred_fetch=no_fred, report_dir=tmp_path / "runs")
    r = report.results[0]
    assert r.status == "submitted" and len(r.entry_ids) == 2 and r.attempts == 1
    system, user = seen["shadow:bullion_broker"]
    assert "## Output format" in system and "Bullion Broker" in system
    assert "SLV: no data today" in user

    rows = store.list(source_type="shadow")
    gld = next(e for e in rows if e.ticker == "GLD")
    assert (gld.source_id, gld.direction, gld.hold_bars, gld.entry_rule) == (
        "expert:gold:bullion_broker", "long", 10, "next_open")
    assert gld.position_usd == 316.0 and gld.domain_benchmark == "GLD"
    assert gld.snapshot_id and store.snapshot(gld.snapshot_id)["GLD"]["price"] > 0
    assert gld.meta["model"] == "flash"
    gdx = next(e for e in rows if e.ticker == "GDX")
    assert gdx.position_usd == 100.0 and gdx.direction == "short"

    bench = store.list(source_type="benchmark")
    assert len(bench) == 1 and bench[0].source_id == "random:expert:gold:bullion_broker"
    assert bench[0].hold_bars == 6 and bench[0].ticker in {"GLD", "GDX", "GDXJ", "SIL", "NEM",
                                                           "AEM", "WPM", "PPLT"}
    assert (tmp_path / "runs" / f"{TODAY}.json").exists()
    assert "1 submitted (2 decisions)" in report.summary()


@pytest.mark.asyncio
async def test_retry_with_errors_then_missed(tmp_path, prices):
    store = LedgerStore(tmp_path / "l.db")
    prompts = []

    async def call(system, user, stage):
        prompts.append(user)
        return reply(good("AAPL")) if len(prompts) == 1 else reply(good("GLD"))

    report = await runner.run_shadow_day(store, [], today=TODAY,
                                         entries=entries("expert:gold:bullion_broker"),
                                         call=call, fred_fetch=no_fred)
    assert report.results[0].status == "submitted" and report.results[0].attempts == 2
    assert "previous reply was rejected" in prompts[1] and "AAPL" in prompts[1]

    async def abstain(system, user, stage):
        return "I prefer to stay in cash today."

    store2 = LedgerStore(tmp_path / "l2.db")
    report = await runner.run_shadow_day(store2, [], today=TODAY,
                                         entries=entries("expert:gold:bullion_broker"),
                                         call=abstain, fred_fetch=no_fred)
    r = report.results[0]
    assert r.status == "missed" and r.attempts == 2 and not r.entry_ids
    assert store2.list() == []  # nothing invented, no benchmark either
    assert "missed: bullion_broker" in report.summary()


@pytest.mark.asyncio
async def test_llm_failure_is_a_miss_not_a_crash(tmp_path, prices):
    async def boom(system, user, stage):
        raise RuntimeError("LLM error: budget_exhausted")

    report = await runner.run_shadow_day(LedgerStore(tmp_path / "l.db"), [], today=TODAY,
                                         entries=entries("expert:gold:bullion_broker"),
                                         call=boom, fred_fetch=no_fred)
    r = report.results[0]
    assert r.status == "missed" and "budget_exhausted" in r.errors[0]


@pytest.mark.asyncio
async def test_scalper_forced_to_one_day_and_marked(tmp_path, prices):
    store = LedgerStore(tmp_path / "l.db")

    async def call(system, user, stage):
        assert "held exactly 1 session" in user
        return reply(good("SPY", hold_days=4))

    await runner.run_shadow_day(store, [], today=TODAY,
                                entries=entries("momentum:intraday:scalper"),
                                call=call, fred_fetch=no_fred)
    e = store.list(source_type="shadow")[0]
    assert e.hold_bars == 1 and e.meta.get("intraday_approx") is True


@pytest.mark.asyncio
async def test_rerun_same_day_skips_and_consensus_feeds_fade_master(tmp_path, prices):
    store = LedgerStore(tmp_path / "l.db")

    async def call(system, user, stage):
        return reply(good("SPY"))

    ids = entries("momentum:weekly:trend_rider", "contrarian:consensus:fade_master")
    await runner.run_shadow_day(store, [], today="2026-09-27", entries=ids, call=call,
                                fred_fetch=no_fred)
    again = await runner.run_shadow_day(store, [], today="2026-09-27", entries=ids, call=call,
                                        fred_fetch=no_fred)
    assert {r.status for r in again.results} == {"skipped"}

    seen = {}

    async def spy(system, user, stage):
        seen[stage] = user
        return reply(good("SPY"))

    await runner.run_shadow_day(store, [], today=TODAY, entries=ids, call=spy, fred_fetch=no_fred)
    assert "SPY: 1 shadows, 100% long" in seen["shadow:fade_master"]
    assert "consensus" not in seen["shadow:trend_rider"].lower()


@pytest.mark.asyncio
async def test_benchmark_is_reproducible(tmp_path, prices):
    async def call(system, user, stage):
        return reply(good("GLD"))

    picks = []
    for i in range(2):
        store = LedgerStore(tmp_path / f"l{i}.db")
        await runner.run_shadow_day(store, [], today=TODAY,
                                    entries=entries("expert:gold:bullion_broker"),
                                    call=call, fred_fetch=no_fred)
        b = store.list(source_type="benchmark")[0]
        picks.append((b.ticker, b.direction))
    assert picks[0] == picks[1]
