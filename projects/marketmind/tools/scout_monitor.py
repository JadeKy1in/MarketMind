"""Scout Monitor — daily source health check with color-coded alerts.

Usage:
    python tools/scout_monitor.py              # standalone
    python tools/scout_monitor.py --pipeline   # called from run_daily (no color)

Outputs a formatted report showing:
- Articles per source (count + content depth)
- NEW failures (previously working sources now broken)
- RECOVERED sources (previously broken sources now working)
- Color-coded urgency: RED=critical loss, YELLOW=degraded, GREEN=recovered

State is persisted to data/scout_state.json for change detection.
"""
from __future__ import annotations
import asyncio, json, logging, os, sys, tempfile
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT.parent))

from marketmind.config.source_authority import SOURCES, Source, SourceTier, SourceStatus
from marketmind.config.settings import MarketMindConfig

logger = logging.getLogger("marketmind.tools.scout_monitor")

STATE_FILE = PROJECT_ROOT / "data" / "scout_state.json"

# ── ANSI colors for terminal output ────────────────────────────────────────
RED = "\033[91m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


@dataclass
class SourceReport:
    name: str
    tier: str
    articles: int
    with_content: int      # articles with summary/description text
    avg_content_len: int
    status: str            # OK / DEGRADED / EMPTY / FAILED / API / SKIPPED
    prev_status: str       # previous known status
    change: str            # STABLE / NEW_FAILURE / RECOVERED / NEW_EMPTY / FIRST_RUN
    error: str
    is_critical: bool      # PRIMARY source now failing?


# ── State persistence ───────────────────────────────────────────────────────

def load_state() -> dict:
    """Load persisted source health state.

    Returns default empty state if the file is missing or corrupted.
    This prevents a corrupted state file from crashing the entire monitor.
    """
    if not STATE_FILE.exists():
        return {"sources": {}, "last_run": None}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(
            "Corrupted scout state file (%s), resetting to empty state. "
            "The corrupted file was NOT deleted — inspect manually and remove: %s",
            e, STATE_FILE
        )
        return {"sources": {}, "last_run": None}


def save_state(reports: list[SourceReport]) -> None:
    """Atomically persist source health state using temp-file + rename.

    This prevents corruption if the process crashes mid-write — the
    original file is only replaced after the full payload is written.
    """
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "last_run": datetime.now(timezone.utc).isoformat(),
        "sources": {r.name: r.status for r in reports},
    }
    tmp = None
    try:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", dir=str(STATE_FILE.parent),
            prefix=".scout_state.", delete=False, encoding="utf-8",
        )
        json.dump(state, tmp, indent=2, ensure_ascii=False)
        tmp.flush()
        os.fsync(tmp.fileno())
    finally:
        if tmp is not None:
            tmp.close()
    os.replace(tmp.name, STATE_FILE)


# ── Change classification ───────────────────────────────────────────────────

def _compute_change(prev: str, current_status: str) -> str:
    """Determine change type given previous and current status.

    On first run (prev="unknown"), all sources report FIRST_RUN instead of
    RECOVERED or NEW_FAILURE — this prevents false-positive alerts when the
    monitor has no baseline to compare against.
    """
    if prev == "unknown":
        return "FIRST_RUN"
    if current_status == "OK":
        return "RECOVERED" if prev != "OK" else "STABLE"
    elif current_status == "EMPTY":
        return "NEW_EMPTY" if prev == "OK" else "STABLE"
    else:  # FAILED, DEGRADED
        return "NEW_FAILURE" if prev == "OK" else "STABLE"


# ── Source health check ─────────────────────────────────────────────────────

async def fetch_one(source: Source, config: MarketMindConfig, prev: str) -> SourceReport:
    """Check the health of a single source.

    Delegates actual fetching to pipeline/scout.py (for RSS, BLS, Bluesky,
    NewsAPI, GNews) and gateway/macro_data.py (for CFTC COT).  The monitor
    only adds its own health-reporting layer on top.

    Args:
        source: Source definition from source_authority.py.
        config: MarketMindConfig with API keys.
        prev: Previous known status string (from persisted state).

    Returns:
        SourceReport with status and change classification.
    """
    tier_name = SourceTier(source.tier).name
    is_primary = bool(source.tier == SourceTier.PRIMARY)

    try:
        # ── NewsAPI / GNews: skip if no API key configured ──
        if source.name == "NewsAPI" and not config.newsapi_key:
            return SourceReport(
                source.name, tier_name, -1, -1, 0, "API", prev,
                "STABLE", "API key not configured", False,
            )
        if source.name == "GNews" and not config.gnews_key:
            return SourceReport(
                source.name, tier_name, -1, -1, 0, "API", prev,
                "STABLE", "API key not configured", False,
            )

        # ── CFTC COT: dedicated health check via CFTC SODA API ──
        if source.name == "CFTC COT":
            from marketmind.gateway.macro_data import get_cot_data

            result = await get_cot_data("ES")
            if "error" in result:
                change = _compute_change(prev, "FAILED")
                return SourceReport(
                    source.name, tier_name, 0, 0, 0, "FAILED", prev,
                    change, result.get("detail", "API unreachable"), is_primary,
                )
            change = _compute_change(prev, "OK")
            return SourceReport(
                source.name, tier_name, -1, -1, 0, "OK", prev, change,
                f"COT available (latest: {result.get('date', 'N/A')})", False,
            )

        # ── RSS / BLS / Bluesky / NewsAPI / GNews: delegate to scout ──
        from marketmind.pipeline.scout import fetch_source as scout_fetch

        items = await scout_fetch(source, config)

        # scout.fetch_source sets source.status in-place — use it
        if source.status == SourceStatus.WORKING:
            if not items:
                change = _compute_change(prev, "EMPTY")
                return SourceReport(
                    source.name, tier_name, 0, 0, 0, "EMPTY", prev,
                    change, "0 articles", is_primary,
                )
            with_content = sum(1 for it in items if it.summary)
            total_len = sum(len(it.summary) for it in items if it.summary)
            avg_len = total_len // with_content if with_content else 0
            change = _compute_change(prev, "OK")
            return SourceReport(
                source.name, tier_name, len(items), with_content, avg_len,
                "OK", prev, change, "", False,
            )
        elif source.status == SourceStatus.DEGRADED:
            change = _compute_change(prev, "DEGRADED")
            return SourceReport(
                source.name, tier_name, len(items), 0, 0, "DEGRADED", prev,
                change, f"{source.consecutive_failures} consecutive failures",
                is_primary,
            )
        elif source.status == SourceStatus.DEAD:
            change = _compute_change(prev, "FAILED")
            return SourceReport(
                source.name, tier_name, 0, 0, 0, "FAILED", prev,
                change, f"{source.consecutive_failures} consecutive failures",
                is_primary,
            )
        else:  # UNTESTED — unknown feed_type, no handler
            return SourceReport(
                source.name, tier_name, 0, 0, 0, "SKIPPED", prev,
                "STABLE", f"feed_type={source.feed_type}", False,
            )
    except Exception as e:
        change = _compute_change(prev, "FAILED")
        return SourceReport(
            source.name, tier_name, 0, 0, 0, "FAILED", prev,
            change, str(e)[:100], is_primary,
        )


async def run_monitor(config: MarketMindConfig | None = None) -> list[SourceReport]:
    """Run full source health check. Returns list of SourceReport.

    Loads persisted state once and passes the previous status to each
    fetch_one call — avoids 35 redundant file reads.
    """
    if config is None:
        config = MarketMindConfig()
    state = load_state()
    prev_sources: dict[str, str] = state.get("sources", {})

    tasks = [
        fetch_one(source, config, prev_sources.get(source.name, "unknown"))
        for source in SOURCES
    ]
    return await asyncio.gather(*tasks)


# ── Report formatting ───────────────────────────────────────────────────────

def _c(text: str, color: str) -> str:
    """Wrap text in ANSI color if stdout supports it."""
    return f"{color}{text}{RESET}"


def print_report(reports: list[SourceReport], use_color: bool = True) -> None:
    """Print formatted monitoring report."""
    c = _c if use_color else lambda t, _: t

    ok = [r for r in reports if r.status == "OK"]
    api_skipped = [r for r in reports if r.status == "API"]
    failed = [r for r in reports if r.status in ("FAILED", "DEGRADED")]
    empty = [r for r in reports if r.status == "EMPTY"]
    new_failures = [r for r in reports if r.change == "NEW_FAILURE"]
    recovered = [r for r in reports if r.change == "RECOVERED"]
    critical = [r for r in reports if r.is_critical and r.status in ("FAILED", "DEGRADED")]
    degraded = [r for r in reports if r.status == "DEGRADED"]

    total_articles = sum(r.articles for r in ok)
    content_rich = sum(1 for r in ok if r.with_content > 0 and r.avg_content_len >= 50)

    # ── Header ──
    print()
    print(c(f"  {'='*60}", CYAN))
    print(c(f"  Scout Monitor — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", BOLD))
    print(c(f"  {'='*60}", CYAN))

    # ── Empty guard ──
    if not reports:
        print("  No sources configured.")
        print()
        return

    # ── Summary line ──
    print(f"  {len(ok)} working | {len(api_skipped)} API | {len(failed)} failed | "
          f"{len(empty)} empty | {total_articles} articles | {content_rich} content-rich")

    # ── CRITICAL alerts ──
    if critical:
        print()
        print(c(f"  !! CRITICAL — PRIMARY sources DOWN:", RED + BOLD))
        for r in critical:
            print(c(f"     {r.name}: {r.error}", RED))

    # ── NEW failures ──
    if new_failures:
        print()
        print(c(f"  !! NEW FAILURES (were working, now broken):", YELLOW + BOLD))
        for r in new_failures:
            print(c(f"     {r.name} [{r.tier}] — {r.error}", YELLOW))

    # ── RECOVERED ──
    if recovered:
        print()
        print(c(f"  -- RECOVERED (were broken, now working):", GREEN))
        for r in recovered:
            print(c(f"     {r.name} — {r.articles} articles", GREEN))

    # ── Degraded (separate from hard failures) ──
    if degraded:
        print()
        print(c(f"  -- DEGRADED (partial failures):", YELLOW))
        for r in degraded:
            print(c(f"     {r.name} [{r.tier}] — {r.error}", YELLOW))

    # ── Content warnings ──
    degraded_content = [r for r in ok if r.with_content == 0]
    if degraded_content:
        print()
        print(c(f"  -- HEADLINES ONLY (no article content):", YELLOW))
        for r in degraded_content:
            print(c(f"     {r.name} — {r.articles} titles, 0 summaries", YELLOW))

    # ── Working sources table ──
    print()
    print(f"  {'Source':<35s} {'Tier':<12s} {'#':>4s} {'Content':>8s} {'AvgLen':>6s}")
    print(f"  {'-'*65}")
    for r in sorted(ok, key=lambda x: (-x.articles, x.name)):
        content_mark = f"{r.with_content}/{r.articles}" if r.articles > 0 else "—"
        color = GREEN if r.change == "RECOVERED" else ""
        print(f"  {c(r.name, color):<35s} {r.tier:<12s} {r.articles:4d} {content_mark:>8s} {r.avg_content_len:5d} chars")

    # ── Failed sources ──
    if failed:
        print()
        print(c(f"  Failed / degraded sources:", RED if failed else ""))
        for r in failed:
            print(f"     {r.name:<35s} [{r.status}] {r.error}")

    # ── Empty sources ──
    if empty:
        print()
        print(c(f"  Empty sources (working but no articles):", YELLOW))
        for r in empty:
            print(f"     {r.name:<35s} {r.error}")

    # ── Footer ──
    print()
    if new_failures or critical:
        print(c(f"  >>> ACTION REQUIRED: {len(new_failures)} newly broken, "
                f"{len(critical)} primary sources down", RED + BOLD))
    elif failed:
        print(c(f"  >>> {len(failed)} sources still offline (no change from last check)", YELLOW))
    else:
        print(c(f"  >>> All sources healthy", GREEN))
    print()


# ── Entry point ─────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--pipeline", action="store_true",
                        help="Called from run_daily pipeline (suppresses ANSI color)")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON instead of text")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable ANSI colors")
    args = parser.parse_args()

    reports = asyncio.run(run_monitor())

    if args.json:
        output = []
        for r in reports:
            output.append({
                "name": r.name, "tier": r.tier, "articles": r.articles,
                "with_content": r.with_content, "avg_content_len": r.avg_content_len,
                "status": r.status, "change": r.change, "error": r.error,
            })
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        # --pipeline suppresses color (pipeline output goes to logs)
        print_report(reports, use_color=not args.no_color and not args.pipeline)

    save_state(reports)


if __name__ == "__main__":
    main()
