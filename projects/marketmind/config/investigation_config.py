"""Heuristic investigation configuration — budgets, thresholds, and limits."""

# ── Token budgets ─────────────────────────────────────────────────
MAX_TOKENS_PER_SESSION = 150_000      # Hard ceiling
WARNING_THRESHOLD = 0.80              # 80% = 120K tokens → start pruning low-score headlines
FLASH_TRIAGE_BATCH_SIZE = 100         # Headlines per Flash triage call (100 tokens/headline)
PRO_BROWSE_HEADLINES_MAX = 20         # Max headlines Pro selects for deeper review
PRO_BROWSE_TOKENS_PER_HEADLINE = 500  # Estimated tokens per headline during browse phase

# ── HVR loop limits ───────────────────────────────────────────────
MAX_HYPOTHESES_PER_SESSION = 5        # Max investigation threads per session
MAX_DEEPENING_STEPS_PER_THREAD = 3    # Max verification rounds per hypothesis
MAX_API_CALLS_PER_THREAD = 5          # Max tool calls per hypothesis
DIMINISHING_RETURNS_THRESHOLD = 0.05  # Stop deepening if confidence gain < 5% per step

# ── Flash triage scoring ──────────────────────────────────────────
MIN_IMPACT_SCORE_FOR_BROWSE = 6       # Pro only sees headlines with impact >= 6
MIN_CORROBORATION_FOR_HIGH_CONF = 3   # Need 3+ independent sources for high corroboration

# ── Confidence scoring weights (4-layer verification) ─────────────
WEIGHT_MARKET_PRICING = 0.30          # Futures, options, prices — market votes with money
WEIGHT_FUNDAMENTAL_DATA = 0.25        # FRED, EIA, BLS — official statistics
WEIGHT_MULTI_SOURCE = 0.25            # 3+ independent news sources
WEIGHT_HISTORICAL_PATTERN = 0.20      # Similar past scenarios

CONFIDENCE_ACTION_THRESHOLD = 0.70    # confidence >= 0.70 → can form investment recommendation
CONFIDENCE_WATCH_THRESHOLD = 0.40     # 0.40-0.70 → mark as "needs monitoring"
                                      # < 0.40 → discard hypothesis

# ── Adversarial self-check ────────────────────────────────────────
ADVERSARIAL_BEAR_CASE_REQUIRED = True # Always generate bear case before final conclusion
BEAR_CASE_CONFIDENCE_DISCOUNT = 0.60  # If bear case confidence > 60% of bull case → mark "high contention"

# ── Expectation gap analysis ──────────────────────────────────────
EXPECTATION_GAP_THRESHOLD = 0.15      # |actual - expected| must exceed 15% for trade value
                                      # Below threshold → mark "priced_in", skip deep verification
