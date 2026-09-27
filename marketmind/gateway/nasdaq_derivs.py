"""Short interest and option-chain summaries from Nasdaq's public quote API.

Used by the squeeze_watch and options_reader shadows (docs/S3_DESIGN.md).
- Short interest: bi-monthly exchange settlement data, Nasdaq-listed stocks only
  (the API answers "not available" for NYSE listings).
- Option chain: per-strike last/bid/ask/volume/open interest for all expiries;
  summarised by code into put/call ratios, an at-the-money straddle "implied
  move", an OTM put/call price ratio (skew proxy) and the largest open-interest
  strikes. No greeks or implied volatilities are provided by the API.
Failures return None (callers show "unavailable"); nothing is estimated.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from datetime import date, datetime

import httpx

logger = logging.getLogger("marketmind.gateway.nasdaq_derivs")

BASE = "https://api.nasdaq.com/api/quote/{symbol}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "application/json",
}
TIMEOUT_S = 20.0
MIN_DAYS_TO_EXPIRY = 5          # the "near" expiry skips contracts about to expire


def _num(v) -> float | None:
    if v is None:
        return None
    s = str(v).replace(",", "").replace("$", "").strip()
    if s in ("", "--", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _symbol(ticker: str) -> str | None:
    t = ticker.strip().upper()
    if not t or t.endswith("-USD") or t.startswith("^"):
        return None
    return t.replace("-", ".")


# ── Short interest ─────────────────────────────────────────────────────────

@dataclass
class ShortInterest:
    ticker: str
    settlement_date: str
    shares_short: float
    days_to_cover: float | None
    change_pct: float | None        # vs the previous settlement
    previous_date: str | None

    def line(self) -> str:
        chg = f"{self.change_pct:+.1f}% vs {self.previous_date}" if self.change_pct is not None else "n/a"
        dtc = f"{self.days_to_cover:.1f}" if self.days_to_cover is not None else "n/a"
        return (f"- {self.ticker}: short interest {self.shares_short:,.0f} shares as of "
                f"{self.settlement_date} ({chg}); days to cover {dtc}")


def parse_short_interest(ticker: str, payload: dict) -> ShortInterest | None:
    rows = ((((payload or {}).get("data") or {}).get("shortInterestTable") or {}).get("rows")) or []
    parsed = []
    for r in rows:
        try:
            d = datetime.strptime(r["settlementDate"], "%m/%d/%Y").date().isoformat()
        except (KeyError, TypeError, ValueError):
            continue
        shares = _num(r.get("interest"))
        if shares is None:
            continue
        parsed.append((d, shares, _num(r.get("daysToCover"))))
    if not parsed:
        return None
    parsed.sort(reverse=True)
    d, shares, dtc = parsed[0]
    prev = parsed[1] if len(parsed) > 1 else None
    change = ((shares / prev[1] - 1) * 100) if prev and prev[1] else None
    return ShortInterest(ticker, d, shares, dtc, change, prev[0] if prev else None)


async def get_short_interest(ticker: str, client: httpx.AsyncClient | None = None
                             ) -> ShortInterest | None:
    symbol = _symbol(ticker)
    if symbol is None:
        return None
    try:
        async with _maybe_client(client) as c:
            resp = await c.get(BASE.format(symbol=symbol) + "/short-interest",
                               params={"assetClass": "stocks"})
        if resp.status_code != 200:
            logger.warning("Nasdaq short interest HTTP %d for %s", resp.status_code, ticker)
            return None
        result = parse_short_interest(ticker, resp.json())
        if result is None:
            logger.info("Nasdaq short interest unavailable for %s (NYSE listing or no data)",
                        ticker)
        return result
    except Exception as e:
        logger.warning("Nasdaq short interest failed for %s: %s", ticker, e)
        return None


# ── Option chain ───────────────────────────────────────────────────────────

@dataclass
class Contract:
    expiry: date
    strike: float
    kind: str                       # call | put
    bid: float | None
    ask: float | None
    last: float | None
    volume: float
    open_interest: float

    @property
    def mid(self) -> float | None:
        if self.bid is not None and self.ask is not None and self.ask >= self.bid > 0:
            return (self.bid + self.ask) / 2
        return self.last


@dataclass
class OptionSummary:
    ticker: str
    spot: float
    as_of: str
    put_call_volume: float | None
    put_call_oi: float | None
    call_volume: float
    put_volume: float
    near_expiry: str | None
    days_to_near: int | None
    implied_move_pct: float | None     # ATM straddle mid / spot, to the near expiry
    otm_put_call_ratio: float | None   # ~5% OTM put mid / ~5% OTM call mid, near expiry
    call_wall: float | None            # largest call OI strike, near expiry
    put_wall: float | None             # largest put OI strike, near expiry

    def line(self) -> str:
        def f(v, fmt):
            return "n/a" if v is None else format(v, fmt)
        return (f"- {self.ticker} options (as of {self.as_of}, spot {self.spot:.4g}): "
                f"put/call volume {f(self.put_call_volume, '.2f')}, put/call OI "
                f"{f(self.put_call_oi, '.2f')}; near expiry {self.near_expiry or 'n/a'} "
                f"({f(self.days_to_near, 'd')}d): implied move ±{f(self.implied_move_pct, '.1f')}%, "
                f"OTM put/call price ratio {f(self.otm_put_call_ratio, '.2f')}, "
                f"call wall {f(self.call_wall, '.4g')}, put wall {f(self.put_wall, '.4g')}")


def parse_chain(payload: dict) -> list[Contract]:
    """Rows arrive grouped: an 'expirygroup' header row, then strike rows."""
    rows = ((((payload or {}).get("data") or {}).get("table") or {}).get("rows")) or []
    out: list[Contract] = []
    expiry: date | None = None
    for r in rows:
        group = (r.get("expirygroup") or "").strip()
        if group:
            try:
                expiry = datetime.strptime(group, "%B %d, %Y").date()
            except ValueError:
                expiry = None
            continue
        strike = _num(r.get("strike"))
        if expiry is None or strike is None:
            continue
        for kind, p in (("call", "c_"), ("put", "p_")):
            out.append(Contract(expiry, strike, kind, _num(r.get(p + "Bid")), _num(r.get(p + "Ask")),
                                _num(r.get(p + "Last")), _num(r.get(p + "Volume")) or 0.0,
                                _num(r.get(p + "Openinterest")) or 0.0))
    return out


def summarise_chain(ticker: str, contracts: list[Contract], spot: float, today: date,
                    as_of: str) -> OptionSummary | None:
    if not contracts or spot <= 0:
        return None
    calls = [c for c in contracts if c.kind == "call"]
    puts = [c for c in contracts if c.kind == "put"]
    cv, pv = sum(c.volume for c in calls), sum(c.volume for c in puts)
    coi, poi = sum(c.open_interest for c in calls), sum(c.open_interest for c in puts)

    expiries = sorted({c.expiry for c in contracts if (c.expiry - today).days >= MIN_DAYS_TO_EXPIRY})
    near = expiries[0] if expiries else None
    implied = otm_ratio = call_wall = put_wall = None
    if near is not None:
        nc = {c.strike: c for c in calls if c.expiry == near}
        np_ = {c.strike: c for c in puts if c.expiry == near}
        strikes = sorted(set(nc) & set(np_))
        if strikes:
            atm = min(strikes, key=lambda k: abs(k - spot))
            cm, pm = nc[atm].mid, np_[atm].mid
            if cm is not None and pm is not None:
                implied = (cm + pm) / spot * 100
            kp = min(strikes, key=lambda k: abs(k - spot * 0.95))
            kc = min(strikes, key=lambda k: abs(k - spot * 1.05))
            pm2, cm2 = np_[kp].mid, nc[kc].mid
            if pm2 is not None and cm2 and cm2 > 0:
                otm_ratio = pm2 / cm2
        if nc:
            best = max(nc.values(), key=lambda c: c.open_interest)
            call_wall = best.strike if best.open_interest > 0 else None
        if np_:
            best = max(np_.values(), key=lambda c: c.open_interest)
            put_wall = best.strike if best.open_interest > 0 else None
    return OptionSummary(
        ticker=ticker, spot=spot, as_of=as_of,
        put_call_volume=(pv / cv) if cv else None, put_call_oi=(poi / coi) if coi else None,
        call_volume=cv, put_volume=pv,
        near_expiry=near.isoformat() if near else None,
        days_to_near=(near - today).days if near else None,
        implied_move_pct=implied, otm_put_call_ratio=otm_ratio,
        call_wall=call_wall, put_wall=put_wall,
    )


async def get_option_summary(ticker: str, spot: float, today: date | None = None,
                             client: httpx.AsyncClient | None = None) -> OptionSummary | None:
    symbol = _symbol(ticker)
    if symbol is None or not spot or math.isnan(spot):
        return None
    today = today or date.today()
    params = {"limit": 3000, "fromdate": "all", "todate": "undefined", "excode": "oprac",
              "callput": "callput", "money": "all", "type": "all"}
    try:
        async with _maybe_client(client) as c:
            for assetclass in ("stocks", "etf"):
                resp = await c.get(BASE.format(symbol=symbol) + "/option-chain",
                                   params={**params, "assetclass": assetclass})
                if resp.status_code != 200:
                    continue
                payload = resp.json()
                contracts = parse_chain(payload)
                if contracts:
                    raw = str(((payload.get("data") or {}).get("lastTrade")) or "")
                    m = re.search(r"AS OF ([A-Z]{3} \d{1,2}, \d{4})", raw)
                    as_of = (datetime.strptime(m.group(1).title(), "%b %d, %Y").date().isoformat()
                             if m else today.isoformat())
                    return summarise_chain(ticker, contracts, spot, today, as_of)
        logger.warning("Nasdaq option chain empty for %s", ticker)
        return None
    except Exception as e:
        logger.warning("Nasdaq option chain failed for %s: %s", ticker, e)
        return None


class _maybe_client:
    """Use the caller's client, or open (and close) a short-lived one."""

    def __init__(self, client: httpx.AsyncClient | None):
        self._given = client
        self._own: httpx.AsyncClient | None = None

    async def __aenter__(self) -> httpx.AsyncClient:
        if self._given is not None:
            return self._given
        self._own = httpx.AsyncClient(timeout=TIMEOUT_S, headers=HEADERS, follow_redirects=True)
        return self._own

    async def __aexit__(self, *exc) -> None:
        if self._own is not None:
            await self._own.aclose()
