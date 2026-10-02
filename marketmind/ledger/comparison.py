"""Trend-tag breakdown and LLM-vs-baseline comparison (docs/S7_DESIGN.md §六).

Pure aggregation over ledger rows (pass rows with baselines included), no I/O.
Only settled rows count; a pair needs both sides settled, except the trend baseline,
which holds cash (return 0) whenever the decision's tag was CASH / WATCH / EXIT.
Decisions whose tag was UNAVAILABLE (or missing) have no trend pair.
"""
from __future__ import annotations

from statistics import mean

from marketmind.ledger.baselines import KINDS, SOURCE_TYPE
from marketmind.ledger.store import LedgerEntry
from marketmind.ledger.trend_tag import FLAT_STATES, TREND

# LLM-decided sources whose records carry a trend tag, grouped for display
TAG_GROUPS = {"shadow": "shadows", "temp_shadow": "temp_shadows", "playground": "playground",
              "main": "main", "main_forced": "main"}
PAIR_GROUPS = {"shadow": "shadows", "main": "main", "main_forced": "main"}
STATE_ORDER = ("TREND", "WATCH", "CASH", "EXIT", "UNAVAILABLE")


def _settled(e: LedgerEntry) -> bool:
    return e.status == "settled" and e.net_return is not None


def _stats(values: list[float]) -> dict:
    return {"n": len(values),
            "mean_net_return": round(mean(values), 6) if values else None,
            "win_rate": round(sum(v > 0 for v in values) / len(values), 4) if values else None}


def trend_breakdown(entries: list[LedgerEntry]) -> list[dict]:
    """Settled LLM-decided rows by source group x direction x trend state at decision."""
    cells: dict[tuple[str, str, str], list[float]] = {}
    for e in entries:
        group = TAG_GROUPS.get(e.source_type)
        tag = (e.meta or {}).get("trend")
        if group is None or not isinstance(tag, dict) or not _settled(e):
            continue
        state = tag.get("state") or "UNAVAILABLE"
        cells.setdefault((group, e.direction, state), []).append(e.net_return)
    order = {s: i for i, s in enumerate(STATE_ORDER)}
    rows = [{"group": g, "direction": d, "state": s, **_stats(v)}
            for (g, d, s), v in cells.items()]
    return sorted(rows, key=lambda r: (r["group"], r["direction"], order.get(r["state"], 99)))


def baseline_comparison(entries: list[LedgerEntry]) -> list[dict]:
    """Per source group x baseline kind, over settled pairs: n pairs, mean LLM net,
    mean baseline net, mean difference (LLM - baseline), LLM / baseline win rates and
    the share of pairs where the LLM did better."""
    by_pair: dict[str, dict[str, LedgerEntry]] = {}
    for e in entries:
        if e.source_type == SOURCE_TYPE:
            pid, kind = (e.meta or {}).get("pairs_with"), (e.meta or {}).get("baseline")
            if pid and kind:
                by_pair.setdefault(pid, {})[kind] = e
    cells: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for e in entries:
        group = PAIR_GROUPS.get(e.source_type)
        if group is None or not _settled(e):
            continue
        mates = by_pair.get(e.entry_id, {})
        for kind in KINDS:
            b = mates.get(kind)
            if kind == "trend" and b is None:
                state = ((e.meta or {}).get("trend") or {}).get("state")
                if state in FLAT_STATES:
                    cells.setdefault((group, kind), []).append((e.net_return, 0.0))
                continue
            if b is not None and _settled(b):
                cells.setdefault((group, kind), []).append((e.net_return, b.net_return))
    out = []
    for group in ("shadows", "main"):
        for kind in KINDS:
            pairs = cells.get((group, kind), [])
            llm = [a for a, _ in pairs]
            base = [b for _, b in pairs]
            out.append({
                "group": group, "baseline": kind, "pairs": len(pairs),
                "llm_mean_net": round(mean(llm), 6) if pairs else None,
                "baseline_mean_net": round(mean(base), 6) if pairs else None,
                "mean_diff": round(mean(a - b for a, b in pairs), 6) if pairs else None,
                "llm_win_rate": _stats(llm)["win_rate"],
                "baseline_win_rate": _stats(base)["win_rate"],
                "llm_better_share": round(sum(a > b for a, b in pairs) / len(pairs), 4)
                if pairs else None})
    return out


def compute(entries: list[LedgerEntry]) -> dict:
    return {"trend_tags": trend_breakdown(entries), "baselines": baseline_comparison(entries),
            "note": "代码基线只记账、不交易、不是建议；trend 基线在非 TREND 时持现金（收益 0，不写记录）。"
                    "只统计已结算记录与已结算的配对。"}


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:+.2f}%"


def summary_line(comp: dict) -> str:
    """One fact line for the daily report (code-computed numbers only)."""
    parts = []
    for r in comp.get("baselines", []):
        if r["pairs"]:
            parts.append(f"{'影子' if r['group'] == 'shadows' else '主管线'} vs {r['baseline']} "
                         f"{r['pairs']} 对，均值差 {_pct(r['mean_diff'])}")
    tags = [f"{r['group']}·{'多' if r['direction'] == 'long' else '空'}·{r['state']} "
            f"n={r['n']} 均值 {_pct(r['mean_net_return'])} 胜率 "
            f"{'—' if r['win_rate'] is None else f'{r['win_rate'] * 100:.0f}%'}"
            for r in comp.get("trend_tags", []) if r["group"] in ("shadows", "main")]
    base = "；".join(parts) if parts else "尚无已结算的基线配对"
    tag = "；".join(tags) if tags else "尚无带趋势标签的已结算记录"
    return f"LLM 与代码基线（已结算配对）：{base}。按趋势标签：{tag}。"
