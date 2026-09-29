"""Write main-pipeline output into the unified ledger (SPEC_v3 §5 step 5, §7).

Trade cards (after the decision guard) are recorded with a zone entry and the
L3 stop / target. When no card survives, the forced paper trade is recorded
instead, so the value of "no trade" can be measured later.
"""
from __future__ import annotations

import logging

from marketmind.ledger.prices import PriceSource, latest_quotes
from marketmind.ledger.settlement import target_session
from marketmind.pipeline.decision import _probability
from marketmind.ledger.store import LedgerEntry, LedgerStore

logger = logging.getLogger("marketmind.ledger.recorder")

# Owner's capital (SPEC_v3 §1); converts a card's size % into virtual dollars.
PAPER_CAPITAL_USD = 30_000.0
FORCED_HOLD_BARS = 10
# Forced trades are sized like shadow bets: confidence-scaled, at least $100 (SPEC_v3 §6.1).
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
              "reward_risk_ratio": card.reward_risk_ratio,
              "risk_statement": card.risk_statement, "red_team_note": card.red_team_note},
    )


def _forced_entry(pt, l3, snapshot_id: str | None) -> LedgerEntry:
    layer, asset_type = classify_ticker(pt.ticker)
    direction = pt.direction
    lvl = l3.get(pt.ticker) if l3 is not None and hasattr(l3, "get") else None
    # L3 levels describe long setups only; use them only for a long paper trade.
    stop = target = None
    if lvl is not None and direction == "long" and getattr(lvl, "data_available", False):
        stop = lvl.stop_loss or None
        target = lvl.target_price or None
    falsifier = (f"{pt.ticker} closes below the L3 stop {stop:.2f}" if stop else
                 f"{pt.ticker} {direction} loses money over {FORCED_HOLD_BARS} trading days")
    conf = _probability(pt.confidence)
    conf_default = not conf  # missing or 0 means "no stated belief", not certainty of loss
    conf = DEFAULT_CONFIDENCE if conf_default else conf
    return LedgerEntry(
        source_type="main_forced", source_id="main_pipeline",
        ticker=pt.ticker.upper(), direction=direction, hold_bars=FORCED_HOLD_BARS,
        confidence=conf, confidence_is_default=conf_default,
        position_usd=max(FORCED_MIN_USD, round(FORCED_BASE_USD * conf, 2)),
        falsifier=falsifier, thesis=(pt.thesis or "")[:2000],
        layer=layer, asset_type=asset_type, entry_rule="next_open",
        stop_loss=stop, target_price=target, snapshot_id=snapshot_id,
        meta={"source": pt.source},
    )


DEFAULT_ORIGIN = {"kind": "news"}


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
    if not cards and paper is None:
        logger.warning("Ledger: decision has neither cards nor a paper trade; nothing recorded")
        return []
    tickers = [c.ticker.upper() for c in cards] or [paper.ticker.upper()]
    snapshot_id = store.save_snapshot(await latest_quotes(source, tickers), taken_at=created_at)
    if cards:
        entries = [_card_entry(c, snapshot_id) for c in cards]
    elif paper.direction in ("long", "short"):
        entries = [_forced_entry(paper, l3, snapshot_id)]
    else:
        # A direction must never be invented (SPEC_v3 L3); log the gap instead.
        logger.warning("Ledger: forced paper trade %s has direction %r; not recorded",
                       paper.ticker, paper.direction)
        return []
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
    ids = store.add_submission(valid, target_session, created_at=created_at)
    if ids is None:
        logger.warning("Ledger: main pipeline already recorded this session; "
                       "duplicate %s submission (%s) not recorded",
                       valid[0].source_type, ", ".join(tickers))
        return []
    logger.info("Ledger: recorded %d entries (%s)", len(ids), ", ".join(tickers))
    return ids
