"""Pure-code anomaly statistics and news coverage (docs/S10_DESIGN.md §1).

For one series `[(date, value)]`:
- change   = latest value minus the value `window` observations earlier
             (daily 5, weekly 4, monthly 3; a series may override the window);
- z        = that change against the trailing-lookback (default 1 year) distribution
             of the same-window changes, the latest change itself excluded;
- level_pct = mid-rank percentile of the latest value among the prior values in the
             lookback (ties count half), 0-100;
- new_high / new_low = latest strictly above / below every prior value in the lookback.

Anomaly if |z| >= 2; or level_pct <= 5 / >= 95 or a new lookback high / low
together with |z| >= 1 (alone only when there is no z) - a trending series
otherwise sits at its extreme every day.
Too little history: no z (fewer than `min_changes` changes) and / or no level
statistics (fewer than `min_level_obs` prior values, or the history spans fewer
than `min_history_days`); the latest level is still reported.

`move` is the direction the anomaly says the series went: the sign of z (the
change against its usual same-window change) when z triggered, else +1 for a high level and -1 for a low level. Proxies' implied
directions (registry priors) are multiplied by it.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime


@dataclass(frozen=True)
class AnomalyConfig:
    z_threshold: float = 2.0
    pct_low: float = 5.0
    pct_high: float = 95.0
    windows: dict = field(default_factory=lambda: {"daily": 5, "weekly": 4, "monthly": 3})
    lookback_days: int = 365
    min_changes: int = 10
    min_level_obs: int = 10
    min_history_days: int = 60
    short_history_days: int = 330      # history shorter than this is flagged `short_history`
    stale_days: dict = field(default_factory=lambda: {"daily": 10, "weekly": 21, "monthly": 75})
    # A level extreme or new high/low alone keeps firing on trending series (bill
    # holdings, JGB yields); it counts only with an unusual change (|z| >= this),
    # or on its own when the series is too short for a z.
    level_needs_z: float = 1.0
    cold_max_coverage: int = 2         # coverage <= this -> cold
    news_days: int = 7

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SeriesStats:
    n_obs: int
    first_date: str
    last_date: str
    latest: float
    window: int
    lookback_start: str
    history_days: int                  # span of the observations used (lookback-bounded)
    short_history: bool
    change: float | None = None
    change_from: str | None = None     # date of the value the change is measured against
    change_pct: float | None = None    # relative change in %, when the base is non-zero
    n_changes: int = 0
    z: float | None = None
    level_pct: float | None = None
    new_high: bool = False
    new_low: bool = False
    triggers: list[str] = field(default_factory=list)
    move: int = 0
    note: str = ""

    @property
    def is_anomaly(self) -> bool:
        return bool(self.triggers)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["is_anomaly"] = self.is_anomaly
        return d


def _r(x: float | None, nd: int = 4) -> float | None:
    return None if x is None else round(x, nd) + 0.0     # + 0.0 turns -0.0 into 0.0


def compute_stats(obs: list[tuple[str, float]], frequency: str, cfg: AnomalyConfig | None = None,
                  window: int | None = None, lookback_days: int | None = None) -> SeriesStats:
    """Stats for observations sorted oldest first (at least one observation)."""
    cfg = cfg or AnomalyConfig()
    if not obs:
        raise ValueError("no observations")
    w = window or cfg.windows.get(frequency) or 1
    lb = lookback_days or cfg.lookback_days
    last_d, latest = obs[-1]
    start = (date.fromisoformat(last_d) - timedelta(days=lb)).isoformat()
    in_lb = [(d, v) for d, v in obs if d >= start]
    span = (date.fromisoformat(last_d) - date.fromisoformat(in_lb[0][0])).days
    s = SeriesStats(n_obs=len(obs), first_date=obs[0][0], last_date=last_d, latest=latest,
                    window=w, lookback_start=start, history_days=span,
                    short_history=span < cfg.short_history_days)
    notes = []
    enough_span = span >= cfg.min_history_days

    if len(obs) > w:
        base_d, base = obs[-1 - w]
        s.change, s.change_from = _r(latest - base, 6), base_d
        s.change_pct = _r((latest / base - 1) * 100) if base else None
        changes = [obs[i][1] - obs[i - w][1] for i in range(w, len(obs) - 1) if obs[i][0] >= start]
        s.n_changes = len(changes)
        if len(changes) >= cfg.min_changes and enough_span:
            sd = statistics.stdev(changes)
            if sd > 0:
                s.z = _r((latest - base - statistics.fmean(changes)) / sd, 3)
            else:
                notes.append("changes have zero dispersion: no z")
        else:
            notes.append(f"too little history for z ({len(changes)} changes over {span} days)")
    else:
        notes.append("too few observations for a change")

    prior = [v for _, v in in_lb[:-1]]
    if len(prior) >= cfg.min_level_obs and enough_span:
        below = sum(1 for v in prior if v < latest)
        ties = sum(1 for v in prior if v == latest)
        s.level_pct = round(100.0 * (below + 0.5 * ties) / len(prior), 2)
        s.new_high = latest > max(prior)
        s.new_low = latest < min(prior)
    else:
        notes.append(f"too little history for level percentile ({len(prior)} prior values)")

    if s.z is not None and abs(s.z) >= cfg.z_threshold:
        s.triggers.append("z")
    level_counts = s.z is None or abs(s.z) >= cfg.level_needs_z
    if level_counts and s.level_pct is not None and s.level_pct >= cfg.pct_high:
        s.triggers.append("level_high")
    if level_counts and s.level_pct is not None and s.level_pct <= cfg.pct_low:
        s.triggers.append("level_low")
    if level_counts and s.new_high:
        s.triggers.append("new_high")
    if level_counts and s.new_low:
        s.triggers.append("new_low")

    if "z" in s.triggers:           # direction of the surprise vs the usual change
        s.move = 1 if s.z > 0 else -1
    elif "level_high" in s.triggers or "new_high" in s.triggers:
        s.move = 1
    elif "level_low" in s.triggers or "new_low" in s.triggers:
        s.move = -1
    s.note = "; ".join(notes)
    return s


def is_stale(last_date: str, frequency: str, today: date, cfg: AnomalyConfig | None = None) -> bool:
    cfg = cfg or AnomalyConfig()
    limit = cfg.stale_days.get(frequency, 75)
    return (today - date.fromisoformat(last_date)).days > limit


# ── news coverage ───────────────────────────────────────────────────────────

def _field(item, *names):
    for n in names:
        v = item.get(n) if isinstance(item, dict) else getattr(item, n, None)
        if v:
            return v
    return None


def _item_date(item) -> date | None:
    raw = _field(item, "published_at", "published", "date", "fetched_at")
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.astimezone(timezone.utc).date() if raw.tzinfo else raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).date() if dt.tzinfo else dt.date()
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(text)
        return dt.astimezone(timezone.utc).date() if dt.tzinfo else dt.date()
    except (TypeError, ValueError, IndexError):
        return None


def _pattern(keyword: str) -> re.Pattern:
    kw = keyword.strip()
    if kw.isascii():      # whole-word match so "TGA" does not hit "outage"
        return re.compile(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", re.IGNORECASE)
    return re.compile(re.escape(kw), re.IGNORECASE)


def news_coverage(news_items, keywords, today: date, days: int = 7) -> int:
    """News items (dicts or objects with title / summary) dated within `days` of
    `today` whose title or summary mentions any keyword. Undated items count."""
    pats = [_pattern(k) for k in keywords if k and k.strip()]
    if not pats:
        return 0
    cutoff = today - timedelta(days=days)
    n = 0
    for item in news_items or []:
        d = _item_date(item)
        if d is not None and (d < cutoff or d > today + timedelta(days=1)):
            continue
        text = f"{_field(item, 'title') or ''} {_field(item, 'summary') or ''}"
        if any(p.search(text) for p in pats):
            n += 1
    return n
