"""Fetch daily bars (project price functions, read-only) for every opened ledger ticker
and cache them as JSON in this analysis folder. Run with cwd = MarketMind repo root."""
import asyncio, json, os, sqlite3, sys
from pathlib import Path
REPO = Path("E:/AI_Studio_Workspace/MarketMind")
OUT = Path(__file__).resolve().parent / "bars"
sys.path.insert(0, str(REPO)); os.chdir(REPO)
import marketmind.config.settings  # noqa: F401  (loads .env for the price sources)
from marketmind.gateway.price_history import get_price_history, complete_bars

async def main():
    OUT.mkdir(exist_ok=True)
    c = sqlite3.connect(f"file:{REPO/'data/ledger.db'}?mode=ro", uri=True)
    tickers = sorted({r[0] for r in c.execute(
        "select ticker from ledger where status in ('settled','open') and entry_date is not null")})
    tickers += ["SPY", "BTC-USD"]
    sem = asyncio.Semaphore(6)
    async def one(t):
        p = OUT / f"{t.replace('^','_').replace('=','_')}.json"
        if p.exists():
            return t, "cached"
        async with sem:
            try:
                h = await get_price_history(t, 2)
            except Exception as exc:
                return t, f"error {exc!r}"
        if h is None or not h.daily:
            return t, "none"
        bars = complete_bars(t, h.daily)
        p.write_text(json.dumps({"ticker": t, "source": h.source, "bars": [
            [b.date, b.open, b.high, b.low, b.close, b.volume, bool(b.close_only)] for b in bars]}))
        return t, f"{h.source} {len(bars)} last={bars[-1].date}"
    res = await asyncio.gather(*(one(t) for t in dict.fromkeys(tickers)))
    for t, s in res:
        print(t, s)
asyncio.run(main())
