"""Thresholds of the shadow-ecosystem health monitor (docs/ECOSYSTEM_DESIGN.md).

The deleted legacy detectors (collusion / concentration / plateau / zombie /
diversity / ecosystem_health) never ran on real data; the values below are
re-derived for the v3 ledger and the rationale of each is in the design doc §3.
Monitoring only: nothing here changes decisions, promotions or alerts.
"""
from __future__ import annotations

# ── Population ──────────────────────────────────────────────────────────
SOURCE_TYPES = ("shadow", "temp_shadow", "playground")
# Code-driven rows that are not an independent decision maker (always long, chosen by
# the main pipeline) - left out of every check except integrity.
NON_ACTOR_PREFIXES = ("missed_path:",)
# Variants re-run their parent's context: counted for correlation (flagged "expected")
# but not as extra votes in the herding check.
NON_VOTER_PREFIXES = ("trial:",)
FULL_RUN_SHARE = 0.5         # a run day is "full" when >= this share of active long-term
                             # shadows submitted (weekend crypto-only runs are not)
LOOKBACK_RUN_DAYS = 60       # full run days kept in the time series

# ── 1. Herding / direction concentration ───────────────────────────────
HERDING_SHARE = 0.80         # share of a group's voters on one direction (legacy 80%)
HERDING_DAYS = 3             # ... on this many consecutive full run days (legacy 3)
HERDING_MIN_VOTERS = 4       # 4/4 is the smallest vote that can reach 80%
HERDING_MAX_JOINT_P = 0.01   # product of the daily two-sided binomial p over the streak
HERDING_ESCALATE_DAYS = 10   # legacy "institutional analysis" escalation, report only

# ── 2. Output correlation / diversity ──────────────────────────────────
NOTIONAL_USD = 10_000.0      # same daily-return convention as the promotion ladder
DUP_CORR = 0.80              # near-duplicate: rho >= this ...
DUP_MIN_DAYS = 20            # ... over at least this many common days
DIRECTION_DUP_COS = 0.80     # direction vectors: cosine >= this ...
DIRECTION_DUP_MIN_CELLS = 20  # ... over at least this many (day, group) cells both traded
DIRECTION_MIN_DAYS = 20      # common full run days for a pair to enter direction N_eff

# ── 3. Source homogenisation ────────────────────────────────────────────
HOMOGEN_WINDOW_DAYS = 20     # full run days
HOMOGEN_SHARE = 0.50         # legacy "BlackRock" warning: >= 50% share one dominant input

# ── 4. Stagnation / plateau ─────────────────────────────────────────────
PLATEAU_DAYS = 20            # an actor's last 20 decision days, split 10 / 10
PLATEAU_JACCARD = 0.80       # ticker sets of the two halves overlap at least this much
PLATEAU_CONF_SHIFT = 0.02    # |mean confidence(first half) - mean(second half)| <= this
PLATEAU_CONF_STD = 0.03      # and confidence std over the window <= this
REPETITION_SHARE = 0.80      # > this share of decisions are one ticker + direction
REPETITION_MIN_DAYS = 10     # decision days needed for the repetition check

# ── 5. Zombies / integrity ──────────────────────────────────────────────
ZOMBIE_RUN_DAYS = 3          # active roster entry silent on this many trailing full run days
KNOWN_TEMP_PREFIXES = ("temp_event:", "trial:", "missed_path:")

# ── 6. Whole-ecosystem degradation trend ────────────────────────────────
BEAT_WINDOW_DAYS = 20        # rolling window of trading days (exit dates)
BEAT_MIN_TRADES = 5          # settled trades of the shadow AND of its random baseline in the window
BEAT_MIN_ELIGIBLE = 5        # shadows needed for a point of the share series
BEAT_STEP_DAYS = 5           # one point every 5 trading days (less window overlap)
MK_MIN_POINTS = 10           # Mann-Kendall needs this many points
MK_ALPHA = 0.05


def thresholds() -> dict:
    """Every threshold above, for the report file and the dashboard."""
    return {k: v for k, v in globals().items() if k.isupper()}
