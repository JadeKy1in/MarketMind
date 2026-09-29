"""Owner-executable, long-only instruments watched by the trend state machine.

Robinhood US account, no options, crypto allowed (SPEC_v3 §1). Kept in one constant
so the backtest, the daily states and (later) alerts all use the same list.
UNG is kept on purpose: tradable, but its futures roll decay makes buy-and-hold a
long loser, which is a useful test of whether the rules stay out of it.
The mega caps are today's winners (survivorship bias - see docs/TREND_DESIGN.md).
"""
from __future__ import annotations

TREND_UNIVERSE: tuple[str, ...] = (
    # US broad market
    "SPY", "QQQ", "IWM", "DIA",
    # sectors
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "SMH",
    # commodities
    "GLD", "SLV", "USO", "UNG",
    # Treasuries
    "TLT", "IEF",
    # crypto (Robinhood crypto)
    "BTC-USD", "ETH-USD", "SOL-USD",
    # mega caps
    "NVDA", "AAPL", "MSFT", "AMZN", "META",
)

# Yahoo symbol of the 13-week T-bill yield (percent, annualised): the hurdle proxy.
TBILL_PROXY = "^IRX"
