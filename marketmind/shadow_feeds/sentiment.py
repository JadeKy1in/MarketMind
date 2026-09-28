"""CNN Fear & Greed index (unofficial JSON endpoint behind cnn.com/markets/fear-and-greed).

The endpoint rejects non-browser clients, so a browser-like User-Agent is sent.
Scores are 0-100 (0 = extreme fear). Component raw values are shown as CNN
publishes them; comparisons (S&P vs its 125-day average, VIX vs 50-day) are
computed here.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from marketmind.shadow_feeds import Feed

CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json",
    "Referer": "https://www.cnn.com/",
}
HTTP_TIMEOUT_S = 30.0
_TRANSPORT: httpx.AsyncBaseTransport | None = None      # tests inject httpx.MockTransport

# key -> (label, description of CNN's raw value, unit suffix)
COMPONENTS = (
    ("stock_price_strength", "Stock price strength", "net new 52-week highs minus lows", ""),
    ("stock_price_breadth", "Stock price breadth", "McClellan volume summation", ""),
    ("put_call_options", "Put/call options", "5-day avg put/call ratio", ""),
    ("junk_bond_demand", "Junk bond demand", "junk minus investment-grade yield spread", " pp"),
    ("safe_haven_demand", "Safe haven demand", "20-day stock minus bond return", " pp"),
)


def _num(x) -> float | None:
    return float(x) if isinstance(x, (int, float)) else None


def _date(ms) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d") if ms else "?"


def _last_y(block: dict) -> float | None:
    data = block.get("data") or []
    return _num(data[-1].get("y")) if data else None


def _score(block: dict) -> str:
    return f"{float(block['score']):.1f} {block.get('rating', '?')}"


async def fetch_graphdata() -> dict:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, follow_redirects=True,
                                 transport=_TRANSPORT, headers=HEADERS) as c:
        r = await c.get(CNN_URL)
        r.raise_for_status()
        return r.json()


def build_lines(d: dict) -> list[str]:
    fg = d["fear_and_greed"]
    ts = datetime.fromisoformat(fg["timestamp"]).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"- Fear & Greed {float(fg['score']):.1f}/100 ({fg['rating']}), as of {ts}"]
    prev = [(lbl, _num(fg.get(k))) for lbl, k in (("previous close", "previous_close"),
                                                    ("1 week ago", "previous_1_week"),
                                                    ("1 month ago", "previous_1_month"),
                                                    ("1 year ago", "previous_1_year"))]
    prev = [f"{lbl} {v:.1f}" for lbl, v in prev if v is not None]
    if prev:
        lines.append("- " + "; ".join(prev))
    mom, avg = d.get("market_momentum_sp500"), d.get("market_momentum_sp125")
    if mom and "score" in mom:
        spx, a = _last_y(mom), _last_y(avg or {})
        extra = (f"; S&P 500 {spx:.2f} vs 125-day avg {a:.2f} ({spx / a - 1:+.1%})"
                 if spx and a else "")
        lines.append(f"- Market momentum: {_score(mom)} ({_date(mom.get('timestamp'))}{extra})")
    vix, vix50 = d.get("market_volatility_vix"), d.get("market_volatility_vix_50")
    if vix and "score" in vix:
        v, a = _last_y(vix), _last_y(vix50 or {})
        extra = f"; VIX {v:.2f} vs 50-day avg {a:.2f}" if v and a else ""
        lines.append(f"- Market volatility: {_score(vix)} ({_date(vix.get('timestamp'))}{extra})")
    for key, label, desc, unit in COMPONENTS:
        b = d.get(key)
        if not b or "score" not in b:
            continue
        y = _last_y(b)
        extra = f"; {desc} {y:.2f}{unit}" if y is not None else ""
        lines.append(f"- {label}: {_score(b)} ({_date(b.get('timestamp'))}{extra})")
    return lines


async def fetch(today: str) -> list[str]:
    return build_lines(await fetch_graphdata())


FEEDS = [Feed("cnn_fear_greed", "Market sentiment: CNN Fear & Greed (unofficial source; component scores 0-100)",
              ("fade_master", "vol_surfer", "crash_hunter"), fetch)]
