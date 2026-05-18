"""Tests for flash_triage cluster context integration (Phase G)."""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from marketmind.pipeline.flash_triage import TriageResult, inject_cluster_context


# ── Mock ClusteringResult / EventCluster (event_clusterer.py not yet built) ────

@dataclass
class MockEventCluster:
    cluster_id: int
    title: str
    headlines: list[str] = field(default_factory=list)


@dataclass
class MockClusteringResult:
    clusters: list[MockEventCluster] = field(default_factory=list)
    cross_cluster_causal_chains: list[tuple] = field(default_factory=list)


def _make_result(headline: str = "ECB raises rates by 50bps", **kwargs) -> TriageResult:
    defaults = dict(
        headline=headline,
        source_name="Reuters",
        source_tier=1,
        source_reliability=0.95,
        url="https://example.com/ecb",
        published_at="2026-05-18T10:00:00Z",
        scores={"market_impact": 8, "cross_source_corroboration": 7,
                "contradicts_consensus": 3, "investigative_depth_needed": 6, "urgency": 7},
        classification="macro",
        affected_assets=["EUR/USD"],
        cluster_hints=["eurozone", "monetary_policy"],
    )
    defaults.update(kwargs)
    return TriageResult(**defaults)


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_triage_result_defaults():
    """New fields should have sensible defaults — backward compatible."""
    r = _make_result()
    assert r.cluster_id is None
    assert r.cluster_title == ""
    assert r.causal_links == []


def test_enrich_adds_cluster_id():
    """Headline matching a cluster → cluster_id populated."""
    cluster = MockEventCluster(cluster_id=3, title="ECB Decision", headlines=["ECB raises rates by 50bps"])
    cr = MockClusteringResult(clusters=[cluster])
    results = [_make_result()]

    enriched = inject_cluster_context(results, cr)

    assert enriched[0].cluster_id == 3
    assert enriched[0].cluster_title == "ECB Decision"


def test_enrich_adds_causal_links():
    """Cluster with causal chains → links populated."""
    src = MockEventCluster(cluster_id=3, title="ECB Decision", headlines=["ECB raises rates by 50bps"])
    dst = MockEventCluster(cluster_id=7, title="EUR/USD Movement", headlines=["EUR/USD jumps 1%"])
    cr = MockClusteringResult(
        clusters=[src, dst],
        cross_cluster_causal_chains=[
            (src, dst, "Rate hike strengthens EUR against USD"),
        ],
    )
    results = [_make_result()]

    enriched = inject_cluster_context(results, cr)

    assert len(enriched[0].causal_links) == 1
    assert "ECB Decision (cluster 3)" in enriched[0].causal_links[0]
    assert "EUR/USD Movement (cluster 7)" in enriched[0].causal_links[0]
    assert "Rate hike strengthens EUR against USD" in enriched[0].causal_links[0]


def test_enrich_no_clustering_result():
    """None clustering result → returns unchanged list."""
    results = [_make_result()]

    enriched = inject_cluster_context(results, None)

    assert enriched[0].cluster_id is None
    assert enriched[0].cluster_title == ""
    assert enriched[0].causal_links == []


def test_headline_not_in_any_cluster():
    """Unmatched headline → cluster_id stays None."""
    cluster = MockEventCluster(cluster_id=5, title="Oil Supply Shock", headlines=["OPEC cuts production"])
    cr = MockClusteringResult(clusters=[cluster])
    results = [_make_result(headline="Unrelated tech earnings beat")]

    enriched = inject_cluster_context(results, cr)

    assert enriched[0].cluster_id is None
    assert enriched[0].cluster_title == ""
    assert enriched[0].causal_links == []


def test_empty_clusters_list():
    """Empty clusters list → returns unchanged."""
    cr = MockClusteringResult(clusters=[])
    results = [_make_result()]

    enriched = inject_cluster_context(results, cr)

    assert enriched[0].cluster_id is None


def test_enrich_preserves_original_fields():
    """Cluster enrichment does not modify non-cluster fields."""
    cluster = MockEventCluster(cluster_id=1, title="Test Cluster", headlines=["ECB raises rates by 50bps"])
    cr = MockClusteringResult(clusters=[cluster])
    results = [_make_result()]

    enriched = inject_cluster_context(results, cr)

    r = enriched[0]
    assert r.headline == "ECB raises rates by 50bps"
    assert r.source_name == "Reuters"
    assert r.source_tier == 1
    assert r.scores["market_impact"] == 8
    assert r.classification == "macro"
    assert r.affected_assets == ["EUR/USD"]
