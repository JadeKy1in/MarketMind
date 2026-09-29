"""Built-in reporter (SPEC_v3 §10, docs/S4_DESIGN.md): read-only Q&A over the ledger.

The model only sees data the code hands it (ledger rows, scoreboard, latest
brief) and must cite ledger record ids. Code then checks every 16-hex id in the
answer against the ledger and appends a warning for ids that do not exist.
Nothing here writes to the ledger or any run file. When the question names a
ticker or asset group, the advisors' latest ledger decisions on it are added
(shadows/v3/elite.py, code-selected, no extra LLM call) and returned as
`advisor_opinions`, so the page can show them even without the LLM.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from marketmind.api import whitebox

logger = logging.getLogger("marketmind.api.reporter")

CONTEXT_MAX_CHARS = 60_000
RECENT_ROWS = 80
MATCH_ROWS = 40
HISTORY_TURNS = 6
_ID_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{16}(?![0-9a-f])")
# near-misses (wrong length or case) are checked too; \b fails next to Chinese text
_ID_LIKE_RE = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{15,17}(?![0-9A-Fa-f])")
_TICKER_RE = re.compile(r"\b[A-Z0-9]{1,6}(?:[.\-=][A-Z0-9]{1,4})?\b")

SYSTEM_PROMPT = """你是 MarketMind 的内置汇报员，只读。
规则：
1. 只根据下面 <data> 中的数据回答。data 以外的事实、价格、预测一律不说。
2. 提到任何一条账本记录时，必须写出它的记录编号，格式 [entry_id]（16 位十六进制）。
3. 数据里没有的，直接说"数据不可用"或"账本中没有这方面的记录"，不要猜，不要估算。
4. 胜率、收益等只能引用 data 里已经算好的数字；没有已结算记录时要说明"尚无已结算记录"。
5. 你不能下单、不能修改任何记录、不能给出新的交易建议；可以解释系统已有的决策和成绩。
6. 用中文，简洁。
7. advisor_opinions 是顾问在账本里已有的决策（代码按问题涉及的资产组选出），只供所有人参考，没有决策权；提到时写记录编号。basis 为 not_yet_advisors 时必须说明它们还不是顾问；basis 为 none 时说明尚无顾问。"""


def _row(e: dict) -> dict:
    keep = ("entry_id", "created_at", "source_type", "source_id", "ticker", "direction",
            "status", "confidence", "position_usd", "hold_bars", "entry_price", "exit_price",
            "exit_reason", "net_return", "pnl_usd", "excess_market", "brier")
    row = {k: e.get(k) for k in keep if e.get(k) is not None}
    if e.get("thesis"):
        row["thesis"] = e["thesis"][:160]
    if e.get("falsifier"):
        row["falsifier"] = e["falsifier"][:120]
    return row


def build_context(question: str) -> dict[str, Any]:
    ledger = whitebox.get_ledger(limit=whitebox.LEDGER_PAGE_MAX)
    ctx: dict[str, Any] = {"ledger_available": ledger.get("available", False),
                           "ledger_total": ledger.get("total", 0),
                           "status_counts": ledger.get("status_counts", {})}
    all_rows = ledger.get("entries", [])
    ctx["recent_records"] = [_row(e) for e in all_rows[:RECENT_ROWS]]

    ids = set(_ID_RE.findall(question))
    tickers = {t for t in _TICKER_RE.findall(question.upper()) if len(t) >= 2}
    matched = [e for e in all_rows
               if e["entry_id"] in ids or e["ticker"].upper() in tickers
               or any(t.lower() in e["source_id"].lower() for t in question.lower().split()
                      if len(t) >= 5)]
    for eid in ids - {e["entry_id"] for e in matched}:
        one = whitebox.get_entry(eid)
        if one.get("available"):
            matched.append(one["entry"])
    if matched:
        ctx["records_matching_question"] = [_row(e) for e in matched[:MATCH_ROWS]]

    arena = whitebox.get_arena()
    ctx["shadow_scores"] = [
        {"shadow_id": r["shadow_id"], "name": r["display_name"], "domain": r["domain"],
         "roster_status": r["roster_status"],
         "score": {k: v for k, v in (r["score"] or {}).items()
                   if k not in ("source_type", "source_id")} or None,
         "random_benchmark_mean_net": (r["random_benchmark"] or {}).get("mean_net_return")}
        for r in arena["shadows"]]
    ctx["other_sources"] = arena["other_sources"]

    brief = whitebox.get_brief()
    if brief.get("available"):
        b = brief["brief"]
        ctx["latest_brief"] = {
            "date": brief["date"], "has_no_trade": b.get("has_no_trade"),
            "decision_summary": b.get("decision_summary"),
            "no_trade_thesis": b.get("no_trade_thesis"),
            "decision_cards": b.get("decision_cards"),
            "l3_green": b.get("l3_green"), "l3_yellow": b.get("l3_yellow"),
            "red_team_challenges": (b.get("red_team_challenges") or [])[:8],
            "paper_trade": b.get("paper_trade"),
            "fragility_summary": b.get("fragility_summary"),
        }
    ev = whitebox.get_evidence()
    if ev.get("available"):
        ctx["evidence_layer"] = {
            "date": ev["date"], "divergences": ev["divergences"],
            "items": [{k: i.get(k) for k in ("claim", "type", "ticker", "verdict_cn", "evidence",
                                              "independent_sources", "entry_id")}
                      for i in ev["items"][:20]]}
    hold = whitebox.get_holdings()
    if hold.get("holdings"):
        rep = hold.get("report") or {}
        ctx["owner_holdings"] = {
            "positions": [{k: h.get(k) for k in ("ticker", "quantity", "cost_basis", "opened", "stop")}
                          for h in hold["holdings"]],
            "inspection_date": rep.get("date"),
            "inspection": [{k: i.get(k) for k in ("ticker", "unrealized_return", "light",
                                                  "reward_risk", "verdict_cn", "reason", "alternatives")}
                           for i in rep.get("items", [])]}
    big = whitebox.get_big_alerts()
    if big.get("available"):
        rep = big.get("report") or {}
        ctx["big_move_alerts"] = {
            "date": big.get("date"), "mode": rep.get("mode"),
            "trend_source": rep.get("trend_source"),
            "fired": [{k: f.get(k) for k in ("ticker", "kind", "direction", "status", "veto",
                                              "asset_group", "entry_id")}
                      for f in rep.get("fired", [])],
            "near_misses": [{k: n.get(k) for k in ("ticker", "note", "asset_group")}
                            for n in rep.get("near_misses", [])][:10],
            "history": big.get("history", [])[:20]}
    rep = whitebox.get_daily_report()
    if rep.get("available"):
        ctx["daily_report"] = {"date": rep["date"], "markdown": rep["markdown"][:6000]}
    ctx["promotion"] = "晋升评审每天运行；账本满 60 个交易日前所有影子都在见习期"
    elite = elite_opinions(question)
    if elite.get("asset_groups"):
        ctx["advisor_opinions"] = _for_model(elite)
    return ctx


def elite_opinions(question: str) -> dict:
    """Advisors' latest ledger decisions on the asset groups in the question (code-selected,
    docs/S7_DESIGN.md §五); {} when unavailable. Read-only, no LLM call."""
    try:
        from marketmind.shadows.v3 import elite
        store = whitebox._store()
        return elite.gather(question, store=store, rows=None if store else [],
                            data_dir=whitebox.data_dir())
    except Exception:
        logger.warning("reporter: advisor opinions unavailable", exc_info=True)
        return {}


def _for_model(elite: dict) -> dict:
    """Signal ids are not ledger ids; leave them out so every cited id is checkable."""
    ops = [{**op, "pending_signals": [{k: v for k, v in sg.items() if k != "signal_id"}
                                      for sg in op.get("pending_signals", [])]}
           for op in elite.get("opinions", [])]
    return {**elite, "opinions": ops}


def render_context(ctx: dict) -> tuple[str, bool]:
    text = json.dumps(ctx, ensure_ascii=False, default=str)
    if len(text) <= CONTEXT_MAX_CHARS:
        return text, False
    ctx = dict(ctx)
    while len(text) > CONTEXT_MAX_CHARS and ctx.get("recent_records"):
        ctx["recent_records"] = ctx["recent_records"][: len(ctx["recent_records"]) // 2]
        ctx["recent_records_truncated"] = True
        text = json.dumps(ctx, ensure_ascii=False, default=str)
    return text[:CONTEXT_MAX_CHARS], True


def check_citations(answer: str) -> list[str]:
    """Ids in the answer that are not ledger records."""
    # pure-digit runs of other lengths are ordinary numbers, not ids
    ids = sorted({m for m in _ID_LIKE_RE.findall(answer)
                  if len(m) == 16 or any(c.isalpha() for c in m)})
    if not ids:
        return []
    store = whitebox._store()
    if store is None:
        return ids
    return [i for i in ids if store.get(i) is None]


def _ensure_gateway() -> None:
    from marketmind.gateway import async_client
    if async_client._gateway is None and not async_client._mock_mode:
        from marketmind.config.settings import MarketMindConfig
        cfg = MarketMindConfig()
        async_client.init_gateway(cfg.deepseek_api_key, cfg.deepseek_base_url)


async def ask(question: str, history: list[dict] | None = None) -> dict[str, Any]:
    question = (question or "").strip()
    if not question:
        return {"error": "question is required"}
    from marketmind.gateway import async_client
    try:
        _ensure_gateway()
    except Exception as e:
        logger.warning("reporter: LLM not available: %s", e)
        return {"answer": "汇报员不可用：未配置 LLM 密钥（DEEPSEEK_API_KEY）。账本和成绩可以直接在页面上查看。",
                "error": "llm_unavailable", "unknown_ids": [],
                "advisor_opinions": elite_opinions(question) or None}
    ctx = build_context(question)
    elite = ctx.get("advisor_opinions")
    ctx_text, truncated = render_context(ctx)
    turns = []
    history = [m for m in history if isinstance(m, dict)] if isinstance(history, list) else []
    for m in history[-HISTORY_TURNS:]:
        role = "所有人" if m.get("role") == "user" else "汇报员"
        turns.append(f"{role}：{str(m.get('content', ''))[:1000]}")
    user_prompt = (f"<data>\n{ctx_text}\n</data>\n"
                   + ("（data 已截断：只含最近的部分记录）\n" if truncated else "")
                   + ("\n之前的对话：\n" + "\n".join(turns) + "\n" if turns else "")
                   + f"\n问题：{question}")
    try:
        result = await async_client.chat_flash(SYSTEM_PROMPT, user_prompt, temperature=0.2,
                                               max_tokens=4096)
    except Exception as e:
        logger.warning("reporter call failed: %s", e)
        return {"answer": "汇报员暂时不可用（LLM 调用失败）。", "error": str(e), "unknown_ids": []}
    answer = (result.get("content") if isinstance(result, dict) else str(result)) or ""
    if not answer.strip():
        err = result.get("error", "empty") if isinstance(result, dict) else "empty"
        return {"answer": "汇报员没有给出回答。", "error": err, "unknown_ids": []}
    unknown = check_citations(answer)
    if unknown:
        answer += "\n\n⚠ 代码核对：以下编号不在账本中，相关说法不可信：" + "、".join(unknown)
    return {"answer": answer, "unknown_ids": unknown, "context_truncated": truncated,
            "advisor_opinions": elite}
