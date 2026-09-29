"""China market data through akshare (owner-approved dependency, 2026-09-29).

akshare (https://github.com/akfamily/akshare, MIT code) scrapes public Chinese
sites; its docs say the data is for academic research only, and upstream sites
change often. Reachability from Riyadh, tested 2026-09-29 (akshare 1.18.97):
- works: stock_zh_index_daily (Sina A-share indices), stock_hk_index_daily_sina (HSI),
  stock_hsgt_hist_em (Eastmoney datacenter: Stock Connect history),
  stock_margin_account_info (Eastmoney datacenter: whole-market margin balances),
  stock_margin_sse (SSE site).
- blocked (connection reset / closed): Eastmoney push2his quote API
  (index_zh_a_hist, stock_zh_index_daily_em) and SZSE (stock_margin_szse).
- northbound: stock_hsgt_hist_em("北向资金") returns NaN net-buy values for recent
  days, and stock_hsgt_fund_flow_summary_em reports northbound net buy as 0.0 —
  that 0.0 is "not published", not a real zero, so it is never used here.

Threading: akshare is synchronous, so calls run in a worker thread. There is exactly
ONE worker: the Sina functions use py_mini_racer (V8), which aborted the whole
Python process with a fatal V8 check when several threads initialised it at once
(observed 2026-09-29). Every call has a timeout and failures raise
AkshareUnavailable with a short label; nothing is filled in.
"""
from __future__ import annotations

import asyncio
import logging
import math
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("marketmind.gateway.china_akshare")

CALL_TIMEOUT_S = 40.0
LICENCE_NOTE = "akshare states its data is for academic research only"
# label -> (akshare function, kwargs)
INDEXES: dict[str, tuple[str, dict]] = {
    "CSI 300": ("stock_zh_index_daily", {"symbol": "sh000300"}),
    "SSE Composite": ("stock_zh_index_daily", {"symbol": "sh000001"}),
    "ChiNext": ("stock_zh_index_daily", {"symbol": "sz399006"}),
    "STAR 50": ("stock_zh_index_daily", {"symbol": "sh000688"}),
    "Hang Seng": ("stock_hk_index_daily_sina", {"symbol": "HSI"}),
}
KEEP_ROWS = 60

_AK = None                                  # the akshare module; tests inject a fake
_EXECUTOR: ThreadPoolExecutor | None = None


class AkshareUnavailable(RuntimeError):
    """An akshare call failed; str() is a short label safe to show in a context."""


def _ak():
    global _AK
    if _AK is None:
        import akshare                          # heavy import, only when first needed
        _AK = akshare
    return _AK


def version() -> str:
    try:
        return str(getattr(_ak(), "__version__", "unknown"))
    except ImportError:
        return "not installed"


def _executor() -> ThreadPoolExecutor:
    global _EXECUTOR
    if _EXECUTOR is None:
        _EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="akshare")
    return _EXECUTOR


def _records(obj) -> list[dict]:
    if hasattr(obj, "to_dict"):
        return obj.to_dict("records")
    return list(obj or [])


async def call(fn_name: str, timeout: float = CALL_TIMEOUT_S, **kwargs) -> list[dict]:
    """Run one akshare function in the akshare worker thread -> list of row dicts."""
    def work():
        return _records(getattr(_ak(), fn_name)(**kwargs))

    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(loop.run_in_executor(_executor(), work), timeout)
    except asyncio.TimeoutError:
        raise AkshareUnavailable(f"{fn_name} timed out after {timeout:.0f}s") from None
    except ImportError:
        raise AkshareUnavailable("akshare not installed") from None
    except Exception as e:
        logger.warning("akshare %s failed: %s", fn_name, e)
        raise AkshareUnavailable(f"{fn_name} failed ({type(e).__name__})") from e


# ── parsers (pure) ──────────────────────────────────────────────────────────

def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def _day(v) -> str:
    return str(v)[:10]


def close_series(rows: list[dict]) -> list[tuple[str, float]]:
    """[(date, close)], date order, last KEEP_ROWS rows."""
    out = sorted((_day(r.get("date")), c) for r in rows
                 if r.get("date") is not None and (c := _num(r.get("close"))) is not None)
    return out[-KEEP_ROWS:]


def connect_series(rows: list[dict]) -> dict:
    """Stock Connect history -> {"series": [(date, net buy)], "last_date": newest row date,
    "blank_since": first date of the trailing run of rows with no value, or None}."""
    rows = sorted(rows, key=lambda r: _day(r.get("日期")))
    vals = [(_day(r.get("日期")), _num(r.get("当日成交净买额"))) for r in rows if r.get("日期")]
    blank_since = None
    for d, v in reversed(vals):
        if v is not None:
            break
        blank_since = d
    series = [(d, v) for d, v in vals if v is not None][-KEEP_ROWS:]
    return {"series": series, "last_date": vals[-1][0] if vals else None,
            "blank_since": blank_since}


def margin_series(rows: list[dict]) -> list[dict]:
    """Whole-market margin balances (亿元), date order: {date, financing, lending}."""
    out = []
    for r in rows:
        fin = _num(r.get("融资余额"))
        if r.get("日期") is None or fin is None:
            continue
        out.append({"date": _day(r.get("日期")), "financing": fin,
                    "lending": _num(r.get("融券余额"))})
    return sorted(out, key=lambda r: r["date"])[-KEEP_ROWS:]


# ── loaders ─────────────────────────────────────────────────────────────────

async def index_closes() -> dict[str, list[tuple[str, float]] | AkshareUnavailable]:
    out: dict = {}
    for label, (fn, kw) in INDEXES.items():
        try:
            out[label] = close_series(await call(fn, **kw))
        except AkshareUnavailable as e:
            out[label] = e
    return out


async def southbound() -> dict:
    return connect_series(await call("stock_hsgt_hist_em", symbol="南向资金"))


async def northbound() -> dict:
    return connect_series(await call("stock_hsgt_hist_em", symbol="北向资金"))


async def margin_balance() -> list[dict]:
    return margin_series(await call("stock_margin_account_info"))
