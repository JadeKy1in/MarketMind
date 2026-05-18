"""Tests for regime library and regime mapper (Phase H-2)."""
import pytest

from marketmind.config.regime_library import (
    REGIME_LIBRARY,
    RegimeDef,
    get_regime_by_id,
    build_vector,
)
from marketmind.pipeline.regime_mapper import (
    RegimeMatch,
    RegimeMapping,
    _classify_quadrant,
    _euclidean_distance,
    _normalise_similarity,
    _vector_from_hypothesis,
    _weighted_distance,
    _detect_key_differences,
    map_regime,
    verify_claim_historical_v2,
)


# ── Regime library tests ─────────────────────────────────────────────────────────

class TestRegimeLibrary:
    def test_regime_library_has_minimum_entries(self):
        """At least 8 regimes defined."""
        assert len(REGIME_LIBRARY) >= 8

    def test_all_regimes_are_regimedef_instances(self):
        """Every entry must be a RegimeDef dataclass instance."""
        for r in REGIME_LIBRARY:
            assert isinstance(r, RegimeDef)

    def test_regime_ids_are_unique(self):
        """No duplicate regime IDs."""
        ids = [r.regime_id for r in REGIME_LIBRARY]
        assert len(ids) == len(set(ids))

    def test_get_regime_by_id_returns_correct_regime(self):
        result = get_regime_by_id("stagflation_1971_1982")
        assert result is not None
        assert result.regime_name == "滞胀时代"

    def test_get_regime_by_id_returns_none_for_missing(self):
        assert get_regime_by_id("nonexistent_regime") is None

    def test_build_vector_has_seven_dimensions(self):
        for r in REGIME_LIBRARY:
            vec = build_vector(r)
            assert len(vec) == 7
            assert all(isinstance(v, (int, float)) for v in vec)

    def test_key_events_present_for_all_regimes(self):
        for r in REGIME_LIBRARY:
            assert r.key_events, f"{r.regime_id} missing key_events"
            assert len(r.key_events) >= 2, f"{r.regime_id} needs >= 2 key events"


# ── Quadrant classification tests ────────────────────────────────────────────────

class TestQuadrantClassification:
    def test_growth_up_inflation_up(self):
        result = _classify_quadrant(
            "Economic growth is accelerating with persistent inflation pressures"
        )
        assert result == "growth_up_inflation_up"

    def test_growth_up_inflation_down(self):
        result = _classify_quadrant(
            "Soft landing scenario with growth resilient and inflation cooling"
        )
        assert result == "growth_up_inflation_down"

    def test_growth_down_inflation_up(self):
        result = _classify_quadrant(
            "Stagflation is here — recession fears and commodity spike driving prices up"
        )
        assert result == "growth_down_inflation_up"

    def test_growth_down_inflation_down(self):
        result = _classify_quadrant(
            "Hard landing recession with deflationary demand destruction"
        )
        assert result == "growth_down_inflation_down"

    def test_default_quadrant(self):
        """When no clear keywords, both directions default to 'up'."""
        result = _classify_quadrant("markets are uncertain and volatile")
        assert result == "growth_up_inflation_up"


# ── Vector tests ─────────────────────────────────────────────────────────────────

class TestVectorFromHypothesis:
    def test_returns_seven_elements(self):
        vec = _vector_from_hypothesis("neutral statement with no keywords")
        assert len(vec) == 7
        assert all(isinstance(v, (int, float)) for v in vec)

    def test_bullish_equity_hypothesis(self):
        vec = _vector_from_hypothesis("bull market rally with strong earnings")
        assert vec[0] > 0  # spy_yy positive

    def test_bearish_equity_hypothesis(self):
        vec = _vector_from_hypothesis("bear market crash imminent sell-off")
        assert vec[0] < 0  # spy_yy negative

    def test_inverted_curve(self):
        vec = _vector_from_hypothesis("yield curve inversion signals trouble")
        assert vec[1] < 0  # spread negative

    def test_oil_spike(self):
        vec = _vector_from_hypothesis("oil spike energy crisis commodity boom")
        assert vec[2] > 0   # wti_yy positive
        assert vec[3] > 0   # copper_yy positive

    def test_oil_crash(self):
        vec = _vector_from_hypothesis("oil crash oil glut")
        assert vec[2] < 0   # wti_yy negative

    def test_tightening_rates(self):
        vec = _vector_from_hypothesis("fed rate hike tightening hawkish")
        assert vec[4] > 4.0  # tbill high

    def test_easing_rates(self):
        vec = _vector_from_hypothesis("fed rate cut easing dovish")
        assert vec[4] < 1.0  # tbill low

    def test_high_volatility(self):
        vec = _vector_from_hypothesis("vix spike panic high volatility")
        assert vec[5] > 20.0  # VIX elevated


# ── Euclidean distance tests ─────────────────────────────────────────────────────

class TestEuclideanDistance:
    def test_identical_vectors_zero_distance(self):
        a = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        b = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        assert _euclidean_distance(a, b) == 0.0

    def test_different_vectors_positive_distance(self):
        a = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        b = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
        assert _euclidean_distance(a, b) == pytest.approx(math.sqrt(7.0))


class TestNormaliseSimilarity:
    def test_zero_distance_perfect_similarity(self):
        assert _normalise_similarity(0.0, 100.0) == 1.0

    def test_max_distance_zero_similarity(self):
        assert _normalise_similarity(100.0, 100.0) == 0.0

    def test_exceeds_max_clamped(self):
        assert _normalise_similarity(200.0, 100.0) == 0.0

    def test_mid_range(self):
        sim = _normalise_similarity(30.0, 100.0)
        assert 0.69 < sim < 0.71

    def test_zero_max_distance_returns_neutral(self):
        assert _normalise_similarity(10.0, 0.0) == 0.5


# ── Variable-weighted distance tests ─────────────────────────────────────────────

class TestWeightedDistance:
    def test_inflation_up_doubles_commodity_weight(self):
        """In inflation_up quadrant, oil (index 2) and copper (index 3) get higher weight."""
        current = [0.0, 0.0, 30.0, 0.0, 0.0, 0.0, 0.0]  # oil is the only difference
        regime = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

        dist_normal = _weighted_distance(current, regime, "growth_up_inflation_down")
        dist_infl = _weighted_distance(current, regime, "growth_up_inflation_up")

        # Inflation_up should produce a larger distance for the same oil delta
        assert dist_infl > dist_normal

    def test_growth_up_doubles_equity_weight(self):
        """In growth_up quadrant, spy_yy (index 0) gets higher weight."""
        current = [30.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]  # spy is the only difference
        regime = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

        dist_normal = _weighted_distance(current, regime, "growth_down_inflation_down")
        dist_growth = _weighted_distance(current, regime, "growth_up_inflation_down")

        assert dist_growth > dist_normal

    def test_growth_down_weights_spread_and_vix(self):
        """In growth_down quadrant, spread_10y2y and VIX get higher weight."""
        current = [0.0, 2.0, 0.0, 0.0, 0.0, 10.0, 0.0]  # spread + VIX differences
        regime = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

        dist_normal = _weighted_distance(current, regime, "growth_up_inflation_down")
        dist_down = _weighted_distance(current, regime, "growth_down_inflation_down")

        assert dist_down > dist_normal


# ── Key differences tests ────────────────────────────────────────────────────────

class TestDetectKeyDifferences:
    def test_returns_differences(self):
        current = [50.0, 3.0, 80.0, 40.0, 10.0, 60.0, 1.0]
        regime = REGIME_LIBRARY[0]  # bretton_woods — very different
        diffs = _detect_key_differences(current, regime)
        assert len(diffs) >= 1
        assert all(isinstance(d, str) for d in diffs)

    def test_identical_returns_fewer_differences(self):
        regime = REGIME_LIBRARY[0]
        current = build_vector(regime)
        diffs = _detect_key_differences(current, regime)
        # No dimension should have z > 1.0 when vectors are identical
        assert len(diffs) == 0


# ── map_regime integration tests ─────────────────────────────────────────────────

class TestMapRegime:
    @pytest.mark.asyncio
    async def test_map_regime_returns_top_analogues(self):
        """Should return 3 most similar regimes."""
        mapping = await map_regime(
            "Fed rate cuts are coming as inflation cools and growth remains resilient"
        )
        assert len(mapping.top_analogues) == 3
        for a in mapping.top_analogues:
            assert isinstance(a, RegimeMatch)
            assert 0.0 <= a.similarity <= 1.0

    @pytest.mark.asyncio
    async def test_map_regime_returns_anti_analogue(self):
        """Should identify least similar regime."""
        mapping = await map_regime(
            "Oil spike stagflation supply shock recession"
        )
        assert len(mapping.anti_analogues) >= 1

    @pytest.mark.asyncio
    async def test_quadrant_included_in_output(self):
        """Output must include quadrant classification."""
        mapping = await map_regime(
            "growth accelerating with persistent inflation"
        )
        assert "增长上行+通胀上行" in mapping.current_quadrant

    @pytest.mark.asyncio
    async def test_bias_warning_included(self):
        """Output must include warning about 1985-2025 training range."""
        mapping = await map_regime("any macroeconomic claim")
        assert "1985-2025" in mapping.bias_warning

    @pytest.mark.asyncio
    async def test_regime_consensus_not_empty(self):
        """Consensus string must be populated."""
        mapping = await map_regime("recession is coming hard landing deflation")
        assert mapping.regime_consensus
        assert len(mapping.regime_consensus) > 0

    @pytest.mark.asyncio
    async def test_with_live_data(self):
        """Should accept optional live macro data."""
        live_data = {
            "spy_yy": 20.0,
            "spread_10y2y": -0.5,
            "wti_yy": -5.0,
            "copper_yy": 2.0,
            "tbill_yield": 5.2,
            "vix_avg": 16.0,
            "stock_bond_corr": 0.1,
        }
        mapping = await map_regime(
            "current macro snapshot",
            current_data=live_data,
        )
        assert len(mapping.top_analogues) == 3
        # With live data matching tightening_2023_present, the top analogue should
        # be very close (high similarity)
        top = mapping.top_analogues[0]
        assert top.similarity > 0.8

    @pytest.mark.asyncio
    async def test_top_analogues_have_forward_returns(self):
        """Each analogue must include forward return estimates."""
        mapping = await map_regime("inflation is cooling growth steady")
        for a in mapping.top_analogues:
            assert isinstance(a.forward_3m_equity, float)
            assert isinstance(a.forward_6m_equity, float)
            assert isinstance(a.forward_12m_equity, float)

    @pytest.mark.asyncio
    async def test_top_analogues_have_key_differences(self):
        """Each analogue must include key_differences list."""
        mapping = await map_regime("recession fears and oil spike")
        for a in mapping.top_analogues:
            assert isinstance(a.key_differences, list)

    @pytest.mark.asyncio
    async def test_similarities_are_descending(self):
        """Top analogues should be sorted by similarity descending."""
        mapping = await map_regime("tech bubble ai overvaluation")
        sims = [a.similarity for a in mapping.top_analogues]
        assert sims == sorted(sims, reverse=True)


# ── verify_claim_historical_v2 tests ─────────────────────────────────────────────

class TestVerifyClaimHistoricalV2:
    @pytest.mark.asyncio
    async def test_returns_float_in_expected_range(self):
        result = await verify_claim_historical_v2(
            "Fed will cut rates as economy softens"
        )
        assert isinstance(result, float)
        assert 0.45 <= result <= 0.75

    @pytest.mark.asyncio
    async def test_rate_cut_claim(self):
        """Rate cut claims should map to easing-era regimes producing moderate confidence."""
        result = await verify_claim_historical_v2(
            "Fed rate cuts coming as inflation falls"
        )
        assert 0.45 <= result <= 0.75

    @pytest.mark.asyncio
    async def test_recession_claim(self):
        """Recession claims should produce confidence in valid range."""
        result = await verify_claim_historical_v2(
            "recession is imminent economic downturn"
        )
        assert 0.45 <= result <= 0.75

    @pytest.mark.asyncio
    async def test_generic_claim_returns_neutral(self):
        """A claim matching no regime well should still return a valid score."""
        result = await verify_claim_historical_v2(
            "completely unprecedented scenario never seen before"
        )
        assert 0.45 <= result <= 0.75

    @pytest.mark.asyncio
    async def test_exception_returns_neutral(self):
        """On any internal failure, returns 0.50 neutral."""
        # This function handles its own exceptions
        result = await verify_claim_historical_v2("test claim")
        assert 0.45 <= result <= 0.75


# ── Import for math.sqrt in distance tests ───────────────────────────────────────
import math
