"""Write main-pipeline output into the unified ledger (SPEC_v3 §5 step 5, §7).

Trade cards (after the decision guard) are recorded with a zone entry and the
L3 stop / target. When no card survives, the forced paper trade is recorded
instead, so the value of "no trade" can be measured later. There is always one:
the code-chosen trade from the decision, else long SPY (SPEC_v3 L7).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from marketmind.ledger.prices import PriceSource, latest_quotes
from marketmind.ledger.settlement import target_session
from marketmind.pipeline.decision import _pick_paper_trade
from marketmind.pipeline.decision_guard import levels_stop_pct
from marketmind.ledger.store import LedgerEntry, LedgerStore

logger = logging.getLogger("marketmind.ledger.recorder")

# Owner's capital (SPEC_v3 §1); converts a card's size % into virtual dollars.
PAPER_CAPITAL_USD = 30_000.0
FORCED_HOLD_BARS = 10
# Forced trades are sized like shadow bets: confidence-scaled, at least $100 (SPEC_v3 §6.1).
# Their confidence is unstated (code picks them), so they get the flagged 0.5 default.
FORCED_BASE_USD = 1_000.0
FORCED_MIN_USD = 100.0
DEFAULT_CONFIDENCE = 0.5


def classify_ticker(ticker: str) -> tuple[str, str]:
    """(layer, asset_type) from the universe when available, else a suffix heuristic."""
    try:
        from marketmind.universe import classify
        c = classify(ticker)
        if c.layer != "unknown":
            return c.layer, c.asset_type
    except Exception:
        logger.warning("Universe classification failed for %s; using heuristic", ticker, exc_info=True)
    t = ticker.upper()
    if t.endswith("-USD"):
        return "tradable", "crypto"
    if "." in t or t.startswith("^"):
        return "linkage", "index" if t.startswith("^") else "stock"
    return "tradable", "stock"


def _card_entry(card, snapshot_id: str | None) -> LedgerEntry:
    layer, asset_type = classify_ticker(card.ticker)
    conf = getattr(card, "confidence", None)
    falsifier = (card.invalidation or "").strip() or (
        f"{card.ticker} closes below the stop {card.stop_loss:.2f}" if card.stop_loss
        else f"{card.ticker} {card.direction} loses money over {card.max_hold_days} trading days")
    return LedgerEntry(
        source_type="main", source_id="main_pipeline",
        ticker=card.ticker.upper(), direction=card.direction,
        hold_bars=max(1, int(card.max_hold_days)),
        confidence=DEFAULT_CONFIDENCE if conf is None else float(conf),
        confidence_is_default=conf is None,
        position_usd=round(PAPER_CAPITAL_USD * card.position_size_pct / 100, 2),
        falsifier=falsifier, thesis=card.thesis or "",
        layer=layer, asset_type=asset_type, entry_rule="zone",
        entry_low=card.entry_low, entry_high=card.entry_high,
        stop_loss=card.stop_loss or None, target_price=card.target_price or None,
        snapshot_id=snapshot_id,
        meta={"position_size_pct": card.position_size_pct,
              "llm_size_pct": getattr(card, "llm_size_pct", None),   # record only, never used
              "reward_risk_ratio": card.reward_risk_ratio,
              "risk_statement": card.risk_statement, "red_team_note": card.red_team_note},
    )


def _forced_entry(pt, l3, snapshot_id: str | None) -> LedgerEntry:
    layer, asset_type = classify_ticker(pt.ticker)
    direction = pt.direction
    lvl = l3.get(pt.ticker) if l3 is not None and hasattr(l3, "get") else None
    # L3 levels describe long setups only; use them only for a long paper trade.
    stop = target = None
    # (The SPY fallback may meet a non-green SPY result: use its levels only when sane.)
    if (lvl is not None and direction == "long" and getattr(lvl, "data_available", False)
            and levels_stop_pct(lvl.entry_zone_low, lvl.entry_zone_high, lvl.stop_loss)):
        stop = lvl.stop_loss or None
        target = lvl.target_price or None
    falsifier = (f"{pt.ticker} closes below the L3 stop {stop:.2f}" if stop else
                 f"{pt.ticker} {direction} loses money over {FORCED_HOLD_BARS} trading days")
    # The forced trade is chosen by code, not believed in: its confidence is unstated
    # whatever the object carries, and it is kept out of Brier aggregates (scoreboard).
    return LedgerEntry(
        source_type="main_forced", source_id="main_pipeline",
        ticker=pt.ticker.upper(), direction=direction, hold_bars=FORCED_HOLD_BARS,
        confidence=DEFAULT_CONFIDENCE, confidence_is_default=True,
        position_usd=max(FORCED_MIN_USD, round(FORCED_BASE_USD * DEFAULT_CONFIDENCE, 2)),
        falsifier=falsifier, thesis=(pt.thesis or "")[:2000],
        layer=layer, asset_type=asset_type, entry_rule="next_open",
        stop_loss=stop, target_price=target, snapshot_id=snapshot_id,
        meta={"source": pt.source, "confidence_unstated": True},
    )


DEFAULT_ORIGIN = {"kind": "news"}
TAG_FETCH_TIMEOUT_S = 120


async def _tag_inputs(source: PriceSource, tickers: list[str]) -> dict:
    """Daily bars for the trend tag / baselines: the same source the snapshot just read
    (cached per process), bounded by a timeout; a failure leaves the ticker out."""
    async def one(t):
        try:
            return t, await source.daily_bars(t)
        except Exception:
            logger.warning("Ledger: bars for the trend tag of %s unavailable", t, exc_info=True)
            return t, None
    try:
        got = await asyncio.wait_for(asyncio.gather(*(one(t) for t in dict.fromkeys(tickers))),
                                     timeout=TAG_FETCH_TIMEOUT_S)
    except Exception:
        logger.warning("Ledger: trend-tag bars timed out", exc_info=True)
        return {}
    return dict(got)


def _tag_and_baselines(store: LedgerStore, entries: list[LedgerEntry], daily: dict,
                       quotes: dict, created_at: str | None) -> list[LedgerEntry]:
    """Trend tag on every record (annotate only) and the paired code baselines
    (docs/S7_DESIGN.md §六). Never raises: tagging must not fail the submission."""
    from marketmind.ledger.baselines import MAIN_SOURCES, tag_and_build
    from marketmind.ledger.trend_tag import TrendTagger
    today = (created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))[:10]
    try:
        tagger = TrendTagger(today)
    except Exception:
        logger.error("Ledger: trend tagger unavailable", exc_info=True)
        tagger = None
    refs = {t: q[0] for t, q in quotes.items() if q and q[0]}
    sources = {t: q[2] for t, q in quotes.items() if q and q[2]}
    return tag_and_build(store, entries, daily, tagger, refs, today, with_baselines=True,
                         sources=sources, long_share_sources=MAIN_SOURCES)


async def record_main_decision(decision, l3, store: LedgerStore, source: PriceSource,
                               created_at: str | None = None,
                               origins: dict[str, dict] | None = None) -> list[str]:
    """Record today's cards (or the forced paper trade). Returns the new entry ids.

    `origins` maps ticker -> meta["origin"] (docs/S10_DESIGN.md §4): which cold-data
    anomaly led to the idea; tickers without one came from the news-driven path.
    One submission per target session (docs/S2_DESIGN.md §4): a second run for the
    same session records nothing and returns []."""
    cards = list(getattr(decision, "decision_cards", []) or [])
    paper = getattr(decision, "paper_trade", None)
    if not cards and (paper is None or getattr(paper, "direction", None) not in ("long", "short")
                      or not (getattr(paper, "ticker", "") or "").strip()):
        # L7: a no-trade day still records exactly one forced trade. The direction is
        # never invented: the code picker (L3 best R/R, else long SPY) chooses it.
        picked = _pick_paper_trade(None, None, l3, None, None)
        logger.warning("Ledger: forced paper trade %s unusable; recording code pick %s (%s)",
                       None if paper is None else (paper.ticker, paper.direction),
                       picked.ticker, picked.source)
        paper = picked
    tickers = [c.ticker.upper() for c in cards] or [paper.ticker.upper()]
    quotes = await latest_quotes(source, tickers)
    snapshot_id = store.save_snapshot(quotes, taken_at=created_at)
    if cards:
        entries = [_card_entry(c, snapshot_id) for c in cards]
    else:
        entries = [_forced_entry(paper, l3, snapshot_id)]
    provenance = {k: v for k in ("llm", "prompt_version")
                  if (v := getattr(decision, k, None))}      # docs/S9_DESIGN.md §2
    valid = []
    for e in entries:
        e.meta = {**(e.meta or {}), **provenance,
                  "origin": (origins or {}).get(e.ticker.upper(), DEFAULT_ORIGIN)}
        try:
            e.validate()
            valid.append(e)
        except ValueError as exc:
            logger.warning("Ledger: rejected %s %s: %s", e.source_type, e.ticker, exc)
    if not valid:
        return []
    baselines = _tag_and_baselines(store, valid, await _tag_inputs(source, tickers), quotes,
                                   created_at)
    ids = store.add_submission(valid, target_session, created_at=created_at,
                               companions=baselines)
    if ids is None:
        logger.warning("Ledger: main pipeline already recorded this session; "
                       "duplicate %s submission (%s) not recorded",
                       valid[0].source_type, ", ".join(tickers))
        return []
    ids = ids[:len(valid)]                       # the baselines follow the decisions
    logger.info("Ledger: recorded %d entries (%s) + %d code baselines", len(ids),
                ", ".join(tickers), len(baselines))
    return ids
