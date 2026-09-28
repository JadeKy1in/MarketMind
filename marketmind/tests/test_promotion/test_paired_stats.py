"""HAC (Newey-West) t-test and Holm adjustment used by the variant-trial verdict (S7 §二)."""
from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats

from marketmind.promotion import metrics as M


def test_newey_west_hand_value():
    # d = 1,2,3,4: mean 2.5, x = -1.5,-0.5,0.5,1.5; g0 = 5/4, g1 = 1.25/4
    assert M.newey_west_variance([1, 2, 3, 4], 0) == pytest.approx(1.25)
    assert M.newey_west_variance([1, 2, 3, 4], 1) == pytest.approx(1.25 + 2 * 0.5 * 0.3125)
    # lag clipped to n - 1; g2 = ((0.5)(-1.5) + (1.5)(-0.5)) / 4 = -0.375, g3 = -2.25/4
    lrv3 = 1.25 + 2 * (0.75 * 0.3125 + 0.5 * -0.375 + 0.25 * -0.5625)
    assert M.newey_west_variance([1, 2, 3, 4], 99) == pytest.approx(max(lrv3, 0.0))


def test_hac_t_hand_value():
    out = M.hac_t_test([1, 2, 3, 4], 1)
    se = math.sqrt(1.5625 / 4)
    assert out["se"] == pytest.approx(se) and out["t"] == pytest.approx(2.5 / se)
    assert out["t"] == pytest.approx(4.0)
    assert out["p_value"] == pytest.approx(stats.t.sf(4.0, df=3))
    assert out["lag"] == 1 and out["n"] == 4


def test_hac_lag0_is_the_plain_t_with_population_variance():
    d = np.random.default_rng(0).normal(0.1, 1, 50)
    out = M.hac_t_test(d, 0)
    assert out["t"] == pytest.approx(d.mean() / math.sqrt(d.var() / d.size))


def test_hac_untestable_series():
    assert M.hac_t_test([], 1)["p_value"] is None
    assert M.hac_t_test([0.01], 1)["p_value"] is None
    assert M.hac_t_test([0.01] * 40, 3)["p_value"] is None           # no variation


def _ma(rng, n, q, shift=0.0):
    """MA(q) with equal weights: the kind of overlap a q+1-day hold creates."""
    e = rng.standard_normal(n + q)
    return shift + np.convolve(e, np.ones(q + 1), "valid") / math.sqrt(q + 1)


def test_hac_size_under_overlap_and_power():
    """n = 40. iid null: size ~ 5%. MA(4) null (a 5-day hold's overlap): Newey-West at
    lag 4 is still liberal in a sample this small (~12%, documented in S7_DESIGN) but
    far better than ignoring the overlap; a 0.6 sd mean shift is detected most of the time."""
    rng = np.random.default_rng(42)
    reps, n, q = 2000, 40, 4
    iid = hac = naive = power = 0
    for _ in range(reps):
        iid += M.hac_t_test(rng.standard_normal(n), q)["p_value"] <= 0.05
        d = _ma(rng, n, q)
        hac += M.hac_t_test(d, q)["p_value"] <= 0.05
        naive += M.hac_t_test(d, 0)["p_value"] <= 0.05
        power += M.hac_t_test(_ma(rng, n, q, shift=0.6), q)["p_value"] <= 0.05
    assert 0.03 < iid / reps < 0.08
    assert hac / reps < 0.15
    assert naive / reps > 0.2 and naive / reps > 1.5 * hac / reps
    assert power / reps > 0.5


def test_holm_known_example():
    p = [0.01, 0.04, 0.03, 0.005]
    # sorted 0.005 x4 = 0.02, 0.01 x3 = 0.03, 0.03 x2 = 0.06, 0.04 x1 -> max(0.06, 0.04)
    assert M.holm_adjust(p) == pytest.approx([0.03, 0.06, 0.06, 0.02])
    assert M.holm_adjust([0.03]) == [0.03]
    assert M.holm_adjust([]) == []
    assert M.holm_adjust([0.6, 0.9]) == pytest.approx([1.0, 1.0])
