"""Crypto perpetual funding and open interest from OKX public endpoints.

Sources (keyless, verified 2026-09-28):
- https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP
  {"code": "0", "data": [{fundingRate, fundingTime, prevFundingTime, nextFundingTime,
  settFundingRate, ...}]}. fundingRate is the rate for the period that settles at
  fundingTime (the next settlement); fundingTime - prevFundingTime is the interval.
- https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId=BTC-USDT-SWAP
  {"code": "0", "data": [{oi (contracts), oiCcy (coin), oiUsd, ts}]}.
Rates and timestamps are strings; times are Unix ms (UTC).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from marketmind.shadow_feeds import Feed

FUNDING_URL = "https://www.okx.com/api/v5/public/funding-rate"
OI_URL = "https://www.okx.com/api/v5/public/open-interest"
TIMEOUT_S = 20.0
COINS = ("BTC", "ETH", "SOL")
YEAR_MS = 365 * 24 * 3600 * 1000
DEFAULT_INTERVAL_MS = 8 * 3600 * 1000


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT_S, headers={"Accept": "application/json"})


def _utc(ms) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _first(payload: dict) -> dict:
    if not isinstance(payload, dict) or str(payload.get("code")) != "0":
        raise ValueError(f"OKX error {payload.get('code') if isinstance(payload, dict) else payload!r}")
    data = payload.get("data") or []
    if not data or not isinstance(data[0], dict):
        raise ValueError("OKX returned no data")
    return data[0]


def funding_line(coin: str, funding: dict, oi: dict | None) -> str:
    rate = float(funding["fundingRate"])
    nxt, prev = int(funding["fundingTime"]), funding.get("prevFundingTime")
    interval = nxt - int(prev) if prev not in (None, "") else DEFAULT_INTERVAL_MS
    if interval <= 0:
        interval = DEFAULT_INTERVAL_MS
    annual = rate * YEAR_MS / interval * 100
    line = (f"- {coin} perp (OKX {funding.get('instId', coin + '-USDT-SWAP')}): funding "
            f"{rate * 100:+.4f}% per {interval / 3_600_000:.0f}h (~{annual:+.1f}% annualised; "
            f"{'longs pay shorts' if rate > 0 else 'shorts pay longs' if rate < 0 else 'flat'}), "
            f"next settlement {_utc(nxt)}")
    sett = funding.get("settFundingRate")
    if sett not in (None, ""):
        line += f"; last settled {float(sett) * 100:+.4f}%"
    if oi:
        try:
            line += (f"; open interest ${float(oi['oiUsd']) / 1e9:,.2f}B "
                     f"({float(oi['oiCcy']):,.0f} {coin}, {_utc(oi['ts'])[:10]})")
        except (KeyError, TypeError, ValueError):
            pass
    return line


async def _get(client: httpx.AsyncClient, url: str, params: dict) -> dict:
    resp = await client.get(url, params=params)
    resp.raise_for_status()
    return _first(resp.json())


async def _coin(client: httpx.AsyncClient, coin: str) -> str:
    inst = f"{coin}-USDT-SWAP"
    funding, oi = await asyncio.gather(
        _get(client, FUNDING_URL, {"instId": inst}),
        _get(client, OI_URL, {"instType": "SWAP", "instId": inst}), return_exceptions=True)
    if isinstance(funding, Exception):
        raise funding
    return funding_line(coin, funding, None if isinstance(oi, Exception) else oi)


async def fetch(today: str) -> list[str]:
    async with _client() as c:
        results = await asyncio.gather(*(_coin(c, coin) for coin in COINS), return_exceptions=True)
    if all(isinstance(r, Exception) for r in results):
        raise results[0]
    return [r if isinstance(r, str) else f"- {coin} perp (OKX): unavailable ({type(r).__name__})"
            for coin, r in zip(COINS, results)]


FEEDS = [Feed("crypto_derivs", "Crypto perpetual funding (OKX)",
              ("chain_oracle", "defi_scout"), fetch)]
