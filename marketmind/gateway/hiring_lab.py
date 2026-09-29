"""Indeed Hiring Lab Job Postings Index (CC BY 4.0).

Source (keyless, verified reachable from Riyadh 2026-09-29):
https://github.com/hiring-lab/job_postings_tracker — raw CSVs at
https://raw.githubusercontent.com/hiring-lab/job_postings_tracker/master/<CC>/...
- aggregate_job_postings_<CC>.csv: date,jobcountry,indeed_job_postings_index_SA,
  indeed_job_postings_index_NSA,variable ("total postings" | "new postings")
- job_postings_by_sector_<CC>.csv: date,jobcountry,indeed_job_postings_index,variable,
  display_name (sector; seasonally adjusted)
Index = seasonally adjusted postings, 7-day trailing average, 1 Feb 2020 = 100.
Daily observations, refreshed weekly (so the latest date trails today by days).

Licence: CC BY 4.0 — every output carries ATTRIBUTION. Files are cached for a day
under <data dir>/altdata/hiring_lab/; a failed download falls back to the cached
copy with an explicit note.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from marketmind.gateway.altdata_store import altdata_dir, is_fresh, write_bytes_atomic

logger = logging.getLogger("marketmind.gateway.hiring_lab")

RAW_URL = "https://raw.githubusercontent.com/hiring-lab/job_postings_tracker/master/{cc}/{file}"
AGG_FILE = "aggregate_job_postings_{cc}.csv"
SECTOR_FILE = "job_postings_by_sector_{cc}.csv"
ATTRIBUTION = ("Source: Indeed Hiring Lab Job Postings Index, CC BY 4.0 "
               "(github.com/hiring-lab/job_postings_tracker); computed changes are ours")
COUNTRIES = ("US", "GB", "DE", "FR", "CA", "AU")
US_SECTORS = ("Software Development", "Banking & Finance", "Construction",
              "Production & Manufacturing", "Loading & Stocking", "Driving", "Retail",
              "Food Preparation & Service", "Hospitality & Tourism")
TOTAL = "total postings"
CHANGE_DAYS = 28
CACHE_MAX_AGE_S = 20 * 3600
HTTP_TIMEOUT_S = 60.0
_TRANSPORT: httpx.AsyncBaseTransport | None = None      # tests inject httpx.MockTransport


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, follow_redirects=True,
                             headers={"User-Agent": "MarketMind/0.1 (research)"},
                             transport=_TRANSPORT)


# ── parsers (pure) ──────────────────────────────────────────────────────────

def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_aggregate(text: str, variable: str = TOTAL) -> list[tuple[str, float]]:
    """[(date, SA index)] for one variable, date order."""
    r = csv.DictReader(io.StringIO(text))
    if not r.fieldnames or "indeed_job_postings_index_SA" not in r.fieldnames:
        raise ValueError("unexpected Hiring Lab aggregate header")
    out = [(row["date"], v) for row in r
           if row.get("variable") == variable
           and (v := _f(row.get("indeed_job_postings_index_SA"))) is not None]
    return sorted(out)


def parse_sectors(text: str, sectors, variable: str = TOTAL) -> dict[str, list[tuple[str, float]]]:
    """sector -> [(date, SA index)], date order, for the named sectors only."""
    want = set(sectors)
    r = csv.DictReader(io.StringIO(text))
    if not r.fieldnames or "display_name" not in r.fieldnames:
        raise ValueError("unexpected Hiring Lab sector header")
    out: dict[str, list[tuple[str, float]]] = {}
    for row in r:
        name = row.get("display_name")
        if name in want and row.get("variable") == variable:
            v = _f(row.get("indeed_job_postings_index"))
            if v is not None:
                out.setdefault(name, []).append((row["date"], v))
    for rows in out.values():
        rows.sort()
    return out


def change(series: list[tuple[str, float]], days: int = CHANGE_DAYS) -> dict | None:
    """Latest value and the change vs the last observation on or before latest - days."""
    if not series:
        return None
    d, v = series[-1]
    cutoff = (date.fromisoformat(d) - timedelta(days=days)).isoformat()
    prior = [x for x in series if x[0] <= cutoff]
    out = {"date": d, "value": v}
    if prior:
        pd_, pv = prior[-1]
        out.update(ref_date=pd_, ref_value=pv, chg_pts=v - pv,
                   chg_pct=(v / pv - 1) * 100 if pv else None)
    return out


# ── network + cache ─────────────────────────────────────────────────────────

async def _text(client: httpx.AsyncClient, cc: str, file: str, cache: Path) -> tuple[str, str]:
    """(csv text, note). Fresh cache is used as is; a failed download falls back to
    any cached copy and says so."""
    f = cache / file
    if is_fresh(f, CACHE_MAX_AGE_S):
        return f.read_text(encoding="utf-8"), ""
    try:
        r = await client.get(RAW_URL.format(cc=cc, file=file))
        r.raise_for_status()
        write_bytes_atomic(f, r.content)
        return r.content.decode("utf-8"), ""
    except httpx.HTTPError as e:
        if not f.exists():
            raise
        stamp = datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).date().isoformat()
        logger.warning("Hiring Lab %s download failed (%s); using cache", file, e)
        return (f.read_text(encoding="utf-8"),
                f"{file}: download failed ({type(e).__name__}), cached copy from {stamp}")


async def load_postings(countries=COUNTRIES, sectors=US_SECTORS,
                        data_dir: Path | None = None) -> dict:
    """{"countries": {cc: change-dict | {"error"}}, "sectors": {name: change-dict | {"error"}},
    "notes": [...], "attribution": ATTRIBUTION}. Raises only if nothing loaded."""
    cache = altdata_dir("hiring_lab", data_dir)
    out: dict = {"countries": {}, "sectors": {}, "notes": [], "attribution": ATTRIBUTION}
    async with _client() as c:
        for cc in countries:
            try:
                text, note = await _text(c, cc, AGG_FILE.format(cc=cc), cache)
                out["countries"][cc] = change(parse_aggregate(text)) or {"error": "no rows"}
                if note:
                    out["notes"].append(note)
            except (httpx.HTTPError, ValueError, OSError) as e:
                out["countries"][cc] = {"error": type(e).__name__}
        if sectors:
            try:
                text, note = await _text(c, "US", SECTOR_FILE.format(cc="US"), cache)
                parsed = parse_sectors(text, sectors)
                del text
                for s in sectors:
                    out["sectors"][s] = change(parsed.get(s, [])) or {"error": "sector not in file"}
                if note:
                    out["notes"].append(note)
            except (httpx.HTTPError, ValueError, OSError) as e:
                out["sectors"] = {s: {"error": type(e).__name__} for s in sectors}
    ok = [v for v in (*out["countries"].values(), *out["sectors"].values()) if "error" not in v]
    if not ok:
        raise RuntimeError("Hiring Lab: no series loaded")
    return out
