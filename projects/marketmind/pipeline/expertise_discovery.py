"""Cross-shadow expertise discovery and methodology distillation.

Layer 6 of the Phase I learning architecture. Identifies which shadows
consistently outperform on which entities, extracts methodological patterns,
and shares them with other shadows without exposing raw analysis or conclusions."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ShadowExpertise:
    shadow_id: str
    entity_id: str
    brier_score: float
    direction_accuracy: float
    prediction_count: int
    outperformance_margin: float
    methodology_patterns: list[str] = field(default_factory=list)
    last_updated: str = ""


def discover_expertise(
    calibration_data: dict[str, dict],
    min_predictions: int = 10,
    outperformance_threshold: float = 0.20,
) -> list[ShadowExpertise]:
    entity_groups: dict[str, list[tuple[str, dict]]] = {}
    for tracker_id, data in calibration_data.items():
        if not tracker_id.startswith("shadow_"):
            continue
        parts = tracker_id.split("_", 2)
        if len(parts) < 3:
            continue
        entity_id = parts[2]
        if entity_id not in entity_groups:
            entity_groups[entity_id] = []
        entity_groups[entity_id].append((tracker_id, data))

    expertise: list[ShadowExpertise] = []

    for entity_id, trackers in entity_groups.items():
        qualified = [(tid, d) for tid, d in trackers
                     if d.get("total_predictions", 0) >= min_predictions]
        if len(qualified) < 2:
            continue

        brier_scores = [d.get("brier_score_cumulative", 1.0) for _, d in qualified]
        median_bs = sorted(brier_scores)[len(brier_scores) // 2]

        for tracker_id, data in qualified:
            shadow_id = tracker_id.split("_")[1]
            bs = data.get("brier_score_cumulative", 1.0)
            da = data.get("direction_accuracy", 0.5)

            if median_bs > 0 and bs < median_bs * (1 - outperformance_threshold):
                margin = (median_bs - bs) / median_bs
                expertise.append(ShadowExpertise(
                    shadow_id=shadow_id,
                    entity_id=entity_id,
                    brier_score=bs,
                    direction_accuracy=da,
                    prediction_count=data.get("total_predictions", 0),
                    outperformance_margin=round(margin, 4),
                    last_updated=datetime.now(timezone.utc).isoformat(),
                ))

    return sorted(expertise, key=lambda e: e.outperformance_margin, reverse=True)


def generate_methodology_injection(
    expertise: ShadowExpertise,
    entity_memory=None,
) -> str:
    patterns = getattr(entity_memory, "recurring_patterns", []) if entity_memory else []
    blind_spots = getattr(entity_memory, "common_blind_spots", []) if entity_memory else []

    injection = "## 黄金分析方法论提示 (来自表现最佳的分析师)\n以下模式在历史分析中被验证有效：\n"
    for i, pattern in enumerate(patterns[:5], 1):
        injection += f"{i}. {pattern}\n"

    if blind_spots:
        injection += "\n常见盲点（该实体分析中曾反复出现）:\n"
        for spot in blind_spots[:3]:
            injection += f"- {spot}\n"

    injection += (
        f"\n来源: 影子分析师(准确率 {expertise.direction_accuracy:.1%}, "
        f"{expertise.prediction_count}次预测). 仅供方法论参考，不构成投资建议。"
    )

    return injection


def validate_distillation_safety(injection: str) -> bool:
    forbidden = [
        r'\d+\.\d{2,}',
        r'(买入|卖出|做多|做空|SHORT|LONG)',
        r'置信度\s*\d',
        r'confidence\s*\d',
    ]
    for pattern in forbidden:
        if re.search(pattern, injection, re.IGNORECASE):
            return False
    return True
