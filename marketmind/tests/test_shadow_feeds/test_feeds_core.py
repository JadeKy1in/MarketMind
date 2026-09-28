"""Shadow feed extension point (marketmind/shadow_feeds)."""
import pytest

import marketmind.shadow_feeds as sf
from marketmind.shadows.v3 import roster

_real_gather = sf.gather          # captured before conftest stubs it
from marketmind.shadows.v3.context import build_context


async def _ok(today):
    return [f"- VIX3M 20.1 ({today})"]


async def _boom(today):
    raise TimeoutError("slow")


FEEDS = [sf.Feed("vol", "Volatility term structure", ("vega_trader",), _ok),
         sf.Feed("bad", "Broken feed", ("vega_trader", "trend_rider"), _boom)]


@pytest.mark.asyncio
async def test_gather_serves_named_shadows_and_trial_variants():
    out = await _real_gather(["vega_trader", "trial_vega_trader_ab12", "news_hound"],
                             "2026-09-29", feeds=FEEDS)
    assert set(out) == {"vega_trader", "trial_vega_trader_ab12"}
    assert out["vega_trader"]["Volatility term structure"] == ["- VIX3M 20.1 (2026-09-29)"]
    assert "unavailable today (TimeoutError)" in out["vega_trader"]["Broken feed"][0]


def test_context_renders_feed_sections():
    entry = roster.by_id()["expert:vol:vega_trader"]
    ctx = build_context(entry, {}, [], today="2026-09-29",
                        feeds={"Volatility term structure": ["- VIX3M 20.1"]})
    text = ctx.render()
    assert "## Volatility term structure\n- VIX3M 20.1" in text
    assert text.index("## Volatility term structure") < text.index("## Today's headlines")
