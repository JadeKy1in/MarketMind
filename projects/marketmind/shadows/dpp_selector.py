"""Determinantal Point Process (DPP) for quality-diversity shadow selection.

Selects a subset of shadows that maximizes the product of quality and diversity
using DPP sampling: P(S) ∝ det(L_S) where L_ij = q_i * q_j * sim(i,j).

Phase D Module 2 — Analysis Middleware. Zero LLM dependencies.
"""
from __future__ import annotations

import logging
from collections import Counter

import numpy as np

logger = logging.getLogger("marketmind.shadows.dpp_selector")


class DPPSelector:
    """Determinantal Point Process selector for quality-diversity sampling.

    Given quality scores and a pairwise similarity matrix, DPP selects subsets
    that naturally balance quality (high-scoring items) and diversity
    (dissimilar items). Regime specialists are protected from elimination.

    Algorithm: Kulesza & Taskar (2012) "Determinantal Point Processes for
    Machine Learning" — elementary DPP sampling via eigendecomposition
    of the L-kernel matrix followed by iterative row elimination.
    """

    def __init__(
        self,
        quality_scores: dict[str, float],
        similarity_matrix: dict[str, dict[str, float]],
    ):
        """Initialize DPP selector.

        Args:
            quality_scores: Map of shadow_id -> quality score (higher is better).
            similarity_matrix: Pairwise similarity map shadow_id -> {other_id -> sim}
                               where sim in [0, 1] (1 = identical). Must be symmetric.
        """
        self._quality_scores = dict(quality_scores)
        self._similarity_matrix = similarity_matrix
        self._shadow_ids = sorted(self._quality_scores.keys())
        self._id_to_idx = {sid: i for i, sid in enumerate(self._shadow_ids)}
        self._n = len(self._shadow_ids)

        # Build L-kernel matrix: L_ij = q_i * q_j * sim(i,j)
        self._L = self._build_kernel()

    def _build_kernel(self) -> np.ndarray:
        """Build the L-kernel matrix L_ij = q_i * q_j * sim(i,j)."""
        n = self._n
        L = np.zeros((n, n), dtype=np.float64)

        for i, id_i in enumerate(self._shadow_ids):
            qi = self._quality_scores.get(id_i, 0.0)
            for j, id_j in enumerate(self._shadow_ids):
                if i == j:
                    L[i, j] = qi * qi
                else:
                    qj = self._quality_scores.get(id_j, 0.0)
                    sim = self._similarity_matrix.get(id_i, {}).get(id_j, 0.0)
                    sim_rev = self._similarity_matrix.get(id_j, {}).get(id_i, 0.0)
                    # Average for symmetry robustness
                    sim = (sim + sim_rev) / 2.0 if abs(sim - sim_rev) > 1e-10 else sim
                    L[i, j] = qi * qj * sim

        return L

    def select(
        self, k: int, regime_specialists: list[str] | None = None
    ) -> list[str]:
        """Select k shadows maximizing quality × diversity.

        Regime specialists are protected from elimination — they are always
        included in the result, and the remaining slots are filled via DPP
        sampling.

        Args:
            k: Number of shadows to select.
            regime_specialists: Shadow IDs that must be included (protected).

        Returns:
            List of k selected shadow IDs, sorted by quality score descending.
        """
        if k <= 0:
            return []

        specialists = regime_specialists or []
        specialists_set = set(specialists)

        # Validate specialists exist in our shadow list
        valid_specialists = [s for s in specialists if s in self._id_to_idx]
        specialist_count = len(valid_specialists)

        if self._n == 0:
            return []

        if k >= self._n:
            # Return all shadows sorted by quality
            return sorted(
                self._shadow_ids,
                key=lambda s: self._quality_scores.get(s, 0.0),
                reverse=True,
            )

        if k <= specialist_count:
            # Not enough slots — return top-k specialists by quality
            ranked = sorted(
                valid_specialists,
                key=lambda s: self._quality_scores.get(s, 0.0),
                reverse=True,
            )
            return ranked[:k]

        remaining_slots = k - specialist_count

        # Eligible shadows for DPP selection (exclude specialists)
        eligible = [
            sid for sid in self._shadow_ids if sid not in specialists_set
        ]
        if not eligible:
            return sorted(
                valid_specialists,
                key=lambda s: self._quality_scores.get(s, 0.0),
                reverse=True,
            )

        if remaining_slots >= len(eligible):
            # We need all eligible shadows
            result = list(valid_specialists) + list(eligible)
            return sorted(
                result,
                key=lambda s: self._quality_scores.get(s, 0.0),
                reverse=True,
            )

        # DPP sample from eligible shadows for remaining slots
        selected_eligible = self._dpp_sample_from_pool(eligible, remaining_slots)

        # Combine and return sorted by quality
        result = list(valid_specialists) + selected_eligible
        return sorted(
            result, key=lambda s: self._quality_scores.get(s, 0.0),
            reverse=True,
        )

    def _dpp_sample_from_pool(
        self, eligible_ids: list[str], k: int
    ) -> list[str]:
        """Sample k items from eligible pool using DPP eigen-sampling.

        Algorithm (Kulesza & Taskar, Algorithm 1):
        1. Compute eigendecomposition of the sub-kernel L_E over eligible set
        2. Select eigenvectors with probability λ_j / (λ_j + 1)
        3. Iteratively sample items, conditioning on each selection

        Args:
            eligible_ids: List of shadow IDs available for selection.
            k: Number of items to select.

        Returns:
            List of k selected shadow IDs.
        """
        if k <= 0:
            return []

        n_eligible = len(eligible_ids)
        if n_eligible <= k:
            return list(eligible_ids)

        # Build sub-kernel for eligible items only
        idx_map = [self._id_to_idx[sid] for sid in eligible_ids]
        sub_L = self._L[np.ix_(idx_map, idx_map)]

        # Add small regularization for numerical stability
        sub_L = sub_L + np.eye(n_eligible) * 1e-12

        try:
            eigenvalues, eigenvectors = np.linalg.eigh(sub_L)
        except np.linalg.LinAlgError:
            logger.warning(
                "Eigendecomposition failed; falling back to quality-only selection"
            )
            return sorted(
                eligible_ids,
                key=lambda s: self._quality_scores.get(s, 0.0),
                reverse=True,
            )[:k]

        # Clamp tiny negative eigenvalues to zero (floating-point noise)
        eigenvalues = np.maximum(eigenvalues, 0.0)

        # Phase 1: Select eigenvectors probabilistically
        # Each eigenvector j is selected with prob λ_j / (λ_j + 1)
        with np.errstate(divide="ignore", invalid="ignore"):
            probs = np.where(
                eigenvalues + 1.0 > 0,
                eigenvalues / (eigenvalues + 1.0),
                0.0,
            )
        selected_eig = np.where(np.random.random(n_eligible) < probs)[0]

        # Phase 2: Build V from selected eigenvectors
        if len(selected_eig) == 0:
            # No eigenvectors selected — fall back to quality ordering
            logger.debug("No eigenvectors selected in DPP phase 1; using quality order")
            return sorted(
                eligible_ids,
                key=lambda s: self._quality_scores.get(s, 0.0),
                reverse=True,
            )[:k]

        V = eigenvectors[:, selected_eig]

        # Phase 3: Iterative sampling with conditioning
        selected = self._sample_dpp_iterative(V, k, eligible_ids)
        return selected

    def _sample_dpp_iterative(
        self, V: np.ndarray, k: int, eligible_ids: list[str]
    ) -> list[str]:
        """Iterative DPP sampling: repeatedly sample an item, then condition.

        Algorithm (Kulesza & Taskar, Algorithm 1, lines 6-9):
        1. Compute marginal probability P(i) ∝ ||row_i(V)||^2
        2. Sample an item i ~ P
        3. Remove row i from V, then re-orthogonalize columns
        4. Repeat until k items selected or V is exhausted

        This is the "row-elimination" variant: after selecting item i,
        we remove its row from V and orthogonalize. The resulting V_cond
        represents the conditional kernel for remaining items.
        """
        if V.size == 0:
            return []

        if V.ndim == 1:
            V = V.reshape(-1, 1)

        n_items = V.shape[0]
        if k >= n_items:
            return list(eligible_ids)[:k]

        # Track mapping from V row index → original eligible_ids index
        row_indices = list(range(n_items))
        V_current = V.copy()

        selected_global: list[int] = []

        for _ in range(min(k, n_items)):
            if V_current.size == 0 or V_current.shape[0] == 0:
                break

            if V_current.ndim == 1:
                V_current = V_current.reshape(-1, 1)

            # Marginal: P(i) ∝ ||row_i(V)||^2
            row_norms = np.sum(V_current ** 2, axis=1)
            total_norm = row_norms.sum()

            if total_norm <= 1e-15:
                break

            probs = row_norms / total_norm
            local_idx = np.random.choice(V_current.shape[0], p=probs)
            global_idx = row_indices[local_idx]
            selected_global.append(global_idx)

            # Remove the selected row and re-orthogonalize (conditioning)
            mask = np.ones(V_current.shape[0], dtype=bool)
            mask[local_idx] = False
            V_current = V_current[mask, :]

            # Update row index mapping
            row_indices = [
                row_indices[j] for j in range(len(row_indices)) if mask[j]
            ]

            # Re-orthogonalize to maintain basis for the conditional subspace
            if V_current.shape[0] > 0 and V_current.shape[1] > 0:
                V_current = self._gram_schmidt(V_current)

        return [eligible_ids[i] for i in selected_global[:k]]

    @staticmethod
    def _gram_schmidt(V: np.ndarray) -> np.ndarray:
        """Gram-Schmidt orthogonalization of columns for numerical stability."""
        if V.size == 0:
            return V
        if V.ndim == 1:
            return V.reshape(-1, 1)

        n_rows, n_cols = V.shape
        Q = np.zeros_like(V)
        for j in range(n_cols):
            v = V[:, j].copy()
            for i in range(j):
                v -= np.dot(Q[:, i], V[:, j]) * Q[:, i]
            norm = np.linalg.norm(v)
            if norm > 1e-15:
                Q[:, j] = v / norm
            # else: leave as zero column
        return Q

    def sample_dpp(self, k: int, n_samples: int = 100) -> list[str]:
        """DPP sampling repeated n_samples times; return highest-frequency combination.

        Runs the DPP sampling algorithm n_samples times to amortize the
        stochastic nature of the process. Returns the most frequently
        occurring k-item combination.

        Args:
            k: Number of shadows to select.
            n_samples: Number of sampling rounds (default 100).

        Returns:
            List of k shadow IDs forming the highest-frequency combination.
        """
        if n_samples < 1:
            n_samples = 1

        combination_counts: Counter = Counter()

        for _ in range(n_samples):
            selected = self.select(k=k, regime_specialists=None)
            key = tuple(sorted(selected))
            combination_counts[key] += 1

        if not combination_counts:
            return []

        most_common = combination_counts.most_common(1)[0][0]
        return list(most_common)
