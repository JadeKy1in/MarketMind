"""Tests for pipeline/expertise_discovery.py — pure computation, no LLM calls."""

from types import SimpleNamespace

from marketmind.pipeline.expertise_discovery import (
    ShadowExpertise,
    discover_expertise,
    generate_methodology_injection,
    validate_distillation_safety,
)


# ── discover_expertise ────────────────────────────────────────────────────

def test_discover_expertise_finds_outperformer():
    """Shadow with BS=0.2 when median=0.5 -> expert, margin=0.6."""
    calibration = {
        "shadow_1_gold": {"total_predictions": 15, "brier_score_cumulative": 0.5, "direction_accuracy": 0.60},
        "shadow_7_gold": {"total_predictions": 20, "brier_score_cumulative": 0.2, "direction_accuracy": 0.85},
        "shadow_3_gold": {"total_predictions": 12, "brier_score_cumulative": 0.5, "direction_accuracy": 0.55},
    }
    results = discover_expertise(calibration)
    assert len(results) == 1
    assert results[0].shadow_id == "7"
    assert results[0].entity_id == "gold"
    assert results[0].brier_score == 0.2
    assert results[0].direction_accuracy == 0.85
    assert results[0].prediction_count == 20
    assert results[0].outperformance_margin == 0.6  # (0.5 - 0.2) / 0.5
    assert results[0].last_updated  # non-empty timestamp


def test_insufficient_predictions_excluded():
    """Shadow with <10 predictions -> not considered."""
    calibration = {
        "shadow_1_gold": {"total_predictions": 9, "brier_score_cumulative": 0.2, "direction_accuracy": 0.80},
        "shadow_2_gold": {"total_predictions": 15, "brier_score_cumulative": 0.5, "direction_accuracy": 0.60},
    }
    results = discover_expertise(calibration)
    # Only shadow_2 qualifies, need >= 2 qualified for comparison
    assert len(results) == 0


def test_need_multiple_qualified_shadows():
    """Only 1 qualified shadow -> no expertise discovered (need comparison)."""
    calibration = {
        "shadow_1_gold": {"total_predictions": 15, "brier_score_cumulative": 0.2, "direction_accuracy": 0.80},
    }
    results = discover_expertise(calibration)
    assert len(results) == 0


def test_multiple_entities():
    """Expertise discovered independently per entity."""
    calibration = {
        "shadow_1_gold": {"total_predictions": 20, "brier_score_cumulative": 0.3, "direction_accuracy": 0.70},
        "shadow_2_gold": {"total_predictions": 20, "brier_score_cumulative": 0.5, "direction_accuracy": 0.55},
        "shadow_1_crypto": {"total_predictions": 15, "brier_score_cumulative": 0.25, "direction_accuracy": 0.72},
        "shadow_3_crypto": {"total_predictions": 15, "brier_score_cumulative": 0.5, "direction_accuracy": 0.50},
    }
    results = discover_expertise(calibration)
    assert len(results) == 2
    entities = {r.entity_id for r in results}
    assert entities == {"gold", "crypto"}


def test_no_outperformer_when_all_equal():
    """When all Brier scores are equal, no one outperforms by 20%."""
    calibration = {
        "shadow_1_gold": {"total_predictions": 20, "brier_score_cumulative": 0.5, "direction_accuracy": 0.55},
        "shadow_2_gold": {"total_predictions": 20, "brier_score_cumulative": 0.5, "direction_accuracy": 0.55},
        "shadow_3_gold": {"total_predictions": 20, "brier_score_cumulative": 0.5, "direction_accuracy": 0.55},
    }
    results = discover_expertise(calibration)
    assert len(results) == 0


def test_skip_non_shadow_trackers():
    """Trackers not starting with 'shadow_' are ignored."""
    calibration = {
        "main_ai_gold": {"total_predictions": 50, "brier_score_cumulative": 0.1, "direction_accuracy": 0.90},
        "shadow_1_gold": {"total_predictions": 20, "brier_score_cumulative": 0.3, "direction_accuracy": 0.70},
        "shadow_2_gold": {"total_predictions": 20, "brier_score_cumulative": 0.6, "direction_accuracy": 0.50},
    }
    results = discover_expertise(calibration)
    assert len(results) == 1
    assert results[0].shadow_id == "1"


def test_entity_with_underscore():
    """Entity IDs like 'tech_sector' with underscores are handled correctly."""
    calibration = {
        "shadow_1_tech_sector": {"total_predictions": 20, "brier_score_cumulative": 0.2, "direction_accuracy": 0.80},
        "shadow_2_tech_sector": {"total_predictions": 20, "brier_score_cumulative": 0.5, "direction_accuracy": 0.55},
    }
    results = discover_expertise(calibration)
    assert len(results) == 1
    assert results[0].entity_id == "tech_sector"


# ── generate_methodology_injection ────────────────────────────────────────

def test_methodology_injection_no_price_levels():
    """Generated injection must not contain specific price levels."""
    expert = ShadowExpertise(
        shadow_id="7", entity_id="gold",
        brier_score=0.2, direction_accuracy=0.85,
        prediction_count=20, outperformance_margin=0.6,
    )
    entity_memory = SimpleNamespace(
        recurring_patterns=["关注央行政策转向信号", "技术面突破后确认再入场"],
        common_blind_spots=["过度依赖单一数据源"],
    )
    injection = generate_methodology_injection(expert, entity_memory)
    assert "1.1050" not in injection
    assert "2100" not in injection
    assert "央行政策" in injection
    assert "常见盲点" in injection


def test_methodology_injection_no_direction_recommendations():
    """Generated injection must not contain buy/sell recommendations."""
    expert = ShadowExpertise(
        shadow_id="7", entity_id="gold",
        brier_score=0.2, direction_accuracy=0.85,
        prediction_count=20, outperformance_margin=0.6,
    )
    entity_memory = SimpleNamespace(
        recurring_patterns=["关注央行政策转向信号"],
        common_blind_spots=[],
    )
    injection = generate_methodology_injection(expert, entity_memory)
    assert "买入" not in injection
    assert "卖出" not in injection
    assert "做多" not in injection
    assert "做空" not in injection


def test_methodology_injection_none_memory():
    """None entity_memory -> still generates valid injection."""
    expert = ShadowExpertise(
        shadow_id="7", entity_id="gold",
        brier_score=0.2, direction_accuracy=0.85,
        prediction_count=20, outperformance_margin=0.6,
    )
    injection = generate_methodology_injection(expert, None)
    assert "黄金分析方法论提示" in injection
    assert "影子分析师" in injection
    assert "常见盲点" not in injection  # no blind spots when memory is None


def test_methodology_injection_pattern_limit():
    """Only first 5 patterns and first 3 blind spots are included."""
    expert = ShadowExpertise(
        shadow_id="7", entity_id="gold",
        brier_score=0.2, direction_accuracy=0.85,
        prediction_count=20, outperformance_margin=0.6,
    )
    entity_memory = SimpleNamespace(
        recurring_patterns=[f"pattern_{i}" for i in range(10)],
        common_blind_spots=[f"blind_spot_{i}" for i in range(10)],
    )
    injection = generate_methodology_injection(expert, entity_memory)
    assert "pattern_4" in injection
    assert "pattern_5" not in injection
    assert "blind_spot_2" in injection
    assert "blind_spot_3" not in injection


# ── validate_distillation_safety ──────────────────────────────────────────

def test_validate_distillation_safety_blocks_prices():
    """Injection with '1.1050' -> rejected."""
    assert not validate_distillation_safety("价格目标: 1.1050 附近")


def test_validate_distillation_safety_blocks_direction():
    """Injection with '做多EUR' -> rejected."""
    assert not validate_distillation_safety("建议做多EUR")


def test_validate_distillation_safety_blocks_buy():
    """Injection with '买入' -> rejected."""
    assert not validate_distillation_safety("建议买入黄金")


def test_validate_distillation_safety_blocks_confidence():
    """Injection with '置信度 85' -> rejected."""
    assert not validate_distillation_safety("置信度 85%，建议关注")


def test_validate_distillation_safety_clean():
    """Clean methodology injection -> accepted."""
    clean = "关注央行政策转向信号，结合技术面确认入场时机。供方法论参考。"
    assert validate_distillation_safety(clean)


def test_validate_distillation_safety_small_number_ok():
    """Single decimal digit (0.5) is not a price level -> accepted."""
    assert validate_distillation_safety("关注0.5概率以上的事件")


def test_validate_distillation_safety_integer_ok():
    """Integer numbers without decimal are not price levels -> accepted."""
    assert validate_distillation_safety("关注3个关键因素：政策、数据、技术面")
