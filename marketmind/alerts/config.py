"""Big-move alert settings in one place (docs/S8_DESIGN.md, owner decisions 2026-09-29).

Two owner switches, both read at run time:
- MARKETMIND_ALERTS_LIVE      live mode (push). Default off = observe mode: alerts are
                              computed, written to the report and ledger, never pushed.
- MARKETMIND_ALERT_TREND_SOURCE  which trend-signal source feeds the trunk
                              (alerts/trend_source.py::SOURCES, or "package.module:factory").
"""
from __future__ import annotations

import os

# ── owner switches ──────────────────────────────────────────────────────
LIVE = False                           # owner's explicit switch; env below overrides
LIVE_ENV = "MARKETMIND_ALERTS_LIVE"
TREND_SOURCE = "daily_state_machine"   # lean universe when the file has one, else full
TREND_SOURCE_ENV = "MARKETMIND_ALERT_TREND_SOURCE"

# ── advisor votes (annotations, not conditions) ─────────────────────────
WINDOW_DAYS = 5                        # votes / evidence from the last 5 calendar days
MIN_VOTE_HOLD_BARS = 10                # a decision held < 10 bars does not vote
MIN_SUPPORT = 2                        # "supported": >= 2 voters in the alert's direction ...
MIN_SUPPORT_GROUPS = 2                 # ... from >= 2 roster groups (playground = one group) ...
MAX_OPPOSE_RATIO = 0.5                 # ... with opposing voters <= half the supporting ones
# "vetoed": strictly more than half of the voting voters in the opposite direction.

# ── ledger record of an entry alert (unchanged from the first S8 version) ─
HOLD_BARS = 20
POSITION_USD = 1000.0
CONFIDENCE = 0.6
DEDUPE_DAYS = 14                       # look-back for an identical earlier alert

_TRUE = {"1", "true", "yes", "on"}


def live_enabled(env=os.environ) -> bool:
    raw = env.get(LIVE_ENV)
    return LIVE if raw is None else raw.strip().lower() in _TRUE


def trend_source_name(env=os.environ) -> str:
    return (env.get(TREND_SOURCE_ENV) or TREND_SOURCE).strip()
