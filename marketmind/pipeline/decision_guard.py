"""Code-enforced guard on LLM decision cards (SPEC_v3 §5 step 6, law L3).

The LLM writes the thesis, risk statement and red-team note. It does not get to
set numbers: price levels come from Layer 3, and position size is computed here
from the L3 stop distance (fixed risk per trade), then bounded by the single-position,
position-count and total-heat caps. The LLM's own size is kept only for the record. Every change is recorded in the notes, so the dashboard can
show what the guard did.

Main-pipeline-only rules (owner decision 2026-11-20, docs/SPEC_v3.md §5 step 6), applied
only when the caller passes a MainGuardContext (the daily main pipeline does; shadows,
baselines, the forced paper trade and the interactive path never do):
  stop cooldown   a long card on a ticker whose latest main-pipeline stop exit is within
                  the last STOP_COOLDOWN_DAYS trading days becomes a watch item instead
                  of a trade card;
  bear protection a long card whose asset group the trend state machine has in CASH
                  (every member CASH / EXIT) becomes a watch item. Missing or stale
                  trend data never blocks: the card is kept and annotated (fail open).
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger("marketmind.pipeline.decision_guard")

MAX_SINGLE_POSITION_PCT = 25.0   # gate23-architecture.md: single-position hard cap
MAX_TOTAL_HEAT_PCT = 25.0        # design spec §6.3: all stops hit together <= 25% equity
MAX_POSITIONS = 6                # design spec §6.3: attention constraint
# Owner decision 2026-09-29: size = risk budget / stop distance. 1% of the paper capital
# (ledger.recorder.PAPER_CAPITAL_USD) is lost if the L3 stop is hit. Confidence does not
# enter sizing until it is calibrated (S9).
RISK_PER_TRADE_PCT = 1.0

# Fallback when the tradable universe (marketmind.universe) cannot be loaded:
# a foreign-exchange suffix (600900.SS, 0700.HK, 7203.T ...) is never tradable on
# Robinhood US; everything else is given the benefit of the doubt.
_FOREIGN_SUFFIXES = (".SS", ".SZ", ".HK", ".T", ".L", ".PA", ".DE", ".TO", ".AX",
                     ".KS", ".KQ", ".TW", ".NS", ".BO", ".SW", ".AS", ".MI", ".SA")


# Owner decision 2026-09-27: ultra-short T-bill ETFs are cash, not trades. Holding
# them is the no-trade state, so they never take a decision-card slot.
CASH_EQUIVALENT_ETFS = frozenset({
    "SHV", "BIL", "SGOV", "USFR", "TFLO", "BILS", "GBIL", "TBIL", "XBIL", "CLTL",
})


def is_robinhood_tradable(ticker: str) -> bool:
    t = (ticker or "").strip().upper()
    if not t:
        return False
    from marketmind.universe import is_tradable
    verdict = is_tradable(t)
    if verdict is not None:
        return verdict
    logger.warning("Tradable universe unavailable; %s judged by suffix rule", t)
    if t.endswith("-USD"):
        return True
    return not t.endswith(_FOREIGN_SUFFIXES)


@dataclass
class GuardReport:
    kept: list = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # Main-pipeline rules: cards turned into watch items, each
    # {"card", "ticker", "rules", "reason", "conditions", "invalidation", "expiry_days"}
    downgraded: list[dict] = field(default_factory=list)
    annotations: list[dict] = field(default_factory=list)   # fail-open notes per ticker
    main: dict | None = None        # MainGuardContext.describe() when the rules ran

    @property
    def summary(self) -> str:
        return "; ".join(self.notes)

    def main_record(self) -> dict | None:
        """JSON-ready record for the brief and the ledger meta; None when the
        main-pipeline rules did not run."""
        if self.main is None:
            return None
        return {**self.main,
                "downgrades": [{k: d[k] for k in ("ticker", "rules", "reason")}
                               for d in self.downgraded],
                "annotations": list(self.annotations)}


# ── Main-pipeline rules (owner decision 2026-11-20) ────────────────────────────

STOP_COOLDOWN_DAYS = 10          # trading days after a stop exit with no new card
STOP_EXIT_REASONS = ("stop", "gap_stop")   # gap_stop: legacy name of a gap-through stop
TREND_MAX_AGE_DAYS = 4           # a trend file older than this is stale (long weekend ok)
BEAR_GROUP_STATE = "CASH"        # ecosystem.health.group_trend_state: all members CASH/EXIT
EQUITY_DEFAULT_GROUP = "us_equity_index"
CRYPTO_GROUP = "crypto"
WATCH_EXPIRY_DAYS = 30           # downgraded card's watch window (outlasts the cooldown)
BEAR_RECOVERY_MA = 200           # bear downgrade waits for close > SMA200 (trend rule)
COOLDOWN_RECOVERY_MA = 20        # cooldown downgrade also waits for close > SMA20


@dataclass
class MainGuardContext:
    """Inputs of the main-pipeline rules, loaded by load_main_guard_context.

    stops: ticker -> latest stop exit date (YYYY-MM-DD) of its 'main' ledger records.
    trend: ticker -> trend state; None when no usable trend file (fail open).
    """
    today: date
    stops: dict[str, str] = field(default_factory=dict)
    trend: dict[str, str] | None = None
    trend_file: str | None = None
    ledger_note: str = ""
    trend_note: str = ""

    def describe(self) -> dict:
        return {"today": self.today.isoformat(), "trend_file": self.trend_file,
                "trend_available": self.trend is not None, "trend_note": self.trend_note,
                "ledger_note": self.ledger_note, "stop_cooldown_days": STOP_COOLDOWN_DAYS}


def _is_crypto(ticker: str) -> bool:
    return ticker.upper().endswith("-USD")


def trading_days_after(start: date, end: date, crypto: bool = False) -> int:
    """Sessions in (start, end]: weekdays (the codebase has no exchange holiday
    calendar; same convention as ledger.settlement.target_session), every calendar
    day for crypto."""
    if end <= start:
        return 0
    days = (end - start).days
    if crypto:
        return days
    return sum((start + timedelta(days=i)).weekday() < 5 for i in range(1, days + 1))


def nth_trading_day_after(start: date, n: int, crypto: bool = False) -> date:
    d, seen = start, 0
    while seen < n:
        d += timedelta(days=1)
        if crypto or d.weekday() < 5:
            seen += 1
    return d


def cooldown_hit(ticker: str, ctx: MainGuardContext) -> tuple[str, date] | None:
    """(stop exit date, last cooldown day) while the ticker is cooling down, else None."""
    exit_day = ctx.stops.get(ticker.strip().upper())
    if not exit_day:
        return None
    try:
        start = date.fromisoformat(exit_day[:10])
    except ValueError:
        logger.warning("Main guard: unusable stop exit date %r for %s", exit_day, ticker)
        return None
    crypto = _is_crypto(ticker)
    if trading_days_after(start, ctx.today, crypto) > STOP_COOLDOWN_DAYS:
        return None
    return exit_day[:10], nth_trading_day_after(start, STOP_COOLDOWN_DAYS, crypto)


def trend_group(ticker: str, states: dict[str, str]) -> tuple[str, str | None, list[str]]:
    """(group, group state, members with a state) for a card's ticker.

    The group is alerts.asset_groups.asset_group (the mapping alerts, Elite and the
    ecosystem herding check use) and its state ecosystem.health.group_trend_state.
    A ticker outside every listed group (a single stock, an unlisted ETF) uses its own
    state when the trend universe has it, else the US equity index group (crypto pairs:
    the crypto group). A listed group with no trend member has no state."""
    from marketmind.alerts.asset_groups import asset_group
    from marketmind.ecosystem.health import group_trend_state
    t = ticker.strip().upper()
    group = asset_group(t)
    state = group_trend_state(states, group)
    if state is None and group == t:
        group = CRYPTO_GROUP if _is_crypto(t) else EQUITY_DEFAULT_GROUP
        state = group_trend_state(states, group)
    members = sorted(m for m, st in states.items()
                     if asset_group(m) == group and st and st != "UNAVAILABLE")
    return group, state, members


def _main_rules(card, ctx: MainGuardContext, report: GuardReport) -> dict | None:
    """The downgrade record when a main-pipeline rule turns this long card into a
    watch item; None keeps it a trade card (fail-open notes go to the report)."""
    t = card.ticker.strip().upper()
    rules, reasons, conditions = [], [], []
    hit = cooldown_hit(t, ctx)
    if hit:
        exit_day, until = hit
        rules.append("stop_cooldown")
        reasons.append(f"止损冷却：{t} 于 {exit_day[5:]} 止损，{STOP_COOLDOWN_DAYS} 个交易日内"
                       f"不再出卡（至 {until.isoformat()[5:]}）")
        conditions += [{"type": "after_date", "value": until.isoformat()},
                       {"type": "close_above_ma", "value": COOLDOWN_RECOVERY_MA}]
    if ctx.trend is None:
        note = f"趋势数据不可用（{ctx.trend_note or '无趋势文件'}），空头趋势保护未生效，不拦截"
        report.annotations.append({"ticker": t, "rule": "bear_trend", "note": note})
        report.notes.append(f"{t}: {note}")
        logger.warning("Main guard: %s: %s", t, note)
    else:
        group, state, members = trend_group(t, ctx.trend)
        if state is None:
            note = f"趋势状态机未覆盖 {t} 所属组 {group}，空头趋势保护未生效，不拦截"
            report.annotations.append({"ticker": t, "rule": "bear_trend", "note": note})
            report.notes.append(f"{t}: {note}")
            logger.info("Main guard: %s", note)
        elif state == BEAR_GROUP_STATE:
            shown = "、".join(f"{m} {ctx.trend[m]}" for m in members[:6])
            rules.append("bear_trend")
            reasons.append(f"空头趋势保护：{t} 所属组 {group} 趋势状态 {state}（{shown}；"
                           f"趋势文件 {ctx.trend_file}），主管线不做多")
            conditions.append({"type": "close_above_ma", "value": BEAR_RECOVERY_MA})
    if not rules:
        return None
    seen, conds = set(), []
    for c in conditions:
        if (c["type"], c["value"]) not in seen:
            seen.add((c["type"], c["value"]))
            conds.append(c)
    invalidation = ([{"type": "close_below", "value": round(float(card.stop_loss), 4)}]
                    if card.stop_loss and card.stop_loss > 0 else [])
    return {"card": card, "ticker": t, "rules": rules, "reason": "；".join(reasons) + "，降为观察",
            "conditions": conds, "invalidation": invalidation, "expiry_days": WATCH_EXPIRY_DAYS}


def load_trend_states(data_dir: str | Path, today: date
                      ) -> tuple[dict[str, str] | None, str | None, str]:
    """Each instrument's state from the newest trend file (dated <= today, at most
    TREND_MAX_AGE_DAYS old) that has it: weekend files hold crypto only, so equities
    come from the last weekday file. Returns ({ticker: state} or None, newest file, note)."""
    folder = Path(data_dir) / "trend"
    oldest = (today - timedelta(days=TREND_MAX_AGE_DAYS)).isoformat()
    try:
        files = sorted(folder.glob("????-??-??.json"), reverse=True) if folder.is_dir() else []
    except OSError:
        logger.warning("Main guard: trend folder %s unreadable", folder, exc_info=True)
        files = []
    files = [p for p in files if p.stem <= today.isoformat()]
    states: dict[str, str] = {}
    newest = None
    for p in files:
        if p.stem < oldest:
            break
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("Main guard: unreadable trend file %s", p)
            continue
        full = (doc or {}).get("full") or {}
        for t, s in full.items():
            st = s.get("state") if isinstance(s, dict) else None
            if st and st != "UNAVAILABLE":
                states.setdefault(str(t).upper(), st)
        if full and newest is None:
            newest = p.stem
    if not states:
        latest = files[0].stem if files else None
        return None, None, (f"最新趋势文件 {latest} 超过 {TREND_MAX_AGE_DAYS} 天或无可用状态"
                            if latest else "无趋势文件")
    return states, newest, ""


def load_stop_exits(ledger_path: str | Path) -> tuple[dict[str, str], str]:
    """ticker -> latest stop exit date among settled 'main' ledger records (read-only)."""
    import sqlite3
    path = Path(ledger_path)
    if not path.exists():
        return {}, "账本不存在，止损冷却未生效"
    marks = ", ".join("?" for _ in STOP_EXIT_REASONS)
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT upper(ticker), max(exit_date) FROM ledger WHERE source_type = 'main' "
                f"AND status = 'settled' AND exit_reason IN ({marks}) AND exit_date IS NOT NULL "
                "GROUP BY upper(ticker)", STOP_EXIT_REASONS).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        logger.error("Main guard: ledger %s unreadable; stop cooldown not applied", path,
                     exc_info=True)
        return {}, "账本读取失败，止损冷却未生效"
    return {t: d for t, d in rows if t and d}, ""


def load_main_guard_context(data_dir: str | Path, today: date | None = None) -> MainGuardContext:
    """Ledger stop exits and trend states for the main-pipeline rules. Never raises:
    an unreadable source leaves its rule inactive and says so in its note."""
    if today is None:
        from marketmind.trend.daily import ny_date
        today = date.fromisoformat(ny_date())
    stops, ledger_note = load_stop_exits(Path(data_dir) / "ledger.db")
    trend, trend_file, trend_note = load_trend_states(data_dir, today)
    if trend is None:
        logger.warning("Main guard: trend states unavailable (%s); bear protection fails open",
                       trend_note)
    return MainGuardContext(today=today, stops=stops, trend=trend, trend_file=trend_file,
                            ledger_note=ledger_note, trend_note=trend_note)


def enforce(cards: list, l3, max_single_pct: float = MAX_SINGLE_POSITION_PCT,
            max_heat_pct: float = MAX_TOTAL_HEAT_PCT, max_positions: int = MAX_POSITIONS,
            main: MainGuardContext | None = None) -> GuardReport:
    """Return the cards that survive, with L3 levels and bounded sizes. `main` (the
    daily main pipeline only) adds the stop-cooldown and bear-trend downgrades."""
    report = GuardReport(main=main.describe() if main is not None else None)
    green = {r.ticker: r for r in getattr(l3, "green_lights", [])}

    for card in cards:
        t = (card.ticker or "").strip().upper()
        lvl = green.get(t) or green.get(card.ticker)
        if lvl is None:
            report.notes.append(f"dropped {card.ticker}: not an L3 green light")
            continue
        if getattr(lvl, "recommendation", "enter") != "enter":
            report.notes.append(f"dropped {card.ticker}: L3 says '{lvl.recommendation}' "
                                f"(R/R {lvl.reward_risk_ratio:.2f} < 2)")
            continue
        if card.direction != "long":
            report.notes.append(f"dropped {card.ticker}: L3 only validates long setups (got {card.direction})")
            continue
        if not is_robinhood_tradable(card.ticker):
            report.notes.append(f"dropped {card.ticker}: not tradable on Robinhood US")
            continue
        if t in CASH_EQUIVALENT_ETFS:
            report.notes.append(f"dropped {card.ticker}: cash-equivalent T-bill ETF counts as no-trade")
            continue
        card.entry_low, card.entry_high = lvl.entry_zone_low, lvl.entry_zone_high
        card.stop_loss, card.target_price = lvl.stop_loss, lvl.target_price
        card.reward_risk_ratio, card.max_hold_days = lvl.reward_risk_ratio, lvl.max_hold_days
        if main is not None:
            down = _main_rules(card, main, report)
            if down is not None:
                report.downgraded.append(down)
                report.notes.append(f"downgraded {card.ticker} to watch: {down['reason']}")
                logger.info("Main guard: %s", down["reason"])
                continue
        stop_pct = stop_distance_pct(card)
        if stop_pct is None:
            report.notes.append(f"dropped {card.ticker}: L3 stop distance is not positive and "
                                f"finite (entry {card.entry_low}-{card.entry_high}, stop "
                                f"{card.stop_loss}); size cannot be computed")
            continue
        # stop > 0 bounds stop_pct below 100, so the size is always at least RISK_PER_TRADE_PCT.
        card.position_size_pct = risk_sized_pct(stop_pct, max_single_pct)
        capped = " (single-position cap)" if card.position_size_pct >= max_single_pct else ""
        report.notes.append(f"{card.ticker}: size {card.position_size_pct:.2f}% = "
                            f"{RISK_PER_TRADE_PCT:g}% risk / {stop_pct:.2f}% stop{capped}")
        report.kept.append(card)

    if len(report.kept) > max_positions:
        report.kept.sort(key=lambda c: c.reward_risk_ratio, reverse=True)
        for c in report.kept[max_positions:]:
            report.notes.append(f"dropped {c.ticker}: over the {max_positions}-position limit")
        report.kept = report.kept[:max_positions]

    heat = sum(card_heat_pct(c) for c in report.kept)
    if heat > max_heat_pct and heat > 0:
        scale = max_heat_pct / heat
        for c in report.kept:
            c.position_size_pct = round(c.position_size_pct * scale, 2)
        report.notes.append(f"total heat {heat:.1f}% > {max_heat_pct:.0f}%: sizes scaled x{scale:.2f}")
    return report


def stop_distance_pct(card) -> float | None:
    """(entry_mid - stop) / entry_mid * 100, or None when not positive and finite."""
    return levels_stop_pct(card.entry_low, card.entry_high, card.stop_loss)


def levels_stop_pct(entry_low, entry_high, stop_loss) -> float | None:
    """Stop distance % from raw levels (a card's or an L3 result's); None if unusable."""
    try:
        entry_mid = (float(entry_low) + float(entry_high)) / 2
        stop = float(stop_loss)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(entry_mid) and math.isfinite(stop)) or entry_mid <= 0 or stop <= 0:
        return None
    pct = (entry_mid - stop) / entry_mid * 100
    return pct if math.isfinite(pct) and pct > 0 else None


def risk_sized_pct(stop_pct: float, max_single_pct: float = MAX_SINGLE_POSITION_PCT,
                   risk_pct: float = RISK_PER_TRADE_PCT) -> float:
    """Size % of capital so that a stop-out loses `risk_pct` % of capital, capped."""
    return round(min(max_single_pct, risk_pct / stop_pct * 100), 2)


def card_heat_pct(card) -> float:
    """Equity % lost if the stop is hit: size% * (entry_mid - stop) / entry_mid."""
    entry_mid = (card.entry_low + card.entry_high) / 2
    if entry_mid <= 0 or card.stop_loss <= 0 or card.stop_loss >= entry_mid:
        return 0.0
    return card.position_size_pct * (entry_mid - card.stop_loss) / entry_mid
