"""Code-computed review facts of a shadow's settled records (docs/S7_DESIGN.md §二 继承输入).

Summarises the ledger `review` JSON (docs/S9_DESIGN.md §3) for the variant /
successor rewrite prompts: error_class distribution, right_but_stopped share (stops
too tight), mean MFE / MAE in ATR units, ambiguous-bar share, and win rate / mean net
return split by entry regime (above / below MA200, sign of the 20-day return).
Every number comes from code; groups with fewer than MIN_EVIDENCE records are
labelled as weak evidence. Pure code, no LLM.
"""
from __future__ import annotations

from statistics import mean

ERROR_CLASSES = ("win", "beta_carried", "cost_flipped", "right_but_stopped", "thesis_wrong")
MIN_EVIDENCE = 20                # below this many records a figure is weak evidence
MAX_CHARS = 1500                 # cap of one formatted facts section in a prompt


def _rows(entries) -> list:
    return [e for e in entries if e.status == "settled" and isinstance(e.review, dict)
            and e.net_return is not None]


def _perf(rows) -> dict:
    return {"n": len(rows),
            "win_rate": sum(1 for e in rows if e.net_return > 0) / len(rows) if rows else None,
            "mean_net": mean(e.net_return for e in rows) if rows else None}


def _avg(vals) -> float | None:
    vals = [float(v) for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return mean(vals) if vals else None


def review_facts(entries) -> dict:
    """Facts over the settled records that carry a `review` (others are ignored)."""
    rows = _rows(entries)
    n = len(rows)
    counts = {c: 0 for c in ERROR_CLASSES}
    other = 0
    for e in rows:
        c = e.review.get("error_class")
        if c in counts:
            counts[c] += 1
        else:
            other += 1
    atr_rows = [e for e in rows if e.review.get("mfe_atr") is not None]

    def regime(e, key):
        return (e.review.get("regime") or {}).get(key)
    ma200 = {"above": [e for e in rows if regime(e, "above_ma200") is True],
             "below": [e for e in rows if regime(e, "above_ma200") is False],
             "unknown": [e for e in rows if regime(e, "above_ma200") is None]}
    r20 = {"up": [e for e in rows if isinstance(regime(e, "ret_20d"), (int, float))
                  and regime(e, "ret_20d") > 0],
           "down": [e for e in rows if isinstance(regime(e, "ret_20d"), (int, float))
                    and regime(e, "ret_20d") <= 0],
           "unknown": [e for e in rows if not isinstance(regime(e, "ret_20d"), (int, float))]}
    return {
        "n": n,
        "error_class": counts, "error_class_other": other,
        "error_class_share": {c: (k / n if n else None) for c, k in counts.items()},
        "right_but_stopped_share": counts["right_but_stopped"] / n if n else None,
        "mfe_atr": _avg(e.review.get("mfe_atr") for e in atr_rows),
        "mae_atr": _avg(e.review.get("mae_atr") for e in atr_rows),
        "atr_n": len(atr_rows),
        "ambiguous_bar_share": (sum(1 for e in rows if e.review.get("ambiguous_bar")) / n
                                if n else None),
        "overall": _perf(rows),
        "by_ma200": {k: _perf(v) for k, v in ma200.items()},
        "by_ret20": {k: _perf(v) for k, v in r20.items()},
    }


def _pct(x, digits=1) -> str:
    return "n/a" if x is None else f"{x * 100:.{digits}f}%"


def _num(x, digits=2) -> str:
    return "n/a" if x is None else f"{x:.{digits}f}"


def _weak(n: int) -> str:
    return f" (n < {MIN_EVIDENCE}, weak evidence)" if n < MIN_EVIDENCE else ""


def _perf_line(label: str, p: dict) -> str:
    if not p["n"]:
        return f"- {label}: no records"
    return (f"- {label}: n={p['n']}, win rate {_pct(p['win_rate'])}, "
            f"mean net return {_pct(p['mean_net'], 2)}{_weak(p['n'])}")


def format_facts(f: dict) -> str:
    """Plain-text facts for a prompt, at most MAX_CHARS characters."""
    n = f["n"]
    if not n:
        return "(no settled records with review facts yet)"
    lines = [f"settled records with review facts: {n}{_weak(n)}",
             "error_class distribution (code-classified): " + ", ".join(
                 f"{c} {f['error_class'][c]} ({_pct(f['error_class_share'][c])})"
                 for c in ERROR_CLASSES)
             + (f", other {f['error_class_other']}" if f["error_class_other"] else ""),
             f"right_but_stopped share (stopped out, then the target was reached within the "
             f"planned hold; stops too tight): {_pct(f['right_but_stopped_share'])}",
             f"mean MFE {_num(f['mfe_atr'])} ATR, mean MAE {_num(f['mae_atr'])} ATR "
             f"(records with ATR: {f['atr_n']}){_weak(f['atr_n'])}",
             f"ambiguous_bar share (stop and target inside one daily bar): "
             f"{_pct(f['ambiguous_bar_share'])}",
             "by entry regime (market state before entry):",
             _perf_line("above MA200", f["by_ma200"]["above"]),
             _perf_line("below MA200", f["by_ma200"]["below"]),
             _perf_line("20-day return > 0", f["by_ret20"]["up"]),
             _perf_line("20-day return <= 0", f["by_ret20"]["down"])]
    unknown = f["by_ma200"]["unknown"]["n"]
    if unknown:
        lines.append(f"- MA200 state unknown (too little price history): {unknown} records")
    text = "\n".join(lines)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS - 3] + "..."
