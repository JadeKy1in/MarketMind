"""Daily inspection of the owner's real holdings (docs/S6_DESIGN.md).

Verdicts come from fixed code rules over L3 technicals, the owner's stop and
ledger evidence; no LLM. When prices are missing the verdict is "unavailable".
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from marketmind.holdings.store import Holding, load
from marketmind.ledger.store import LedgerStore

logger = logging.getLogger("marketmind.holdings.inspect")

EXIT, SWITCH, HOLD, UNAVAILABLE = "exit", "switch", "hold", "unavailable"
VERDICT_CN = {EXIT: "离场", SWITCH: "换仓", HOLD: "持有", UNAVAILABLE: "数据不可用"}
SWITCH_MIN_RR = 2.0
SWITCH_MIN_GAP = 1.0
HOLDING_WEAK_RR = 1.0
ALT_LOOKBACK_DAYS = 5
ALT_MAX_CANDIDATES = 40
ALT_TOP = 3
VIEW_LOOKBACK_DAYS = 10
EARNINGS_NOTE_DAYS = 7


@dataclass
class Alternative:
    ticker: str
    reward_risk: float
    light: str
    close: float
    stop: float
    target: float
    sources: list[str] = field(default_factory=list)


@dataclass
class HoldingReport:
    ticker: str
    quantity: float
    cost_basis: float
    price: float | None
    price_date: str | None
    unrealized_return: float | None
    unrealized_usd: float | None
    light: str | None
    recommendation: str | None
    reward_risk: float | None
    l3_stop: float | None
    l3_target: float | None
    owner_stop: float | None
    verdict: str
    verdict_cn: str
    reason: str
    l3_line: str = ""
    alternatives: list[dict] = field(default_factory=list)
    shadow_views: dict = field(default_factory=dict)
    ticker_record: dict = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)


async def _default_history(ticker: str):
    from marketmind.gateway.price_history import completed_history, get_price_history
    hist = await get_price_history(ticker)
    return completed_history(hist) if hist is not None else None


def decide(h: Holding, snap, alternatives: list[Alternative]) -> tuple[str, str]:
    """(verdict, reason) from the rules in docs/S6_DESIGN.md."""
    if snap is None:
        return UNAVAILABLE, "取不到足够的行情（L3 需要 ≥ 60 根日线），不给建议"
    close = snap.close
    if h.stop is not None and close < h.stop:
        return EXIT, f"现价 {close:.2f} 已跌破你设的止损 {h.stop:.2f}"
    if snap.light == "red":
        return EXIT, "L3 红灯：长期趋势、结构、阻力三项全部不合格"
    if snap.wma200 is not None and not snap.above_200wma and not snap.structure_intact:
        return EXIT, "跌破 200 周均线且日线结构已破坏（低点下移或 50 日均线走弱）"
    rr = snap.reward_risk_ratio
    best = alternatives[0] if alternatives else None
    if rr < HOLDING_WEAK_RR and best and best.reward_risk >= SWITCH_MIN_RR \
            and best.reward_risk - rr >= SWITCH_MIN_GAP:
        return SWITCH, (f"持仓风险回报比只有 {rr:.2f}（按现价、L3 止损 {snap.stop_loss:.2f} 和目标 "
                        f"{snap.target_price:.2f} 计算），{best.ticker} 为 {best.reward_risk:.2f}")
    parts = [f"L3 {snap.light}", f"风险回报比 {rr:.2f}"]
    if not snap.structure_intact:
        parts.append("结构已破坏，注意")
    if snap.wma200 is None:
        parts.append("历史不足 200 周，长期趋势无法判断")
    elif not snap.above_200wma:
        parts.append("在 200 周均线下方")
    return HOLD, "未触发离场或换仓条件：" + "，".join(parts)


def _recent(entries, days: int, now: datetime):
    cutoff = (now - timedelta(days=days)).isoformat()
    return [e for e in entries if e.created_at >= cutoff]


async def find_alternatives(store: LedgerStore | None, exclude: set[str], history_fn,
                            now: datetime) -> list[Alternative]:
    """Owner-executable longs from recent main/shadow records with an L3 'enter' setup."""
    if store is None:
        return []
    from marketmind.pipeline.decision_guard import is_robinhood_tradable
    from marketmind.pipeline.l3_indicators import compute_snapshot
    pool: dict[str, set[str]] = {}
    for e in _recent(store.list(), ALT_LOOKBACK_DAYS, now):
        if e.direction != "long" or e.source_type not in ("main", "main_forced", "shadow"):
            continue
        t = e.ticker.upper()
        if t in exclude or not is_robinhood_tradable(t):
            continue
        pool.setdefault(t, set()).add(e.source_id)
    out = []
    for t in sorted(pool, key=lambda k: -len(pool[k]))[:ALT_MAX_CANDIDATES]:
        hist = await history_fn(t)
        snap = compute_snapshot(hist) if hist is not None else None
        if snap is None or snap.recommendation != "enter":
            continue
        out.append(Alternative(t, snap.reward_risk_ratio, snap.light, snap.close,
                               snap.stop_loss, snap.target_price, sorted(pool[t])[:5]))
    out.sort(key=lambda a: -a.reward_risk)
    return out[:ALT_TOP]


def _ledger_context(store: LedgerStore | None, ticker: str, now: datetime) -> tuple[dict, dict]:
    if store is None:
        return {}, {}
    rows = [e for e in store.list() if e.ticker.upper() == ticker]
    recent = [e for e in _recent(rows, VIEW_LOOKBACK_DAYS, now) if e.source_type == "shadow"]
    views = {"long": sum(1 for e in recent if e.direction == "long"),
             "short": sum(1 for e in recent if e.direction == "short"),
             "ids": [e.entry_id for e in recent][:10]}
    settled = [e for e in rows if e.status == "settled" and e.net_return is not None
               and e.source_type != "owner"]
    record = {"settled": len(settled),
              "mean_net_return": (round(sum(e.net_return for e in settled) / len(settled), 6)
                                  if settled else None)}
    return views, record


def _evidence_for(ticker: str) -> list[dict]:
    from marketmind.api.whitebox import get_evidence
    try:
        ev = get_evidence()
    except Exception:
        return []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not ev.get("available") or ev.get("date") != today:
        return []
    return [{k: i.get(k) for k in ("claim", "verdict_cn", "evidence", "entry_id")}
            for i in ev["items"] if (i.get("ticker") or "").upper() == ticker]


async def finnhub_earnings(tickers: list[str], start: str, days: int) -> dict[str, list[dict]]:
    from marketmind.shadow_feeds.company_events import earnings_for
    return await earnings_for(tickers, start, days)


async def _earnings_notes(earnings_fn, tickers: list[str], now: datetime) -> dict[str, str]:
    """ticker -> note for earnings within EARNINGS_NOTE_DAYS; any failure gives no notes."""
    if earnings_fn is None or not tickers:
        return {}
    try:
        found = await earnings_fn(tickers, now.strftime("%Y-%m-%d"), EARNINGS_NOTE_DAYS)
    except Exception:
        logger.warning("holdings earnings lookup failed", exc_info=True)
        return {}
    hours = {"bmo": "盘前", "amc": "盘后", "dmh": "盘中"}
    notes = {}
    for t, rows in (found or {}).items():
        when = "、".join(f"{r.get('date')}" + (f" {hours[r['hour']]}" if r.get("hour") in hours else "")
                        for r in rows if r.get("date"))
        if when:
            notes[t.upper()] = f"注意：{EARNINGS_NOTE_DAYS} 天内有财报（{when}，Finnhub 财报日历）"
    return notes


async def inspect_holdings(holdings: list[Holding] | None = None, *,
                           store: LedgerStore | None = None, history_fn=None,
                           now: datetime | None = None, earnings_fn=None) -> list[HoldingReport]:
    """`earnings_fn(tickers, start, days)` adds an earnings-soon note to the reason
    (never changes the verdict); None skips the lookup."""
    from marketmind.pipeline.l3_indicators import compute_snapshot, describe
    holdings = load() if holdings is None else holdings
    history_fn = history_fn or _default_history
    now = now or datetime.now(timezone.utc)
    alternatives = await find_alternatives(store, {h.ticker for h in holdings}, history_fn, now)
    earnings = await _earnings_notes(earnings_fn, [h.ticker for h in holdings], now)
    reports = []
    for h in holdings:
        hist = await history_fn(h.ticker)
        snap = compute_snapshot(hist) if hist is not None else None
        verdict, reason = decide(h, snap, alternatives)
        price = snap.close if snap else None
        ret = price / h.cost_basis - 1 if price else None
        if ret is not None and ret >= 0 and verdict != UNAVAILABLE:
            reason = "盈利中。" + reason
        if h.ticker.upper() in earnings:
            reason = f"{reason}。{earnings[h.ticker.upper()]}"
        views, record = _ledger_context(store, h.ticker, now)
        reports.append(HoldingReport(
            ticker=h.ticker, quantity=h.quantity, cost_basis=h.cost_basis, price=price,
            price_date=snap.as_of if snap else None,
            unrealized_return=round(ret, 6) if ret is not None else None,
            unrealized_usd=round((price - h.cost_basis) * h.quantity, 2) if price else None,
            light=snap.light if snap else None,
            recommendation=snap.recommendation if snap else None,
            reward_risk=snap.reward_risk_ratio if snap else None,
            l3_stop=snap.stop_loss if snap else None, l3_target=snap.target_price if snap else None,
            owner_stop=h.stop, verdict=verdict, verdict_cn=VERDICT_CN[verdict], reason=reason,
            l3_line=describe(snap) if snap else "",
            alternatives=[asdict(a) for a in alternatives] if verdict in (SWITCH, EXIT) or
            (ret is not None and ret < 0) else [],
            shadow_views=views, ticker_record=record, evidence=_evidence_for(h.ticker)))
    return reports


def report_dir() -> Path:
    return Path(os.getenv("MARKETMIND_DATA_DIR", "data")) / "holdings_reports"


def write_report(reports: list[HoldingReport], today: str | None = None,
                 folder: Path | None = None) -> Path:
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    folder = folder or report_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{today}.json"
    path.write_text(json.dumps({
        "date": today, "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "items": [asdict(r) for r in reports]}, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def alert_on(reports: list[HoldingReport]) -> int:
    """Dashboard alert for every exit / switch verdict; returns how many were sent."""
    from marketmind.notification.alert_manager import emit_alert
    from marketmind.notification.alert_schema import ImpactScope, Severity
    sent = 0
    for r in reports:
        if r.verdict not in (EXIT, SWITCH):
            continue
        emit_alert(Severity.WARN, "holdings", ImpactScope.NONE,
                   f"持仓巡检：{r.ticker} 建议{r.verdict_cn}", detail=r.reason,
                   action_advice="结论由代码规则给出，是否执行由你决定（系统不下单）")
        sent += 1
    return sent


async def run_inspection(store: LedgerStore | None = None) -> tuple[list[HoldingReport], Path | None]:
    holdings = load()
    if not holdings:
        return [], None
    reports = await inspect_holdings(holdings, store=store, earnings_fn=finnhub_earnings)
    path = write_report(reports)
    try:
        alert_on(reports)
    except Exception:
        logger.warning("holdings alert failed", exc_info=True)
    return reports, path
