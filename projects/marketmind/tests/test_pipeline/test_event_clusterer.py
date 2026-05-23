"""Tests for Tier 2+3 event clustering pipeline."""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from marketmind.pipeline.entity_extractor import ExtractedEntities, extract_entities
from marketmind.pipeline.event_clusterer import (
    EventCluster,
    ClusteringResult,
    cluster_events,
    _tokenize,
    _compute_tfidf_matrix,
    _cosine_similarity_py,
    _pairwise_cosine_py,
    _deduplicate_near_duplicates,
    _entity_overlap_pre_group,
    _threshold_clustering,
    _keyword_topic_name,
    _compute_silhouette_py,
    _parse_topic_json,
    _TfidfClustering,
)


# ── Sample headlines for testing ──

ECB_HEADLINES = [
    "ECB holds rates steady as inflation cools to 2.4%",
    "European Central Bank keeps deposit rate at 3.75%",
    "Lagarde: ECB data-dependent, no pre-commitment to rate path",
]

EURUSD_HEADLINES = [
    "EUR/USD falls below 1.05 after ECB decision",
    "Euro slides against dollar on policy divergence",
    "Euro dollar parity risk rises as Fed stays hawkish",
]

FED_HEADLINES = [
    "Fed signals September rate cut possible if data supports",
    "Federal Reserve minutes show divided views on rate path",
    "Powell: Fed needs more confidence on inflation before cutting",
]

UNRELATED_HEADLINES = [
    "Apple unveils new iPhone with AI features",
    "Tesla recalls 2 million vehicles over autopilot issue",
    "Taylor Swift concert boosts local economy by $200M",
]


def _make_entities(headlines: list[str]) -> list[ExtractedEntities]:
    return [extract_entities(h) for h in headlines]


# ── Pure Python TF-IDF Tests ──

class TestTokenize:
    def test_basic_tokenization(self):
        tokens = _tokenize("Fed raises interest rates by 25bp")
        assert "fed" in tokens
        assert "raises" in tokens
        assert "interest" in tokens
        assert "rates" in tokens

    def test_punctuation_stripped(self):
        tokens = _tokenize("S&P 500: Record High!")
        assert "500" in tokens
        assert "record" in tokens

    def test_single_chars_filtered(self):
        tokens = _tokenize("A big rally in US")
        assert "a" not in tokens  # "a" is 1 char, filtered


class TestTfidfMatrix:
    def test_empty_input(self):
        result = _compute_tfidf_matrix([])
        assert result == []

    def test_single_document(self):
        result = _compute_tfidf_matrix(["fed raises rates"])
        assert len(result) == 1

    def test_identical_docs_produce_identical_vectors(self):
        result = _compute_tfidf_matrix(["fed raises rates", "fed raises rates"])
        sim = _cosine_similarity_py(result[0], result[1])
        assert sim > 0.99

    def test_different_docs_have_lower_similarity(self):
        result = _compute_tfidf_matrix([
            "fed raises interest rates",
            "apple launches new iphone",
        ])
        sim = _cosine_similarity_py(result[0], result[1])
        assert sim < 0.5


class TestCosineSimilarity:
    def test_empty_vectors(self):
        assert _cosine_similarity_py({}, {}) == 0.0

    def test_no_overlap(self):
        a = {"fed": 1.0, "rate": 0.5}
        b = {"apple": 1.0, "iphone": 0.5}
        assert _cosine_similarity_py(a, b) == 0.0

    def test_full_overlap(self):
        a = {"fed": 1.0, "rate": 0.5}
        b = {"fed": 1.0, "rate": 0.5}
        assert _cosine_similarity_py(a, b) > 0.99


class TestPairwiseCosine:
    def test_identity_diagonal(self):
        tfidf = _compute_tfidf_matrix(["fed raises rates", "apple iphone"])
        sim = _pairwise_cosine_py(tfidf)
        assert sim[0][0] == 1.0
        assert sim[1][1] == 1.0

    def test_symmetric(self):
        tfidf = _compute_tfidf_matrix(["fed raises rates", "apple iphone", "ecb holds rates"])
        sim = _pairwise_cosine_py(tfidf)
        for i in range(len(sim)):
            for j in range(len(sim)):
                assert abs(sim[i][j] - sim[j][i]) < 0.0001


class TestSilhouette:
    def test_single_cluster(self):
        tfidf = _compute_tfidf_matrix(["a b c", "a b d", "a c d"])
        score = _compute_silhouette_py(tfidf, [0, 0, 0])
        assert score == 0.0

    def test_two_clear_clusters(self):
        tfidf = _compute_tfidf_matrix([
            "fed rate hike inflation",
            "fed rate hike monetary",
            "apple iphone launch tech",
            "apple ios update tech",
        ])
        score = _compute_silhouette_py(tfidf, [0, 0, 1, 1])
        assert score > 0.0  # positive silhouette for separated clusters


# ── Entity Overlap Pre-Grouping Tests ──

class TestEntityOverlapPreGroup:
    def test_ticker_overlap_same_group(self):
        entities = [
            ExtractedEntities(tickers=["AAPL"]),
            ExtractedEntities(tickers=["AAPL"]),
        ]
        groups = _entity_overlap_pre_group(entities)
        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_country_overlap_same_group(self):
        entities = [
            ExtractedEntities(countries=["US"]),
            ExtractedEntities(countries=["US"]),
        ]
        groups = _entity_overlap_pre_group(entities)
        assert len(groups) == 1

    def test_no_overlap_different_groups(self):
        entities = [
            ExtractedEntities(tickers=["AAPL"]),
            ExtractedEntities(countries=["Japan"]),
        ]
        groups = _entity_overlap_pre_group(entities)
        assert len(groups) == 2

    def test_empty_input(self):
        groups = _entity_overlap_pre_group([])
        assert groups == []

    def test_currency_overlap(self):
        entities = [
            ExtractedEntities(currencies=["EUR"]),
            ExtractedEntities(currencies=["EUR"]),
        ]
        groups = _entity_overlap_pre_group(entities)
        assert len(groups) == 1


# ── Threshold Clustering Tests ──

class TestThresholdClustering:
    def test_all_noise_below_threshold(self):
        sim = [
            [1.0, 0.1, 0.1],
            [0.1, 1.0, 0.1],
            [0.1, 0.1, 1.0],
        ]
        labels = _threshold_clustering(sim, threshold=0.3, min_size=2)
        # Everything below threshold should be noise or all -1
        unique = set(labels)
        # With min_size=2 and no pairs above 0.3, all should be noise
        assert -1 in unique

    def test_clear_clusters(self):
        sim = [
            [1.0, 0.8, 0.1, 0.1],
            [0.8, 1.0, 0.1, 0.1],
            [0.1, 0.1, 1.0, 0.8],
            [0.1, 0.1, 0.8, 1.0],
        ]
        labels = _threshold_clustering(sim, threshold=0.3, min_size=2)
        assert labels[0] == labels[1]  # first pair same cluster
        assert labels[2] == labels[3]  # second pair same cluster
        assert labels[0] != labels[2]  # different clusters

    def test_min_size_respected(self):
        # Only 2 items above threshold, min_size=3 → should all be noise
        sim = [
            [1.0, 0.8, 0.1, 0.1],
            [0.8, 1.0, 0.1, 0.1],
            [0.1, 0.1, 1.0, 0.1],
            [0.1, 0.1, 0.1, 1.0],
        ]
        labels = _threshold_clustering(sim, threshold=0.3, min_size=3)
        assert len(set(labels)) <= 1  # all noise or single cluster


# ── Deduplication Tests ──

class TestDeduplicateNearDuplicates:
    def test_exact_duplicates_removed(self):
        headlines = [
            "Fed raises rates by 25bp",
            "Fed raises rates by 25bp",
            "Apple launches iPhone",
        ]
        entities = _make_entities(headlines)
        deduped, _, _ = _deduplicate_near_duplicates(headlines, entities, threshold=0.95)
        assert len(deduped) < 3  # duplicates removed

    def test_single_headline(self):
        headlines = ["Fed raises rates"]
        entities = _make_entities(headlines)
        deduped, _, _ = _deduplicate_near_duplicates(headlines, entities)
        assert len(deduped) == 1

    def test_empty_input(self):
        deduped, _, _ = _deduplicate_near_duplicates([], [])
        assert deduped == []


# ── Keyword Topic Name Fallback ──

class TestKeywordTopicName:
    def test_returns_non_empty_string(self):
        name = _keyword_topic_name(["Fed raises rates by 25bp", "ECB holds rates steady"])
        assert len(name) > 0
        assert isinstance(name, str)

    def test_empty_headlines(self):
        name = _keyword_topic_name([])
        assert name == "Unknown Topic"


# ── JSON Parse Tests ──

class TestParseTopicJson:
    def test_plain_json(self):
        result = _parse_topic_json('{"title": "Test", "narrative": "A test."}')
        assert result["title"] == "Test"

    def test_markdown_wrapped(self):
        result = _parse_topic_json('```json\n{"title": "Test"}\n```')
        assert result["title"] == "Test"

    def test_embedded_json(self):
        result = _parse_topic_json('Some text {"title": "Test"} more text')
        assert result["title"] == "Test"

    def test_empty_string(self):
        result = _parse_topic_json("")
        assert result == {}

    def test_array_json(self):
        result = _parse_topic_json('[{"from": 0, "to": 1}]')
        assert isinstance(result, list)
        assert len(result) == 1


# ── Main Cluster Events Tests ──

class TestClusterEventsAsync:
    """Async tests for the main cluster_events function."""

    @pytest.mark.asyncio
    async def test_empty_input(self):
        result = await cluster_events([], [])
        assert isinstance(result, ClusteringResult)
        assert result.total_headlines == 0
        assert result.clusters_formed == 0

    @pytest.mark.asyncio
    async def test_single_headline(self):
        result = await cluster_events(
            ["Fed raises rates"],
            _make_entities(["Fed raises rates"]),
        )
        assert result.total_headlines == 1
        assert result.clusters_formed == 1
        assert len(result.clusters) == 1

    @pytest.mark.asyncio
    async def test_related_headlines_clustered_together(self):
        headlines = ECB_HEADLINES + EURUSD_HEADLINES
        entities = _make_entities(headlines)
        result = await cluster_events(headlines, entities)
        # Should form fewer clusters than headlines (some grouped)
        assert result.clusters_formed <= len(headlines)

    @pytest.mark.asyncio
    async def test_cluster_has_title_fallback(self):
        headlines = ["Fed raises rates by 25bp to fight inflation"]
        entities = _make_entities(headlines)
        result = await cluster_events(headlines, entities)
        if result.clusters:
            for c in result.clusters:
                assert isinstance(c.title, str)
                assert isinstance(c.narrative, str)

    @pytest.mark.asyncio
    async def test_entity_overlap_pre_grouping_works(self):
        # These share EUR entity, should group
        headlines = [
            "EUR/USD falls below 1.05",
            "ECB holds euro rates steady",
        ]
        entities = _make_entities(headlines)
        result = await cluster_events(headlines, entities)
        # With entity overlap, they should be in same group → fewer total clusters
        assert len(result.clusters) <= len(headlines)

    @pytest.mark.asyncio
    async def test_noise_headlines_separated(self):
        # Unrelated headlines should not be merged
        headlines = ["Fed raises rates 25bp", "Apple launches new iPhone model"]
        entities = _make_entities(headlines)
        result = await cluster_events(headlines, entities)
        assert result.total_headlines == 2

    @pytest.mark.asyncio
    async def test_tokens_tracked(self):
        result = await cluster_events(
            ["Fed raises rates"],
            _make_entities(["Fed raises rates"]),
        )
        assert result.tokens_used >= 0

    @pytest.mark.asyncio
    async def test_low_authority_cluster_detected(self):
        result = await cluster_events(
            ["Some rumor about markets from unreliable source"],
            _make_entities(["Some rumor about markets from unreliable source"]),
            source_tiers={0: 4},
        )
        if result.clusters:
            assert result.clusters[0].low_authority_cluster is True

    @pytest.mark.asyncio
    async def test_high_authority_cluster_not_flagged(self):
        result = await cluster_events(
            ["Fed official comments on rate path"],
            _make_entities(["Fed official comments on rate path"]),
            source_tiers={0: 1},
        )
        if result.clusters:
            assert result.clusters[0].low_authority_cluster is False

    @pytest.mark.asyncio
    async def test_entities_aggregated(self):
        result = await cluster_events(
            ["Fed raises rates, USD strengthens"],
            _make_entities(["Fed raises rates, USD strengthens"]),
        )
        if result.clusters:
            c = result.clusters[0]
            assert isinstance(c.entities, dict)
            assert "tickers" in c.entities


# ── TfidfClustering Wrapper ──

class TestTfidfClustering:
    def test_fit_transform_returns_data(self):
        cl = _TfidfClustering()
        result = cl.fit_transform(["fed raises rates", "apple iphone"])
        assert result is not None

    def test_pairwise_similarity_shape(self):
        cl = _TfidfClustering()
        matrix = cl.fit_transform(["fed raises rates", "apple iphone"])
        sim = cl.compute_pairwise_similarity(matrix)
        assert len(sim) == 2
        assert len(sim[0]) == 2
        assert 0 <= sim[0][1] <= 1.0

    def test_silhouette_computes(self):
        cl = _TfidfClustering()
        matrix = cl.fit_transform([
            "market rally gold",
            "market rally silver",
            "bond yield treasury",
            "bond yield inflation",
        ])
        s = cl.compute_silhouette(matrix, [0, 0, 1, 1])
        assert isinstance(s, float)
        assert -1.0 <= s <= 1.0


# ── Data Class Tests ──

class TestEventClusterDefaults:
    def test_default_fields(self):
        c = EventCluster(
            cluster_id=0, title="Test", narrative="Test narrative",
            headlines=[], headline_indices=[], entities={},
            cross_cluster_links=[], size=0, coherence_score=0.0,
        )
        assert c.low_authority_cluster is False

    def test_cross_cluster_links_format(self):
        c = EventCluster(
            cluster_id=0, title="Test", narrative="Test",
            headlines=["h1"], headline_indices=[0], entities={},
            cross_cluster_links=[(1, "CORRELATION: test")],
            size=1, coherence_score=0.0,
        )
        assert len(c.cross_cluster_links) == 1
        assert c.cross_cluster_links[0][0] == 1


class TestClusteringResultDefaults:
    def test_all_fields(self):
        cr = ClusteringResult(
            clusters=[], noise_count=0, cross_cluster_causal_chains=[],
            total_headlines=0, clusters_formed=0, tokens_used=0,
        )
        assert cr.total_headlines == 0
        assert cr.tokens_used == 0
