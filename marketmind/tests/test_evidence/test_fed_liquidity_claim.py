"""Evidence claim type `fed_liquidity` (docs/S5_DESIGN.md): SOMA total over ~4 weeks."""
import json

import httpx
import pytest

from marketmind.evidence import checks as ck
from marketmind.evidence import sources as src
from marketmind.evidence.extract import CHECKABLE_WORDS, SYSTEM_PROMPT, parse_claims

T = 6_400_000_000_000


class _Data:
    def __init__(self, rows):
        self.rows = rows

    async def soma(self):
        return self.rows


def _weeks(*totals, start="2026-08-26"):
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    return [((d0 + timedelta(weeks=i)).isoformat(), float(t)) for i, t in enumerate(totals)]


def test_parse_soma_sorts_and_skips_bad_rows():
    payload = {"soma": {"summary": [
        {"asOfDate": "2026-09-23", "total": "6365055221192.60"},
        {"asOfDate": "2026-08-26", "total": "6355853153593.90"},
        {"asOfDate": "2026-09-02", "total": ""},
        {"total": "1"}]}}
    assert src.parse_soma(payload) == [("2026-08-26", 6355853153593.9),
                                       ("2026-09-23", 6365055221192.6)]
    assert src.parse_soma({}) == [] and src.parse_soma(None) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("last,expected", [
    (T * 1.0015, "up"),      # +0.15%: e.g. reserve-management bill buying
    (T * 0.995, "down"),     # -0.5%: QT
    (T * 1.0005, "flat"),    # +0.05%: inside the 0.1% band
])
async def test_direction_against_four_weeks_ago(last, expected):
    rows = _weeks(T * 0.9, T, T * 1.01, T * 1.02, T * 1.03, last)     # 4w-ago point is the 2nd row
    obs = await ck.observe("fed_liquidity", None, _Data(rows))
    assert obs.direction == expected
    assert obs.data["past"] == rows[1] and obs.data["last"] == rows[-1]
    assert "纽约联储 SOMA 持仓" in obs.summary and "$6,400.0B" in obs.summary


@pytest.mark.asyncio
async def test_live_sample_2026_09_23_is_up():
    rows = [("2026-08-26", 6355853153593.9), ("2026-09-02", 6362218153593.9),
            ("2026-09-16", 6364278356116.0), ("2026-09-23", 6365055221192.6)]
    obs = await ck.observe("fed_liquidity", None, _Data(rows))
    assert obs.direction == "up" and round(obs.data["change"], 4) == 0.0014
    assert "+9.2B" in obs.summary


@pytest.mark.asyncio
async def test_missing_or_short_history_is_unverifiable():
    assert (await ck.observe("fed_liquidity", None, _Data([]))).direction is None
    short = _weeks(T, T * 1.01)                    # only one week back
    assert (await ck.observe("fed_liquidity", None, _Data(short))).direction is None

    class _Broken:
        async def soma(self):
            raise RuntimeError("down")
    obs = await ck.observe("fed_liquidity", None, _Broken())
    assert obs.direction is None and "RuntimeError" in obs.summary


def test_ledger_proxy_is_tlt_long_when_liquidity_grows():
    assert ck.CLAIM_TYPES["fed_liquidity"] == (False, "TLT", "long")
    assert ck.ledger_bet("fed_liquidity", None, "down", "up") == ("TLT", "long")
    assert ck.ledger_bet("fed_liquidity", None, "up", "down") == ("TLT", "short")
    # data flat while news said "QT / draining" -> bet against the narrative
    assert ck.ledger_bet("fed_liquidity", None, "down", "flat") == ("TLT", "long")


def test_extraction_prompt_and_validation_accept_the_type():
    assert "- fed_liquidity：" in SYSTEM_PROMPT
    text = json.dumps({"claims": [
        {"claim": "美联储继续缩表", "type": "fed_liquidity", "ticker": "TLT",
         "asserted": "down", "news_ids": ["n1"]}]})
    claims, dropped = parse_claims(text, {"n1"})
    assert dropped == [] and claims[0].type == "fed_liquidity" and claims[0].ticker is None
    for s in ("Fed ends QT", "the Fed's balance sheet shrank", "美联储缩表"):
        assert CHECKABLE_WORDS.search(s)
    assert not CHECKABLE_WORDS.search("Apple's balance sheet is strong")


@pytest.mark.asyncio
async def test_live_data_fetches_soma_once():
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(200, json={"soma": {"summary": [
            {"asOfDate": "2026-09-23", "total": "6365055221192.60"}]}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        data = src.LiveEvidenceData(client=c)
        assert await data.soma() == [("2026-09-23", 6365055221192.6)]
        await data.soma()
    assert len(calls) == 1 and str(calls[0].url) == src.SOMA_URL
