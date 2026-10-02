"""Daily report to the owner (docs/DAILY_REPORT.md, owner request 2026-09-28).

After the weekday run: code gathers today's facts from the files and ledger the
run wrote (headlines, evidence layer, main-pipeline decision, shadow activity,
temporary shadows, holdings inspection, alerts, promotion), one LLM call writes
a Chinese report from those facts only, and the report is saved for the
dashboard and pushed to WeChat. The reporter (api/reporter.py) can then be asked
follow-up questions about it.
"""
from __future__ import annotations

import json
import logging
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("marketmind.reports.daily")

PUSH_MAX_CHARS = 4000
SYSTEM_PROMPT = """你是 MarketMind 的每日汇报员，给所有人写今天的投研汇报。
规则：
1. 只使用 <facts> 里的信息；不得补充任何 facts 以外的事实、价格、数字或预测。
2. 用中文，结构如下（Markdown，每节 2–6 条要点，括号里另有规定的从其规定；没有内容的节写"今日无"）：
   ## 今日要闻（从 headlines 里挑最重要的 5–8 条，说明为什么重要）
   ## 冷门数据异常（discovery：新闻很少报道的官方数据异动；写出序列、z 值、新闻覆盖篇数、代理标的是否已被价格反映）
   ## 证据层（叙事与数据是否背离）
   ## 主管线决策（交易卡或不交易的理由、被迫纸面交易、红队最重要的质疑）
   ## 观察名单（watchlist：今天新增 / 触发 / 到期 / 失效的项目与等待的确认条件）
   ## 趋势状态（趋势状态：今天进入 / 退出 TREND 的标的，当前 TREND 名单与代码计算的止损位；明确写出这只是信息性的状态记录，不是警报，也不是交易指令）
   ## 影子动向（多空分布、共识集中的标的、新出现的事件影子）
   ## 生态健康（ecosystem，简短：一行转述 summary；有 herding_flags 时逐条写资产组、方向、连续天数，并注明是"市场驱动"（market_driven，与趋势状态一致）还是"行为性"（behavioural，更值得警惕）；有 duplicate_clusters 时写出成员；都没有就写"无异常"；date 不是今天时注明报告日期）
   ## Playground 实验（playground，简短，1–3 条：今天各实验 agent 的调用——标的、方向、记录编号；注明这是实验性来源，不是建议；calls 为 0 写"今日无"）
   ## 实盘持仓（巡检结论；没有持仓就写"未录入持仓"）
   ## 大行情警报（触发 / 接近触发；观察模式要注明不推送）
   ## 待批准：影子退役提案（retirement_proposals：影子、理由——未通过的挑战者与评估期相对领域基准的平均超额、拟接任者与方法论来源、批准命令；只是提案，需所有人批准）
   ## 值得关注（从以上事实中归纳 2–3 点，明确标注"观察"而非建议）
3. 提到账本记录时写出记录编号。
4. 结尾不写免责声明，不给交易指令；系统不下单。"""


def data_dir() -> Path:
    return Path(os.getenv("MARKETMIND_DATA_DIR", "data"))


def reports_dir() -> Path:
    return data_dir() / "reports"


def save_headlines(news_items: list, today: str | None = None, limit: int = 40) -> None:
    """Keep the day's top headlines for the report (the brief does not store them)."""
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    top = sorted(news_items, key=lambda n: -(getattr(n, "priority_score", 0) or 0))[:limit]
    rows = [{"title": n.title, "source": getattr(n, "source_name", ""), "url": getattr(n, "url", ""),
             "priority": round(getattr(n, "priority_score", 0) or 0, 3)} for n in top]
    path = data_dir() / "news" / f"{today}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        logger.warning("headlines not saved", exc_info=True)


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def gather_facts(today: str, store=None, brief_dir: Path | None = None) -> dict:
    from marketmind.api import whitebox
    d = data_dir()
    facts: dict = {"date": today}
    facts["headlines"] = (_read(d / "news" / f"{today}.json") or [])[:30]
    brief = _read((brief_dir or whitebox.brief_dir()) / f"{today}.json")
    if brief:
        facts["main_pipeline"] = {
            "decision_summary": brief.get("decision_summary"),
            "no_trade": brief.get("has_no_trade"), "no_trade_thesis": brief.get("no_trade_thesis"),
            "decision_cards": brief.get("decision_cards"), "paper_trade": brief.get("paper_trade"),
            "watch_cards": brief.get("watch_cards"),
            "l3_green": brief.get("l3_green"), "red_team_top": (brief.get("red_team_challenges") or [])[:3],
            "fragility": brief.get("fragility_summary")}
    disc = _read(d / "discovery" / f"{today}.json")
    if disc:
        facts["discovery"] = {"counts": disc.get("counts"), "anomalies": [
            {"series": a.get("series"), "title": a.get("title"), "obs_date": a.get("obs_date"),
             "latest": a.get("latest"), "unit": a.get("unit"), "z": a.get("z"),
             "triggers": a.get("triggers"), "news_coverage": a.get("coverage"), "cold": a.get("cold"),
             "proxies": [{k: p.get(k) for k in ("ticker", "direction", "bucket", "move_atr")}
                         for p in (a.get("proxies") or [])]}
            for a in (disc.get("anomalies") or [])[:10]],
            "unavailable": [u.get("id") or u.get("series") for u in disc.get("unavailable") or []]}
    if (d / "watchlist.db").exists():
        try:
            from marketmind.watchlist import daily_summary
            from marketmind.watchlist.store import WatchlistStore
            facts["watchlist"] = daily_summary(today, WatchlistStore(d / "watchlist.db"))
        except Exception:
            logger.warning("watchlist summary unavailable", exc_info=True)
    ev = _read(d / "evidence" / f"{today}.json")
    if ev:
        facts["evidence"] = {"divergences": ev.get("divergences"), "items": [
            {k: i.get(k) for k in ("claim", "verdict_cn", "evidence", "entry_id")}
            for i in (ev.get("items") or [])[:10]]}
    if store is not None:
        rows = [e for e in store.list() if (e.meta or {}).get("run_date") == today
                and e.source_type in ("shadow", "temp_shadow", "playground")]
        long_ = Counter(e.ticker for e in rows if e.direction == "long")
        short = Counter(e.ticker for e in rows if e.direction == "short")
        facts["shadows"] = {"decisions": len(rows), "long": sum(long_.values()),
                            "short": sum(short.values()),
                            "most_long": long_.most_common(5), "most_short": short.most_common(5)}
    events = _read(d / "temp_shadows" / "events.json") or {}
    facts["event_shadows"] = [{k: e.get(k) for k in ("type", "title", "spawned", "status")}
                              for e in events.get("events", []) if e.get("status") == "active"]
    hold = _read(d / "holdings_reports" / f"{today}.json")
    if hold:
        facts["holdings"] = [{k: i.get(k) for k in ("ticker", "unrealized_return", "verdict_cn", "reason")}
                             for i in hold.get("items", [])]
    try:
        from marketmind.trend.daily import report_facts
        trend = report_facts(d, today)
        if trend:
            facts["趋势状态"] = trend
    except Exception:
        logger.warning("trend facts unavailable", exc_info=True)
    alerts = _read(d / "alerts" / f"{today}.json")
    if alerts:
        facts["alerts"] = {"mode": alerts.get("mode"),
                           "fired": [f.get("ticker") for f in alerts.get("fired", [])],
                           "near_misses": [n.get("ticker") for n in alerts.get("near_misses", [])]}
    promo = _read(d / "promotion" / "state.json")
    if promo:
        facts["promotion"] = dict(Counter(r.get("stage") for r in promo.get("shadows", {}).values()))
    facts["retirement_proposals"] = retirement_facts()
    eco = ecosystem_facts(today)
    if eco:
        facts["ecosystem"] = eco
    if store is not None:
        facts["playground"] = playground_facts(today, store)
    return facts


def ecosystem_facts(today: str) -> dict | None:
    """The ecosystem one-liner plus its herding and unexpected duplicate-cluster flags
    (docs/ECOSYSTEM_DESIGN.md). Today's report, else the latest one (its date says so)."""
    try:
        from marketmind.ecosystem import read_report
        doc = read_report(today, root=data_dir()) or read_report(root=data_dir())
    except Exception:
        logger.warning("ecosystem report unavailable", exc_info=True)
        return None
    if not doc:
        return None
    div = doc.get("diversity") or {}
    return {
        "date": doc.get("date"), "summary": doc.get("summary"),
        "herding_flags": [{k: f.get(k) for k in ("group", "direction", "days", "verdict", "escalate")}
                          for f in (doc.get("herding") or {}).get("flags") or []],
        "duplicate_clusters": [{"measure": m, "members": c.get("members")}
                               for m in ("pnl", "direction")
                               for c in (div.get(m) or {}).get("clusters") or [] if not c.get("expected")]}


def playground_facts(today: str, store, per_agent: int = 5) -> dict:
    """Playground calls recorded today (ledger source_type "playground", meta.run_date)."""
    rows = [e for e in store.list(source_type="playground") if (e.meta or {}).get("run_date") == today]
    by_agent: dict[str, list[dict]] = {}
    for e in rows:
        by_agent.setdefault(e.source_id.split(":", 1)[-1], []).append(
            {"ticker": e.ticker, "direction": e.direction, "confidence": e.confidence,
             "entry_id": e.entry_id})
    return {"calls": len(rows), "by_agent": {a: c[:per_agent] for a, c in sorted(by_agent.items())}}


def retirement_facts() -> list[dict]:
    """Pending shadow retirement proposals awaiting the owner (docs/S7_DESIGN.md §一 退役)."""
    try:
        from marketmind.promotion import retirement
        pending = retirement.summary(data_dir()).get("pending", [])
    except Exception:
        logger.warning("retirement proposals unavailable", exc_info=True)
        return []
    out = []
    for p in pending:
        reason, succ = p.get("reason") or {}, p.get("successor") or {}
        out.append({"shadow_id": p.get("shadow_id"), "proposed_at": p.get("proposed_at"),
                    "stage": p.get("stage"), "failed_challengers": reason.get("challengers"),
                    "excess_vs_domain_mean": reason.get("excess_domain_mean"),
                    "excess_n": reason.get("excess_n"), "window": reason.get("window"),
                    "domain_benchmark": reason.get("domain_benchmark"),
                    "successor": succ.get("shadow_id"), "donor": succ.get("donor_id"),
                    "method": succ.get("method"),
                    "approve": f"python -m marketmind.promotion retire approve {p.get('shadow_id')}",
                    "reject": f"python -m marketmind.promotion retire reject {p.get('shadow_id')}"})
    return out


async def _call_llm(system: str, user: str) -> str:
    from marketmind.gateway import usage_tracker
    from marketmind.gateway.async_client import chat_pro
    token = usage_tracker.set_stage("daily_report")
    try:
        result = await chat_pro(system, user, temperature=0.3, max_tokens=8192)
    finally:
        usage_tracker.reset_stage(token)
    if result.get("error"):
        raise RuntimeError(f"LLM error: {result.get('error')}")
    return result.get("content") or ""


def fallback_text(facts: dict) -> str:
    """Plain facts when the LLM is unavailable: the owner still gets the day."""
    mp = facts.get("main_pipeline") or {}
    sh = facts.get("shadows") or {}
    lines = [f"## 今日汇报（{facts['date']}，LLM 不可用，以下为原始事实）",
             f"- 主管线：{mp.get('decision_summary') or '无简报'}",
             f"- 影子：{sh.get('decisions', 0)} 笔（多 {sh.get('long', 0)} / 空 {sh.get('short', 0)}）",
             f"- 冷门数据异常：{((facts.get('discovery') or {}).get('counts') or {}).get('anomalies', 0)}",
             f"- 观察名单：新增 {len((facts.get('watchlist') or {}).get('new', []))}，"
             f"触发 {len((facts.get('watchlist') or {}).get('triggered', []))}",
             f"- 证据层背离：{(facts.get('evidence') or {}).get('divergences', 0)}",
             f"- 警报：{(facts.get('alerts') or {}).get('fired') or '无'}",
             f"- 待批准退役提案：{[r['shadow_id'] for r in facts.get('retirement_proposals') or []] or '无'}",
             f"- 生态健康：{(facts.get('ecosystem') or {}).get('summary') or '无报告'}",
             f"- Playground 调用：{(facts.get('playground') or {}).get('calls', 0)}"]
    lines += [f"- 要闻：{h['title']}（{h['source']}）" for h in facts.get("headlines", [])[:5]]
    return "\n".join(lines)


async def build_report(today: str | None = None, *, store=None, call=_call_llm,
                       brief_dir: Path | None = None) -> dict:
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    facts = gather_facts(today, store, brief_dir)
    try:
        text = (await call(SYSTEM_PROMPT, "<facts>\n" + json.dumps(facts, ensure_ascii=False, default=str)
                           + "\n</facts>")).strip()
        source = "llm"
    except Exception as e:
        logger.warning("daily report LLM failed: %s", e)
        text, source = "", "fallback"
    if not text:
        text, source = fallback_text(facts), "fallback"
    report = {"date": today, "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "source": source, "markdown": text, "facts": facts}
    folder = reports_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{today}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str),
                                          encoding="utf-8")
    return report


def push_message(report: dict) -> tuple[str, str]:
    """(title, body) pushed for a report; long reports point to the dashboard."""
    body = report["markdown"]
    if len(body) > PUSH_MAX_CHARS:
        body = body[:PUSH_MAX_CHARS] + "\n\n……（完整版见仪表盘 http://127.0.0.1:8520 ）"
    return f"MarketMind 今日汇报 {report['date']}", body


async def push(report: dict) -> list[dict]:
    from marketmind.alerts.notify import send
    return await send(*push_message(report))


def latest() -> dict | None:
    folder = reports_dir()
    files = sorted(folder.glob("????-??-??.json")) if folder.is_dir() else []
    return _read(files[-1]) if files else None
