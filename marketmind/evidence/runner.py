"""Daily evidence run: claims -> checks -> divergence list -> ledger (docs/S5_DESIGN.md)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from marketmind.config.source_independence import count_independent_sources
from marketmind.evidence.checks import (
    CONTRADICT, VERDICT_CN, ledger_bet, observe, verdict,
)
from marketmind.evidence.extract import SYSTEM_PROMPT, parse_claims, pick_news, render_news
from marketmind.gateway import usage_tracker
from marketmind.ledger.store import LedgerEntry, LedgerStore

logger = logging.getLogger("marketmind.evidence.runner")

SOURCE_ID = "evidence:v1:{type}"
HOLD_BARS = 10
POSITION_USD = 100.0
CONF_ONE_SOURCE = 0.55
CONF_MULTI_SOURCE = 0.60
CALL_TIMEOUT_S = 240
STAGE = "evidence"


@dataclass
class EvidenceItem:
    claim: str
    type: str
    ticker: str | None
    asserted: str
    news_ids: list[str]
    sources: list[str]
    independent_sources: int
    observed: str | None
    verdict: str
    verdict_cn: str
    evidence: str
    data: dict = field(default_factory=dict)
    entry_id: str | None = None
    ledger_note: str = ""


@dataclass
class EvidenceReport:
    date: str
    status: str = "ok"                 # ok | skipped | no_news | llm_failed
    items: list[EvidenceItem] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    news_considered: int = 0
    written_at: str = ""

    def summary(self) -> str:
        n = {v: sum(1 for i in self.items if i.verdict == v)
             for v in ("support", "contradict", "unverifiable")}
        booked = sum(1 for i in self.items if i.entry_id)
        return (f"evidence {self.date}: {len(self.items)} claims — support {n['support']}, "
                f"contradict {n['contradict']} ({booked} to ledger), "
                f"unverifiable {n['unverifiable']}" + (f" [{self.status}]" if self.status != "ok" else ""))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["divergences"] = sum(1 for i in self.items if i.verdict == CONTRADICT)
        return d


def default_report_dir() -> Path:
    return Path(os.getenv("MARKETMIND_DATA_DIR", "data")) / "evidence"


async def _call_llm(system: str, user: str) -> str:
    from marketmind.gateway.async_client import chat_flash
    token = usage_tracker.set_stage(STAGE)
    try:
        result = await asyncio.wait_for(chat_flash(system, user, temperature=0.1,
                                                   max_tokens=8192), timeout=CALL_TIMEOUT_S)
    finally:
        usage_tracker.reset_stage(token)
    if result.get("error"):
        raise RuntimeError(f"LLM error: {result.get('error')}")
    return result.get("content") or ""


def _entry_for(item: EvidenceItem, today: str, snapshot_id: str | None) -> LedgerEntry | None:
    from marketmind.ledger.recorder import classify_ticker
    bet = ledger_bet(item.type, item.ticker, item.asserted, item.observed or "flat")
    if bet is None:
        return None
    ticker, direction = bet
    layer, asset_type = classify_ticker(ticker)
    narrative = "看涨" if direction == "short" else "看跌"
    return LedgerEntry(
        source_type="evidence", source_id=SOURCE_ID.format(type=item.type), ticker=ticker,
        direction=direction, hold_bars=HOLD_BARS,
        confidence=CONF_MULTI_SOURCE if item.independent_sources >= 2 else CONF_ONE_SOURCE,
        position_usd=POSITION_USD,
        falsifier=(f"若 {HOLD_BARS} 个交易日内 {ticker} 按新闻叙事方向（{narrative}）运行、"
                   "本笔净收益为负，则背离判断错误"),
        thesis=f"叙事与数据背离：{item.claim}｜数据：{item.evidence}"[:600],
        layer="linkage" if ticker != item.ticker else layer, asset_type=asset_type,
        entry_rule="next_open", snapshot_id=snapshot_id,
        meta={"run_date": today, "claim_type": item.type, "claim": item.claim,
              "asserted": item.asserted, "observed": item.observed,
              "news_ids": item.news_ids, "sources": item.sources,
              "independent_sources": item.independent_sources, "data": item.data},
    )


def _already_ran(report_dir: Path, today: str) -> bool:
    p = report_dir / f"{today}.json"
    if not p.exists():
        return False
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("status") == "ok"
    except (OSError, ValueError):
        return False


async def run_evidence_day(store: LedgerStore, news_items: list, *, today: str | None = None,
                           data=None, call=_call_llm, price_source=None,
                           report_dir: Path | None = None) -> EvidenceReport:
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_dir = report_dir or default_report_dir()
    report = EvidenceReport(today)
    if _already_ran(report_dir, today):
        report.status = "skipped"
        return report
    news = pick_news(news_items)
    report.news_considered = len(news)
    if not news:
        report.status = "no_news"
        _write(report, report_dir)
        return report
    by_id = {n.id: n for n in news}
    try:
        raw = await call(SYSTEM_PROMPT, render_news(news))
    except Exception as e:
        logger.warning("evidence: claim extraction failed: %s", e)
        report.status = "llm_failed"
        report.dropped.append(str(e))
        _write(report, report_dir)
        return report
    claims, report.dropped = parse_claims(raw, set(by_id))
    if not claims and any(d.startswith("no JSON") or d == "claims is not a list"
                          for d in report.dropped):
        report.status = "llm_failed"       # unusable reply: leave the day retryable
        _write(report, report_dir)
        return report

    if data is None:
        from marketmind.evidence.sources import LiveEvidenceData
        data = LiveEvidenceData()
    for c in claims:
        obs = await observe(c.type, c.ticker, data)
        sources = sorted({getattr(by_id[i], "source_name", "") or "unknown" for i in c.news_ids})
        v = verdict(c.asserted, obs.direction)
        report.items.append(EvidenceItem(
            claim=c.claim, type=c.type, ticker=c.ticker, asserted=c.asserted,
            news_ids=c.news_ids, sources=sources,
            independent_sources=count_independent_sources(sources),
            observed=obs.direction, verdict=v, verdict_cn=VERDICT_CN[v],
            evidence=obs.summary, data=obs.data))

    await _book_divergences(store, report, today, price_source)
    _write(report, report_dir)
    return report


async def _book_divergences(store: LedgerStore, report: EvidenceReport, today: str,
                            price_source) -> None:
    pending = []
    # records already booked today (an interrupted earlier run) count as seen
    seen: set[tuple[str, str]] = {
        ((e.meta or {}).get("claim_type"), e.ticker)
        for e in store.list(source_type="evidence") if (e.meta or {}).get("run_date") == today}
    for item in report.items:
        if item.verdict != CONTRADICT:
            continue
        entry = _entry_for(item, today, None)
        if entry is None:
            item.ledger_note = "该类型没有可交易的代理标的，不进账本"
            continue
        key = (item.type, entry.ticker)
        if key in seen:
            item.ledger_note = "同日同类型同标的已记一条"
            continue
        seen.add(key)
        pending.append((item, entry))
    if not pending:
        return
    from marketmind.ledger.prices import HistoryPriceSource, latest_quotes
    source = price_source or HistoryPriceSource()
    quotes = await latest_quotes(source, [e.ticker for _, e in pending])
    snapshot_id = store.save_snapshot(quotes)
    for item, entry in pending:
        if quotes.get(entry.ticker, (None,))[0] is None:
            item.ledger_note = f"{entry.ticker} 取不到行情，不进账本"
            continue
        entry.snapshot_id = snapshot_id
        try:
            item.entry_id = store.add(entry)
        except ValueError as e:
            item.ledger_note = f"账本拒绝：{e}"


def _write(report: EvidenceReport, report_dir: Path) -> None:
    report.written_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / f"{report.date}.json").write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        logger.warning("evidence report not written", exc_info=True)
