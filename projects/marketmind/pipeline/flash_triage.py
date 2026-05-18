"""Flash lightweight news triage — score and classify all headlines for Pro browsing.

Replaces flash_preprocessor.py in the heuristic pipeline:
  - Old: full signal extraction on ~50 articles (event_type, event_grade, direction,
    confidence, affected_assets, key_facts)
  - New: lightweight 5-axis score + classification on ALL ~587 articles
  - Deep analysis moves to the Pro HVR loop.

Stage 2 in the main pipeline: Scout → Flash Triage → L1 Narrative → ...
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from marketmind.pipeline.event_clusterer import ClusteringResult

from marketmind.config.flash_output_schema import validate_flash_output
from marketmind.config.investigation_config import (
    FLASH_TRIAGE_BATCH_SIZE,
    MIN_IMPACT_SCORE_FOR_BROWSE,
)
from marketmind.gateway.async_client import chat_flash
from marketmind.pipeline.scout import NewsItem

logger = logging.getLogger("marketmind.pipeline.flash_triage")

# ── Flash Triage System Prompt (kept minimal — ~500 tokens for 100 headlines) ────

FLASH_TRIAGE_SYSTEM_PROMPT = """You are a financial news triage system. For each headline below, score it on 5 axes (0-10) and classify it.

Scoring axes:
- market_impact: How likely is this to move prices? (0=none, 10=central bank rate decision)
- cross_source_corroboration: Are other sources reporting this? (0=unique, 10=everyone reporting)
- contradicts_consensus: Does this challenge the prevailing narrative? (0=confirms, 10=directly contradicts)
- investigative_depth_needed: How much further research does this need? (0=read and done, 10=requires multiple API calls)
- urgency: How time-sensitive is this? (0=can wait, 10=must act today)

Classification: macro | company | geopolitical | sentiment | technical

Output ONLY a JSON array. No markdown, no explanation.
[{"headline_index": 0, "scores": {"market_impact": 7, "cross_source_corroboration": 8, "contradicts_consensus": 2, "investigative_depth_needed": 5, "urgency": 6}, "classification": "macro", "affected_assets": ["EUR/USD"], "cluster_hints": ["eurozone", "monetary_policy"]}, ...]"""


@dataclass
class TriageResult:
    """Lightweight news scoring result for a single headline.

    Contains 5-axis scores, classification, ticker hints, and cluster keywords.
    Deep analysis (event_type, event_grade, direction, confidence, key_facts)
    is deferred to the Pro HVR loop.
    """
    headline: str              # truncated to 300 chars
    source_name: str
    source_tier: int           # 1-4
    source_reliability: float
    url: str
    published_at: str
    scores: dict               # {market_impact, cross_source_corroboration,
                               #  contradicts_consensus, investigative_depth_needed, urgency}
    classification: str        # macro | company | geopolitical | sentiment | technical
    affected_assets: list[str]  # ticker hints only (not full analysis)
    cluster_hints: list[str]    # keywords for later clustering (country, sector, event type)

    # Event clustering context (NEW — Phase G)
    cluster_id: int | None = None
    cluster_title: str = ""
    causal_links: list[str] = field(default_factory=list)
    # causal_links example: ["ECB decision (cluster 3) → EUR/USD movement (cluster 7)"]


def _build_triage_prompt(items: list[NewsItem]) -> str:
    """Build the user prompt text from a batch of news items.

    Each headline is formatted as: [index] [source_name] title | summary
    """
    lines: list[str] = []
    for i, item in enumerate(items):
        summary_snippet = item.summary[:120] if item.summary else ""
        lines.append(f"[{i}] [{item.source_name}] {item.title} | {summary_snippet}")
    return "\n".join(lines)


def _parse_json_response(content: str) -> list[dict]:
    """Extract JSON array from LLM response, handling markdown wrapping.

    Copied pattern from flash_preprocessor.py — Flash models sometimes wrap
    JSON in ``` fences despite being instructed not to.
    """
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        # Remove opening fence
        content = "\n".join(lines[1:]) if len(lines) > 1 else content
        # Remove closing fence
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
    try:
        parsed = json.loads(content)
        if isinstance(parsed, list):
            return parsed
        elif isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        # Attempt to extract JSON array embedded in surrounding text
        start = content.find("[")
        end = content.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(content[start:end + 1])
            except json.JSONDecodeError:
                pass
    return []


async def triage_batch(
    items: list[NewsItem],
    batch_size: int | None = None,
) -> list[TriageResult]:
    """Score and classify all news items using Flash. Processes in batches.

    Args:
        items: News items from scout pipeline (all ~587 articles).
        batch_size: Items per Flash call. Defaults to FLASH_TRIAGE_BATCH_SIZE from config.

    Returns:
        List of TriageResult, one per successfully triaged item.
        Items that fail validation or parse are silently excluded.
    """
    if not items:
        return []

    if batch_size is None:
        batch_size = FLASH_TRIAGE_BATCH_SIZE

    results: list[TriageResult] = []

    for batch_start in range(0, len(items), batch_size):
        batch = items[batch_start:batch_start + batch_size]
        user_prompt = _build_triage_prompt(batch)

        try:
            flash_result = await chat_flash(
                system_prompt=FLASH_TRIAGE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.2,
                max_tokens=4096,
            )
        except Exception as exc:
            logger.warning(
                "Flash triage API call failed for batch %d-%d: %s",
                batch_start,
                batch_start + len(batch),
                exc,
            )
            continue

        content = flash_result.get("content", "")
        logger.debug("Flash raw response (first 300 chars): %s", content[:300] if content else "EMPTY")
        if not content or flash_result.get("error"):
            logger.warning(
                "Flash triage returned empty/error for batch %d-%d: %s. Prompt was %d chars. System prompt: %s",
                batch_start,
                batch_start + len(batch),
                flash_result.get("error", "empty content"),
                len(user_prompt),
                FLASH_TRIAGE_SYSTEM_PROMPT[:100],
            )
            continue

        raw_items = _parse_json_response(content)
        if not raw_items:
            logger.warning(
                "Flash triage JSON parse returned no items for batch %d-%d. Content (first 200): %s",
                batch_start,
                batch_start + len(batch),
                (content or "None")[:200],
            )
            continue

        for raw in raw_items:
            try:
                if not isinstance(raw, dict):
                    continue

                idx = raw.get("headline_index", -1)
                if not isinstance(idx, int) or idx < 0 or idx >= len(batch):
                    logger.debug("Flash triage: invalid headline_index %s, skipping", idx)
                    continue

                news_item = batch[idx]

                # Build a combined dict for validate_flash_output() which requires
                # "headline" and "source_tier" in addition to the LLM-returned fields
                validation_dict: dict = {
                    "headline": news_item.title[:300],
                    "source_tier": news_item.source_tier,
                    "scores": raw.get("scores", {}),
                    "classification": raw.get("classification", "sentiment"),
                }

                if not validate_flash_output(validation_dict):
                    logger.debug(
                        "Flash triage: validation failed for headline_index %d: %s",
                        idx,
                        news_item.title[:80],
                    )
                    continue

                scores = raw.get("scores", {})
                classification = raw.get("classification", "sentiment")
                affected_assets = raw.get("affected_assets", [])
                cluster_hints = raw.get("cluster_hints", [])

                # Ensure list types (Flash may return non-list values)
                if not isinstance(affected_assets, list):
                    affected_assets = []
                if not isinstance(cluster_hints, list):
                    cluster_hints = []

                results.append(TriageResult(
                    headline=news_item.title[:300],
                    source_name=news_item.source_name,
                    source_tier=news_item.source_tier,
                    source_reliability=news_item.source_reliability,
                    url=news_item.url,
                    published_at=news_item.published_at,
                    scores={
                        "market_impact": scores.get("market_impact", 0),
                        "cross_source_corroboration": scores.get("cross_source_corroboration", 0),
                        "contradicts_consensus": scores.get("contradicts_consensus", 0),
                        "investigative_depth_needed": scores.get("investigative_depth_needed", 0),
                        "urgency": scores.get("urgency", 0),
                    },
                    classification=classification,
                    affected_assets=affected_assets,
                    cluster_hints=cluster_hints,
                ))

            except Exception as exc:
                logger.debug("Flash triage: error processing raw item: %s", exc)
                continue

        logger.info(
            "Flash triage batch %d-%d: %d/%d items scored",
            batch_start,
            batch_start + len(batch),
            len([r for r in results
                 if r.source_name in {it.source_name for it in batch}]),
            len(batch),
        )

    logger.info(
        "Flash triage complete: %d results from %d input items",
        len(results),
        len(items),
    )
    return results


def filter_for_pro_browse(
    results: list[TriageResult],
    min_impact: int | None = None,
) -> list[TriageResult]:
    """Filter triage results to only those meeting the Pro browse threshold.

    Args:
        results: Full list of TriageResult from triage_batch().
        min_impact: Minimum market_impact score. Defaults to MIN_IMPACT_SCORE_FOR_BROWSE.

    Returns:
        Subset of results with market_impact >= min_impact.
    """
    if min_impact is None:
        min_impact = MIN_IMPACT_SCORE_FOR_BROWSE
    return [r for r in results if r.scores.get("market_impact", 0) >= min_impact]


def count_by_classification(results: list[TriageResult]) -> dict[str, int]:
    """Count triage results by classification category.

    Returns:
        Dict mapping classification to count.
    """
    counts: dict[str, int] = {}
    for r in results:
        counts[r.classification] = counts.get(r.classification, 0) + 1
    return counts


def inject_cluster_context(
    triage_results: list[TriageResult],
    clustering_result: ClusteringResult | None,
) -> list[TriageResult]:
    """Enrich triage results with event cluster membership.

    Maps each triage result's headline to its cluster (by headline text match).
    Adds cross-cluster causal links where applicable. Results without a matching
    cluster keep their defaults (cluster_id=None, cluster_title="", causal_links=[]).

    Args:
        triage_results: List of TriageResult from triage_batch().
        clustering_result: ClusteringResult from event_clusterer pipeline,
            or None if clustering hasn't run.

    Returns:
        Same list of TriageResult, enriched in-place with cluster context.
    """
    if clustering_result is None or not clustering_result.clusters:
        return triage_results

    # Build headline → cluster lookup
    headline_to_cluster: dict[str, object] = {}
    for cluster in clustering_result.clusters:
        for headline in cluster.headlines:
            headline_to_cluster[headline] = cluster

    # Build causal link descriptions for each cluster
    cluster_links: dict[int, list[str]] = {}
    for src, dst, reason in clustering_result.cross_cluster_causal_chains:
        desc = f"{src.title} (cluster {src.cluster_id}) → {dst.title} (cluster {dst.cluster_id}): {reason}"
        if src.cluster_id not in cluster_links:
            cluster_links[src.cluster_id] = []
        cluster_links[src.cluster_id].append(desc)

    # Enrich each result
    for result in triage_results:
        cluster = headline_to_cluster.get(result.headline)
        if cluster:
            result.cluster_id = cluster.cluster_id
            result.cluster_title = cluster.title
            result.causal_links = cluster_links.get(cluster.cluster_id, [])

    return triage_results
