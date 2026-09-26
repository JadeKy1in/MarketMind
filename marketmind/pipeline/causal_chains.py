"""Cross-cluster causal chain detection via Flash LLM — Tier 3.

Extracted from event_clusterer.py to reduce module size.
Detects causal and thematic relationships between event clusters.
"""

from __future__ import annotations

import logging

from marketmind.pipeline.cluster_synthesis import _parse_topic_json, _estimate_tokens

logger = logging.getLogger("marketmind.pipeline.causal_chains")

# ── Flash Tier 3 Prompt ──

CROSS_CLUSTER_SYSTEM = """You are a financial news correlation analyst. Given a set of event clusters with titles, identify which clusters are causally or thematically related.

IMPORTANT RULES:
- Only identify causal chains when there is explicit temporal or textual evidence in the headlines showing causation (e.g., 'due to', 'because of', 'led to', 'resulted in').
- Otherwise, group events under 'CORRELATED THEMES' without implying causation.
- Always cite article timestamps for any claimed temporal ordering.
- All cross-cluster links MUST start with 'CORRELATION:' — never claim CAUSATION without explicit causal language in at least two source headlines.

Output ONLY a JSON array:
[{"from_cluster": 0, "to_cluster": 1, "relationship": "CORRELATION: ECB rate hold + German PMI beat → EUR/USD decline", "confidence": "correlation_only"}]"""


# ── Main API ──

async def detect_causal_chains(
    clusters: list,
) -> tuple[int, list]:
    """Tier 3: Flash-based cross-cluster causal chain detection (single call).

    Sends cluster titles and sizes to Flash LLM in one batch call.
    Parses the JSON array response and builds (from_cluster, to_cluster,
    relationship_str) tuples keyed by cluster_id.

    Args:
        clusters: List of EventCluster objects with titles already set
            (call synthesize_cluster_themes first).

    Returns:
        (tokens_used, list of (from_cluster, to_cluster, relationship_str)).
    """
    from marketmind.gateway.async_client import chat_flash
    from marketmind.integrity.input_guard import sanitize_for_llm_prompt

    cluster_listing = "\n".join(
        f"Cluster {c.cluster_id}: {c.title} ({c.size} articles)"
        for c in clusters
    )

    user_prompt = (
        "CLUSTERS:\n"
        f"{cluster_listing}\n\n"
        "Identify cross-cluster relationships. Output JSON array:"
    )

    tokens_used = _estimate_tokens(CROSS_CLUSTER_SYSTEM) + _estimate_tokens(user_prompt)

    try:
        sys_prompt = sanitize_for_llm_prompt(CROSS_CLUSTER_SYSTEM, source="llm_prompt")
        user_prompt_sanitized = sanitize_for_llm_prompt(user_prompt, source="llm_prompt")
        result = await chat_flash(
            system_prompt=sys_prompt.sanitized,
            user_prompt=user_prompt_sanitized.sanitized,
            temperature=0.2,
            max_tokens=1024,
        )
    except Exception as exc:
        logger.warning("Flash cross-cluster detection failed: %s", exc)
        return tokens_used, []

    content = result.get("content", "") if isinstance(result, dict) else ""
    if result.get("error") if isinstance(result, dict) else False:
        return tokens_used, []

    tokens_used += _estimate_tokens(content)
    raw = _parse_topic_json(content)
    if not isinstance(raw, list):
        return tokens_used, []

    causal_chains: list[tuple] = []
    cluster_by_id = {c.cluster_id: c for c in clusters}
    for item in raw:
        if not isinstance(item, dict):
            continue
        from_id = item.get("from_cluster", -1)
        to_id = item.get("to_cluster", -1)
        relationship = item.get("relationship", "")
        if from_id in cluster_by_id and to_id in cluster_by_id and relationship:
            relationship = f"CORRELATION: {relationship}" if not relationship.startswith("CORRELATION") else relationship
            causal_chains.append((
                cluster_by_id[from_id],
                cluster_by_id[to_id],
                relationship,
            ))

    return tokens_used, causal_chains
