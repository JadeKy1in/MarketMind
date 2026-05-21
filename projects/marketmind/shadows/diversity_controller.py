"""Five-layer diversity monitoring for shadow ecosystem.

Detects homogenization across shadows by comparing source fingerprints,
strategy overlap, output correlation, map-elites cell assignment, and
combined homogenization flags.

Phase D Module 1 — Analysis Middleware. Zero LLM dependencies.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from collections import Counter

from marketmind.shadows.data_fingerprint import (
    DataFingerprint,
    DataFingerprinter,
    SOURCE_CATALOG,
)

logger = logging.getLogger("marketmind.shadows.diversity_controller")


@dataclass
class DiversityReport:
    """Five-layer diversity assessment for a single shadow.

    Attributes:
        shadow_id: Unique shadow identifier.
        source_similarity: Cosine similarity of data source fingerprints vs cohort.
        strategy_similarity: Methodology overlap score (0-1).
        output_correlation: Decision direction correlation with cohort (0-1).
        map_elites_cell: Behavior descriptor cell identifier.
        is_homogenized: True if shadow is flagged as homogenized on any layer.
    """
    shadow_id: str
    source_similarity: float = 0.0
    strategy_similarity: float = 0.0
    output_correlation: float = 0.0
    map_elites_cell: str = ""
    is_homogenized: bool = False


class DiversityController:
    """Monitors shadow diversity across five independent layers.

    Layers:
    1. Source fingerprint similarity (cosine similarity of data sources)
    2. Strategy similarity (methodology vector overlap)
    3. Output correlation (decision direction alignment)
    4. Map-Elites cell assignment (behavior descriptor grid)
    5. Combined homogenization flag

    All methods are deterministic pure math — zero LLM calls.
    """

    # Map-Elites behavior descriptor grid dimensions
    _MAP_ELITES_BINS = {
        "risk_appetite": 3,   # conservative / moderate / aggressive
        "time_horizon": 3,    # short / medium / long
        "asset_focus": 3,     # single / multi / macro
    }

    def __init__(self, state_db=None):
        """Initialize with optional state database for reading shadow metadata.

        Args:
            state_db: Optional ShadowStateDB instance for querying shadow configs.
        """
        self._state_db = state_db

    # ── Layer 1: Source fingerprint similarity ─────────────────────────────

    def check_source_similarity(
        self, shadow_id: str, fingerprints: dict[str, DataFingerprint]
    ) -> float:
        """Cosine similarity of this shadow's fingerprint vs cohort average.

        Args:
            shadow_id: The shadow to evaluate.
            fingerprints: Dict mapping shadow_id -> DataFingerprint.

        Returns:
            Mean cosine similarity with all other shadows in [0, 1].
            Returns 0.0 if no other shadows exist or fingerprint missing.
        """
        target = fingerprints.get(shadow_id)
        if target is None:
            logger.warning("No fingerprint found for %s", shadow_id)
            return 0.0

        other_ids = [sid for sid in fingerprints if sid != shadow_id]
        if not other_ids:
            return 0.0

        similarities = []
        for other_id in other_ids:
            sim = DataFingerprinter.fingerprint_similarity(
                target, fingerprints[other_id]
            )
            similarities.append(sim)

        mean_sim = sum(similarities) / len(similarities)
        return round(mean_sim, 4)

    # ── Layer 2: Strategy similarity ────────────────────────────────────────

    def check_strategy_similarity(
        self,
        shadow_id: str,
        strategy_vectors: dict[str, dict[str, float]],
    ) -> float:
        """Cosine similarity of methodology strategy vectors vs cohort.

        Strategy vectors map methodology dimensions to weights (e.g.,
        {"fundamental": 0.6, "technical": 0.3, "sentiment": 0.1}).

        Args:
            shadow_id: The shadow to evaluate.
            strategy_vectors: Dict mapping shadow_id -> {dimension: weight}.

        Returns:
            Mean cosine similarity with all other shadows in [0, 1].
        """
        target = strategy_vectors.get(shadow_id)
        if target is None:
            return 0.0

        other_ids = [sid for sid in strategy_vectors if sid != shadow_id]
        if not other_ids:
            return 0.0

        similarities = []
        for other_id in other_ids:
            sim = self._cosine_similarity(target, strategy_vectors[other_id])
            similarities.append(sim)

        mean_sim = sum(similarities) / len(similarities)
        return round(mean_sim, 4)

    # ── Layer 3: Output correlation ─────────────────────────────────────────

    def check_output_correlation(
        self,
        shadow_id: str,
        decision_directions: dict[str, list[float]],
    ) -> float:
        """Mean absolute Pearson correlation of decision directions vs cohort.

        Each shadow provides a list of directional scores (e.g., daily
        -1.0=strong sell to +1.0=strong buy).

        Args:
            shadow_id: The shadow to evaluate.
            decision_directions: Dict mapping shadow_id -> list of floats.

        Returns:
            Mean absolute correlation with all other shadows in [0, 1].
            Returns 0.0 if insufficient data or shadow missing.
        """
        target = decision_directions.get(shadow_id)
        if target is None or len(target) < 3:
            return 0.0

        other_ids = [sid for sid in decision_directions if sid != shadow_id]
        if not other_ids:
            return 0.0

        correlations = []
        for other_id in other_ids:
            other = decision_directions[other_id]
            if len(other) < 3:
                continue
            min_len = min(len(target), len(other))
            corr = self._pearson_correlation(target[-min_len:], other[-min_len:])
            correlations.append(abs(corr))

        if not correlations:
            return 0.0

        mean_corr = sum(correlations) / len(correlations)
        return round(mean_corr, 4)

    # ── Layer 4: Map-Elites cell assignment ─────────────────────────────────

    def compute_map_elites_cell(
        self,
        risk_appetite: float,
        time_horizon_days: int,
        asset_focus_breadth: int,
    ) -> str:
        """Assign a shadow to a Map-Elites behavior descriptor cell.

        Three dimensions binned into discrete levels:
          - risk_appetite (0-1): 0=conservative, 1=aggressive → 3 bins
          - time_horizon_days: short (<30), medium (30-90), long (>90)
          - asset_focus_breadth: single (1), multi (2-5), macro (>5)

        Cell format: "R{0-2}_T{0-2}_A{0-2}"

        Args:
            risk_appetite: 0.0 (conservative) to 1.0 (aggressive).
            time_horizon_days: Average holding period in days.
            asset_focus_breadth: Number of assets the shadow covers.

        Returns:
            Map-Elites cell string, e.g. "R1_T0_A2".
        """
        # Risk: bin into [0, 0.33, 0.67, 1.0]
        if risk_appetite <= 0.33:
            r_bin = 0
        elif risk_appetite <= 0.67:
            r_bin = 1
        else:
            r_bin = 2

        # Time horizon
        if time_horizon_days < 30:
            t_bin = 0
        elif time_horizon_days <= 90:
            t_bin = 1
        else:
            t_bin = 2

        # Asset breadth
        if asset_focus_breadth <= 1:
            a_bin = 0
        elif asset_focus_breadth <= 5:
            a_bin = 1
        else:
            a_bin = 2

        cell = f"R{r_bin}_T{t_bin}_A{a_bin}"
        logger.debug("Map-Elites cell: %s (risk=%.2f, horizon=%d, breadth=%d)",
                      cell, risk_appetite, time_horizon_days, asset_focus_breadth)
        return cell

    def detect_cell_crowding(
        self, cell_assignments: dict[str, str], crowding_threshold: float = 0.30
    ) -> list[str]:
        """Flag shadows in Map-Elites cells that exceed crowding threshold.

        A cell is "crowded" if the fraction of total shadows in it exceeds
        the threshold. All shadows in crowded cells are flagged.

        Args:
            cell_assignments: Dict mapping shadow_id -> cell string.
            crowding_threshold: Fraction above which a cell is considered crowded.

        Returns:
            List of shadow_ids in crowded cells.
        """
        if not cell_assignments:
            return []

        total = len(cell_assignments)
        cell_counts = Counter(cell_assignments.values())
        max_count = max(cell_counts.values()) if cell_counts else 0

        crowded_cells = {
            cell for cell, count in cell_counts.items()
            if count / total > crowding_threshold
        }

        flagged = [
            sid for sid, cell in cell_assignments.items()
            if cell in crowded_cells
        ]

        if flagged:
            logger.info(
                "Map-Elites crowding detected: %d cells crowded (%d/%d shadows, "
                "most-crowded cell has %d/%d=%.1f%%)",
                len(crowded_cells), len(flagged), total,
                max_count, total, max_count / total * 100,
            )

        return flagged

    # ── Layer 5: Combined homogenization ────────────────────────────────────

    def check_homogenized(
        self,
        source_similarity: float,
        strategy_similarity: float,
        output_correlation: float,
        cell_crowded: bool,
        thresholds: dict[str, float] | None = None,
    ) -> bool:
        """Flag shadow as homogenized if ANY layer exceeds threshold.

        Default thresholds:
          - source: 0.85 (high fingerprint similarity)
          - strategy: 0.80 (high methodology overlap)
          - output: 0.70 (high decision correlation)
          - cell_crowded: True (in a crowded Map-Elites cell)

        Args:
            source_similarity: Layer 1 score.
            strategy_similarity: Layer 2 score.
            output_correlation: Layer 3 score.
            cell_crowded: Whether shadow is in a crowded Map-Elites cell.
            thresholds: Optional per-layer thresholds override.

        Returns:
            True if shadow is homogenized on any layer.
        """
        t = thresholds or {
            "source": 0.85,
            "strategy": 0.80,
            "output": 0.70,
        }

        if source_similarity >= t.get("source", 0.85):
            logger.debug("Homogenized: source similarity %.4f >= %.2f",
                          source_similarity, t["source"])
            return True
        if strategy_similarity >= t.get("strategy", 0.80):
            logger.debug("Homogenized: strategy similarity %.4f >= %.2f",
                          strategy_similarity, t["strategy"])
            return True
        if output_correlation >= t.get("output", 0.70):
            logger.debug("Homogenized: output correlation %.4f >= %.2f",
                          output_correlation, t["output"])
            return True
        if cell_crowded:
            logger.debug("Homogenized: Map-Elites cell crowding")
            return True

        return False

    # ── Master check: run all 5 layers ──────────────────────────────────────

    def check_diversity(
        self,
        shadow_id: str,
        fingerprints: dict[str, DataFingerprint],
        strategy_vectors: dict[str, dict[str, float]],
        decision_directions: dict[str, list[float]],
        map_elites_params: dict[str, tuple[float, int, int]] | None = None,
    ) -> DiversityReport:
        """Run full 5-layer diversity check for one shadow.

        Args:
            shadow_id: The shadow to evaluate.
            fingerprints: All shadows' data source fingerprints.
            strategy_vectors: All shadows' methodology strategy vectors.
            decision_directions: All shadows' recent decision direction sequences.
            map_elites_params: Optional dict of shadow_id -> (risk, horizon, breadth).

        Returns:
            DiversityReport with all five layer scores and homogenization flag.
        """
        # Layer 1: Source similarity
        source_sim = self.check_source_similarity(shadow_id, fingerprints)

        # Layer 2: Strategy similarity
        strategy_sim = self.check_strategy_similarity(shadow_id, strategy_vectors)

        # Layer 3: Output correlation
        output_corr = self.check_output_correlation(shadow_id, decision_directions)

        # Layer 4: Map-Elites cell
        map_cell = ""
        cell_crowded = False
        if map_elites_params and shadow_id in map_elites_params:
            risk, horizon, breadth = map_elites_params[shadow_id]
            map_cell = self.compute_map_elites_cell(risk, horizon, breadth)

            # Build cell assignments for all shadows
            all_cells = {}
            for sid, params in map_elites_params.items():
                r, h, b = params
                all_cells[sid] = self.compute_map_elites_cell(r, h, b)

            crowded_list = self.detect_cell_crowding(all_cells)
            cell_crowded = shadow_id in crowded_list

        # Layer 5: Homogenization
        is_homogenized = self.check_homogenized(
            source_similarity=source_sim,
            strategy_similarity=strategy_sim,
            output_correlation=output_corr,
            cell_crowded=cell_crowded,
        )

        return DiversityReport(
            shadow_id=shadow_id,
            source_similarity=source_sim,
            strategy_similarity=strategy_sim,
            output_correlation=output_corr,
            map_elites_cell=map_cell,
            is_homogenized=is_homogenized,
        )

    # ── BlackRock warning ──────────────────────────────────────────────────

    def detect_blackrock_warning(
        self,
        fingerprints: list[DataFingerprint],
        threshold: float = 0.50,
    ) -> bool:
        """>=50% shadows share same dominant source → warning.

        "Dominant source" = the source with the highest weight in a fingerprint.

        Args:
            fingerprints: List of all shadow fingerprints.
            threshold: Fraction of shadows sharing dominant source to trigger
                       warning. Default 0.50 (50%).

        Returns:
            True if >= threshold fraction of shadows share the same dominant source.
        """
        if not fingerprints:
            return False

        dominant_sources = []
        for fp in fingerprints:
            if fp.source_weights:
                dominant = max(fp.source_weights, key=fp.source_weights.get)
                dominant_sources.append(dominant)

        if not dominant_sources:
            return False

        counts = Counter(dominant_sources)
        most_common, most_count = counts.most_common(1)[0]
        fraction = most_count / len(dominant_sources)

        if fraction >= threshold:
            logger.warning(
                "BlackRock warning: %.1f%% of shadows (%d/%d) share dominant "
                "source '%s'",
                fraction * 100, most_count, len(dominant_sources), most_common,
            )
            return True

        return False

    # ── Static helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _cosine_similarity(
        vec_a: dict[str, float], vec_b: dict[str, float]
    ) -> float:
        """Cosine similarity between two sparse float vectors."""
        all_keys = set(vec_a.keys()) | set(vec_b.keys())
        if not all_keys:
            return 0.0

        vals_a = [vec_a.get(k, 0.0) for k in all_keys]
        vals_b = [vec_b.get(k, 0.0) for k in all_keys]

        dot = sum(va * vb for va, vb in zip(vals_a, vals_b))
        mag_a = math.sqrt(sum(v * v for v in vals_a))
        mag_b = math.sqrt(sum(v * v for v in vals_b))

        if mag_a == 0.0 or mag_b == 0.0:
            return 0.0

        return dot / (mag_a * mag_b)

    @staticmethod
    def _pearson_correlation(x: list[float], y: list[float]) -> float:
        """Pearson correlation coefficient between two equal-length lists."""
        n = len(x)
        if n < 2:
            return 0.0

        mean_x = sum(x) / n
        mean_y = sum(y) / n

        cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        std_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
        std_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))

        if std_x == 0.0 or std_y == 0.0:
            return 0.0

        r = cov / (std_x * std_y)
        return max(-1.0, min(1.0, r))
