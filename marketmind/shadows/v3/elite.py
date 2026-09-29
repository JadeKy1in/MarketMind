"""Elite participation: advisors' opinions when the owner discusses an asset.

Owner decision 2026-09-29 (SPEC_v3 §6.1, docs/S7_DESIGN.md §五; rebuilt from the
deleted legacy shadows/elite_participation.py). Pure code by default:

- Who: the advisors in data/advisors.json (S7 promotion; retired shadows left out).
  Until advisors exist: the top STAND_IN_COUNT ranked shadows by composite score
  (promotion/state.json), labelled "not yet advisors". Probation shadows have no
  composite score (C04: no ranking before enough data), so before the first formal
  promotions nothing is shown and the reason is stated.
- What: for each of them, its latest ledger decision(s) on the discussed asset
  group(s) (alerts/asset_groups.py: a GC=F long speaks for GLD), chosen by code, with
  record ids and current ledger status, plus its open conditional signals there.
  No LLM call per shadow. `summarize` is optional: at most ONE LLM call that condenses
  the theses and must keep only the record ids it was given (else it is dropped).
- No decision authority and isolation preserved: this only reads the ledger and shows
  the owner; nothing is fed back to any shadow or into the main pipeline's prompts.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger("marketmind.shadows.v3.elite")

STAND_IN_COUNT = 3
ROWS_PER_SHADOW = 2
PENDING_PER_SHADOW = 2
SOURCE_TYPES = ("shadow", "temp_shadow", "playground")
RANKED_STAGES = ("formal", "advisor", "paused")

ADVISORS = "advisors"
NOT_YET = "not_yet_advisors"
NONE = "none"
LABELS = {
    ADVISORS: "顾问意见（仅供参考，无决策权；来自账本，不是新的分析）",
    NOT_YET: "尚无顾问。以下是综合分前 3 的影子——还不是顾问，仅供参考，无决策权",
    NONE: "尚无顾问；见习期影子还没有综合分（数据不足前不排名），暂不显示影子意见",
}

# Words that name an asset group without a ticker (Latin: word start; Chinese: substring)
GROUP_KEYWORDS: dict[str, tuple[str, ...]] = {
    "precious_metals": ("gold", "silver", "bullion", "precious metal", "黄金", "白银", "贵金属", "金价"),
    "crypto": ("bitcoin", "ethereum", "crypto", "比特币", "以太坊", "加密"),
    "energy": ("crude", "oil", "opec", "原油", "石油", "油价"),
    "natural_gas": ("natural gas", "天然气"),
    "long_rates": ("treasury", "treasuries", "bond", "美债", "国债", "长债"),
    "us_dollar": ("dollar", "美元"),
    "us_equity_index": ("s&p", "nasdaq", "标普", "纳指", "美股大盘"),
    "industrial_metals": ("copper", "铜价"),
}
_TICKER_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9^]{1,6}(?:[.\-=][A-Za-z0-9]{1,4})?(?![A-Za-z0-9])")


def _root(data_dir: str | Path | None) -> Path:
    return Path(data_dir) if data_dir is not None else Path(os.getenv("MARKETMIND_DATA_DIR", "data"))


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        logger.warning("%s unreadable", path)
        return {}


# ── who speaks ───────────────────────────────────────────────────────────

def participants(data_dir: str | Path | None = None) -> tuple[str, list[str]]:
    """(basis, shadow ids): advisors, else the top ranked non-advisors, else nobody."""
    from marketmind.shadows.v3 import roster
    root = _root(data_dir)
    retired = roster.retired_ids(root)
    ids = [i for i in _read_json(root / "advisors.json").get("advisors", []) or []
           if isinstance(i, str) and i not in retired]
    if ids:
        return ADVISORS, ids
    shadows = (_read_json(root / "promotion" / "state.json").get("shadows") or {})
    scored = []
    for sid, rec in shadows.items():
        sc = (rec or {}).get("score")
        v = sc.get("score") if isinstance(sc, dict) else None
        if (sid not in retired and (rec or {}).get("stage") in RANKED_STAGES
                and isinstance(v, (int, float))):
            scored.append((float(v), sid))
    top = [sid for _, sid in sorted(scored, key=lambda x: (-x[0], x[1]))[:STAND_IN_COUNT]]
    return (NOT_YET, top) if top else (NONE, [])


# ── what is being discussed ──────────────────────────────────────────────

def known_tickers(rows=()) -> set[str]:
    from marketmind.alerts.asset_groups import ASSET_GROUPS
    from marketmind.shadows.v3 import roster
    out = {t for members in ASSET_GROUPS.values() for t in members}
    out |= {t for r in roster.all_entries() for t in r.watchlist}
    out |= {r.ticker.upper() for r in rows}
    return out


def asset_groups_in(text: str = "", tickers=(), known: set[str] | None = None) -> list[str]:
    """Asset groups named in `text` (tickers or group words) plus those of `tickers`."""
    from marketmind.alerts.asset_groups import asset_group
    known = known if known is not None else known_tickers()
    found: list[str] = []

    def add(g: str) -> None:
        if g and g not in found:
            found.append(g)
    for t in tickers or ():
        add(asset_group(str(t)))
    for tok in _TICKER_RE.findall(text or ""):
        up = tok.upper()
        # typed upper-case, or at least 3 characters: avoids "on", "it", "ai" ...
        if up in known and (tok == up or len(tok) >= 3):
            add(asset_group(up))
    low = (text or "").lower()
    for group, words in GROUP_KEYWORDS.items():
        for w in words:
            hit = (re.search(r"(?<![a-z])" + re.escape(w), low) if w[:1].isascii()
                   else w in low)
            if hit:
                add(group)
                break
    return found


# ── opinions ─────────────────────────────────────────────────────────────

def _run_date(e) -> str:
    return (e.meta or {}).get("run_date") or (e.created_at or "")[:10]


def _record(e) -> dict:
    row = {"entry_id": e.entry_id, "run_date": _run_date(e), "ticker": e.ticker,
           "direction": e.direction, "hold_bars": e.hold_bars, "confidence": e.confidence,
           "status": e.status, "thesis": (e.thesis or "")[:160],
           "falsifier": (e.falsifier or "")[:120]}
    for k in ("entry_price", "exit_price", "exit_reason", "net_return"):
        if getattr(e, k, None) is not None:
            row[k] = getattr(e, k)
    if (e.meta or {}).get("pending_signal_id"):
        row["from_conditional_signal"] = True
    return row


def gather(text: str = "", tickers=(), *, store=None, data_dir: str | Path | None = None,
           rows: list | None = None, exclude_groups=()) -> dict:
    """Code-selected opinions on the asset groups in `text` / `tickers`.

    `store`: a LedgerStore (default: the data dir's ledger); `rows` overrides it.
    Returns {"basis", "label", "asset_groups", "opinions": [{shadow_id, name, domain,
    records: [...], pending_signals: [...]}], "silent": [ids with nothing on them]}.
    """
    from marketmind.alerts.asset_groups import asset_group
    from marketmind.shadows.v3 import pending_signals, roster
    root = _root(data_dir)
    basis, ids = participants(root)
    out = {"basis": basis, "label": LABELS[basis], "asset_groups": [], "opinions": [],
           "silent": []}
    if rows is None:
        if store is None:
            from marketmind.ledger.store import LedgerStore, default_ledger_path
            path = default_ledger_path()
            store = LedgerStore(path) if path.exists() else None
        rows = [e for st in SOURCE_TYPES for e in store.list(source_type=st)] if store else []
    groups = [g for g in asset_groups_in(text, tickers, known_tickers(rows))
              if g not in set(exclude_groups)]
    out["asset_groups"] = groups
    if not groups or not ids:
        return out
    wanted = set(groups)
    names = roster.by_id(root)
    try:
        open_sigs = pending_signals.open_signals(pending_signals.load(pending_signals.default_path(root)))
    except (OSError, ValueError):
        open_sigs = []
    for sid in ids:
        mine = [e for e in rows if e.source_id == sid and e.source_type in SOURCE_TYPES
                and e.status != "void" and asset_group(e.ticker) in wanted]
        sigs = [s for s in open_sigs if s.get("shadow_id") == sid
                and asset_group(s.get("ticker", "")) in wanted][:PENDING_PER_SHADOW]
        if not mine and not sigs:
            out["silent"].append(sid)
            continue
        latest = max((_run_date(e) for e in mine), default=None)
        recent = sorted((e for e in mine if _run_date(e) == latest),
                        key=lambda e: (e.created_at, e.entry_id), reverse=True)[:ROWS_PER_SHADOW]
        entry = names.get(sid)
        out["opinions"].append({
            "shadow_id": sid, "name": entry.display_name if entry else sid,
            "domain": entry.domain if entry else "",
            "records": [_record(e) for e in recent],
            "pending_signals": [{"signal_id": s["signal_id"], "ticker": s["ticker"],
                                 "direction": s["direction"],
                                 "condition": pending_signals.describe(s["condition"], s["direction"]),
                                 "registered": s.get("run_date"),
                                 "expires_in_days": s.get("expires_in_days")} for s in sigs],
        })
    return out


_SIDE = {"long": "做多", "short": "做空"}
_STATUS = {"pending": "待入场", "open": "持仓中", "settled": "已结算", "void": "作废"}


def format_text(result: dict) -> str:
    """Chinese block for the CLI / reports; empty string when there is nothing to say."""
    if not result.get("asset_groups"):
        return ""
    head = f"【影子意见 · {'、'.join(result['asset_groups'])}】{result['label']}"
    if result["basis"] == NONE:
        return head
    lines = [head]
    for op in result["opinions"]:
        lines.append(f"- {op['name']}（{op['shadow_id']}）")
        for r in op["records"]:
            ret = (f"，净收益 {r['net_return']:+.2%}" if r.get("net_return") is not None else "")
            tag = "（条件信号触发）" if r.get("from_conditional_signal") else ""
            lines.append(f"  · [{r['entry_id']}] {r['run_date']} {r['ticker']} "
                         f"{_SIDE.get(r['direction'], r['direction'])} {r['hold_bars']} 天，"
                         f"确信度 {r['confidence']:.2f}，{_STATUS.get(r['status'], r['status'])}"
                         f"{ret}{tag}：{r['thesis']}")
        for s in op["pending_signals"]:
            lines.append(f"  · 等待条件（{s['signal_id']}）：{s['ticker']} "
                         f"{_SIDE.get(s['direction'], s['direction'])}，{s['condition']}，"
                         f"{s['registered']} 登记，最多等 {s['expires_in_days']} 根 K 线")
    if result["silent"]:
        lines.append(f"- 在这些资产上没有记录：{'、'.join(result['silent'])}")
    return "\n".join(lines)


SUMMARY_PROMPT = """你把几位虚拟基金经理（影子）在账本里已有的论点压缩成给所有人看的摘要。
规则：只用给出的内容，不加新观点、价格或建议；最多 3 句中文；提到某条记录时写出它的编号 [entry_id]，只能用给出的编号；说明它们只供参考、没有决策权。"""


async def summarize(result: dict, call=None) -> str | None:
    """Optional: ONE LLM call condensing the theses. None when there is nothing to
    summarise, the call fails, or the answer cites an id that was not given."""
    ids = {r["entry_id"] for op in result.get("opinions", []) for r in op["records"]}
    if not ids:
        return None
    if call is None:
        from marketmind.gateway import async_client

        async def call(system, user):
            res = await async_client.chat_flash(system, user, temperature=0.2, max_tokens=600)
            return (res.get("content") if isinstance(res, dict) else str(res)) or ""
    body = json.dumps([{k: op[k] for k in ("name", "records")} for op in result["opinions"]],
                      ensure_ascii=False)
    try:
        text = (await call(SUMMARY_PROMPT, body)).strip()
    except Exception as exc:
        logger.warning("elite summary unavailable: %s", type(exc).__name__)
        return None
    cited = set(re.findall(r"(?<![0-9a-f])[0-9a-f]{16}(?![0-9a-f])", text))
    if not text or cited - ids:
        logger.warning("elite summary dropped (empty or cites unknown ids %s)", sorted(cited - ids))
        return None
    return text


def summary_enabled(env=os.environ) -> bool:
    """The optional one-call summary is off unless MARKETMIND_ELITE_SUMMARY=on."""
    return str(env.get("MARKETMIND_ELITE_SUMMARY", "")).strip().lower() in ("1", "on", "true", "yes")


async def owner_block(text: str = "", tickers=(), *, store=None,
                      data_dir: str | Path | None = None, exclude_groups=(),
                      call=None) -> tuple[str, list[str]]:
    """(printable block, asset groups covered) for the interactive mode."""
    res = gather(text, tickers, store=store, data_dir=data_dir, exclude_groups=exclude_groups)
    block = format_text(res)
    if block and res["opinions"] and summary_enabled():
        summary = await summarize(res, call)
        if summary:
            block += f"\n摘要（一次 LLM 调用，只转述上面的记录）：{summary}"
    return block, res["asset_groups"]
