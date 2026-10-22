"""Global confidence calibration (docs/S9_DESIGN.md 第 1 步, owner decision 2026-10-22).

Annotation only: the map is written to data/calibration/latest.json and shown in the
daily report next to the stated confidence. It never changes a position, a size, a
settlement, a Brier score or an alert.

Data: settled LLM-sourced ledger rows (source types in ELIGIBLE_SOURCE_TYPES, not the
code-only missed_path shadow, not rows whose confidence is the default). Outcome:
net_return > 0, the same outcome the ledger's Brier uses. Rows from one decision day
are correlated (same news, same market), so the effective sample is the number of
distinct decision days (meta.run_date) and every interval is a date-block bootstrap
(whole days resampled with replacement).

Model (S9 §5): logit(p) = a + b * logit(stated confidence).
- Below MIN_DAYS_GLOBAL days: no correction (identity).
- The slope b is estimated only with MIN_DAYS_SLOPE days and a spread of at least
  MIN_LOGIT_SD in logit(stated). Otherwise b = 1 (the spread of stated confidence is
  kept) and only the intercept a is fitted: a pooled shift. Stated confidence is
  almost constant (0.50-0.69 on 2026-10-22), so the shift is the realistic case.
- Shrinkage toward "no correction": a normal prior N(0, PRIOR_SD^2) on a (and on b - 1),
  combined with the bootstrap standard error: estimate * PRIOR_SD^2 / (PRIOR_SD^2 + se^2).
  The bootstrap se reflects the day clustering, which a row-level likelihood would not.
- Per-source parameters: the gate (>= MIN_DAYS_PER_SOURCE distinct days and a bootstrap
  CI of the source's own shift that excludes 0) is computed and reported, but frozen off
  (PER_SOURCE_ENABLED) until the owner confirms.
Resolution (discrimination) is reported separately: AUC with a date-block CI and the
Murphy decomposition of the Brier score over the stated-confidence values.
Pure code, numpy only.
"""
from __future__ import annotations

import json
import logging
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

logger = logging.getLogger("marketmind.ledger.calibration")

VERSION = 1
ELIGIBLE_SOURCE_TYPES = ("main", "main_forced", "shadow", "temp_shadow", "playground")
CODE_SOURCE_IDS = ("missed_path:main",)      # temp_shadow rows written by code, no LLM
MIN_DAYS_GLOBAL = 10          # below: identity map
MIN_DAYS_SLOPE = 50           # slope b needs this many days ...
MIN_LOGIT_SD = 0.25           # ... and this spread of logit(stated confidence)
MIN_DAYS_PER_SOURCE = 50      # per-source gate (S9 §5)
PER_SOURCE_ENABLED = False    # frozen (S9 第 1 步): the gate is reported, never applied
PRIOR_SD = 0.5                # logit units; shrinkage toward no correction
BOOTSTRAP_B = 1000
SEED = 20261022
CLIP = (0.01, 0.99)


def calibration_dir() -> Path:
    return Path(os.getenv("MARKETMIND_DATA_DIR", "data")) / "calibration"


def latest_path() -> Path:
    return calibration_dir() / "latest.json"


# ── data ────────────────────────────────────────────────────────────────

def decision_day(e) -> str:
    return (e.meta or {}).get("run_date") or (e.created_at or "")[:10]


def eligible(e) -> bool:
    return (e.status == "settled" and e.source_type in ELIGIBLE_SOURCE_TYPES
            and e.source_id not in CODE_SOURCE_IDS and not e.confidence_is_default
            and e.net_return is not None and e.confidence is not None)


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), *CLIP)
    return np.log(p / (1 - p))


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.asarray(z, dtype=float)))


# ── fits ────────────────────────────────────────────────────────────────

def fit_intercept(offset, y, iters: int = 50) -> float:
    """MLE of a in logit(p) = a + offset (Newton). A tiny ridge keeps it finite when
    every outcome is the same; the result is clamped to [-6, 6]."""
    offset, y = np.asarray(offset, float), np.asarray(y, float)
    a = 0.0
    for _ in range(iters):
        p = _sigmoid(a + offset)
        g = float(np.sum(y - p)) - 1e-6 * a
        h = float(np.sum(p * (1 - p))) + 1e-6
        step = g / h
        a = max(-6.0, min(6.0, a + step))
        if abs(step) < 1e-10:
            break
    return a


def fit_platt(x, y, iters: int = 50) -> tuple[float, float] | None:
    """MLE of (a, b) in logit(p) = a + b x, or None when x has no spread."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 2 or float(np.std(x)) < 1e-9:
        return None
    a, b = 0.0, 1.0
    X = np.column_stack([np.ones_like(x), x])
    for _ in range(iters):
        p = _sigmoid(a + b * x)
        g = X.T @ (y - p) - 1e-6 * np.array([a, b - 1.0])
        H = (X * (p * (1 - p))[:, None]).T @ X + 1e-6 * np.eye(2)
        step = np.linalg.solve(H, g)
        a, b = float(np.clip(a + step[0], -20, 20)), float(np.clip(b + step[1], -20, 20))
        if float(np.max(np.abs(step))) < 1e-10:
            break
    return a, b


def auc(scores, y) -> float | None:
    """Mann-Whitney AUC with average ranks for ties; None with only one class."""
    s, y = np.asarray(scores, float), np.asarray(y, int)
    n1, n0 = int(y.sum()), int(len(y) - y.sum())
    if n1 == 0 or n0 == 0:
        return None
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s))
    ss = s[order]
    i = 0
    while i < len(ss):
        j = i
        while j + 1 < len(ss) and ss[j + 1] == ss[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def murphy(conf, y) -> dict:
    """Brier = reliability - resolution + uncertainty over the stated-confidence values
    (rounded to 0.01, the precision the shadows state)."""
    conf, y = np.round(np.asarray(conf, float), 2), np.asarray(y, float)
    n, base = len(y), float(np.mean(y))
    rel = res = 0.0
    values = np.unique(conf)
    for v in values:
        m = conf == v
        k, yk = int(m.sum()), float(np.mean(y[m]))
        rel += k * (v - yk) ** 2
        res += k * (yk - base) ** 2
    return {"reliability": rel / n, "resolution": res / n, "uncertainty": base * (1 - base),
            "bins": int(len(values))}


def _shrink(est: float, se: float | None) -> tuple[float, float]:
    """(shrunk estimate, weight) under a N(0, PRIOR_SD^2) prior."""
    if se is None or not math.isfinite(se):
        return 0.0, 0.0
    w = PRIOR_SD ** 2 / (PRIOR_SD ** 2 + se ** 2)
    return est * w, w


def _blocks(days: list[str]) -> list[np.ndarray]:
    idx: dict[str, list[int]] = defaultdict(list)
    for i, d in enumerate(days):
        idx[d].append(i)
    return [np.array(v) for _, v in sorted(idx.items())]


def _boot_samples(blocks: list[np.ndarray], b: int, seed: int):
    rng = np.random.default_rng(seed)
    k = len(blocks)
    for _ in range(b):
        pick = rng.integers(0, k, size=k)
        yield np.concatenate([blocks[j] for j in pick])


def _ci(vals) -> tuple[list[float] | None, float | None]:
    vals = [v for v in vals if v is not None and math.isfinite(v)]
    if len(vals) < 20:
        return None, None
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return [float(lo), float(hi)], float(np.std(vals, ddof=1))


def _shift_with_ci(x, y, days, b, seed) -> dict:
    a_hat = fit_intercept(x, y)
    boots = [fit_intercept(x[s], y[s]) for s in _boot_samples(_blocks(days), b, seed)]
    ci, se = _ci(boots)
    return {"a_hat": a_hat, "ci": ci, "se": se,
            "excludes_no_correction": bool(ci and (ci[0] > 0 or ci[1] < 0))}


# ── summary ─────────────────────────────────────────────────────────────

def compute(entries, *, b: int = BOOTSTRAP_B, seed: int = SEED, today: str | None = None) -> dict:
    rows = [e for e in entries if eligible(e)]
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out: dict = {"v": VERSION, "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "date": today, "outcome": "net_return > 0",
                 "annotation_only": True,
                 "thresholds": {"min_days_global": MIN_DAYS_GLOBAL, "min_days_slope": MIN_DAYS_SLOPE,
                                "min_logit_sd": MIN_LOGIT_SD, "min_days_per_source": MIN_DAYS_PER_SOURCE,
                                "prior_sd": PRIOR_SD, "bootstrap": b}}
    days = [decision_day(e) for e in rows]
    n_days = len(set(days))
    out["sample"] = {"rows": len(rows), "days": n_days,
                     "first_day": min(days) if days else None, "last_day": max(days) if days else None}
    identity = {"status": "none", "a": 0.0, "b": 1.0}
    if not rows:
        out.update(global_map=identity, slope=None, resolution=None, by_source_type={},
                   per_source={"enabled": False, "sources": 0, "eligible": []})
        out["line"] = summary_line(out)
        return out
    conf = np.array([float(e.confidence) for e in rows])
    y = np.array([1.0 if e.net_return > 0 else 0.0 for e in rows])
    x = _logit(conf)
    x_sd = float(np.std(x))
    out["stated"] = {"mean": float(conf.mean()), "min": float(conf.min()), "max": float(conf.max()),
                     "logit_sd": x_sd}
    out["realized"] = {"win_rate": float(y.mean())}

    # slope (reported always when computable; used only past the gate)
    platt = fit_platt(x, y)
    slope: dict = {"b_hat": None, "ci": None, "identifiable": False}
    if platt is not None:
        bb = [p[1] for s in _boot_samples(_blocks(days), b, seed + 1)
              if (p := fit_platt(x[s], y[s])) is not None]
        ci, se = _ci(bb)
        slope.update(b_hat=platt[1], ci=ci, se=se)
    slope["identifiable"] = bool(platt is not None and n_days >= MIN_DAYS_SLOPE
                                 and x_sd >= MIN_LOGIT_SD and slope.get("se") is not None)
    slope["reason"] = ("estimated" if slope["identifiable"] else
                       f"fixed at 1: needs >= {MIN_DAYS_SLOPE} days and logit sd >= {MIN_LOGIT_SD} "
                       f"(have {n_days} days, sd {x_sd:.3f})")
    out["slope"] = slope

    if n_days < MIN_DAYS_GLOBAL:
        gm = dict(identity, reason=f"fewer than {MIN_DAYS_GLOBAL} decision days")
    else:
        b_used, w_b = 1.0, None
        if slope["identifiable"]:
            d, w_b = _shrink(slope["b_hat"] - 1.0, slope["se"])
            b_used = 1.0 + d
        shift = _shift_with_ci(b_used * x, y, days, b, seed + 2)
        a_used, w_a = _shrink(shift["a_hat"], shift["se"])
        gm = {"status": "platt" if slope["identifiable"] else "shift", "a": a_used, "b": b_used,
              "a_hat": shift["a_hat"], "a_ci": shift["ci"], "a_se": shift["se"],
              "a_shrink_weight": w_a, "b_shrink_weight": w_b,
              "excludes_no_correction": shift["excludes_no_correction"]}
    out["global_map"] = gm
    cal = _sigmoid(gm["a"] + gm["b"] * x)
    out["calibrated"] = {"mean": float(cal.mean())}

    au = auc(conf, y)
    au_boot = [auc(conf[s], y[s]) for s in _boot_samples(_blocks(days), b, seed + 3)]
    au_ci, _ = _ci(au_boot)
    out["resolution"] = {"auc": au, "auc_ci": au_ci,
                         "brier_raw": float(np.mean((conf - y) ** 2)),
                         "brier_calibrated_in_sample": float(np.mean((cal - y) ** 2)),
                         **murphy(conf, y)}

    by_type: dict[str, dict] = {}
    for st in sorted({e.source_type for e in rows}):
        m = np.array([e.source_type == st for e in rows])
        by_type[st] = {"rows": int(m.sum()), "days": len({d for d, k in zip(days, m) if k}),
                       "stated_mean": float(conf[m].mean()), "win_rate": float(y[m].mean()),
                       "calibrated_mean": float(cal[m].mean())}
    out["by_source_type"] = by_type
    out["per_source"] = per_source_gate(rows, x, y, days, b, seed + 4)
    out["line"] = summary_line(out)
    return out


def per_source_gate(rows, x, y, days, b, seed) -> dict:
    """Per-source shift only for sources with >= MIN_DAYS_PER_SOURCE days whose own
    bootstrap CI excludes no correction; frozen off (PER_SOURCE_ENABLED)."""
    by_src: dict[str, list[int]] = defaultdict(list)
    for i, e in enumerate(rows):
        by_src[e.source_id].append(i)
    src_days = {s: len({days[i] for i in ix}) for s, ix in by_src.items()}
    eligible_ = []
    for s, ix in sorted(by_src.items()):
        if src_days[s] < MIN_DAYS_PER_SOURCE:
            continue
        ix = np.array(ix)
        r = _shift_with_ci(x[ix], y[ix], [days[i] for i in ix], b, seed)
        if r["excludes_no_correction"]:
            eligible_.append({"source_id": s, "days": src_days[s], **r})
    return {"enabled": PER_SOURCE_ENABLED, "min_days": MIN_DAYS_PER_SOURCE,
            "sources": len(by_src), "max_days": max(src_days.values()) if src_days else 0,
            "eligible": eligible_}


def calibrate(conf: float, summary: dict | None, source_id: str | None = None) -> float:
    """Calibrated P(net_return > 0) for a stated confidence (identity without a map)."""
    if not summary:
        return float(conf)
    gm = summary.get("global_map") or {}
    a, b = float(gm.get("a", 0.0)), float(gm.get("b", 1.0))
    ps = summary.get("per_source") or {}
    if ps.get("enabled") and source_id:
        for s in ps.get("eligible") or []:
            if s.get("source_id") == source_id:
                a = float(s.get("a_hat", a))
    return float(_sigmoid(a + b * _logit(conf)))


def _pct(v, d=1) -> str:
    return "n/a" if v is None else f"{v * 100:.{d}f}%"


def summary_line(s: dict) -> str:
    """One Chinese line for the daily report (code-written)."""
    sm = s.get("sample") or {}
    if not sm.get("rows"):
        return "确信度校准：还没有已结算的 LLM 记录。"
    gm, res = s.get("global_map") or {}, s.get("resolution") or {}
    head = (f"{sm['days']} 个决策日 {sm['rows']} 条已结算：自报确信度平均 {_pct(s['stated']['mean'])}，"
            f"实际胜率 {_pct(s['realized']['win_rate'])}")
    if gm.get("status") == "none":
        mid = f"；样本不足（少于 {MIN_DAYS_GLOBAL} 个决策日），不做修正"
    else:
        ci = gm.get("a_ci")
        ci_txt = f"，95% 区间 [{ci[0]:+.2f}, {ci[1]:+.2f}]" if ci else ""
        mid = (f"；全局修正后平均 {_pct(s['calibrated']['mean'])}"
               f"（logit 截距 {gm['a']:+.2f}{ci_txt}"
               + ("" if gm.get("status") == "platt" else "，斜率固定为 1：自报确信度几乎没有离散度")
               + "）")
    au = res.get("auc")
    if au is None:
        tail = "；区分度无法计算（只有一类结果）"
    else:
        aci = res.get("auc_ci")
        aci_txt = f"，区间 [{aci[0]:.2f}, {aci[1]:.2f}]" if aci else ""
        verdict = ("自报确信度不能区分输赢" if not aci or aci[0] <= 0.5 <= aci[1]
                   else "有一定区分度" if au > 0.5 else "区分方向相反")
        tail = f"；区分度 AUC {au:.2f}{aci_txt}（0.5 = 无区分），{verdict}"
    return "确信度校准（代码计算，仅注释，不影响仓位）：" + head + mid + tail + "。"


def write(summary: dict, folder: Path | None = None) -> Path:
    folder = folder or calibration_dir()
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / "latest.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return p


def read(path: Path | None = None) -> dict | None:
    p = path or latest_path()
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, ValueError):
        logger.warning("calibration summary %s unreadable", p)
        return None


def refresh(store, folder: Path | None = None) -> dict:
    """Recompute from the ledger and write latest.json (called after settlement)."""
    s = compute(store.list(status="settled"))
    write(s, folder)
    return s
