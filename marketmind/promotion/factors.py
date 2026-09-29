"""Factor diagnostics for promotion candidates (docs/S7_DESIGN.md §三). Reporting only:
no ladder gate reads these results (wiring them into gates is an owner decision).

For each shadow, the promotion ladder's own record — its matured settled trades
(`ladder.matured`) on the $10,000 notional (`config.NOTIONAL_USD`) — is regressed on
daily equity factors:

    r_t - x_t * RF_t = alpha + sum_j beta_j * F_jt [+ beta_btc * (BTC_t - RF_t)] + e_t

- r_t: the shadow's MARK-TO-MARKET daily P&L / notional. The ladder books a trade's
  whole P&L on one day (decision or exit day), which is right for its gates but puts
  a 10-day trade's return against one day's factor returns; a factor regression needs
  the P&L on the days it was earned. So each trade is marked daily from its entry
  price through the closes of the days held to its exit price (shares = position /
  entry price); the rest of the ledger P&L (costs) is booked on the exit day, so the
  series sums exactly to the ledger pnl_usd of the same trades. A trade without usable
  bars (missing ticker, gap > MAX_GAP_DAYS) is spread evenly over its holding days and
  counted in `mtm.spread`. Non-trading days of the factor calendar (crypto weekends,
  foreign holidays) are summed into the next factor day.
- x_t * RF_t: financing. Paper trades use no cash, so the ledger return is an
  overlay; x_t = net signed position / notional on day t (short positions earn RF).
- Factors: Fama-French 5 + momentum from the Ken French Data Library when it covers
  the whole window; otherwise ETF proxies (MKT, SMB, HML, MOM) for the whole window
  (`gateway/factor_data.py`). Sources are never mixed within one regression.
- Crypto: when crypto is >= CRYPTO_FACTOR_SHARE of the shadow's gross dollar-days,
  BTC-USD (close-to-close on factor days, weekends included in Monday) minus RF is
  added. At >= HEAVY_SHARE crypto (or non-US equity, whose closes are hours away from
  US factor returns) the equity loadings are marked not meaningful (`meaningful`).
- Standard errors: Newey-West (Bartlett) HAC with lag floor(4 (n/100)^(2/9)) (Newey &
  West 1994 rule), small-sample factor n / (n - k); two-sided p from Student t(n - k).
- Alpha is reported daily and annualised (x 252) on the $10k notional, and per dollar
  of average gross exposure (`alpha_annual_per_exposure`), since shadow positions are
  a few percent of the notional.
- Style drift: rolling ROLL_WINDOW-day betas (stored every ROLL_STEP days). Drift is
  flagged for a factor when the latest ROLL_WINDOW days' beta differs from the beta on
  all earlier days (non-overlapping) by more than DRIFT_Z combined HAC standard errors
  sqrt(se_recent^2 + se_prior^2); needs 2 x ROLL_WINDOW observations. With 4-6
  factors about a quarter of constant-beta shadows get at least one 2-SE flag
  (simulated 2026-09-29), so `flags_family` also lists the factors past the Bonferroni
  threshold z(1 - 0.05 / 2k) over the k factors (k = 4: 2.50).
- Fewer than MIN_OBS factor days in the window -> status "insufficient".
"""
from __future__ import annotations

import logging
import math
from bisect import bisect_left
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Callable

import numpy as np
from scipy import stats

from marketmind.gateway import factor_data as FD
from marketmind.ledger.store import LedgerEntry
from marketmind.markets import market_for
from marketmind.promotion import config as C

log = logging.getLogger(__name__)

MIN_OBS = 40                     # factor days in the regression window, else "insufficient"
ROLL_WINDOW = 40                 # rolling beta window (days)
ROLL_STEP = 5                    # rolling betas stored every this many days ...
ROLL_MAX_POINTS = 50             # ... at most this many (latest kept)
DRIFT_Z = 2.0                    # |beta_recent - beta_prior| > DRIFT_Z combined SEs -> drift
DRIFT_FAMILY_ALPHA = 0.05        # stricter Bonferroni flag over all factors (`flags_family`)
CRYPTO_FACTOR_SHARE = 0.10       # crypto share of gross dollar-days that adds the BTC factor
HEAVY_SHARE = 0.50               # crypto or non-US equity share that makes equity betas not meaningful
MAX_GAP_DAYS = 4                 # calendar days between a trade's consecutive bars (holidays)
BTC = "BTC-USD"


def hac_lag(n: int) -> int:
    """Newey & West (1994) rule of thumb: floor(4 (n / 100)^(2/9)), at least 1."""
    return max(1, int(math.floor(4 * (n / 100.0) ** (2.0 / 9.0))))


def ols_hac(y, X, lag: int) -> dict:
    """OLS with Newey-West (Bartlett) HAC covariance. X includes the intercept column."""
    y = np.asarray(y, dtype=float)
    X = np.asarray(X, dtype=float)
    n, k = X.shape
    xtx_inv = np.linalg.pinv(X.T @ X)
    b = xtx_inv @ (X.T @ y)
    e = y - X @ b
    u = X * e[:, None]
    S = u.T @ u
    for lag_i in range(1, min(lag, n - 1) + 1):
        w = 1.0 - lag_i / (lag + 1.0)
        G = u[lag_i:].T @ u[:-lag_i]
        S += w * (G + G.T)
    V = xtx_inv @ S @ xtx_inv * (n / max(n - k, 1))
    se = np.sqrt(np.clip(np.diag(V), 0.0, None))
    sst = float(((y - y.mean()) ** 2).sum())
    ssr = float((e ** 2).sum())
    r2 = 1.0 - ssr / sst if sst > 0 else None
    adj = (1.0 - (1.0 - r2) * (n - 1) / (n - k)) if r2 is not None and n > k else None
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(se > 0, b / se, np.nan)
    p = 2.0 * stats.t.sf(np.abs(t), max(n - k, 1))
    return {"coef": b, "se": se, "t": t, "p": p, "r2": r2, "adj_r2": adj, "n": n, "k": k}


# ── Mark-to-market daily P&L ───────────────────────────────────────────

def _gap(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _holding_days(ticker: str, entry: str, exit_: str) -> list[str]:
    """Days a trade without usable bars is spread over: weekdays, or every calendar
    day for UTC-day markets (crypto, FX)."""
    days = np.arange(np.datetime64(entry), np.datetime64(exit_) + 1, dtype="datetime64[D]")
    if not market_for(ticker).utc_days:
        days = [d for d in days if np.is_busday(d)] or [np.datetime64(exit_)]
    return [str(d) for d in days]


def mark_to_market(trades: list[LedgerEntry], bars: dict, notional: float = C.NOTIONAL_USD) -> dict:
    """Daily P&L / notional of settled trades, marked on each day held (see module doc).

    Returns {"pnl", "net", "gross", "crypto", "non_us"} as {day: value} maps (positions
    and P&L divided by notional) and counts {"marked", "spread", "skipped"}."""
    pnl: dict[str, float] = defaultdict(float)
    net: dict[str, float] = defaultdict(float)
    gross: dict[str, float] = defaultdict(float)
    crypto: dict[str, float] = defaultdict(float)
    non_us: dict[str, float] = defaultdict(float)
    counts = {"marked": 0, "spread": 0, "skipped": 0}
    for e in trades:
        if e.status != "settled" or e.pnl_usd is None or not e.entry_date or not e.exit_date:
            counts["skipped"] += 1
            continue
        ent, ex = e.entry_date[:10], e.exit_date[:10]
        sign = 1.0 if e.direction == "long" else -1.0
        seg = [b for b in (bars.get(e.ticker) or []) if ent <= b.date <= ex]
        ok = (bool(seg) and seg[0].date == ent and seg[-1].date == ex
              and (e.entry_price or 0) > 0 and (e.exit_price or 0) > 0
              and all(_gap(a.date, b.date) <= MAX_GAP_DAYS for a, b in zip(seg, seg[1:])))
        if ok:
            shares = e.position_usd / e.entry_price
            prev, total, days = e.entry_price, 0.0, []
            for b in seg[:-1]:
                v = sign * shares * (b.close - prev)
                pnl[b.date] += v / notional
                total += v
                prev = b.close
                days.append(b.date)
            v = sign * shares * (e.exit_price - prev)
            pnl[ex] += (v + (e.pnl_usd - total - v)) / notional     # rest = ledger costs
            days.append(ex)
            counts["marked"] += 1
        else:
            days = _holding_days(e.ticker, ent, ex)
            for d in days:
                pnl[d] += e.pnl_usd / len(days) / notional
            counts["spread"] += 1
        m = market_for(e.ticker)
        is_crypto = m.code == "CRYPTO"
        is_non_us = m.asset_class == "equity" and m.code != "US"
        for d in days:
            net[d] += sign * e.position_usd / notional
            gross[d] += e.position_usd / notional
            if is_crypto:
                crypto[d] += e.position_usd / notional
            if is_non_us:
                non_us[d] += e.position_usd / notional
    return {"pnl": dict(pnl), "net": dict(net), "gross": dict(gross), "crypto": dict(crypto),
            "non_us": dict(non_us), **counts}


def align(by_day: dict[str, float], calendar: list[str]) -> tuple[np.ndarray, float]:
    """Sum each day's value into the first calendar day on or after it (weekends and
    foreign holidays into the next factor day). Returns (series, value after the end)."""
    out = np.zeros(len(calendar))
    after = 0.0
    for d, v in by_day.items():
        i = bisect_left(calendar, d)
        if i < len(calendar):
            out[i] += v
        else:
            after += v
    return out, after


# ── Factor sources ─────────────────────────────────────────────────────

class FactorProvider:
    """Lazy factor tables and bars for one promotion run.

    `bars_for(tickers) -> {ticker: bars}` is the ladder's loader (shared price cache);
    French data are cached under `cache_dir` (gateway/factor_data.py). Pass
    `french=None` to disable the library (tests), or a FactorTable to inject one."""

    _UNSET = object()

    def __init__(self, bars_for: Callable, cache_dir: str | Path | None = None,
                 fetch=None, french=_UNSET):
        self.bars_for = bars_for
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._fetch = fetch
        self._french = french
        self._proxy = self._UNSET
        self.used: set[str] = set()

    def french(self) -> FD.FactorTable | None:
        if self._french is self._UNSET:
            self._french = None
            if self.cache_dir is not None:
                try:
                    self._french = FD.french_factors(self.cache_dir, fetch=self._fetch)
                except Exception:                  # noqa: BLE001 - diagnostics never fail the run
                    log.warning("French factors unavailable", exc_info=True)
        return self._french

    def proxy(self) -> FD.FactorTable | None:
        if self._proxy is self._UNSET:
            self._proxy = None
            try:
                self._proxy = FD.etf_proxy_factors(self.bars_for(list(FD.PROXY_TICKERS)))
            except Exception:                      # noqa: BLE001
                log.warning("ETF factor proxies unavailable", exc_info=True)
        return self._proxy

    def table_for(self, lo: str, hi: str) -> FD.FactorTable | None:
        """French when it covers [lo, hi] entirely, else the ETF proxies."""
        fr = self.french()
        if fr is not None and fr.covers(lo, hi):
            return fr
        px = self.proxy()
        return px if px is not None and px.first is not None and px.first <= lo else None

    def meta(self) -> dict:
        fr = self._french if self._french is not self._UNSET else None
        px = self._proxy if self._proxy is not self._UNSET else None
        return {"french_last_day": fr.last if fr else None,
                "french_loaded": fr is not None,
                "proxy_last_day": px.last if px else None,
                "sources_used": sorted(self.used)}


# ── Per-shadow analysis ────────────────────────────────────────────────

def _roll(y: np.ndarray, X: np.ndarray, days: list[str], names: list[str]) -> dict:
    n = len(y)
    ends = list(range(n, ROLL_WINDOW - 1, -ROLL_STEP))[:ROLL_MAX_POINTS][::-1]
    out = {"window": ROLL_WINDOW, "step": ROLL_STEP, "days": [], "betas": {k: [] for k in names}}
    for end in ends:
        Xw, yw = X[end - ROLL_WINDOW:end], y[end - ROLL_WINDOW:end]
        b = np.linalg.pinv(Xw.T @ Xw) @ (Xw.T @ yw)
        out["days"].append(days[end - 1])
        for j, k in enumerate(names):
            out["betas"][k].append(float(b[j + 1]))
    return out


def style_drift(y: np.ndarray, X: np.ndarray, names: list[str]) -> dict:
    """Latest ROLL_WINDOW days vs all earlier days, per factor (HAC SEs, see module doc)."""
    n = len(y)
    if n < 2 * ROLL_WINDOW:
        return {"status": "insufficient", "reason": f"needs {2 * ROLL_WINDOW} days, has {n}",
                "flags": []}
    rec = ols_hac(y[-ROLL_WINDOW:], X[-ROLL_WINDOW:], hac_lag(ROLL_WINDOW))
    pri = ols_hac(y[:-ROLL_WINDOW], X[:-ROLL_WINDOW], hac_lag(n - ROLL_WINDOW))
    z_family = float(stats.norm.ppf(1 - DRIFT_FAMILY_ALPHA / (2 * len(names))))
    detail, flags, strict = {}, [], []
    for j, k in enumerate(names, start=1):
        se = math.sqrt(rec["se"][j] ** 2 + pri["se"][j] ** 2)
        z = (rec["coef"][j] - pri["coef"][j]) / se if se > 0 else None
        detail[k] = {"recent": float(rec["coef"][j]), "prior": float(pri["coef"][j]),
                     "z": None if z is None else float(z)}
        if z is not None and abs(z) > DRIFT_Z:
            flags.append(k)
        if z is not None and abs(z) > z_family:
            strict.append(k)
    return {"status": "ok", "recent_days": ROLL_WINDOW, "prior_days": n - ROLL_WINDOW,
            "threshold_z": DRIFT_Z, "flags": flags,
            "family_threshold_z": z_family, "flags_family": strict, "detail": detail}


def analyze(trades: list[LedgerEntry], provider: FactorProvider,
            notional: float = C.NOTIONAL_USD) -> dict:
    """Factor regression of one shadow's matured settled trades (see module doc)."""
    rows = [e for e in trades if e.status == "settled" and e.pnl_usd is not None
            and e.entry_date and e.exit_date]
    if not rows:
        return {"status": "insufficient", "reason": "no settled trades", "obs": 0}
    lo = min(e.entry_date[:10] for e in rows)
    hi = max(e.exit_date[:10] for e in rows)
    approx = int(np.busday_count(lo, np.datetime64(hi) + 1))
    if approx < MIN_OBS:
        return {"status": "insufficient", "reason": f"< {MIN_OBS} daily observations",
                "obs": approx, "window": [lo, hi]}
    table = provider.table_for(lo, hi)
    if table is None:
        return {"status": "unavailable", "reason": "no factor data covering the window",
                "window": [lo, hi]}
    i0 = bisect_left(table.days, lo)
    i1 = bisect_left(table.days, hi)
    i1 = i1 + 1 if i1 < len(table.days) and table.days[i1] == hi else i1
    cal = table.days[i0:i1]
    if len(cal) < MIN_OBS:
        return {"status": "insufficient", "reason": f"< {MIN_OBS} daily observations",
                "obs": len(cal), "window": [lo, hi], "source": table.source}

    bars = provider.bars_for(sorted({e.ticker for e in rows}))
    mtm = mark_to_market(rows, bars, notional)
    r, after = align(mtm["pnl"], cal)
    net = np.array([mtm["net"].get(d, 0.0) for d in cal])
    gross = np.array([mtm["gross"].get(d, 0.0) for d in cal])
    dollar_days = sum(mtm["gross"].values())
    crypto_share = sum(mtm["crypto"].values()) / dollar_days if dollar_days else 0.0
    non_us_share = sum(mtm["non_us"].values()) / dollar_days if dollar_days else 0.0

    F = table.values[i0:i0 + len(cal)]
    rf = table.rf[i0:i0 + len(cal)]
    names = list(table.names)
    notes = list(table.notes)
    if crypto_share >= CRYPTO_FACTOR_SHARE:
        prev = table.days[i0 - 1] if i0 > 0 else \
            str(np.datetime64(cal[0]) - np.timedelta64(1, "D"))
        btc = FD.aligned_returns((provider.bars_for([BTC]) or {}).get(BTC), [prev] + cal)
        if btc is not None and np.all(np.isfinite(btc)):
            F = np.column_stack([F, btc - rf])
            names.append("BTC")
        else:
            notes.append("crypto share needs a BTC factor but BTC bars are unavailable")
    y = r - net * rf
    if not np.any(y != 0) or float(np.std(y)) == 0.0:
        return {"status": "insufficient", "reason": "no variation in the daily P&L",
                "obs": len(cal), "window": [cal[0], cal[-1]], "source": table.source}

    X = np.column_stack([np.ones(len(y)), F])
    lag = hac_lag(len(y))
    fit = ols_hac(y, X, lag)
    meaningful = crypto_share < HEAVY_SHARE and non_us_share < HEAVY_SHARE
    if crypto_share >= HEAVY_SHARE:
        notes.append(f"crypto is {crypto_share:.0%} of exposure: equity factor loadings are "
                     "not meaningful; read alpha and the BTC beta only")
    if non_us_share >= HEAVY_SHARE:
        notes.append(f"non-US equity is {non_us_share:.0%} of exposure: US factor returns are "
                     "not synchronous with its closes, loadings are not meaningful")
    mean_gross = float(gross.mean())
    alpha_ann = float(fit["coef"][0]) * C.TRADING_DAYS_PER_YEAR
    provider.used.add(table.source)
    return {
        "status": "ok", "source": table.source, "factors": names,
        "window": [cal[0], cal[-1]], "obs": len(cal),
        "exposed_days": int((gross > 0).sum()), "mean_gross_exposure": mean_gross,
        "alpha_daily": float(fit["coef"][0]), "alpha_annual": alpha_ann,
        "alpha_annual_per_exposure": alpha_ann / mean_gross if mean_gross > 0 else None,
        "alpha_t": _f(fit["t"][0]), "alpha_p": _f(fit["p"][0]),
        "betas": {k: {"beta": float(fit["coef"][j]), "se": float(fit["se"][j]),
                      "t": _f(fit["t"][j])} for j, k in enumerate(names, start=1)},
        "r2": fit["r2"], "adj_r2": fit["adj_r2"], "hac_lag": lag,
        "crypto_share": crypto_share, "non_us_share": non_us_share, "meaningful": meaningful,
        "notes": notes,
        "mtm": {"marked": mtm["marked"], "spread": mtm["spread"], "skipped": mtm["skipped"],
                "pnl_after_window": after},
        "rolling": _roll(y, X, cal, names) if len(y) >= ROLL_WINDOW else None,
        "drift": style_drift(y, X, names),
    }


def _f(v) -> float | None:
    v = float(v)
    return v if math.isfinite(v) else None
