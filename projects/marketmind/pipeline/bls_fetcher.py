"""BLS (Bureau of Labor Statistics) Public Data API v2 fetcher.

Free API, no key required (registration optional for higher daily quota).
Fetches latest values for CPI, Core CPI, Unemployment Rate, PPI.

API docs: https://www.bls.gov/developers/api_signature_v2.htm
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger("marketmind.pipeline.bls_fetcher")

BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

# Series ID → human-readable indicator name
BLS_SERIES: dict[str, str] = {
    "CUUR0000SA0": "CPI",
    "CUUR0000SA0L1E": "Core CPI",
    "LNS14000000": "Unemployment Rate",
    "WPUFD4": "PPI",
}

# Series ID → unit label
BLS_UNITS: dict[str, str] = {
    "CUUR0000SA0": "pct",
    "CUUR0000SA0L1E": "pct",
    "LNS14000000": "pct",
    "WPUFD4": "pct",
}


async def fetch_bls_indicators() -> list[dict]:
    """Fetch the latest values for CPI, Core CPI, Unemployment Rate, and PPI.

    Uses BLS Public Data API v2 (POST request with JSON body).
    Returns the most recent data point for each series.

    Returns:
        List of dicts with keys: indicator, value, date, unit, source.
        Returns empty list on API error (logs warning).
    """
    series_ids = list(BLS_SERIES.keys())
    current_year = datetime.now(timezone.utc).year

    body: dict[str, Any] = {
        "seriesid": series_ids,
        "startyear": str(current_year - 1),
        "endyear": str(current_year),
        "registrationkey": "",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                BLS_API_URL,
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "MarketMind/0.1 (contact@marketmind.dev)",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") != "REQUEST_SUCCEEDED":
            error_msg = "; ".join(data.get("message", ["Unknown error"]))
            logger.warning("BLS API returned non-success status: %s", error_msg)
            return []

        results: list[dict[str, Any]] = data.get("Results", {}).get("series", [])
        if not results:
            logger.warning("BLS API returned no series data")
            return []

        indicators: list[dict] = []
        for series in results:
            series_id = series.get("seriesID", "")
            indicator_name = BLS_SERIES.get(series_id, series_id)
            unit = BLS_UNITS.get(series_id, "pct")

            observations: list[dict] = series.get("data", [])
            if not observations:
                if series_id == "WPUFD4":
                    logger.warning("PPI data unavailable — series may be deprecated or data delayed")
                else:
                    logger.warning("BLS API: no observations for %s (%s)", indicator_name, series_id)
                continue

            # Observations are sorted newest-first by BLS API
            latest = observations[0]
            year = latest.get("year", "")
            period = latest.get("period", "")  # e.g., "M04"
            value_raw = latest.get("value", "0.0")

            date_str = f"{year}-{period.replace('M', '').zfill(2)}" if year and period else ""

            try:
                value = float(value_raw)
            except (TypeError, ValueError):
                logger.warning("BLS API: non-numeric value for %s: %s", indicator_name, value_raw)
                value = 0.0

            indicators.append({
                "indicator": indicator_name,
                "value": value,
                "date": date_str,
                "unit": unit,
                "source": "bls",
            })

        return indicators

    except httpx.HTTPStatusError as e:
        logger.warning("BLS API HTTP error: %s (status=%s)", e, e.response.status_code)
        return []
    except Exception as e:
        logger.warning("BLS API fetch failed: %s", e)
        return []
