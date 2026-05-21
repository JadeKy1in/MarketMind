"""Per-shadow data source fingerprint for diversity control.

Each shadow maintains a unique data-source weight vector.
DiversityController monitors fingerprint similarity to detect homogenization.

Phase A Module 1 — Data Foundation layer. Zero LLM dependencies.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field

logger = logging.getLogger("marketmind.shadows.data_fingerprint")


@dataclass
class DataFingerprint:
    """A shadow's data source weight vector.

    Attributes:
        shadow_id: Unique shadow identifier (e.g. "expert:gold:gold_bug").
        source_weights: Per-source weight map. Values 0.0-1.0, normalized to sum=1.0.
        primary_sources: Sources with weight >= 0.10 (the shadow's "information diet").
        uniqueness_score: 0.0-1.0, where 1.0 = maximally unique / even weight distribution.
        last_updated: ISO-8601 timestamp of last fingerprint update.
    """
    shadow_id: str
    source_weights: dict[str, float]
    primary_sources: list[str]
    uniqueness_score: float = 1.0
    last_updated: str = ""


class DataFingerprinter:
    """Computes and manages per-shadow data source fingerprints.

    Each shadow's fingerprint is derived from its source weight vector.
    Two shadows with identical weight vectors will have similarity = 1.0.
    A diversity controller can use detect_homogenization() to find shadows
    whose data sources are too similar.

    All methods are static — this is a pure computation class with no state.
    """

    @staticmethod
    def compute_fingerprint(shadow_id: str, source_weights: dict[str, float]) -> DataFingerprint:
        """Create a fingerprint from a source weight vector.

        Normalizes weights to sum to 1.0. Computes a uniqueness score based
        on weight distribution evenness (inverse of a Gini-like concentration metric).
        Identifies primary sources as those with normalized weight >= 0.10.

        Args:
            shadow_id: Unique identifier for the shadow.
            source_weights: Raw source_name -> weight mapping. Weights are
                            normalized internally, so raw values need not sum to 1.0.

        Returns:
            DataFingerprint with normalized weights and computed metadata.

        Raises:
            ValueError: If shadow_id is empty or source_weights is empty.
            ValueError: If any weight is negative.
        """
        if not shadow_id or not isinstance(shadow_id, str):
            raise ValueError(f"shadow_id must be a non-empty string, got {shadow_id!r}")
        if not source_weights or not isinstance(source_weights, dict):
            raise ValueError(f"source_weights must be a non-empty dict, got {type(source_weights).__name__}")

        for src, w in source_weights.items():
            if w < 0:
                raise ValueError(f"Weight for source '{src}' must be >= 0, got {w}")

        total = sum(source_weights.values())
        if total > 0:
            normalized = {k: round(v / total, 4) for k, v in source_weights.items()}
        else:
            # All weights are zero — treat as uniform
            n = len(source_weights)
            normalized = {k: round(1.0 / n, 4) for k in source_weights}

        # Primary sources: weight >= 10% of total
        primary = sorted([k for k, v in normalized.items() if v >= 0.10])

        # Uniqueness: 1 - normalized Gini coefficient (bounded to [0,1])
        # Gini = 0 means perfectly even distribution → uniqueness = 1.0
        # Gini = 1 means one source has all weight → uniqueness = 0.0
        weights = sorted(normalized.values())
        n = len(weights)
        if n == 0:
            uniqueness = 0.0
        elif n == 1:
            uniqueness = 0.0  # single source = no diversity
        else:
            # Gini = (2 * sum(i * w_i) - (n+1) * sum(w_i)) / (n * sum(w_i))
            sum_w = sum(weights)
            if sum_w == 0:
                uniqueness = 0.0
            else:
                weighted_sum = sum((i + 1) * w for i, w in enumerate(weights))
                gini = (2.0 * weighted_sum - (n + 1) * sum_w) / (n * sum_w)
                uniqueness = round(max(0.0, min(1.0, 1.0 - gini)), 4)

        logger.debug("Computed fingerprint for %s: uniqueness=%.4f, primary=%s",
                      shadow_id, uniqueness, primary)
        return DataFingerprint(
            shadow_id=shadow_id,
            source_weights=normalized,
            primary_sources=primary,
            uniqueness_score=uniqueness,
            last_updated="",
        )

    @staticmethod
    def fingerprint_similarity(a: DataFingerprint, b: DataFingerprint) -> float:
        """Cosine similarity between two fingerprints. 1.0 = identical source distributions.

        Constructs a unified source vector from the union of both fingerprints'
        source sets. Missing sources get weight 0.0.

        Args:
            a, b: DataFingerprint instances to compare.

        Returns:
            Cosine similarity in [0.0, 1.0]. Returns 0.0 if either fingerprint
            has an all-zero weight vector.
        """
        all_sources = set(a.source_weights.keys()) | set(b.source_weights.keys())
        if not all_sources:
            logger.warning("fingerprint_similarity called with two empty fingerprints")
            return 0.0

        vec_a = [a.source_weights.get(s, 0.0) for s in all_sources]
        vec_b = [b.source_weights.get(s, 0.0) for s in all_sources]

        dot = sum(va * vb for va, vb in zip(vec_a, vec_b))
        mag_a = (sum(v * v for v in vec_a)) ** 0.5
        mag_b = (sum(v * v for v in vec_b)) ** 0.5

        if mag_a == 0.0 or mag_b == 0.0:
            return 0.0

        similarity = dot / (mag_a * mag_b)
        # Clamp to [0, 1] to avoid floating-point edge cases
        return round(max(0.0, min(1.0, similarity)), 4)

    @staticmethod
    def detect_homogenization(fingerprints: list[DataFingerprint],
                              threshold: float = 0.85) -> list[str]:
        """Return shadow_ids whose fingerprint similarity exceeds threshold.

        Compares all pairs. A shadow is flagged if its similarity with ANY
        other shadow exceeds the threshold.

        Args:
            fingerprints: List of DataFingerprint objects to compare.
            threshold: Cosine similarity above which shadows are considered
                       homogenized. Default 0.85.

        Returns:
            Sorted list of shadow_ids that exceeded the similarity threshold
            with at least one other shadow. Empty list if no homogenization detected.
        """
        if len(fingerprints) < 2:
            return []

        flagged: set[str] = set()
        n = len(fingerprints)

        for i in range(n):
            for j in range(i + 1, n):
                sim = DataFingerprinter.fingerprint_similarity(
                    fingerprints[i], fingerprints[j]
                )
                if sim >= threshold:
                    flagged.add(fingerprints[i].shadow_id)
                    flagged.add(fingerprints[j].shadow_id)
                    logger.info(
                        "Homogenization detected: %s <-> %s similarity=%.4f (threshold=%.2f)",
                        fingerprints[i].shadow_id, fingerprints[j].shadow_id,
                        sim, threshold,
                    )

        return sorted(flagged)


# ---------------------------------------------------------------------------
# Source Catalog — all known data sources with type classification
# ---------------------------------------------------------------------------

SOURCE_CATALOG: dict[str, dict] = {
    "fred":          {"type": "macro",          "cost": "free"},
    "cboe":          {"type": "sentiment",      "cost": "free"},
    "cnn_fg":        {"type": "sentiment",      "cost": "free"},
    "aaii":          {"type": "sentiment",      "cost": "free"},
    "defillama":     {"type": "crypto_onchain", "cost": "free"},
    "blockchain_com": {"type": "crypto_onchain", "cost": "free"},
    "lme":           {"type": "commodity",      "cost": "free"},
    "usda":          {"type": "commodity",      "cost": "free"},
    "eia":           {"type": "commodity",      "cost": "free"},
    "cftc":          {"type": "positioning",    "cost": "free"},
    "yfinance":      {"type": "market_data",    "cost": "free"},
    "sec_edgar":     {"type": "filings",        "cost": "free"},
    "bls":           {"type": "macro",          "cost": "free"},
    "newsapi":       {"type": "news",           "cost": "free"},
    "gnews":         {"type": "news",           "cost": "free"},
    "bluesky":       {"type": "social",         "cost": "free"},
}
