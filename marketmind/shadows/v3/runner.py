"""Daily shadow run: context -> Flash -> validated decisions -> unified ledger.

docs/S3_DESIGN.md §3. One call per active shadow (plus one repair retry when
the reply fails validation); a shadow with no valid decision after that has
"missed" the day, which is reported, never filled in. Each shadow that
submitted also gets a same-domain random benchmark record (§3.6).
A shadow submits once per target session (docs/S2_DESIGN.md §4): a re-run skips
shadows that already have records for the session a record made now would trade
in, and the ledger rejects a second submission for the same session atomically.
Conditional signals (docs/S3_DESIGN.md §9, pending_signals.py) are registered with a
recorded submission and checked at the start of every run; a triggered one becomes a
ledger record with meta.pending_signal_id, which the once-per-session check ignores
(it never stands in for the forced daily decision).
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import statistics
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from marketmind.gateway import llm_trace, usage_tracker
from marketmind.gateway.price_history import get_price_histories
from marketmind.ledger import baselines as baselines_mod
from marketmind.ledger.settlement import target_session
from marketmind.ledger.store import LedgerEntry, LedgerStore
from marketmind.ledger.trend_tag import TrendTagger
from marketmind.shadows.v3 import pending_signals
from marketmind.shadows.v3 import roster as roster_mod
from marketmind.shadows.v3 import self_feedback
from marketmind.shadows.v3.context import (
    BEAR_TRACKER_ID, FADE_MASTER_ID, NEWS_HOUND_ID, OPTIONS_READER_ID, SQUEEZE_WATCH_ID,
    ShadowContext, build_context, news_tickers, red_flag_tickers, ticker_view,
)
from marketmind.markets import market_for
from marketmind.shadows.v3.decision import OUTPUT_INSTRUCTIONS, ParseResult, parse_decisions

logger = logging.getLogger("marketmind.shadows.v3.runner")

MODEL = "flash"                  # owner decision 2026-09-28: shadows use Flash
CONCURRENCY = 5
CALL_TIMEOUT_S = 300
SCALPER_ID = "momentum:intraday:scalper"


def _lineage(entry) -> str:
    """Shadow-specific inputs are keyed by the original roster id, so a successor
    ("x@2", docs/S7_DESIGN.md §一 退役) gets its predecessor's inputs."""
    return roster_mod.lineage_id(entry.shadow_id)


@dataclass
class ShadowResult:
    shadow_id: str
    status: str                      # submitted | missed | skipped | duplicate
    entry_ids: list[str] = field(default_factory=list)
    benchmark_id: str | None = None
    baseline_ids: list[str] = field(default_factory=list)   # code baselines (comparison only)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    attempts: int = 0
    raw: list[str] = field(default_factory=list)
    pending_ids: list[str] = field(default_factory=list)     # conditional signals registered


@dataclass
class RunReport:
    date: str
    results: list[ShadowResult] = field(default_factory=list)
    pending: dict = field(default_factory=dict)     # conditional-signal check (pending_signals.check)

    def summary(self) -> str:
        n = {s: sum(r.status == s for r in self.results)
             for s in ("submitted", "missed", "skipped", "duplicate")}
        records = sum(len(r.entry_ids) for r in self.results)
        text = (f"shadows: {n['submitted']} submitted ({records} decisions), "
                f"{n['missed']} missed, {n['skipped']} already done today")
        if n["duplicate"]:
            text += f", {n['duplicate']} duplicate submissions not recorded"
        new = sum(len(r.pending_ids) for r in self.results)
        fired, gone = len(self.pending.get("triggered", [])), (
            len(self.pending.get("expired", [])) + len(self.pending.get("cancelled", [])))
        if new or fired or gone:
            text += f"; conditional signals: {new} new, {fired} triggered, {gone} expired"
        missed = [r.shadow_id.rsplit(':', 1)[-1] for r in self.results if r.status == "missed"]
        return text + (f" — missed: {', '.join(missed)}" if missed else "")


def _tradable(ticker: str) -> bool:
    """Shadows trade any real market instrument (docs/S3_DESIGN.md §7), not only Robinhood's."""
    from marketmind.markets import is_shadow_tradable
    return is_shadow_tradable(ticker)


MAX_OFF_CONTEXT = 3


async def _price_off_context(text: str, known: dict[str, float]) -> dict[str, float]:
    """Last close for tickers the reply names that the context did not price."""
    from marketmind.shadows.v3.decision import extract_json
    try:
        data = extract_json(text)
    except ValueError:
        return {}
    raw = data.get("decisions") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        return {}
    extra = data.get("conditional_signals") if isinstance(data, dict) else None
    raw = raw + (extra if isinstance(extra, list) else [])
    known_upper = {k.upper() for k in known}
    wanted = []
    for d in raw:
        if isinstance(d, dict):
            t = str(d.get("ticker", "")).strip().upper().lstrip("$")
            if t and t not in known_upper and _tradable(t) and t not in wanted:
                wanted.append(t)
    if not wanted:
        return {}
    histories = await get_price_histories(wanted[:MAX_OFF_CONTEXT])
    out = {}
    for t in wanted[:MAX_OFF_CONTEXT]:
        view = ticker_view(t, histories.get(t))
        if view.snap is not None:
            out[t] = view.snap.close
        else:
            logger.info("Off-context ticker %s has no price data; decision will be dropped", t)
    return out


def _asset_type(ticker: str) -> str:
    from marketmind.ledger.recorder import classify_ticker
    return classify_ticker(ticker)[1]


def _run_date(e: LedgerEntry) -> str:
    return (e.meta or {}).get("run_date") or e.created_at[:10]


def _from_signal(e: LedgerEntry) -> bool:
    """A triggered conditional signal: counts toward the record, not the daily minimum."""
    return bool((e.meta or {}).get("pending_signal_id"))


def daily_session(e: LedgerEntry) -> str | None:
    """Session key of the once-per-session submission check; triggered conditional
    signals have none, so they neither block nor satisfy a day's forced decision."""
    return None if _from_signal(e) else target_session(e)


def _already_recorded(store: LedgerStore, entries: list, created_at: str) -> set[str]:
    """Shadows that already have a record for the session the same ticker would
    target if recorded at `created_at` (so no LLM call is spent on a duplicate)."""
    done = set()
    for e in entries:
        for r in store.recent(e.source_type, e.shadow_id, created_at):
            if _from_signal(r):
                continue
            if target_session(r) == target_session(replace(r, created_at=created_at)):
                done.add(e.shadow_id)
                break
    return done


def _previous_consensus(store: LedgerStore, today: str) -> list[tuple[str, str, str]]:
    """(source_id, ticker, direction) of the most recent earlier day with shadow records."""
    rows = [e for e in store.list(source_type="shadow")
            if _run_date(e) < today and not _from_signal(e)]
    if not rows:
        return []
    last = max(_run_date(e) for e in rows)
    return [(e.source_id, e.ticker, e.direction) for e in rows if _run_date(e) == last]


async def _call_llm(system: str, user: str, stage: str) -> str:
    from marketmind.gateway.async_client import chat_with_integrity
    token = usage_tracker.set_stage(stage)
    try:
        result = await asyncio.wait_for(
            chat_with_integrity(model=MODEL, system_prompt=system, user_prompt=user,
                                caller_agent=stage, temperature=0.4),
            timeout=CALL_TIMEOUT_S)
    finally:
        usage_tracker.reset_stage(token)
    if result.get("error"):
        raise RuntimeError(f"LLM error: {result.get('error')}")
    return result.get("content") or ""


def system_prompt(entry, own_record: bool = False) -> str:
    """Methodology + output format; the self-feedback treatment arm (docs/S3_DESIGN.md §8)
    also gets the instruction on using its record, so its prompt_version differs."""
    text = roster_mod.load_prompt(entry) + "\n\n" + OUTPUT_INSTRUCTIONS
    return text + "\n\n" + self_feedback.SYSTEM_INSTRUCTIONS if own_record else text


async def decide(ctx: ShadowContext, call=_call_llm) -> tuple[ParseResult, list[str], int]:
    """Ask once, retry once with the validation errors; returns (result, raw replies, attempts)."""
    system = system_prompt(ctx.entry, bool(ctx.own_record))
    user = ctx.render()
    fixed = 1 if _lineage(ctx.entry) == SCALPER_ID else None
    stage = f"shadow:{ctx.entry.name}"
    raws: list[str] = []
    result = ParseResult()
    off_context: dict[str, float] = {}
    ctx.off_context = off_context
    for attempt in (1, 2):
        try:
            text = await call(system, user, stage)
        except Exception as e:  # transport/budget failure: counted as an attempt, reported
            result = ParseResult(errors=[f"attempt {attempt}: {type(e).__name__}: {e}"])
            raws.append("")
            continue
        raws.append(text)
        extra = await _price_off_context(text, ctx.closes)
        off_context.update(extra)
        result = parse_decisions(text, {**ctx.closes, **extra}, fixed_hold=fixed,
                                 no_levels=set(extra), atrs=ctx.atrs,
                                 ret_5d={v.ticker: v.ret_5d for v in ctx.views
                                         if v.ret_5d is not None})
        if result.ok:
            return result, raws, attempt
        user = (ctx.render() + "\n\n## Your previous reply was rejected\n"
                + "\n".join(f"- {e}" for e in result.errors)
                + "\nReply again with valid JSON only, at least one decision.")
    return result, raws, 2


async def _check_pending(store: LedgerStore, entries: list, retired: set[str], today: str,
                         created_at: str, path: Path, tagger: TrendTagger | None = None) -> dict:
    """Trigger check of the run's shadows' conditional signals; never fails the run."""
    try:
        ids = {e.shadow_id for e in entries}
        tickers = pending_signals.tickers_to_check(path, ids)
        histories = await get_price_histories(tickers) if tickers else {}
        out = pending_signals.check(path, store, histories, shadow_ids=ids, retired=retired,
                                    today=today, created_at=created_at, tagger=tagger)
    except Exception as exc:
        logger.error("conditional-signal check failed", exc_info=True)
        return {"error": f"{type(exc).__name__}: {exc}"}
    if out["triggered"] or out["expired"] or out["cancelled"]:
        logger.info("conditional signals: %d triggered, %d expired, %d cancelled, %d waiting",
                    len(out["triggered"]), len(out["expired"]), len(out["cancelled"]),
                    out["waiting"])
    return out


async def _derivatives_lines(todo: list, histories: dict, today: str, fetch=None) -> dict:
    """Short interest for squeeze_watch, option-chain summaries for options_reader."""
    from datetime import date as _date
    if fetch is None:
        from marketmind.gateway import nasdaq_derivs as fetch
    out: dict[str, dict] = {}
    for e in todo:
        if _lineage(e) == SQUEEZE_WATCH_ID:
            stocks = [t for t in e.watchlist if t != e.domain_benchmark]
            got = await asyncio.gather(*(fetch.get_short_interest(t) for t in stocks))
            out[e.shadow_id] = {"short_interest": [
                g.line() if g else f"- {t}: short interest unavailable"
                for t, g in zip(stocks, got)]}
        elif _lineage(e) == OPTIONS_READER_ID:
            day = _date.fromisoformat(today)
            spots = {t: ticker_view(t, histories.get(t)).snap for t in e.watchlist}
            tickers = [t for t, snap in spots.items() if snap is not None]
            got = await asyncio.gather(*(fetch.get_option_summary(t, spots[t].close, day)
                                         for t in tickers))
            out[e.shadow_id] = {"options": [
                g.line() if g else f"- {t}: option chain unavailable"
                for t, g in zip(tickers, got)]}
    return out


TAG_FETCH_TIMEOUT_S = 120


async def _trend_inputs(tickers: list[str], histories: dict) -> dict:
    """Histories for tickers the run did not fetch up front (off-context picks): the
    gateway cache already holds them, so this is bounded and normally no network.
    Failure leaves them out (their tag says UNAVAILABLE)."""
    missing = [t for t in dict.fromkeys(tickers) if t not in histories]
    if not missing:
        return histories
    try:
        got = await asyncio.wait_for(get_price_histories(missing), timeout=TAG_FETCH_TIMEOUT_S)
    except Exception:
        logger.warning("trend tag: histories for %s unavailable", ", ".join(missing),
                       exc_info=True)
        return histories
    return {**histories, **{t: h for t, h in (got or {}).items() if t in missing}}


def tag_and_baselines(store: LedgerStore, records: list[LedgerEntry], histories: dict,
                      tagger: TrendTagger | None, ref_prices: dict, today: str,
                      with_baselines: bool) -> list[LedgerEntry]:
    """Trend tag on every record and, for a long-term shadow, its code baselines
    (ledger.baselines.tag_and_build; never raises)."""
    daily = {r.ticker: (h.daily if (h := histories.get(r.ticker)) is not None else None)
             for r in records}
    sources = {t: h.source for t in daily if (h := histories.get(t)) is not None}
    return baselines_mod.tag_and_build(store, records, daily, tagger, ref_prices, today,
                                       with_baselines, sources=sources)


def _benchmark_entry(ctx: ShadowContext, holds: list[int], today: str,
                     snapshot_id: str) -> LedgerEntry | None:
    """Random same-domain pick: seeded by date + shadow id so it is reproducible."""
    tickers = sorted(ctx.closes)
    if not tickers:
        return None
    rng = random.Random(f"{today}:{ctx.entry.shadow_id}")
    ticker = rng.choice(tickers)
    direction = rng.choice(["long", "short"])
    hold = int(statistics.median(holds)) if holds else 5
    return LedgerEntry(
        source_type="benchmark", source_id=f"random:{ctx.entry.shadow_id}", ticker=ticker,
        direction=direction, hold_bars=hold, confidence=0.5, position_usd=100.0,
        falsifier="random benchmark (no thesis)", thesis="same-domain random pick",
        asset_type=_asset_type(ticker), entry_rule="next_open",
        domain_benchmark=ctx.entry.domain_benchmark, snapshot_id=snapshot_id,
        meta={"benchmark": "random_same_domain", "seed": f"{today}:{ctx.entry.shadow_id}",
              "run_date": today},
    )


async def run_shadow_day(store: LedgerStore, news_items: list, *, today: str | None = None,
                         entries: list | None = None, call=_call_llm, fred_fetch=None,
                         derivs_fetch=None, report_dir: Path | None = None,
                         feeds_fetch=None, created_at: str | None = None,
                         pending_path: Path | None = None) -> RunReport:
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    created_at = created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entries = entries if entries is not None else roster_mod.active()
    retired = roster_mod.retired_ids()      # owner-approved retirements: no more LLM calls
    entries = [e for e in entries if e.shadow_id not in retired]
    report = RunReport(today)
    pending_path = pending_path or pending_signals.default_path()
    try:
        tagger = TrendTagger(today)
    except Exception:
        logger.error("trend tagger unavailable; records are tagged UNAVAILABLE", exc_info=True)
        tagger = None
    report.pending = await _check_pending(store, entries, retired, today, created_at,
                                          pending_path, tagger)
    done = _already_recorded(store, entries, created_at)
    todo = []
    for e in entries:
        if e.shadow_id in done:
            report.results.append(ShadowResult(e.shadow_id, "skipped"))
        else:
            todo.append(e)
    if not todo:
        return report

    extra = {NEWS_HOUND_ID: news_tickers(news_items, _tradable),
             BEAR_TRACKER_ID: red_flag_tickers(news_items, _tradable)}
    tickers = sorted({t for e in todo for t in (*e.watchlist, *extra.get(_lineage(e), []))})
    histories = await get_price_histories(tickers)
    if fred_fetch is None:
        from marketmind.gateway.fred_client import get_fred_for_shadow as fred_fetch
    consensus = _previous_consensus(store, today)

    derivs = await _derivatives_lines(todo, histories, today, derivs_fetch)
    if feeds_fetch is None:
        from marketmind.shadow_feeds import gather as feeds_fetch
    try:
        feeds = await feeds_fetch([e.name for e in todo], today)
    except Exception:
        logger.warning("shadow feeds unavailable", exc_info=True)
        feeds = {}

    # Self-feedback treatment arm: each shadow's own ledger rows only (isolation)
    shadow_rows = bench_rows = []
    if any(self_feedback.is_on(e) for e in todo):
        shadow_rows, bench_rows = store.list(source_type="shadow"), store.list(source_type="benchmark")

    try:
        open_pending = pending_signals.load(pending_path)
    except (OSError, ValueError):
        logger.warning("pending-signal registry unreadable", exc_info=True)
        open_pending = {"signals": []}

    contexts = []
    for e in todo:
        fred_failed = False
        try:
            fred = await fred_fetch(_lineage(e))
        except Exception as exc:
            logger.warning("FRED for %s failed: %s", e.shadow_id, exc)
            fred, fred_failed = {}, True
        contexts.append(build_context(e, histories, news_items, fred=fred, fred_failed=fred_failed,
                                      consensus_rows=consensus if _lineage(e) == FADE_MASTER_ID else None,
                                      extra_tickers=extra.get(_lineage(e)), today=today,
                                      feeds=feeds.get(e.name), **derivs.get(e.shadow_id, {})))
        if self_feedback.is_on(e):
            contexts[-1].own_record = self_feedback.lines_for(e, shadow_rows, bench_rows)
        if lines := pending_signals.context_lines(open_pending, e.shadow_id):
            contexts[-1].feeds = {**contexts[-1].feeds,
                                  "Your open conditional signals (checked by code daily)": lines}

    quotes = {}
    for ctx in contexts:
        for v in ctx.views:
            if v.snap is not None:
                src = histories[v.ticker].source if histories.get(v.ticker) else None
                quotes[v.ticker] = (v.snap.close, v.snap.as_of, src)
    snapshot_id = store.save_snapshot(quotes)

    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(ctx: ShadowContext) -> ShadowResult:
        async with sem:
            with llm_trace.trace() as models:
                parsed, raws, attempts = await decide(ctx, call)
        res = ShadowResult(ctx.entry.shadow_id, "submitted" if parsed.ok else "missed",
                           errors=parsed.errors, warnings=parsed.warnings,
                           attempts=attempts, raw=raws)
        if not parsed.ok:
            logger.warning("Shadow %s missed today: %s", ctx.entry.shadow_id,
                           "; ".join(parsed.errors)[:300])
            return res
        on = bool(ctx.own_record)
        meta = {"model": MODEL, "shadow": ctx.entry.name, "attempts": attempts,
                "run_date": today, "llm": llm_trace.label(models),
                "prompt_version": llm_trace.prompt_version(system_prompt(ctx.entry, on)),
                "self_feedback": "on" if on else "off",
                "news_sources": list(ctx.news_sources)}
        if ctx.entry.source_type != "shadow":
            meta["temp"] = ctx.entry.group        # temp_event | trial
        if _lineage(ctx.entry) == SCALPER_ID:
            meta["intraday_approx"] = True
        records = []
        for d in parsed.decisions:
            d_meta = {**meta, "market": market_for(d.ticker).code}
            if d.ticker in ctx.off_context:
                d_meta["off_context"] = True
            records.append(LedgerEntry(
                source_type=ctx.entry.source_type, source_id=ctx.entry.shadow_id, ticker=d.ticker,
                direction=d.direction, hold_bars=d.hold_days, confidence=d.confidence,
                position_usd=d.position_usd, falsifier=d.falsifier, thesis=d.thesis,
                asset_type=_asset_type(d.ticker), entry_rule="next_open",
                stop_loss=d.stop, target_price=d.target, falsifier_rule=d.falsifier_rule,
                domain_benchmark=ctx.entry.domain_benchmark, snapshot_id=snapshot_id,
                meta=d_meta,
            ))
        # random benchmarks pair with long-term shadows; trials compare with their parent
        bench = (_benchmark_entry(ctx, [d.hold_days for d in parsed.decisions], today, snapshot_id)
                 if ctx.entry.source_type == "shadow" else None)
        # trend tag on every record; code baselines for long-term shadows (ledger only)
        tag_hist = await _trend_inputs([r.ticker for r in records], histories)
        base = tag_and_baselines(store, records, tag_hist, tagger,
                                 {**ctx.closes, **ctx.off_context}, today,
                                 with_baselines=ctx.entry.source_type == "shadow")
        # one transaction: a duplicate session writes neither the calls nor the
        # benchmark nor the baselines
        companions = ([bench] if bench is not None else []) + base
        ids = store.add_submission(records, daily_session, created_at=created_at,
                                   companions=companions)
        if ids is None:
            res.status = "duplicate"
            sessions = sorted({s for r in records if (s := target_session(r))})
            res.errors.append(f"already submitted for session {', '.join(sessions)}; "
                              "not recorded")
            logger.warning("Shadow %s: duplicate submission for session %s not recorded",
                           ctx.entry.shadow_id, ", ".join(sessions))
            return res
        res.entry_ids = ids[:len(records)]
        res.benchmark_id = ids[len(records)] if bench is not None else None
        res.baseline_ids = ids[len(records) + (bench is not None):]
        if parsed.conditionals:          # only with a recorded submission
            try:
                res.pending_ids, warn = pending_signals.register(
                    pending_path, ctx.entry, parsed.conditionals, today=today,
                    created_at=created_at, closes={**ctx.closes, **ctx.off_context},
                    as_of={v.ticker: v.snap.as_of for v in ctx.views if v.snap is not None},
                    atrs=ctx.atrs, meta=meta)
                res.warnings = [*res.warnings, *warn]
            except Exception as exc:
                logger.error("Shadow %s: conditional signals not registered",
                             ctx.entry.shadow_id, exc_info=True)
                res.warnings = [*res.warnings,
                                f"conditional signals not registered ({type(exc).__name__})"]
        return res

    results = await asyncio.gather(*(one(c) for c in contexts), return_exceptions=True)
    for ctx, r in zip(contexts, results):
        if isinstance(r, BaseException):
            logger.error("Shadow %s crashed", ctx.entry.shadow_id, exc_info=r)
            r = ShadowResult(ctx.entry.shadow_id, "missed", errors=[f"{type(r).__name__}: {r}"])
        report.results.append(r)

    if report_dir is not None:
        _write_report(report, report_dir)
    logger.info(report.summary())
    return report


def _write_report(report: RunReport, report_dir: Path) -> None:
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        path = report_dir / f"{report.date}.json"
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        existing.append({"written_at": datetime.now(timezone.utc).isoformat(),
                         "results": [asdict(r) for r in report.results]})
        path.write_text(json.dumps(existing, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        logger.warning("Shadow run report not written", exc_info=True)


def default_report_dir() -> Path:
    import os
    return Path(os.getenv("MARKETMIND_DATA_DIR", "data")) / "shadows" / "v3_runs"
