"""Economic calendar — pre-pipeline event filter for HIGH-impact events.

Phase G Layer 6: Check for economic events BEFORE the scout phase runs.
Sources: FOMC dates (hardcoded, no machine-readable endpoint) + FRED release calendar.

Red Team design: CONDITIONAL PASS (red-team-options-calendar-design.md).
Blockers addressed:
  3. FRED API key via standard .env addition (fred_key in MarketMindConfig).
  FOMC dates hardcoded with expiration check and fail-safe conservative default.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone, timedelta
from typing import Any

import httpx

logger = logging.getLogger("marketmind.pipeline.economic_calendar")

# ── FOMC Meeting Dates for 2026 ─────────────────────────────────────────────────
# Industry-wide limitation: no machine-readable FOMC endpoint exists.
# These 8 meetings/year are the scheduled dates from the Federal Reserve calendar.
# After expiry (2026-12-31), a CRITICAL warning is logged and a conservative
# fail-safe assumes every day COULD be FOMC day.
FOMC_DATES_2026: list[str] = [
    "2026-01-28", "2026-03-18", "2026-05-06", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
]
FOMC_EXPIRY_DATE: str = "2026-12-31"
FOMC_EXPIRY_WARNING_LOGGED: bool = False

# ── FRED Release Impact Classification ──────────────────────────────────────────
# HIGH: FOMC, CPI, NFP — these dominate all other market signals
# MEDIUM: GDP, PCE, Retail Sales, Jobless Claims — significant but secondary
# LOW: everything else (Industrial Production, Housing Starts, etc.)
_HIGH_IMPACT_KEYWORDS: list[str] = [
    "consumer price index", "cpi",
    "nonfarm payroll", "employment situation",
    "federal open market committee", "fomc",
]
_MEDIUM_IMPACT_KEYWORDS: list[str] = [
    "gross domestic product", "gdp",
    "personal consumption expenditures", "pce",
    "retail sales",
    "jobless claims", "initial claims",
]

# ── FRED API Configuration ──────────────────────────────────────────────────────
FRED_RELEASE_URL = "https://api.stlouisfed.org/fred/releases"


def _classify_fred_impact(release_name: str) -> str:
    """Classify a FRED release by name into HIGH/MEDIUM/LOW impact."""
    name_lower = release_name.lower()
    for kw in _HIGH_IMPACT_KEYWORDS:
        if kw in name_lower:
            return "HIGH"
    for kw in _MEDIUM_IMPACT_KEYWORDS:
        if kw in name_lower:
            return "MEDIUM"
    return "LOW"


def _parse_date(date_str: str) -> date | None:
    """Parse a date string into a date object, returning None on failure."""
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%B %d, %Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def _get_fomc_window_events(
    lookahead_hours: int,
    now_utc: datetime | None = None,
) -> list[dict]:
    """Get FOMC events within the lookahead window.

    Args:
        lookahead_hours: Hours to look ahead from now.
        now_utc: Current UTC datetime override (for testing).

    Returns:
        List of FOMC event dicts within the window.
    """
    global FOMC_EXPIRY_WARNING_LOGGED
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    now_date = now_utc.date()
    window_end = now_utc + timedelta(hours=lookahead_hours)
    window_end_date = window_end.date()

    # Check expiry
    expiry_date = _parse_date(FOMC_EXPIRY_DATE)
    if expiry_date and now_date > expiry_date:
        if not FOMC_EXPIRY_WARNING_LOGGED:
            logger.critical(
                "FOMC_DATES_2026 has expired (past %s). "
                "Using conservative default: assume every trading day COULD be FOMC. "
                "Update FOMC_DATES_2026 in pipeline/economic_calendar.py.",
                FOMC_EXPIRY_DATE,
            )
            FOMC_EXPIRY_WARNING_LOGGED = True
        # Conservative fail-safe: check if any weekday within window
        current = now_date
        fomc_events = []
        while current <= window_end_date:
            if current.weekday() < 5:  # Mon-Fri
                fomc_events.append({
                    "name": "FOMC (expired — conservative default)",
                    "date": current.isoformat(),
                    "impact": "HIGH",
                    "source": "fomc_hardcoded_expired",
                    "hours_until": max(0.0, (
                        datetime.combine(current, datetime.min.time(), tzinfo=timezone.utc)
                        - now_utc
                    ).total_seconds() / 3600.0),
                })
            current += timedelta(days=1)
        return fomc_events

    # Normal operation: check hardcoded dates
    fomc_events = []
    for fomc_str in FOMC_DATES_2026:
        fomc_date = _parse_date(fomc_str)
        if fomc_date is None:
            continue
        if now_date <= fomc_date <= window_end_date:
            fomc_dt = datetime.combine(fomc_date, datetime.min.time(), tzinfo=timezone.utc)
            hours_until = max(0.0, (fomc_dt - now_utc).total_seconds() / 3600.0)
            fomc_events.append({
                "name": "FOMC Meeting",
                "date": fomc_str,
                "impact": "HIGH",
                "source": "fomc_hardcoded",
                "hours_until": round(hours_until, 1),
            })
    return fomc_events


async def _fetch_fred_releases(fred_key: str) -> list[dict]:
    """Fetch FRED release calendar via the St. Louis Fed API.

    Args:
        fred_key: FRED API key (from config or env).

    Returns:
        List of release dicts with name, date, impact classification.
    """
    if not fred_key:
        logger.warning("FRED API key not configured — skipping FRED release check")
        return []

    params: dict[str, str] = {
        "api_key": fred_key,
        "file_type": "json",
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            resp = await client.get(
                FRED_RELEASE_URL,
                params=params,
                headers={"User-Agent": "MarketMind/0.1"},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        logger.warning("FRED release API HTTP error: %s", e)
        return []
    except Exception as e:
        logger.warning("FRED release API unexpected error: %s", e)
        return []

    releases = data.get("releases", [])
    if not isinstance(releases, list):
        logger.warning("FRED API returned unexpected format: %s", type(releases))
        return []

    return releases


def _filter_releases_by_window(
    releases: list[dict],
    lookahead_hours: int,
    now_utc: datetime | None = None,
) -> list[dict]:
    """Filter FRED releases to those within the lookahead window.

    Args:
        releases: Raw FRED release dicts.
        lookahead_hours: Lookahead window in hours.
        now_utc: Current UTC datetime (for testing).

    Returns:
        Filtered and classified release events, sorted by date.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    now_date = now_utc.date()
    window_end = now_date + timedelta(hours=lookahead_hours // 24 + 1)

    filtered = []
    for rel in releases:
        release_name = rel.get("name", "")
        next_date_str = rel.get("next_release_date", "")
        release_date = _parse_date(next_date_str)
        if release_date is None:
            continue
        if now_date <= release_date <= window_end:
            impact = rel.get("impact", _classify_fred_impact(release_name))
            # Override with our keyword-based classification if not pre-set
            if impact not in ("HIGH", "MEDIUM", "LOW"):
                impact = _classify_fred_impact(release_name)

            release_dt = datetime.combine(
                release_date, datetime.min.time(), tzinfo=timezone.utc
            )
            hours_until = max(
                0.0, (release_dt - now_utc).total_seconds() / 3600.0
            )

            filtered.append({
                "name": release_name,
                "date": release_date.isoformat(),
                "impact": impact,
                "source": f"fred_release_{rel.get('id', 'unknown')}",
                "hours_until": round(hours_until, 1),
            })

    # Sort by date then impact (HIGH first)
    filtered.sort(key=lambda x: (x["date"], {"HIGH": 0, "MEDIUM": 1, "LOW": 2}[x["impact"]]))
    return filtered


async def check_economic_calendar(
    lookahead_hours: int = 24,
    fred_key: str = "",
    now_utc: datetime | None = None,
) -> dict:
    """Check for HIGH-impact economic events within the lookahead window.

    This should be called BEFORE the scout phase (stage 0.5 in app.py).
    Results inform the entire pipeline: confidence discounts are applied
    mechanically (not via LLM judgment) to downstream analysis.

    Args:
        lookahead_hours: Hours to look ahead from now (default 24).
        fred_key: FRED API key. If empty, only FOMC hardcoded dates are checked.
        now_utc: Current UTC datetime override (for testing).

    Returns:
        Dict with:
          - high_impact_events: list of HIGH-impact event dicts
          - medium_impact_events: list of MEDIUM-impact event dicts
          - has_high_impact: bool
          - pipeline_annotation: str for context injection
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    all_events: list[dict] = []

    # 1. FOMC dates (hardcoded)
    fomc_events = _get_fomc_window_events(lookahead_hours, now_utc=now_utc)
    all_events.extend(fomc_events)

    # 2. FRED release calendar
    if fred_key:
        fred_releases = await _fetch_fred_releases(fred_key)
        fred_events = _filter_releases_by_window(fred_releases, lookahead_hours, now_utc)
        all_events.extend(fred_events)

    # Separate HIGH from MEDIUM/LOW
    high_events = [e for e in all_events if e["impact"] == "HIGH"]
    medium_events = [e for e in all_events if e["impact"] == "MEDIUM"]
    has_high = len(high_events) > 0

    # Build annotation for pipeline context
    if has_high:
        names = ", ".join(e["name"] for e in high_events[:3])
        pipeline_annotation = (
            f"HIGH-IMPACT ECONOMIC EVENT(S) DETECTED: {names}. "
            "Apply event-aware confidence discounts. "
            "Do NOT treat price movements as thesis-confirming signals until "
            "at least 2 hours after event resolution."
        )
    elif medium_events:
        names = ", ".join(e["name"] for e in medium_events[:3])
        pipeline_annotation = (
            f"MEDIUM-IMPACT economic data releases scheduled: {names}. "
            "Heightened attention but no automatic discount applied."
        )
    else:
        pipeline_annotation = "No high-impact economic events in the lookahead window."

    result = {
        "high_impact_events": high_events,
        "medium_impact_events": medium_events,
        "has_high_impact": has_high,
        "pipeline_annotation": pipeline_annotation,
        "checked_at": now_utc.isoformat(),
        "lookahead_hours": lookahead_hours,
    }
    logger.info(
        "Economic calendar check: %d HIGH, %d MEDIUM events in %dh window",
        len(high_events), len(medium_events), lookahead_hours,
    )
    return result


def get_event_confidence_discount(events: dict) -> float:
    """Return a confidence multiplier based on economic event proximity.

    This is a MECHANICAL rule — NOT LLM judgment. Applied uniformly to
    all downstream confidence estimates when high-impact events are near.

    Multipliers:
      0.40 = FOMC within 4 hours (dominates all other signals)
      0.60 = ANY high-impact event within 4 hours
      0.70 = FOMC within 4-24 hours
      0.85 = ANY high-impact event within 4-24 hours
      0.90 = MEDIUM-impact event within 4 hours
      1.00 = no high-impact event in window

    Args:
        events: The dict returned by check_economic_calendar().

    Returns:
        Float multiplier in [0.40, 1.0]. Apply as: confidence *= discount.
    """
    has_high = events.get("has_high_impact", False)
    if not has_high:
        # Check for medium events only
        medium_events = events.get("medium_impact_events", [])
        if medium_events:
            for e in medium_events:
                if e.get("hours_until", 99) < 4:
                    return 0.90
        return 1.0

    high_events = events.get("high_impact_events", [])
    min_hours = min(
        (e.get("hours_until", 99) for e in high_events),
        default=99,
    )

    # Check if any HIGH event is FOMC
    is_fomc = any("FOMC" in e.get("name", "") for e in high_events)

    if min_hours < 4:
        return 0.40 if is_fomc else 0.60
    if min_hours < 24:
        return 0.70 if is_fomc else 0.85

    return 1.0
