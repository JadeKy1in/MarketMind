"""Tier 2+3: Embedding-based semantic clustering + Flash topic synthesis."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from marketmind.pipeline.entity_extractor import ExtractedEntities
from marketmind.pipeline.cluster_synthesis import (
    _keyword_topic_name,
    _parse_topic_json,
    _estimate_tokens,
    synthesize_cluster_themes,
)
from marketmind.pipeline.causal_chains import detect_causal_chains

from marketmind.pipeline.tfidf_clustering import (
    _tokenize,
    _compute_tfidf_matrix,
    _cosine_similarity_py,
    _pairwise_cosine_py,
    _compute_silhouette_py,
    _TfidfClustering,
)

logger = logging.getLogger("marketmind.pipeline.event_clusterer")

# ── Data Classes ──

@dataclass
class EventCluster:
    cluster_id: int
    title: str
    narrative: str
    headlines: list[str]
    headline_indices: list[int]
    entities: dict
    cross_cluster_links: list[tuple[int, str]]
    size: int
    coherence_score: float
    low_authority_cluster: bool = False


@dataclass
class ClusteringResult:
    clusters: list[EventCluster]
    noise_count: int
    cross_cluster_causal_chains: list[tuple[EventCluster, EventCluster, str]]
    total_headlines: int
    clusters_formed: int
    tokens_used: int


def _deduplicate_near_duplicates(
    headlines: list[str],
    entities: list[ExtractedEntities],
    threshold: float = 0.95,
) -> tuple[list[str], list[ExtractedEntities], list[int]]:
    """RT-14: Remove near-duplicate headlines (cosine sim > 0.95)."""
    if len(headlines) <= 1:
        return headlines, entities, list(range(len(headlines)))

    clustering = _TfidfClustering()
    matrix = clustering.fit_transform(headlines)
    pairwise = clustering.compute_pairwise_similarity(matrix)

    keep_indices: list[int] = []
    removed = set()
    for i in range(len(headlines)):
        if i in removed:
            continue
        keep_indices.append(i)
        for j in range(i + 1, len(headlines)):
            if j in removed:
                continue
            if pairwise[i][j] >= threshold:
                removed.add(j)

    return (
        [headlines[i] for i in keep_indices],
        [entities[i] for i in keep_indices],
        keep_indices,
    )


def _entity_overlap_pre_group(
    entities: list[ExtractedEntities],
) -> list[list[int]]:
    """Group headline indices by entity overlap (Tier 1 output).

    Two headlines share a group if they share at least one ticker, country,
    sector, or currency. Headlines with no overlap become singletons.
    """
    n = len(entities)
    if n == 0:
        return []

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for i in range(n):
        ei = entities[i]
        i_terms: set[str] = set()
        i_terms.update(ei.tickers)
        i_terms.update(ei.countries)
        i_terms.update(ei.sectors)
        i_terms.update(ei.currencies)
        for j in range(i + 1, n):
            ej = entities[j]
            j_terms: set[str] = set()
            j_terms.update(ej.tickers)
            j_terms.update(ej.countries)
            j_terms.update(ej.sectors)
            j_terms.update(ej.currencies)
            if i_terms & j_terms:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(i)

    return list(groups.values())


def _select_representatives(
    headlines: list[str],
    indices: list[int],
    source_tiers: dict[int, int],
    impact_scores: dict[int, float],
    count: int = 5,
) -> list[str]:
    """RT-13: Select representative headlines by composite score.

    composite_score = source_tier_rank * 0.3 + market_impact * 0.7
    Lower source_tier = better (1=PRIMARY), so rank = (5-tier)/4 normalized to 0-1.
    """
    scored: list[tuple[float, str]] = []
    for idx in indices:
        tier = source_tiers.get(idx, 4)
        if tier <= 0:
            tier = 4
        tier_rank = (5.0 - tier) / 4.0  # 1→1.0, 4→0.25
        impact = impact_scores.get(idx, 5.0) / 10.0  # normalize 0-10 → 0-1
        composite = tier_rank * 0.3 + impact * 0.7
        scored.append((composite, headlines[idx]))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [h for _, h in scored[:count]]


def _check_low_authority(
    indices: list[int],
    source_tiers: dict[int, int],
) -> bool:
    """RT-9: True if cluster contains only tier 3-4 sources (no tier 1-2)."""
    for idx in indices:
        tier = source_tiers.get(idx, 4)
        if tier in (1, 2):
            return False
    return len(indices) > 0


def _aggregate_entities(
    indices: list[int],
    entities_list: list[ExtractedEntities],
) -> dict:
    """Aggregate extracted entities across all headlines in a cluster."""
    result: dict[str, list[str]] = {
        "tickers": [],
        "countries": [],
        "sectors": [],
        "currencies": [],
        "indices": [],
        "central_banks": [],
        "keywords": [],
    }
    seen: dict[str, set] = {k: set() for k in result}
    for i in indices:
        if i >= len(entities_list):
            continue
        e = entities_list[i]
        for field in result:
            values = getattr(e, field, [])
            if not isinstance(values, list):
                values = []
            for v in values:
                if v not in seen[field]:
                    seen[field].add(v)
                    result[field].append(v)
    return result


# ── Main API ──

async def cluster_events(
    headlines: list[str],
    entities: list[ExtractedEntities],
    max_clusters: int = 50,
    source_tiers: dict[int, int] | None = None,
    impact_scores: dict[int, float] | None = None,
) -> ClusteringResult:
    """Cluster headlines into event groups using TF-IDF + cosine similarity.

    Tier 0: Near-duplicate dedup (cosine > 0.95) — RT-14
    Tier 1: Entity overlap pre-grouping
    Tier 2: Within-group TF-IDF cosine similarity clustering
    Tier 3: Flash LLM topic synthesis + cross-cluster detection

    Args:
        headlines: Raw news headlines.
        entities: ExtractedEntities per headline (from entity_extractor).
        max_clusters: Maximum number of clusters to form.
        source_tiers: Optional mapping from headline index to source tier (1-4).
        impact_scores: Optional mapping from headline index to market_impact score (0-10).

    Returns:
        ClusteringResult with clusters, noise count, and token usage.
    """
    if source_tiers is None:
        source_tiers = {}
    if impact_scores is None:
        impact_scores = {}

    tokens_used = 0
    total_headlines = len(headlines)

    if total_headlines == 0:
        return ClusteringResult(
            clusters=[], noise_count=0, cross_cluster_causal_chains=[],
            total_headlines=0, clusters_formed=0, tokens_used=0,
        )

    # Tier 0: Near-duplicate dedup (RT-14)
    deduped_headlines, deduped_entities, keep_indices = _deduplicate_near_duplicates(
        headlines, entities,
    )
    # Remap source_tiers and impact_scores to deduped indices
    deduped_tiers: dict[int, int] = {}
    deduped_impacts: dict[int, float] = {}
    for new_idx, old_idx in enumerate(keep_indices):
        if old_idx in source_tiers:
            deduped_tiers[new_idx] = source_tiers[old_idx]
        if old_idx in impact_scores:
            deduped_impacts[new_idx] = impact_scores[old_idx]

    n = len(deduped_headlines)
    if n <= 1:
        clusters = []
        if n == 1:
            clusters = [_build_single_cluster(
                0, deduped_headlines, [keep_indices[0]], deduped_entities,
                deduped_tiers,
            )]
        return ClusteringResult(
            clusters=clusters, noise_count=0, cross_cluster_causal_chains=[],
            total_headlines=total_headlines, clusters_formed=len(clusters),
            tokens_used=0,
        )

    # Tier 1: Entity overlap pre-grouping
    entity_groups = _entity_overlap_pre_group(deduped_entities)

    # Tier 2: Within-group TF-IDF clustering
    clustering_engine = _TfidfClustering()
    cluster_id = 0
    all_clusters: list[EventCluster] = []
    noise_indices: list[int] = []

    for group_indices in entity_groups:
        if cluster_id >= max_clusters:
            noise_indices.extend(group_indices)
            continue

        group_headlines = [deduped_headlines[i] for i in group_indices]
        group_size = len(group_headlines)

        if group_size <= 2:
            # Small group: treat as single cluster
            all_clusters.append(_build_single_cluster(
                cluster_id, deduped_headlines, group_indices,
                deduped_entities, deduped_tiers,
            ))
            cluster_id += 1
            continue

        try:
            matrix = clustering_engine.fit_transform(group_headlines)
            pairwise_sim = clustering_engine.compute_pairwise_similarity(matrix)

            # RT-11: min_cluster_size = max(3, floor(group_size / 10))
            min_cluster_size = max(3, group_size // 10)
            if min_cluster_size > group_size:
                min_cluster_size = max(2, group_size // 2)

            labels = _threshold_clustering(pairwise_sim, threshold=0.3, min_size=min_cluster_size)

            # Build clusters from labels
            label_to_indices: dict[int, list[int]] = {}
            for local_idx, label in enumerate(labels):
                label_to_indices.setdefault(label, []).append(local_idx)

            for label, local_indices in label_to_indices.items():
                if cluster_id >= max_clusters:
                    noise_indices.extend(group_indices[i] for i in local_indices)
                    continue
                if label < 0:
                    # Noise
                    noise_indices.extend(group_indices[i] for i in local_indices)
                    continue

                all_clusters.append(_build_single_cluster(
                    cluster_id, deduped_headlines,
                    [group_indices[i] for i in local_indices],
                    deduped_entities, deduped_tiers,
                ))
                cluster_id += 1

            # Log silhouette (RT-10)
            labels_to_score = [max(l, 0) for l in labels]  # convert noise (-1) to 0
            sil = clustering_engine.compute_silhouette(matrix, labels_to_score)
            logger.debug("Group silhouette score: %.3f (size=%d)", sil, group_size)

        except Exception as exc:
            logger.warning("Clustering failed for group size %d: %s", group_size, exc)
            noise_indices.extend(group_indices)

    # Tier 3: Flash topic synthesis + cross-cluster detection
    if all_clusters:
        try:
            tokens_spent, all_clusters = await synthesize_cluster_themes(all_clusters)
            tokens_used += tokens_spent
        except Exception as exc:
            logger.warning("Flash topic synthesis failed: %s", exc)
            for cluster in all_clusters:
                if not cluster.title:
                    cluster.title = _keyword_topic_name(cluster.headlines)
                    cluster.narrative = f"Cluster of {cluster.size} related financial news headlines."

        # Cross-cluster causal chains
        causal_chains: list[tuple[EventCluster, EventCluster, str]] = []
        if all_clusters and len(all_clusters) >= 2:
            try:
                tokens_spent_cross, causal_chains = await detect_causal_chains(
                    all_clusters,
                )
                tokens_used += tokens_spent_cross
            except Exception as exc:
                logger.warning("Flash cross-cluster detection failed: %s", exc)
    else:
        causal_chains = []

    return ClusteringResult(
        clusters=all_clusters,
        noise_count=len(noise_indices),
        cross_cluster_causal_chains=causal_chains,
        total_headlines=total_headlines,
        clusters_formed=len(all_clusters),
        tokens_used=tokens_used,
    )


def _threshold_clustering(
    pairwise_sim: list[list[float]],
    threshold: float = 0.3,
    min_size: int = 3,
) -> list[int]:
    """Greedy threshold-based clustering: assign points to nearest cluster center.

    Returns label list where -1 = noise.
    """
    n = len(pairwise_sim)
    labels = [-1] * n
    next_label = 0

    # Find cluster seeds: item with most neighbors above threshold
    unassigned = set(range(n))
    while unassigned:
        # Find the unassigned item with most above-threshold connections to other unassigned
        best_idx = -1
        best_neighbors_count = 0
        for i in unassigned:
            neighbors = sum(1 for j in unassigned if j != i and pairwise_sim[i][j] >= threshold)
            if neighbors > best_neighbors_count:
                best_neighbors_count = neighbors
                best_idx = i

        if best_neighbors_count < min_size - 1:
            break  # Remaining items can't form clusters

        # Form cluster around seed
        cluster_members = [
            j for j in unassigned
            if j == best_idx or pairwise_sim[best_idx][j] >= threshold
        ]
        if len(cluster_members) < min_size:
            break

        for member in cluster_members:
            labels[member] = next_label
            unassigned.discard(member)
        next_label += 1

    return labels


def _build_single_cluster(
    cluster_id: int,
    headlines: list[str],
    indices: list[int],
    entities: list[ExtractedEntities],
    source_tiers: dict[int, int],
) -> EventCluster:
    aggregated = _aggregate_entities(indices, entities)
    low_auth = _check_low_authority(indices, source_tiers)
    return EventCluster(
        cluster_id=cluster_id,
        title="",
        narrative="",
        headlines=[headlines[i] for i in indices],
        headline_indices=list(indices),
        entities=aggregated,
        cross_cluster_links=[],
        size=len(indices),
        coherence_score=0.0,
        low_authority_cluster=low_auth,
    )
