"""Built-in reporter (SPEC_v3 §10, docs/S4_DESIGN.md): read-only Q&A over the ledger.

The model only sees data the code hands it (ledger rows, scoreboard, latest
brief) and must cite ledger record ids. Code then checks every 16-hex id in the
answer against the ledger and appends a warning for ids that do not exist.
Nothing here writes to the ledger or any run file.
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
_ID_RE = re.compile(r"\b[0-9a-f]{16}\b")
_TICKER_RE = re.compile(r"\b[A-Z0-9]{1,6}(?:[.\-=][A-Z0-9]{1,4})?\b")

SYSTEM_PROMPT = """你是 MarketMind 的内置汇报员，只读。
规则：
1. 只根据下面 <data> 中的数据回答。data 以外的事实、价格、预测一律不说。
2. 提到任何一条账本记录时，必须写出它的记录编号，格式 [entry_id]（16 位十六进制）。
3. 数据里没有的，直接说"数据不可用"或"账本中没有这方面的记录"，不要猜，不要估算。
4. 胜率、收益等只能引用 data 里已经算好的数字；没有已结算记录时要说明"尚无已结算记录"。
5. 你不能下单、不能修改任何记录、不能给出新的交易建议；可以解释系统已有的决策和成绩。
6. 用中文，简洁。"""


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
    ctx["promotion"] = "所有影子处于见习期；晋升评审（S7）尚未实现"
    return ctx


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
    ids = sorted(set(_ID_RE.findall(answer)))
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
                "error": "llm_unavailable", "unknown_ids": []}
    ctx_text, truncated = render_context(build_context(question))
    turns = []
    for m in (history or [])[-HISTORY_TURNS:]:
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
    return {"answer": answer, "unknown_ids": unknown, "context_truncated": truncated}
