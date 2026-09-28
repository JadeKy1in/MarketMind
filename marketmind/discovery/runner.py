"""Daily discovery run (docs/S10_DESIGN.md §1, §2, §4, §5).

`run_discovery(news_items)` fetches every registry series concurrently (each with a
timeout), computes anomaly statistics and news coverage, checks every anomaly x
proxy for "already priced in", writes `data/discovery/<date>.json` (respecting
MARKETMIND_DATA_DIR) and returns the report dict. Pure code and data fetches: no
LLM calls, no token spend.

Integration helpers for the main pipeline:
- `candidates(report)` / `candidate_tickers(report)`: proxies of anomalies whose
  priced-in bucket is not_priced or partial, cold anomalies first, then |z|;
- `origin_for(report, ticker)`: the ledger `meta.origin` dict for a candidate;
- `prompt_block(report)`: compact text for the L2 / decision prompt.

Anomaly ids are `<run date>:<series id>`. The same weekly observation stays an
anomaly on several run dates; dedupe bookings on (`series`, `obs_date`).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from marketmind.discovery.anomaly import AnomalyConfig, compute_stats, is_stale, news_coverage
from marketmind.discovery.priced_in import (
    NOT_PRICED, PARTIAL, SECTOR_ETF, UNAVAILABLE, PricedInConfig, assess,
)
from marketmind.discovery.series import FetchContext, Series, default_registry

logger = logging.getLogger("marketmind.discovery.runner")

FETCH_TIMEOUT_S = 90
PRICE_TIMEOUT_S = 120
PRICE_YEARS = 1
CANDIDATE_BUCKETS = (NOT_PRICED, PARTIAL)

PriceLoader = Callable[[str], Awaitable[list | None]]


def default_report_dir() -> Path:
    return Path(os.getenv("MARKETMIND_DATA_DIR", "data")) / "discovery"


def _redact(text: str) -> str:
    from marketmind.gateway.fred_client import _redact as fred_redact
    return fred_redact(text)


def _today(today) -> date:
    if today is None:
        return datetime.now(timezone.utc).date()
    if isinstance(today, datetime):
        return today.date()
    if isinstance(today, date):
        return today
    return date.fromisoformat(str(today)[:10])


async def default_price_loader(ticker: str) -> list | None:
    """Complete daily bars (partial session dropped) for a proxy, or None."""
    from marketmind.gateway.price_history import complete_bars, get_price_history
    hist = await get_price_history(ticker, years=PRICE_YEARS)
    return complete_bars(ticker, hist.daily) if hist is not None and hist.daily else None


async def _fetch_one(s: Series, ctx: FetchContext, timeout: float):
    try:
        obs = await asyncio.wait_for(s.fetch(ctx), timeout=timeout)
        return list(obs or []), None
    except asyncio.TimeoutError:
        return None, f"timeout after {timeout:.0f}s"
    except Exception as e:
        logger.warning("discovery series %s failed: %s", s.id, _redact(str(e)))
        return None, _redact(f"{type(e).__name__}: {e}")[:300]


async def _load_prices(tickers: list[str], loader: PriceLoader, timeout: float) -> dict:
    async def one(t):
        try:
            return t, await asyncio.wait_for(loader(t), timeout=timeout), ""
        except asyncio.TimeoutError:
            return t, None, f"price history timeout after {timeout:.0f}s"
        except Exception as e:
            logger.warning("discovery price history %s failed: %s", t, e)
            return t, None, f"price history failed ({type(e).__name__})"
    return {t: (bars, why) for t, bars, why in await asyncio.gather(*(one(t) for t in tickers))}


def _origin(anomaly_id: str, series_id: str, bucket: str, coverage: int) -> dict:
    return {"kind": "anomaly", "series": [series_id], "anomaly_id": anomaly_id,
            "priced_in": bucket, "coverage": coverage}


def _sort_key(a: dict):
    return (0 if a["cold"] else 1, -abs(a["z"] or 0.0), a["coverage"], a["series"])


async def run_discovery(news_items, today=None, *, registry: list[Series] | None = None,
                        config: AnomalyConfig | None = None,
                        priced_config: PricedInConfig | None = None,
                        price_loader: PriceLoader | None = None,
                        out_dir: Path | str | None = None, write: bool = True,
                        fetch_timeout_s: float = FETCH_TIMEOUT_S,
                        price_timeout_s: float = PRICE_TIMEOUT_S) -> dict:
    """Scan the registry, write data/discovery/<date>.json, return the report."""
    day = _today(today)
    run_date = day.isoformat()
    cfg = config or AnomalyConfig()
    pcfg = priced_config or PricedInConfig()
    registry = default_registry() if registry is None else list(registry)
    loader = price_loader or default_price_loader

    ctx = FetchContext(day)
    try:
        fetched = await asyncio.gather(*(_fetch_one(s, ctx, fetch_timeout_s) for s in registry))
    finally:
        await ctx.aclose()

    series_out, unavailable, anomalies = [], [], []
    for s, (obs, err) in zip(registry, fetched):
        base = {"series": s.id, "title": s.title, "source": s.source,
                "frequency": s.frequency, "unit": s.unit}
        if err is None:
            obs = [(d, v) for d, v in obs if d <= run_date]
            if not obs:
                err = "no observations returned"
            elif is_stale(obs[-1][0], s.frequency, day, cfg):
                err = (f"stale: last observation {obs[-1][0]} is more than "
                       f"{cfg.stale_days.get(s.frequency, 75)} days old")
        if err is not None:
            unavailable.append({**base, "reason": err})
            series_out.append({**base, "status": "unavailable", "reason": err})
            continue
        st = compute_stats(obs, s.frequency, cfg, window=s.window, lookback_days=s.lookback_days)
        series_out.append({**base, "status": "ok", **st.to_dict()})
        if not st.is_anomaly:
            continue
        cov = news_coverage(news_items, s.keywords, day, cfg.news_days)
        anomalies.append({
            "anomaly_id": f"{run_date}:{s.id}", **base, "obs_date": st.last_date,
            "latest": st.latest, "change": st.change, "change_from": st.change_from,
            "change_pct": st.change_pct, "window": st.window, "z": st.z,
            "level_pct": st.level_pct, "new_high": st.new_high, "new_low": st.new_low,
            "history_days": st.history_days, "short_history": st.short_history,
            "triggers": st.triggers, "move": st.move, "coverage": cov,
            "cold": cov <= cfg.cold_max_coverage, "keywords": list(s.keywords),
            "prior": s.prior,
            "_proxies": [(t, d * st.move) for t, d in s.proxies],
        })

    tickers = sorted({t for a in anomalies for t, _ in a["_proxies"]}
                     | {SECTOR_ETF[t] for a in anomalies for t, _ in a["_proxies"] if t in SECTOR_ETF})
    prices = await _load_prices(tickers, loader, price_timeout_s) if tickers else {}

    for a in anomalies:
        rows = []
        for t, implied in a.pop("_proxies"):
            bars, why = prices.get(t, (None, "not loaded"))
            etf = SECTOR_ETF.get(t)
            row = assess(t, bars, a["obs_date"], implied, pcfg,
                         sector_bars=prices.get(etf, (None, ""))[0] if etf else None, sector_etf=etf)
            if row["bucket"] == UNAVAILABLE and why:
                row["reason"] = why
            row["direction"] = "long" if implied > 0 else "short" if implied < 0 else None
            row["origin"] = _origin(a["anomaly_id"], a["series"], row["bucket"], a["coverage"])
            rows.append(row)
        a["proxies"] = rows
        primary = next((r for r in rows if r["bucket"] != UNAVAILABLE), rows[0] if rows else None)
        a["priced_in"] = primary["bucket"] if primary else UNAVAILABLE
        a["origin"] = _origin(a["anomaly_id"], a["series"], a["priced_in"], a["coverage"])
    anomalies.sort(key=_sort_key)

    report = {
        "date": run_date,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {"anomaly": cfg.to_dict(), "priced_in": pcfg.to_dict()},
        "counts": {"series": len(registry), "ok": len(registry) - len(unavailable),
                   "unavailable": len(unavailable), "anomalies": len(anomalies),
                   "cold": sum(1 for a in anomalies if a["cold"]),
                   "news_items": len(news_items or [])},
        "anomalies": anomalies,
        "unavailable": unavailable,
        "series": series_out,
    }
    if write:
        path = Path(out_dir) if out_dir is not None else default_report_dir()
        path.mkdir(parents=True, exist_ok=True)
        f = path / f"{run_date}.json"
        f.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        report["file"] = str(f)
    logger.info("discovery %s: %d/%d series ok, %d anomalies (%d cold)", run_date,
                report["counts"]["ok"], len(registry), len(anomalies), report["counts"]["cold"])
    return report


def load_report(day=None, out_dir: Path | str | None = None) -> dict | None:
    f = (Path(out_dir) if out_dir is not None else default_report_dir()) / f"{_today(day).isoformat()}.json"
    if not f.exists():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


# ── integration helpers ─────────────────────────────────────────────────────

def candidates(report: dict, max_n: int = 10) -> list[dict]:
    """Proxy candidates for the main pipeline: not_priced / partial rows, cold
    anomalies first, then |z|; one row per ticker (the best-ranked anomaly wins)."""
    out, seen = [], set()
    for a in sorted(report.get("anomalies") or [], key=_sort_key):
        for p in a.get("proxies") or []:
            t = p.get("ticker")
            if p.get("bucket") not in CANDIDATE_BUCKETS or not p.get("direction") or t in seen:
                continue
            seen.add(t)
            out.append({"ticker": t, "direction": p["direction"], "anomaly_id": a["anomaly_id"],
                        "series": a["series"], "title": a["title"], "cold": a["cold"],
                        "coverage": a["coverage"], "z": a["z"], "priced_in": p["bucket"],
                        "move_atr": p.get("move_atr"), "origin": p["origin"]})
            if len(out) >= max_n:
                return out
    return out


def candidate_tickers(report: dict, max_n: int = 10) -> list[str]:
    return [c["ticker"] for c in candidates(report, max_n)]


def origin_for(report: dict, ticker: str) -> dict | None:
    """`meta.origin` for a ledger entry on `ticker` that came from the discovery scan."""
    for c in candidates(report, max_n=10_000):
        if c["ticker"] == ticker:
            return dict(c["origin"])
    return None


def _num(v) -> str:
    if v is None:
        return "n/a"
    a = abs(v)
    if a >= 1000:
        return f"{v:,.0f}"
    if a >= 1:
        return f"{v:,.2f}"
    return f"{v:.4g}"


def prompt_block(report: dict, max_items: int = 8) -> str:
    """Compact text for the decision / L2 prompt. Every number is from the report."""
    anomalies = sorted(report.get("anomalies") or [], key=_sort_key)
    head = (f"Cold-data anomalies {report.get('date', '')} (code-computed from official series; "
            "coverage = matching news items in the last 7 days; direction = registry prior, "
            "a hypothesis tested by the ledger, not a conclusion):")
    if not anomalies:
        lines = [head, "- none today"]
    else:
        lines = [head]
        for a in anomalies[:max_items]:
            stats = [f"{a['window']}-obs change {_num(a['change'])}"]
            if a["z"] is not None:
                stats.append(f"z {a['z']:+.1f}")
            if a["level_pct"] is not None:
                stats.append(f"level pct {a['level_pct']:.0f}")
            if a["new_high"]:
                stats.append("new lookback high")
            if a["new_low"]:
                stats.append("new lookback low")
            prox = ", ".join(
                f"{p['ticker']} {p['direction'] or '?'} {p['bucket']}"
                + (f" ({p['move_atr']:+.1f} ATR)" if p.get("move_atr") is not None else "")
                for p in a["proxies"])
            lines.append(f"- [{'cold' if a['cold'] else 'covered'}, news {a['coverage']}] {a['title']} "
                         f"({a['series']}) {a['obs_date']}: {_num(a['latest'])} {a['unit']}; "
                         + "; ".join(stats) + (f". Proxies: {prox}" if prox else ""))
        if len(anomalies) > max_items:
            lines.append(f"- ... {len(anomalies) - max_items} more in data/discovery/{report.get('date')}.json")
    un = report.get("unavailable") or []
    if un:
        lines.append(f"- Unavailable series today ({len(un)}): " + ", ".join(u["series"] for u in un))
    return "\n".join(lines)
