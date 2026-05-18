"""Pre-Gate 1 pipeline stages (Stage 0-3): Shadow init → Scout → Flash → Investigation.

Exports:
    run_pre_gate1: Run stages 0-3, return intermediate state dict.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from marketmind.config.settings import MarketMindConfig


class _StageTracker:
    def __init__(self, verbose: bool):
        self.verbose = verbose

    def advance(self, stage: int, msg: str) -> None:
        if self.verbose:
            print(f"[{stage}/10] {msg}")

    def result(self, msg: str) -> None:
        if self.verbose:
            print(f"       {msg}")


async def run_pre_gate1(config: "MarketMindConfig", mock: bool = False,
                        verbose: bool = False,
                        shadow_count: int | None = None) -> dict:
    """Run stages 0-3: Shadow init → Scout → Flash → Investigation.

    Returns dict with all intermediate state needed by stages 4-10.
    """
    from marketmind.gateway.async_client import init_gateway
    init_gateway(config.deepseek_api_key, config.deepseek_base_url)

    tracker = _StageTracker(verbose)

    # Initialize archivist for stage-by-stage save
    from marketmind.storage.archivist import get_archivist
    archivist = get_archivist(config.data_dir)
    archivist.ensure_dirs()
    session_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _archive(subdir, filename, data):
        """Save pipeline stage output to archive. Never crashes pipeline."""
        try:
            archivist.save_json(subdir, filename, data)
        except Exception as e:
            if tracker.verbose:
                print(f"       [archive] {filename}: {e}")

    # 0. Shadow Mother event scan (pre-market)
    shadow_db = None
    mother = None
    if config.shadow.shadows_enabled and shadow_count != 0:
        tracker.advance(0, "Shadow Mother: scanning events...")
        from marketmind.shadows.shadow_state import ShadowStateDB
        from marketmind.shadows.shadow_mother import ShadowMother
        shadow_db = ShadowStateDB(config.shadow.shadows_db_path)
        shadow_db.init_schema()

        # Initialize permanent shadows (15 experts + 8 daredevils)
        from marketmind.shadows.expert_shadows import create_expert_shadows
        from marketmind.shadows.daredevil_shadows import create_daredevil_shadows
        create_expert_shadows(shadow_db, config.shadow)
        create_daredevil_shadows(shadow_db, config.shadow)

        # Initialize ecosystem auditor mechanism (NOT a shadow — post-analysis blind-spot scan)
        from marketmind.shadows.ecosystem_auditor import EcosystemAuditor
        ecosystem_auditor = EcosystemAuditor()

        mother = ShadowMother(config.shadow, shadow_db)
        tracker.result(f"Shadow ecosystem initialized with "
                       f"{len(shadow_db.get_visible_shadows())} shadows")

        # Phase F: Initialize background scheduler (disabled by default)
        if getattr(config.shadow, 'scheduler_enabled', False):
            from marketmind.shadows.background_scheduler import (
                BackgroundScheduler, SchedulerConfig,
            )
            from marketmind.shadows.shadow_memory import ShadowMemoryStore
            memory_store = ShadowMemoryStore(shadow_db)
            scheduler_config = SchedulerConfig(
                reflection_interval_minutes=config.shadow.reflection_interval_minutes,
                crystallization_interval_hours=config.shadow.crystallization_interval_hours,
                max_concurrent_tasks=config.shadow.max_concurrent_tasks,
                enabled=True,
            )
            scheduler = BackgroundScheduler(
                memory_store, shadow_db, mother, scheduler_config,
            )
            scheduler.start()
            tracker.result("Background scheduler started")

        # Phase F: Initialize Gemini Flash multimodal adapter (disabled by default)
        if getattr(config.shadow, 'gemini_flash_enabled', False):
            from marketmind.gateway.multimodal_adapter import MultimodalAdapter
            multimodal = MultimodalAdapter()
            tracker.result("Gemini Flash multimodal adapter initialized")

    # 1. News collection
    tracker.advance(1, "Scout: fetching news from all sources...")
    from marketmind.pipeline.scout import fetch_all_sources
    news_items = await fetch_all_sources(config)
    tracker.result(f"{len(news_items)} articles collected")

    _archive("raw", "01_scout_news", {
        "stage": "scout",
        "articles": len(news_items),
        "sources_used": len(set(n.source_name for n in news_items)),
        "items": [{"title": n.title, "source": n.source_name, "url": n.url,
                   "published": n.published_at} for n in news_items]
    })

    # 1b. Event clustering — group headlines into named themes with cross-cluster links
    clustering_result = None
    try:
        from marketmind.pipeline.entity_extractor import extract_entities
        from marketmind.pipeline.event_clusterer import cluster_events

        headlines = []
        entities = []
        source_tiers = {}
        for item in news_items:
            if item.title:
                source_tiers[len(headlines)] = item.source_tier
                headlines.append(item.title)
                entities.append(extract_entities(item.title))

        clustering_result = await cluster_events(headlines, entities, source_tiers=source_tiers)
        tracker.result(
            f"{clustering_result.clusters_formed} event clusters, "
            f"{clustering_result.noise_count} noise — "
            f"reduced {len(headlines)} headlines to {clustering_result.clusters_formed} themes"
        )
    except Exception as e:
        tracker.result(f"event clustering skipped ({e}) — continuing without clustering")

    # 2. Flash triage — lightweight scoring of ALL headlines
    tracker.advance(2, "Flash: triaging all headlines...")
    try:
        from marketmind.pipeline.flash_triage import triage_batch, filter_for_pro_browse
        triage_results = await triage_batch(news_items)
        browse_candidates = filter_for_pro_browse(triage_results)
        tracker.result(f"{len(triage_results)} scored, {len(browse_candidates)} for Pro browse "
                       f"({len([t for t in triage_results if t.classification == 'macro'])} macro, "
                       f"{len([t for t in triage_results if t.classification == 'company'])} company)")
    except ImportError:
        # Graceful fallback: use old flash_preprocessor
        from marketmind.pipeline.flash_preprocessor import preprocess_batch
        triage_results = await preprocess_batch(news_items[:50])
        browse_candidates = triage_results  # pass all for investigation
        tracker.result(f"flash_triage unavailable — fell back to preprocessor "
                       f"({len(triage_results)} signals)")

    # Enrich triage results with event cluster context
    try:
        from marketmind.pipeline.flash_triage import inject_cluster_context
        triage_results = inject_cluster_context(triage_results, clustering_result)
    except Exception as e:
        tracker.result(f"cluster context injection skipped ({e})")

    _archive("analysis", "02_flash_triage", {
        "stage": "flash_triage",
        "total_scored": len(triage_results),
        "browse_candidates": len(browse_candidates),
        "by_classification": {c: sum(1 for t in triage_results
                                     if getattr(t, 'classification', 'unknown') == c)
                              for c in set(getattr(t, 'classification', 'unknown')
                                           for t in triage_results)},
        "top_scored": [{"headline": getattr(t, 'headline', getattr(t, 'source_headline', '')),
                        "scores": getattr(t, 'scores', {}),
                        "classification": getattr(t, 'classification', 'unknown')}
                       for t in sorted(triage_results,
                                       key=lambda t: getattr(t, 'scores', {}).get("market_impact", 0),
                                       reverse=True)[:20]]
    })

    # 3. Pro HVR investigation loop
    tracker.advance(3, "Pro: investigating top signals...")
    hypotheses = []
    actionable: list = []
    monitor: list = []
    priced_in: list = []
    try:
        from marketmind.pipeline.investigation_loop import run_investigation_loop, InvestigationConfig
        inv_config = InvestigationConfig()
        hypotheses = await run_investigation_loop(browse_candidates[:20], inv_config)

        actionable = [h for h in hypotheses if h.verdict == "ACTIONABLE"]
        monitor = [h for h in hypotheses if h.verdict == "MONITOR"]
        priced_in = [h for h in hypotheses if h.verdict == "PRICED_IN"]
        tracker.result(f"{len(actionable)} actionable, {len(monitor)} monitor, "
                       f"{len(priced_in)} priced in, {len(hypotheses)} total")
    except ImportError as e:
        tracker.result(f"investigation_loop unavailable ({e}) — skipping Pro HVR")

    _archive("analysis", "025_investigation", {
        "stage": "investigation",
        "actionable": len(actionable),
        "monitor": len(monitor),
        "priced_in": len(priced_in),
        "total_hypotheses": len(hypotheses),
        "hypotheses": [{"hypothesis": h.hypothesis, "confidence": h.confidence,
                        "verdict": h.verdict, "bear_case": h.bear_case}
                       for h in hypotheses[:50]]
    })

    return {
        "tracker": tracker,
        "archivist": archivist,
        "session_date": session_date,
        "shadow_db": shadow_db,
        "mother": mother,
        "news_items": news_items,
        "triage_results": triage_results,
        "hypotheses": hypotheses,
        "actionable": actionable,
    }
