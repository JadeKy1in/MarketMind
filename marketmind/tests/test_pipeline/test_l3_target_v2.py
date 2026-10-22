"""Counterfactual L3 target_v2 (pipeline/l3_indicators.alt_target; owner decision 2026-10-22).
The live target / light / R/R / recommendation must not change."""
import pytest

from marketmind.pipeline import l3_indicators as L
from marketmind.pipeline.l3_indicators import alt_target, compute_snapshot, swing_highs, swing_lows
from marketmind.pipeline.layer3_technical import from_snapshot
from marketmind.tests.test_pipeline.test_l3_indicators import make_history, uptrend

# close 100, ATR 2, stop 96 (risk 4): R/R 1.5 needs a target >= 106; cap = 100 + 6 * 2 = 112


def test_long_nearest_already_good_is_the_live_target():
    assert alt_target(100, 96, 2, [107, 110]) == (107, 0)


def test_long_steps_to_next_level_while_rr_below_threshold():
    assert alt_target(100, 96, 2, [102, 104, 108, 111]) == (108, 2)   # 0.5, 1.0, then 2.0
    assert alt_target(100, 96, 2, [104, 102, 106]) == (106, 2)        # unsorted input; exactly 1.5


def test_long_levels_too_close_are_not_candidates():
    # 100.5 is within 0.5 ATR of the close (not a target, as in the live rule)
    assert alt_target(100, 96, 2, [100.5, 99, 103]) == (103, 0)


def test_long_cap_ends_the_search():
    assert alt_target(100, 96, 2, [102, 115, 120]) == (112, 1)        # next level beyond the cap
    assert alt_target(100, 96, 2, [130]) == (112, 0)                  # live is the cap too


def test_long_no_further_level_keeps_the_farthest():
    assert alt_target(100, 96, 2, [102, 103]) == (103, 1)             # R/R 0.75: nothing higher
    assert alt_target(100, 96, 2, [102]) == (102, 0)


def test_long_no_level_is_the_cap_like_the_live_rule():
    assert alt_target(100, 96, 2, []) == (112, 0)
    assert alt_target(100, 96, 2, [90, 95]) == (112, 0)               # all below the close


def test_short_mirror_swing_lows_and_floor():
    # close 100, stop 104 (risk 4), floor 100 - 12 = 88; R/R 1.5 needs <= 94
    assert alt_target(100, 104, 2, [98, 96, 93], "short") == (93, 2)
    assert alt_target(100, 104, 2, [93], "short") == (93, 0)
    assert alt_target(100, 104, 2, [98, 80], "short") == (88, 1)      # floor
    assert alt_target(100, 104, 2, [98, 97], "short") == (97, 1)      # no lower level
    assert alt_target(100, 104, 2, [], "short") == (88, 0)
    assert alt_target(100, 104, 2, [101, 103], "short") == (88, 0)    # all above the close


def test_non_positive_risk_returns_the_nearest_level():
    assert alt_target(100, 100, 2, [102, 108]) == (102, 0)


def _bars(closes):
    return make_history(closes, spread=0.0).daily


def test_swing_highs_and_lows_detection():
    # flat 100, a peak at 110 then a drop to 100; a trough at 90 then a rise to 100
    closes = [100.0] * 30 + [105, 110, 105] + [100.0] * 30 + [95, 90, 95] + [100.0] * 30
    bars = _bars(closes)
    a = 1.0
    highs, lows = swing_highs(bars, a), swing_lows(bars, a)
    assert max(highs) == 110 and 90 not in highs   # (flat closes before a drop qualify too)
    assert min(lows) == 90 and 110 not in lows
    assert swing_highs(bars, 10.0) == [] and swing_lows(bars, 10.0) == []   # < 2 * ATR 10


def _two_peak_history():
    """Uptrend to a high peak, drop, rally to a lower peak, drop, recover just under it."""
    closes = uptrend()
    hi = closes[-1] + 30
    seg = []
    seg += [closes[-1] + (hi - closes[-1]) * (i + 1) / 20 for i in range(20)]      # up to hi
    seg += [hi - 1.5 * (i + 1) for i in range(15)]                                  # drop
    lo_peak = hi - 8
    start = seg[-1]
    seg += [start + (lo_peak - start) * (i + 1) / 20 for i in range(20)]           # second peak
    seg += [lo_peak - 1.5 * (i + 1) for i in range(15)]                             # drop
    start = seg[-1]
    seg += [start + (lo_peak * 0.99 - start) * (i + 1) / 40 for i in range(40)]    # recover
    return make_history(closes + seg), hi, lo_peak


def test_snapshot_exposes_v2_and_leaves_live_rule_unchanged():
    hist, hi, lo_peak = _two_peak_history()
    s = compute_snapshot(hist)
    assert s is not None
    risk = s.close - s.stop_loss
    # live rule: nearest swing high (the lower second peak), unchanged
    assert s.target_price == pytest.approx(lo_peak, abs=0.01)
    assert s.reward_risk_ratio == pytest.approx((s.target_price - s.close) / risk, abs=0.01)
    assert s.reward_risk_ratio < L.TARGET_V2_MIN_RR
    # v2: the next (higher) level, still under the cap
    assert s.target_price_v2 == pytest.approx(hi, abs=0.01)
    assert s.target_v2_levels_skipped == 1
    assert s.reward_risk_ratio_v2 == pytest.approx((s.target_price_v2 - s.close) / risk, abs=0.01)
    assert s.target_price_v2 <= s.close + L.TARGET_CAP_ATR * s.atr14 + 0.01
    # the decision text never mentions v2
    r = from_snapshot(s)
    assert "v2" not in r.raw_analysis
    assert r.target_price == s.target_price and r.target_price_v2 == s.target_price_v2
    assert r.reward_risk_ratio_v2 == s.reward_risk_ratio_v2 and r.target_v2_levels_skipped == 1


def test_snapshot_breakout_v2_equals_live_cap():
    s = compute_snapshot(make_history(uptrend()))
    assert s.target_price_v2 == s.target_price
    assert s.reward_risk_ratio_v2 == s.reward_risk_ratio
    assert s.target_v2_levels_skipped == 0
