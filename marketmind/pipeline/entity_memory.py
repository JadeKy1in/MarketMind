"""Entity memory accumulation — per-asset knowledge that deepens with each analysis."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class EntityMemory:
    entity_id: str           # "EUR/USD" | "AAPL" | "gold" | "ECB" | "tech_sector"
    entity_type: str         # "asset" | "central_bank" | "sector" | "macro_indicator"
    analysis_count: int = 0
    avg_prediction_accuracy: float = 0.0
    recurring_patterns: list[str] = field(default_factory=list)
    key_levels: list[dict] = field(default_factory=list)
    best_performing_shadows: list[str] = field(default_factory=list)
    common_blind_spots: list[str] = field(default_factory=list)
    last_analyzed: str = ""
    memory_freshness: float = 1.0  # 0-1, decays when not analyzed
    recent_lessons: list[dict] = field(default_factory=list)  # last 20 lessons


_CB_KEYWORDS: dict[str, str] = {
    "ecb": "ECB", "fed": "Fed", "美联储": "Fed", "boj": "BOJ", "日本央行": "BOJ",
    "boe": "BOE", "英国央行": "BOE", "pbc": "PBoC", "人民银行": "PBoC",
}

_SECTOR_KEYWORDS: dict[str, str] = {
    "tech": "tech_sector", "科技": "tech_sector",
    "energy": "energy_sector", "能源": "energy_sector",
    "financial": "financials_sector", "金融": "financials_sector",
    "healthcare": "healthcare_sector", "医药": "healthcare_sector",
}

_INDICATOR_KEYWORDS: dict[str, str] = {
    "cpi": "CPI", "通胀": "CPI", "gdp": "GDP", "pmi": "PMI",
    "unemployment": "Unemployment", "失业": "Unemployment",
}


def identify_entities(
    hypothesis_text: str, tickers: list[str] | None = None
) -> list[tuple[str, str]]:
    """Extract entity references from hypothesis text.

    Returns list of (entity_id, entity_type) tuples. May contain duplicates —
    callers should deduplicate.

    Heuristics:
    - "ECB"/"Fed"/"BOJ" → central_bank
    - "tech"/"energy"/"financials" → sector
    - "CPI"/"GDP"/"PMI" → macro_indicator
    - Ticker in tickers list → asset type from asset_class_routing
    """
    entities: list[tuple[str, str]] = []
    text_lower = hypothesis_text.lower()

    for kw, name in _CB_KEYWORDS.items():
        if kw in text_lower:
            entities.append((name, "central_bank"))

    for kw, name in _SECTOR_KEYWORDS.items():
        if kw in text_lower:
            entities.append((name, "sector"))

    for kw, name in _INDICATOR_KEYWORDS.items():
        if kw in text_lower:
            entities.append((name, "macro_indicator"))

    if tickers:
        from marketmind.config.asset_class_routing import route_asset_class
        config, _ = route_asset_class(hypothesis_text, tickers)
        if config:
            for t in tickers:
                entities.append((t, "asset"))

    return entities


async def load_entity_memories(
    entities: list[tuple[str, str]],
    store,  # LearningStore
) -> dict[str, EntityMemory]:
    """Load or initialize entity memories for given entities.

    Returns dict keyed by entity_id.
    """
    memories: dict[str, EntityMemory] = {}
    for entity_id, entity_type in entities:
        data = store.get_entity_memory(entity_id)
        if data:
            mem = EntityMemory(
                entity_id=entity_id,
                entity_type=data.get("entity_type", entity_type),
                analysis_count=data.get("analysis_count", 0),
                avg_prediction_accuracy=data.get("avg_accuracy", 0.0),
                recurring_patterns=json.loads(data.get("recurring_patterns", "[]")),
                key_levels=json.loads(data.get("key_levels", "[]")),
                best_performing_shadows=json.loads(data.get("best_shadows", "[]")),
                common_blind_spots=json.loads(data.get("common_blind_spots", "[]")),
                last_analyzed=data.get("last_analyzed", ""),
                memory_freshness=data.get("memory_freshness", 1.0),
                recent_lessons=json.loads(data.get("recent_lessons", "[]")),
            )
        else:
            mem = EntityMemory(entity_id=entity_id, entity_type=entity_type)
        memories[entity_id] = mem
    return memories


async def update_entity_memory(
    entity_id: str,
    entity_type: str,
    lesson: dict,  # from StructuredLesson
    store,  # LearningStore
) -> EntityMemory:
    """Update an entity's memory with a new lesson and increment analysis count.

    The store auto-increments analysis_count and auto-sets last_analyzed.
    This function computes the new accuracy from (old_count, old_acc, outcome)
    so the stored value matches the returned EntityMemory.
    """
    mem_data = store.get_entity_memory(entity_id)

    if mem_data:
        old_count = mem_data.get("analysis_count", 0)
        old_acc = mem_data.get("avg_accuracy", 0.0)
        new_count = old_count + 1

        mem = EntityMemory(
            entity_id=entity_id,
            entity_type=mem_data.get("entity_type", entity_type),
            analysis_count=new_count,
            avg_prediction_accuracy=old_acc,
            recurring_patterns=json.loads(mem_data.get("recurring_patterns", "[]")),
            key_levels=json.loads(mem_data.get("key_levels", "[]")),
            best_performing_shadows=json.loads(mem_data.get("best_shadows", "[]")),
            common_blind_spots=json.loads(mem_data.get("common_blind_spots", "[]")),
            last_analyzed=datetime.now(timezone.utc).isoformat(),
            memory_freshness=1.0,
            recent_lessons=json.loads(mem_data.get("recent_lessons", "[]")),
        )
    else:
        mem = EntityMemory(
            entity_id=entity_id,
            entity_type=entity_type,
            analysis_count=1,
            last_analyzed=datetime.now(timezone.utc).isoformat(),
        )

    # Add lesson to recent list (keep last 20)
    mem.recent_lessons.append(lesson)
    if len(mem.recent_lessons) > 20:
        mem.recent_lessons = mem.recent_lessons[-20:]

    # Update blind spots if lesson has a meaningful root_cause
    root_cause = lesson.get("root_cause", "")
    if root_cause and root_cause not in ("CORRECT_REASONING", "BLACK_SWAN"):
        if root_cause not in mem.common_blind_spots:
            mem.common_blind_spots.append(root_cause)
            if len(mem.common_blind_spots) > 10:
                mem.common_blind_spots = mem.common_blind_spots[-10:]

    # Update rolling accuracy
    outcome = lesson.get("outcome")
    if outcome:
        n = mem.analysis_count
        old_acc = mem.avg_prediction_accuracy
        success = 1.0 if outcome == "SUCCESS" else 0.0
        mem.avg_prediction_accuracy = round((old_acc * (n - 1) + success) / n, 4)

    # Save to store (lists passed as-is; store serializes via _serialize_json)
    store.update_entity_memory(entity_id, {
        "entity_type": entity_type,
        "avg_accuracy": mem.avg_prediction_accuracy,
        "recurring_patterns": mem.recurring_patterns,
        "key_levels": mem.key_levels,
        "best_shadows": mem.best_performing_shadows,
        "common_blind_spots": mem.common_blind_spots,
        "memory_freshness": mem.memory_freshness,
        "recent_lessons": mem.recent_lessons,
    })

    return mem


async def decay_memories(store) -> int:
    """Decay memory freshness for entities not analyzed recently.

    Should be called periodically (e.g., weekly). Returns number of memories
    decayed. Full implementation needs store.list_all_entities() — placeholder
    until that method is available.
    """
    return 0
