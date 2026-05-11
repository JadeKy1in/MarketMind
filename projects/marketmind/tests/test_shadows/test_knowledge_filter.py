"""Tests for KnowledgeFilter — Learngenes selective inheritance, ACE risk detection."""
import pytest

from projects.marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig


@pytest.fixture
def knowledge_filter():
    from projects.marketmind.shadows.knowledge_filter import KnowledgeFilter
    return KnowledgeFilter()


# ── Helper ─────────────────────────────────────────────────────────────────

def _make_item(item_id, source, category, content, verification_count=0,
               false_positive_count=0):
    from projects.marketmind.shadows.knowledge_filter import KnowledgeItem
    return KnowledgeItem(
        item_id=item_id,
        source_shadow_id=source,
        category=category,
        content=content,
        verification_count=verification_count,
        false_positive_count=false_positive_count,
    )


# ── Filter tests ───────────────────────────────────────────────────────────

def test_knowledge_filter_passes_verified_insights(knowledge_filter):
    """Insights with verification_count >= 2 should PASS."""
    items = [
        _make_item("k1", "shadow_a", "insight", "Gold tends to rise on geopolitical tension",
                   verification_count=3),
        _make_item("k2", "shadow_a", "insight", "Oil correlates with USD weakness",
                   verification_count=2),
        _make_item("k3", "shadow_b", "insight", "Tech leads in low-rate environments",
                   verification_count=5),
    ]
    passed = knowledge_filter.filter_inheritance("shadow_a", items)
    assert len(passed) == 3
    passed_ids = {k.item_id for k in passed}
    assert passed_ids == {"k1", "k2", "k3"}


def test_knowledge_filter_passes_verified_methodology(knowledge_filter):
    """Methodology components with verification_count >= 1 should PASS."""
    items = [
        _make_item("m1", "shadow_a", "methodology_component",
                   "Use MACD crossovers for entry timing", verification_count=1),
        _make_item("m2", "shadow_a", "methodology_component",
                   "Volume confirmation required for breakouts", verification_count=3),
    ]
    passed = knowledge_filter.filter_inheritance("shadow_a", items)
    assert len(passed) == 2
    passed_ids = {k.item_id for k in passed}
    assert passed_ids == {"m1", "m2"}


def test_knowledge_filter_drops_unverified_heuristics(knowledge_filter):
    """Heuristics with verification_count == 0 should be DROPPED."""
    items = [
        _make_item("h1", "shadow_a", "heuristic",
                   "Always buy on Mondays", verification_count=0),
        _make_item("h2", "shadow_a", "insight",
                   "A verified insight", verification_count=2),
        _make_item("h3", "shadow_b", "heuristic",
                   "Sell when RSI > 70 always", verification_count=0),
    ]
    passed = knowledge_filter.filter_inheritance("shadow_a", items)
    passed_ids = {k.item_id for k in passed}
    # Only h2 should pass (verified insight)
    assert "h2" in passed_ids
    assert "h1" not in passed_ids
    assert "h3" not in passed_ids
    assert len(passed) == 1


def test_knowledge_filter_isolates_false_positives(knowledge_filter):
    """Known false positives should be ISOLATED (not passed for inheritance, queued for 30-day re-verification)."""
    items = [
        _make_item("fp1", "shadow_a", "insight",
                   "Claimed pattern that was disproven",
                   verification_count=1, false_positive_count=2),
        _make_item("fp2", "shadow_a", "rule",
                   "A rule marked as false positive",
                   verification_count=0, false_positive_count=1),
        _make_item("good1", "shadow_a", "insight",
                   "A properly verified insight",
                   verification_count=3, false_positive_count=0),
    ]
    passed = knowledge_filter.filter_inheritance("shadow_a", items)
    passed_ids = {k.item_id for k in passed}
    # Only good1 should pass
    assert "good1" in passed_ids
    # False positives should be isolated (not passed)
    assert "fp1" not in passed_ids
    assert "fp2" not in passed_ids
    # Verify isolated items are tracked
    isolated = knowledge_filter.get_isolated_items()
    isolated_ids = {k.item_id for k in isolated}
    assert "fp1" in isolated_ids
    assert "fp2" in isolated_ids
    assert len(isolated) == 2


def test_knowledge_filter_drops_unverified_rules(knowledge_filter):
    """Rules with verification_count == 0 should be DROPPED."""
    items = [
        _make_item("r1", "shadow_a", "rule",
                   "Unverified trading rule", verification_count=0),
        _make_item("r2", "shadow_a", "rule",
                   "Verified rule", verification_count=1),
    ]
    passed = knowledge_filter.filter_inheritance("shadow_a", items)
    passed_ids = {k.item_id for k in passed}
    assert "r2" in passed_ids
    assert "r1" not in passed_ids
    assert len(passed) == 1


def test_knowledge_filter_methodology_always_passes_when_verified(knowledge_filter):
    """Methodology components with verification_count >= 1 pass, even verification_count == 0 DROPS."""
    items = [
        _make_item("method_good", "shadow_a", "methodology_component",
                   "Proven methodology step", verification_count=1),
        _make_item("method_bad", "shadow_a", "methodology_component",
                   "Unproven methodology step", verification_count=0),
    ]
    passed = knowledge_filter.filter_inheritance("shadow_a", items)
    passed_ids = {k.item_id for k in passed}
    assert "method_good" in passed_ids
    assert "method_bad" not in passed_ids
    assert len(passed) == 1


# ── ACE Risk tests ─────────────────────────────────────────────────────────

def test_ace_risk_increases_with_cascade_depth(knowledge_filter):
    """ACE risk score should increase with deeper cascade generation depth."""
    # Shallow cascade: gen 1, all verified
    items_shallow = [
        _make_item(f"k{i}", f"shadow_gen1", "insight", f"Insight {i}",
                   verification_count=2, false_positive_count=0)
        for i in range(5)
    ]
    # Deep cascade: mix of verified and unverified across multiple generations
    items_deep = [
        _make_item(f"d{i}", f"shadow_gen{i//2}", "insight", f"Deep insight {i}",
                   verification_count=(i % 3), false_positive_count=(1 if i % 4 == 0 else 0))
        for i in range(10)
    ]

    risk_shallow = knowledge_filter.detect_ace_risk(items_shallow)
    risk_deep = knowledge_filter.detect_ace_risk(items_deep)

    # Deep cascade (higher unverified ratio, more diverse sources) should have higher risk
    assert risk_deep > risk_shallow
    assert 0.0 <= risk_shallow <= 1.0
    assert 0.0 <= risk_deep <= 1.0


def test_ace_risk_zero_for_all_verified(knowledge_filter):
    """ACE risk should be 0.0 when ALL items are verified and have no false positives."""
    items = [
        _make_item(f"k{i}", f"shadow_src", "insight", f"Verified insight {i}",
                   verification_count=3, false_positive_count=0)
        for i in range(5)
    ] + [
        _make_item(f"m{i}", f"shadow_src", "methodology_component", f"Method {i}",
                   verification_count=2, false_positive_count=0)
        for i in range(3)
    ]
    risk = knowledge_filter.detect_ace_risk(items)
    assert risk == 0.0


def test_ace_risk_high_for_all_unverified(knowledge_filter):
    """ACE risk should be high when all items are unverified."""
    items = [
        _make_item(f"k{i}", f"shadow_src", "heuristic", f"Unverified heuristic {i}",
                   verification_count=0, false_positive_count=0)
        for i in range(10)
    ]
    risk = knowledge_filter.detect_ace_risk(items)
    # With all unverified, risk should be substantial
    assert risk > 0.5
    assert risk <= 1.0


def test_ace_risk_handles_empty_input(knowledge_filter):
    """ACE risk for empty item list should be 0.0."""
    risk = knowledge_filter.detect_ace_risk([])
    assert risk == 0.0


def test_filter_inheritance_clears_previous_isolated(knowledge_filter):
    """Each call to filter_inheritance should reset the isolated items list."""
    items1 = [
        _make_item("fp1", "shadow_a", "insight", "Bad insight",
                   verification_count=1, false_positive_count=2),
    ]
    knowledge_filter.filter_inheritance("shadow_a", items1)
    assert len(knowledge_filter.get_isolated_items()) == 1

    # Second call with no false positives
    items2 = [
        _make_item("good1", "shadow_b", "insight", "Good insight",
                   verification_count=3, false_positive_count=0),
    ]
    knowledge_filter.filter_inheritance("shadow_b", items2)
    assert len(knowledge_filter.get_isolated_items()) == 0
