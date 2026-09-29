"""Crypto on-chain valuation, crypto sentiment and spot BTC ETF flows for the crypto shadows.

Data: marketmind.gateway.crypto_signals (Coin Metrics community MVRV, alternative.me
Crypto Fear & Greed, TFTC spot BTC ETF flows under CC BY 4.0), cached once per UTC day.
All numbers are computed here; each part fails on its own with an explicit
"unavailable" line, and the feed raises only when every part failed.
"""
from __future__ import annotations

from datetime import date, timedelta

from marketmind.gateway import crypto_signals as cs
from marketmind.shadow_feeds import Feed

ASSETS = (("btc", "BTC"), ("eth", "ETH"))
ETF_WINDOW = 5                     # trading days
FNG_LOOKBACK_DAYS = 7


def _stale(series: cs.Series) -> str:
    return f"; stale cache fetched {series.fetched_on}" if series.origin == "stale-cache" else ""


def mvrv_line(label: str, series: cs.Series) -> str:
    pts = series.points
    last = pts[-1]
    pct = cs.expanding_percentiles([p.mvrv for p in pts])[-1]
    z = cs.expanding_mvrv_z(pts)[-1]
    z_txt = f"; MVRV Z {z:+.2f}" if z is not None else ""
    return (f"- {label} MVRV {last.mvrv:.2f} on {last.date} (Coin Metrics CapMVRVCur): "
            f"percentile {pct:.0f}/100 of its own daily history since {pts[0].date}{z_txt}; "
            f"realized cap ${last.realized_cap / 1e9:,.0f}B (market cap / MVRV){_stale(series)}")


def fng_line(series: cs.Series) -> str:
    last = series.points[-1]
    week_ago = (date.fromisoformat(last.date) - timedelta(days=FNG_LOOKBACK_DAYS)).isoformat()
    prev = cs.point_on_or_before(series.points, week_ago)
    change = (f"; {prev.date}: {prev.value} ({prev.label}), 7-day change {last.value - prev.value:+d}"
              if prev is not None and prev.date == week_ago else "; 7-day change unavailable")
    return (f"- Crypto Fear & Greed (alternative.me) {last.value}/100 ({last.label}) on "
            f"{last.date}{change}{_stale(series)}")


def etf_line(series: cs.Series) -> str:
    days = series.points[-ETF_WINDOW:]
    total = sum(d.net_flow_usd for d in days)
    daily = ", ".join(f"{d.date[5:]} {d.net_flow_usd / 1e6:+,.0f}M" for d in days)
    return (f"- US spot BTC ETF net flow, {len(days)} trading days {days[0].date} to {days[-1].date}: "
            f"{total / 1e6:+,.0f}M USD ({daily}); source {cs.ETF_ATTRIBUTION}{_stale(series)}")


async def fetch(today: str) -> list[str]:
    lines, errors = [], 0
    for asset, label in ASSETS:
        try:
            lines.append(mvrv_line(label, await cs.mvrv_history(asset, today=today)))
        except Exception as e:
            errors += 1
            lines.append(f"- {label} MVRV (Coin Metrics): unavailable ({type(e).__name__})")
    for name, getter, render in (("Crypto Fear & Greed (alternative.me)", cs.fear_greed_history, fng_line),
                                 ("US spot BTC ETF flows (TFTC)", cs.etf_flow_history, etf_line)):
        try:
            lines.append(render(await getter(today=today)))
        except Exception as e:
            errors += 1
            lines.append(f"- {name}: unavailable ({type(e).__name__})")
    if errors == len(lines):
        raise cs.CryptoDataUnavailable("all crypto on-chain parts failed")
    return lines


FEEDS = [Feed("crypto_onchain", "Crypto on-chain valuation, sentiment and ETF flows "
              "(Coin Metrics, alternative.me, TFTC CC BY 4.0)", ("chain_oracle", "defi_scout"), fetch)]
