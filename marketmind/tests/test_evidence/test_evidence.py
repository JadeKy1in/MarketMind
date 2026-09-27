"""Evidence layer v1 (docs/S5_DESIGN.md): parsers, checks, extraction, run, ledger."""
import json
from dataclasses import dataclass

import pytest

from marketmind.evidence import checks as ck
from marketmind.evidence import sources as src
from marketmind.evidence.extract import Claim, parse_claims, pick_news
from marketmind.evidence.runner import run_evidence_day
from marketmind.gateway.price_history import Bar
from marketmind.ledger.prices import StaticPriceSource
from marketmind.ledger.store import LedgerStore


# ── parsers ─────────────────────────────────────────────────────────────────

def _q(start, end, val):
    return {"start": start, "end": end, "val": val}


def test_revenue_yoy_picks_latest_quarter_and_year_ago():
    facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        _q("2025-04-01", "2025-06-30", 100.0), _q("2026-04-01", "2026-06-30", 120.0),
        _q("2025-07-01", "2026-06-30", 450.0),          # annual: ignored
        _q("2026-01-01", "2026-03-31", 110.0)]}}}}}
    r = src.parse_revenue_yoy(facts)
    assert (r.period_end, r.prior_end) == ("2026-06-30", "2025-06-30")
    assert r.yoy == pytest.approx(0.2)
    assert src.parse_revenue_yoy({}) is None


def test_small_parsers():
    assert src.parse_cik_map({"0": {"cik_str": 320193, "ticker": "aapl"}}) == {"AAPL": 320193}
    text = "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n20260925|AAPL|40|0|100|Q\nbad"
    assert src.parse_finra_day(text) == {"AAPL": 0.4}
    assert src.parse_sofr({"refRates": [{"effectiveDate": "2026-09-24", "percentRate": 3.88},
                                         {"effectiveDate": "2026-09-23", "percentRate": 3.9}]}) \
        == [("2026-09-23", 3.9), ("2026-09-24", 3.88)]
    auctions = src.parse_auctions({"data": [
        {"auction_date": "2026-09-24", "security_type": "Note", "security_term": "9-Year 10-Month",
         "original_security_term": "10-Year", "bid_to_cover_ratio": "2.42"},
        {"auction_date": "2026-09-24", "security_type": "Bill", "security_term": "8-Week",
         "original_security_term": "17-Week", "bid_to_cover_ratio": "2.76"},
        {"auction_date": "2026-09-29", "security_type": "Bill", "security_term": "52-Week",
         "bid_to_cover_ratio": None}]})
    assert [(a["type"], a["term"]) for a in auctions] == [("Note", "10-Year"), ("Bill", "8-Week")]
    stable = src.parse_stablecoin_supply([{"date": "1790467200",
                                           "totalCirculatingUSD": {"peggedUSD": 5.0}}])
    assert stable[0][1] == 5.0


# ── checks ──────────────────────────────────────────────────────────────────

@dataclass
class _SI:
    settlement_date: str = "2026-09-15"
    shares_short: float = 1e6
    change_pct: float | None = 12.0
    previous_date: str = "2026-08-29"


class FakeData:
    def __init__(self, **kw):
        self.kw = kw

    async def revenue_yoy(self, t):
        return self.kw.get("rev")

    async def short_interest(self, t):
        return self.kw.get("si")

    async def short_volume_ratios(self, t, n=5):
        return self.kw.get("sv", [])

    async def sofr(self):
        return self.kw.get("sofr", [])

    async def auctions(self):
        return self.kw.get("auctions", [])

    async def stablecoin_supply(self):
        return self.kw.get("stable", [])

    async def red_flag_filings(self, t):
        return self.kw.get("flags")


@pytest.mark.asyncio
async def test_each_check_direction():
    rev = src.RevenueYoY("Revenues", "2026-06-30", 90.0, "2025-06-30", 100.0)
    assert (await ck.observe("revenue_growth", "X", FakeData(rev=rev))).direction == "down"
    assert (await ck.observe("short_interest", "X", FakeData(si=_SI()))).direction == "up"
    sv = [("d1", 0.40), ("d2", 0.40), ("d3", 0.40), ("d4", 0.40), ("d5", 0.30)]
    assert (await ck.observe("short_selling_pressure", "X", FakeData(sv=sv))).direction == "down"
    sofr = [(f"d{i:02d}", 3.90) for i in range(21)] + [("d21", 3.80)]
    assert (await ck.observe("funding_rates", None, FakeData(sofr=sofr))).direction == "down"
    auctions = [{"date": "2026-09-24", "type": "Note", "term": "7-Year", "bid_to_cover": 2.0}] + [
        {"date": f"2026-0{m}-01", "type": "Note", "term": "7-Year", "bid_to_cover": 2.6}
        for m in range(8, 2, -1)]
    assert (await ck.observe("treasury_demand", None, FakeData(auctions=auctions))).direction == "down"
    stable = [(f"2026-08-{d:02d}", 100.0) for d in range(1, 31)] + [("2026-09-01", 105.0)]
    assert (await ck.observe("stablecoin_supply", None, FakeData(stable=stable))).direction == "up"
    flags = [{"filed": "2026-09-01", "form": "8-K", "phrase": "going concern"}]
    assert (await ck.observe("filing_red_flag", "X", FakeData(flags=flags))).direction == "up"


@pytest.mark.asyncio
async def test_missing_data_is_unverifiable_never_guessed():
    empty = FakeData(flags=[])
    for t in ck.CLAIM_TYPES:
        obs = await ck.observe(t, "X", empty)
        assert obs.direction is None, t
        assert ck.verdict("up", obs.direction) == ck.UNVERIFIABLE


@pytest.mark.asyncio
async def test_broken_source_does_not_raise():
    class Boom(FakeData):
        async def sofr(self):
            raise RuntimeError("boom")
    obs = await ck.observe("funding_rates", None, Boom())
    assert obs.direction is None and "RuntimeError" in obs.summary


def test_verdict_and_ledger_bet():
    assert ck.verdict("up", "up") == ck.SUPPORT
    assert ck.verdict("up", "down") == ck.CONTRADICT
    assert ck.verdict("up", "flat") == ck.CONTRADICT
    # data says revenue fell while news said it grew -> short the company
    assert ck.ledger_bet("revenue_growth", "ACME", "up", "down") == ("ACME", "short")
    # data says shorts fell -> long
    assert ck.ledger_bet("short_interest", "ACME", "up", "down") == ("ACME", "long")
    # rates flat while news said rising -> bet against the narrative: rates not up -> long TLT
    assert ck.ledger_bet("funding_rates", None, "up", "flat") == ("TLT", "long")
    assert ck.ledger_bet("treasury_demand", None, "up", "down") == ("TLT", "short")
    assert ck.ledger_bet("stablecoin_supply", None, "down", "up") == ("BTC-USD", "long")
    assert ck.ledger_bet("etf_flows", None, "up", "down") is None
    assert ck.ledger_bet("filing_red_flag", "ACME", "up", "down") is None


# ── extraction ──────────────────────────────────────────────────────────────

def test_parse_claims_validates_everything():
    text = json.dumps({"claims": [
        {"claim": "A 营收增长", "type": "revenue_growth", "ticker": "acme", "asserted": "up",
         "news_ids": ["n1", "zz"]},
        {"claim": "x", "type": "gdp", "asserted": "up", "news_ids": ["n1"]},
        {"claim": "x", "type": "revenue_growth", "ticker": None, "asserted": "up", "news_ids": ["n1"]},
        {"claim": "x", "type": "funding_rates", "asserted": "sideways", "news_ids": ["n1"]},
        {"claim": "x", "type": "funding_rates", "asserted": "up", "news_ids": ["nope"]},
        {"claim": "利率上行", "type": "funding_rates", "ticker": "SPY", "asserted": "UP",
         "news_ids": ["n2"]}]})
    claims, dropped = parse_claims(f"```json\n{text}\n```", {"n1", "n2"})
    assert [c.type for c in claims] == ["revenue_growth", "funding_rates"]
    assert claims[0].ticker == "ACME" and claims[0].news_ids == ["n1"]
    assert claims[1].ticker is None and claims[1].asserted == "up"
    assert len(dropped) == 4
    assert parse_claims("no json here", set())[0] == []


@dataclass
class _News:
    id: str
    title: str
    source_name: str
    summary: str = ""
    priority_score: float = 1.0
    content_type: str = "news_article"


def test_pick_news_skips_social_and_sorts():
    items = [_News("a", "t", "s", priority_score=1), _News("b", "t", "s", priority_score=5),
             _News("c", "t", "s", priority_score=9, content_type="social_mention")]
    assert [n.id for n in pick_news(items)] == ["b", "a"]
    items.append(_News("d", "Treasury auction draws weak demand", "s", priority_score=0))
    assert [n.id for n in pick_news(items)] == ["d", "b", "a"]


# ── full run ────────────────────────────────────────────────────────────────

def _bars(n=30):
    return [Bar(f"2026-08-{d:02d}", 100, 101, 99, 100, 1000) for d in range(1, n)]


@pytest.mark.asyncio
async def test_run_books_divergences_once_and_writes_report(tmp_path):
    store = LedgerStore(tmp_path / "ledger.db")
    news = [_News("n1", "ACME revenue soars", "Reuters"),
            _News("n2", "ACME sales jump", "Bloomberg"),
            _News("n3", "Repo rates rise", "MarketWatch")]
    reply = json.dumps({"claims": [
        {"claim": "ACME 营收大增", "type": "revenue_growth", "ticker": "ACME", "asserted": "up",
         "news_ids": ["n1", "n2"]},
        {"claim": "ACME 营收增长", "type": "revenue_growth", "ticker": "ACME", "asserted": "up",
         "news_ids": ["n1"]},
        {"claim": "回购利率上行", "type": "funding_rates", "asserted": "up", "news_ids": ["n3"]},
        {"claim": "ETF 资金流入", "type": "etf_flows", "asserted": "up", "news_ids": ["n3"]}]})

    async def call(system, user):
        assert "[n1]" in user
        return reply
    rev = src.RevenueYoY("Revenues", "2026-06-30", 80.0, "2025-06-30", 100.0)
    sofr = [(f"d{i:02d}", 3.90) for i in range(22)]
    prices = StaticPriceSource({"ACME": _bars(), "TLT": _bars()})
    report = await run_evidence_day(store, news, today="2026-09-28", call=call,
                                    data=FakeData(rev=rev, sofr=sofr), price_source=prices,
                                    report_dir=tmp_path / "ev")
    verdicts = [i.verdict for i in report.items]
    assert verdicts == ["contradict", "contradict", "contradict", "unverifiable"]
    entries = store.list(source_type="evidence")
    assert sorted((e.ticker, e.direction) for e in entries) == [("ACME", "short"), ("TLT", "long")]
    acme = next(e for e in entries if e.ticker == "ACME")
    assert acme.confidence == 0.60 and acme.hold_bars == 10 and acme.snapshot_id
    assert acme.meta["independent_sources"] == 2 and acme.layer != "linkage"
    tlt = next(e for e in entries if e.ticker == "TLT")
    assert tlt.layer == "linkage" and tlt.confidence == 0.55
    assert report.items[1].ledger_note == "同日同类型同标的已记一条"
    saved = json.loads((tmp_path / "ev" / "2026-09-28.json").read_text(encoding="utf-8"))
    assert saved["divergences"] == 3 and saved["status"] == "ok"

    again = await run_evidence_day(store, news, today="2026-09-28", call=call,
                                   data=FakeData(), report_dir=tmp_path / "ev")
    assert again.status == "skipped" and len(store.list(source_type="evidence")) == 2


@pytest.mark.asyncio
async def test_run_without_price_does_not_book(tmp_path):
    store = LedgerStore(tmp_path / "ledger.db")
    reply = json.dumps({"claims": [{"claim": "c", "type": "revenue_growth", "ticker": "ACME",
                                    "asserted": "up", "news_ids": ["n1"]}]})

    async def call(s, u):
        return reply
    rev = src.RevenueYoY("Revenues", "2026-06-30", 80.0, "2025-06-30", 100.0)
    report = await run_evidence_day(store, [_News("n1", "t", "Reuters")], today="2026-09-28",
                                    call=call, data=FakeData(rev=rev),
                                    price_source=StaticPriceSource({}), report_dir=tmp_path)
    assert report.items[0].entry_id is None and "取不到行情" in report.items[0].ledger_note
    assert store.list() == []


@pytest.mark.asyncio
async def test_llm_failure_is_recorded_not_raised(tmp_path):
    async def call(s, u):
        raise RuntimeError("timeout")
    report = await run_evidence_day(LedgerStore(tmp_path / "l.db"), [_News("n1", "t", "s")],
                                    today="2026-09-28", call=call, data=FakeData(),
                                    report_dir=tmp_path)
    assert report.status == "llm_failed"
    # a failed day can be retried
    assert json.loads((tmp_path / "2026-09-28.json").read_text("utf-8"))["status"] == "llm_failed"


def test_dashboard_evidence_provider(tmp_path, monkeypatch):
    from marketmind.api import whitebox
    monkeypatch.setenv("MARKETMIND_DATA_DIR", str(tmp_path))
    assert whitebox.get_evidence()["available"] is False
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "2026-09-28.json").write_text(json.dumps({
        "status": "ok", "divergences": 1, "news_considered": 3, "items": [
            {"claim": "a", "verdict": "support"}, {"claim": "b", "verdict": "contradict"}]}),
        encoding="utf-8")
    d = whitebox.get_evidence()
    assert d["date"] == "2026-09-28" and [i["claim"] for i in d["items"]] == ["b", "a"]


def test_tips_and_frn_are_their_own_series():
    rows = src.parse_auctions({"data": [
        {"auction_date": "2026-09-17", "security_type": "Note", "security_term": "9-Year 10-Month",
         "original_security_term": "10-Year", "bid_to_cover_ratio": "2.24",
         "inflation_index_security": "Yes", "floating_rate": "No"},
        {"auction_date": "2026-09-23", "security_type": "Note", "security_term": "1-Year 10-Month",
         "original_security_term": "2-Year", "bid_to_cover_ratio": "2.63",
         "inflation_index_security": "No", "floating_rate": "Yes"}]})
    assert [r["type"] for r in rows] == ["FRN", "TIPS"]


def test_efts_hits_carry_filing_id():
    hits = src.parse_efts_hits({"hits": {"hits": [
        {"_id": "0000950170-26-000001:msft-ex97_1.htm",
         "_source": {"form": "10-K", "file_date": "2026-07-29", "display_names": ["MSFT"]}}]}})
    assert hits[0]["adsh"] == "0000950170-26-000001"


def test_revenue_prefers_total_when_two_concepts_share_a_quarter():
    facts = {"facts": {"us-gaap": {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            _q("2025-04-01", "2025-06-30", 80.0), _q("2026-04-01", "2026-06-30", 90.0)]}},
        "Revenues": {"units": {"USD": [
            _q("2025-04-01", "2025-06-30", 100.0), _q("2026-04-01", "2026-06-30", 130.0)]}}}}}
    assert src.parse_revenue_yoy(facts).concept == "Revenues"


@pytest.mark.asyncio
async def test_unparseable_reply_keeps_day_retryable(tmp_path):
    async def call(s, u):
        return "sorry, no json"
    report = await run_evidence_day(LedgerStore(tmp_path / "l.db"), [_News("n1", "t", "s")],
                                    today="2026-09-28", call=call, data=FakeData(),
                                    report_dir=tmp_path)
    assert report.status == "llm_failed"


@pytest.mark.asyncio
async def test_rerun_after_interruption_does_not_double_book(tmp_path):
    store = LedgerStore(tmp_path / "ledger.db")
    reply = json.dumps({"claims": [{"claim": "c", "type": "revenue_growth", "ticker": "ACME",
                                    "asserted": "up", "news_ids": ["n1"]}]})

    async def call(s, u):
        return reply
    rev = src.RevenueYoY("Revenues", "2026-06-30", 80.0, "2025-06-30", 100.0)
    prices = StaticPriceSource({"ACME": _bars()})
    kw = dict(today="2026-09-28", call=call, data=FakeData(rev=rev), price_source=prices)
    await run_evidence_day(store, [_News("n1", "t", "Reuters")], report_dir=tmp_path / "a", **kw)
    # report lost (e.g. cancelled before writing): a second run must not book again
    again = await run_evidence_day(store, [_News("n1", "t", "Reuters")],
                                   report_dir=tmp_path / "b", **kw)
    assert len(store.list(source_type="evidence")) == 1
    assert again.items[0].ledger_note == "同日同类型同标的已记一条"
