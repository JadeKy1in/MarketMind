"""Pure Python TF-IDF clustering engine with sklearn fallback.

Extracted from event_clusterer.py to reduce module size.
Provides: tokenization, TF-IDF matrix, cosine similarity, silhouette score,
and _TfidfClustering wrapper that auto-selects sklearn or pure-Python.
"""

from __future__ import annotations

import logging
import math
import re

logger = logging.getLogger("marketmind.pipeline.tfidf_clustering")

# ── Optional dependency imports ──
_sklearn_available = False
_sentence_transformers_available = False

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity as _sk_cosine
    from sklearn.metrics import silhouette_score as _sk_silhouette
    _sklearn_available = True
except ImportError:
    pass

try:
    from sentence_transformers import SentenceTransformer
    _sentence_transformers_available = True
except ImportError:
    pass


# ── Tokenization ──

def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase alphanumeric words (2+ chars)."""
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return [w for w in text.split() if len(w) > 1]


# ── Pure Python TF-IDF ──

def _compute_tfidf_matrix(documents: list[str]) -> list[list[float]]:
    """Pure-Python TF-IDF matrix. Returns list of rows (each row = document vector)."""
    tokenized = [_tokenize(d) for d in documents]
    doc_count = len(documents)
    if doc_count == 0:
        return []

    # Document frequency
    df: dict[str, int] = {}
    for tokens in tokenized:
        for word in set(tokens):
            df[word] = df.get(word, 0) + 1

    # IDF
    idf: dict[str, float] = {}
    for word, count in df.items():
        idf[word] = math.log((doc_count + 1) / (count + 1)) + 1.0

    # TF-IDF matrix
    matrix: list[list[float]] = []
    for tokens in tokenized:
        tf: dict[str, float] = {}
        word_count = len(tokens) or 1
        for word in tokens:
            tf[word] = tf.get(word, 0) + 1.0 / word_count
        # Build sparse vector: only include words with idf > 0
        vec: dict[str, float] = {w: tf[w] * idf.get(w, 0) for w in tf}
        matrix.append(vec)

    return matrix


def _cosine_similarity_py(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """Pure-Python cosine similarity between two sparse vectors."""
    common_keys = set(vec_a.keys()) & set(vec_b.keys())
    if not common_keys:
        return 0.0
    dot = sum(vec_a[k] * vec_b[k] for k in common_keys)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values())) or 1.0
    norm_b = math.sqrt(sum(v * v for v in vec_b.values())) or 1.0
    return dot / (norm_a * norm_b)


def _pairwise_cosine_py(tfidf_matrix: list[dict[str, float]]) -> list[list[float]]:
    """Compute pairwise cosine similarity matrix from pure-Python TF-IDF vectors."""
    n = len(tfidf_matrix)
    sim: list[list[float]] = [[0.0] * n for _ in range(n)]
    for i in range(n):
        sim[i][i] = 1.0
        for j in range(i + 1, n):
            s = _cosine_similarity_py(tfidf_matrix[i], tfidf_matrix[j])
            sim[i][j] = s
            sim[j][i] = s
    return sim


def _compute_silhouette_py(
    tfidf_matrix: list[dict[str, float]],
    labels: list[int],
) -> float:
    """Pure-Python silhouette score."""
    n = len(labels)
    if n <= 1 or len(set(labels)) <= 1:
        return 0.0

    cluster_points: dict[int, list[int]] = {}
    for i, label in enumerate(labels):
        cluster_points.setdefault(label, []).append(i)

    pairwise = _pairwise_cosine_py(tfidf_matrix)

    scores: list[float] = []
    for i in range(n):
        my_cluster = labels[i]
        my_cluster_indices = cluster_points[my_cluster]
        if len(my_cluster_indices) <= 1:
            scores.append(0.0)
            continue

        # a = mean intra-cluster distance (1 - similarity)
        a_val = sum(1.0 - pairwise[i][j] for j in my_cluster_indices if j != i)
        a_val /= (len(my_cluster_indices) - 1)

        # b = min mean inter-cluster distance
        b_val = float("inf")
        for cid, indices in cluster_points.items():
            if cid == my_cluster:
                continue
            dist = sum(1.0 - pairwise[i][j] for j in indices) / len(indices)
            if dist < b_val:
                b_val = dist

        if b_val == float("inf"):
            b_val = 0.0
        max_ab = max(a_val, b_val)
        scores.append((b_val - a_val) / max_ab if max_ab > 0 else 0.0)

    return sum(scores) / n if n > 0 else 0.0


# ── Clustering Wrapper ──

class _TfidfClustering:
    """Thin wrapper over sklearn TF-IDF + cosine similarity or pure-Python fallback."""

    def __init__(self) -> None:
        self._use_sklearn = _sklearn_available
        self._vectorizer: TfidfVectorizer | None = None
        if self._use_sklearn:
            self._vectorizer = TfidfVectorizer(
                max_features=5000,
                stop_words="english",
                ngram_range=(1, 2),
            )

    def fit_transform(self, documents: list[str]):
        """Return a matrix representation and a similarity function."""
        if self._use_sklearn and self._vectorizer is not None:
            tfidf_matrix = self._vectorizer.fit_transform(documents)
            return tfidf_matrix
        return _compute_tfidf_matrix(documents)

    def compute_pairwise_similarity(self, matrix) -> list[list[float]]:
        """Compute pairwise cosine similarities."""
        if self._use_sklearn and not isinstance(matrix, list):
            return _sk_cosine(matrix).tolist()
        return _pairwise_cosine_py(matrix)

    def compute_silhouette(self, matrix, labels: list[int]) -> float:
        """Compute silhouette score."""
        if self._use_sklearn and not isinstance(matrix, list):
            n_labels = len(set(labels))
            if n_labels <= 1 or n_labels >= len(labels):
                return 0.0
            try:
                return float(_sk_silhouette(matrix, labels))
            except Exception:
                return 0.0
        return _compute_silhouette_py(matrix, labels)
