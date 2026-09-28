"""Live inputs for the fragility scanner (SPEC_v3 S1: fragility no longer gets `{}`).

Maps each threshold metric in config/fragility_thresholds.py to a real source,
converted into the threshold's unit. Metrics without a verified source or unit
are reported as unavailable instead of being guessed.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from marketmind.gateway.fred_client import get_fred_series

logger = logging.getLogger("marketmind.gateway.fragility_inputs")

# Metrics we deliberately do not feed yet, with the reason shown to the user.
UNSOURCED: dict[str, str] = {
    "margin_debt_gdp": "FINRA margin statistics not wired",
    "copper_gold_ratio": "threshold 3.5 has no verified unit convention (HG/GC*1000 ~1.5 today)",
    "em_import_cover": "IMF IFS not wired",
    "crypto_exchange_reserves": "CryptoQuant/Glassnode not wired",
}


@dataclass
class FragilityInputs:
    values: dict[str, float] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    unavailable: dict[str, str] = field(default_factory=dict)


async def fetch_fragility_inputs() -> FragilityInputs:
    out = FragilityInputs(unavailable=dict(UNSOURCED))
    fred_keys = ["DGS10", "RRPONTSYD", "WTREGEN", "WRESBAL", "SOFR", "IORB", "BAMLH0A3HYC",
                 "BAMLH0A0HYM2", "BAMLC0A0CM"]
    fred_results, yf_results = await asyncio.gather(
        asyncio.gather(*(get_fred_series(k) for k in fred_keys)),
        asyncio.gather(*(_yf_last(s) for s in ("^VIX", "^TNX", "DX-Y.NYB"))),
    )
    fred = {k: _fred_value(r) for k, r in zip(fred_keys, fred_results)}
    fred_dates = {k: r.get("date") if isinstance(r, dict) else None
                  for k, r in zip(fred_keys, fred_results)}
    vix, tnx, dxy = yf_results

    def put(metric: str, value: float | None, source: str, missing_reason: str) -> None:
        if value is None:
            out.unavailable[metric] = missing_reason
        else:
            out.values[metric] = round(value, 4)
            out.sources[metric] = source

    fred_missing = "FRED unavailable (FRED_KEY/FRED_API_KEY not set or unreachable)"
    if fred["DGS10"] is not None:
        put("us10y_yield", fred["DGS10"], "FRED:DGS10", "")
    else:
        put("us10y_yield", tnx, "yfinance:^TNX", "neither FRED nor yfinance returned 10Y yield")
    put("on_rrp", fred["RRPONTSYD"], "FRED:RRPONTSYD", fred_missing)
    put("tga", fred["WTREGEN"] / 1000 if fred["WTREGEN"] is not None else None,
        "FRED:WTREGEN (M->B USD)", fred_missing)
    put("bank_reserves", fred["WRESBAL"] / 1000 if fred["WRESBAL"] is not None else None,
        "FRED:WRESBAL (B->T USD)", fred_missing)
    spread = (fred["SOFR"] - fred["IORB"]) * 100 if None not in (fred["SOFR"], fred["IORB"]) else None
    put("sofr_iorb_spread", spread, "FRED:SOFR-IORB (bp)", fred_missing)
    put("ccc_treasury_spread", fred["BAMLH0A3HYC"] * 100 if fred["BAMLH0A3HYC"] is not None else None,
        "FRED:BAMLH0A3HYC (%->bp)", fred_missing)
    # hyg_lqd_spread: threshold is "HY vs IG spread >200bp" sourced from ICE BofA OAS
    # data, so we read it as HY OAS minus IG OAS, in basis points. FRED publishes both
    # indices' OAS in percent (e.g. 2.80 and 0.79), so the difference is x100 -> bp.
    # These are the index OAS the HYG/LQD ETFs track, not the ETFs' own spreads.
    hy, ig = fred["BAMLH0A0HYM2"], fred["BAMLC0A0CM"]
    hy_ig, hy_ig_missing = None, fred_missing
    if None not in (hy, ig):
        if fred_dates["BAMLH0A0HYM2"] == fred_dates["BAMLC0A0CM"]:
            hy_ig = (hy - ig) * 100
        else:
            hy_ig_missing = (f"HY/IG OAS dates differ ({fred_dates['BAMLH0A0HYM2']} vs "
                             f"{fred_dates['BAMLC0A0CM']})")
    put("hyg_lqd_spread", hy_ig, "FRED:BAMLH0A0HYM2-BAMLC0A0CM (%->bp)", hy_ig_missing)
    put("vix", vix, "yfinance:^VIX", "yfinance ^VIX unavailable")
    put("dollar_index", dxy, "yfinance:DX-Y.NYB", "yfinance DX-Y.NYB unavailable")
    return out


def _fred_value(result: dict) -> float | None:
    if not isinstance(result, dict) or result.get("error") or result.get("value") is None:
        return None
    return float(result["value"])


async def _yf_last(symbol: str) -> float | None:
    try:
        import yfinance as yf
        df = await asyncio.wait_for(
            asyncio.to_thread(lambda: yf.Ticker(symbol).history(period="5d")), timeout=30)
        if df is None or df.empty:
            return None
        return float(df["Close"].dropna().iloc[-1])
    except Exception as exc:
        logger.warning("yfinance last close failed for %s: %s", symbol, exc)
        return None
