"""Tests for KnowledgeFilter.evaluate_external — external observation evaluation."""
import pytest

from marketmind.shadows.shadow_agent import ExternalObservation
from marketmind.shadows.knowledge_filter import KnowledgeFilter, KnowledgeVerdict, KnowledgeItem


@pytest.fixture
def knowledge_filter():
    return KnowledgeFilter()


def _make_item(item_id, source, category, content, verification_count=0,
               false_positive_count=0):
    return KnowledgeItem(
        item_id=item_id,
        source_shadow_id=source,
        category=category,
        content=content,
        verification_count=verification_count,
        false_positive_count=false_positive_count,
    )


def _make_observation(obs_id="obs-1", source_type="text", extracted_text="Valid observation text",
                      confidence=0.9, source_attribution=""):
    return ExternalObservation(
        observation_id=obs_id,
        source_type=source_type,
        source_path="/tmp/test_obs.txt",
        extracted_text=extracted_text,
        confidence=confidence,
        source_attribution=source_attribution,
    )


# ── PASS ──────────────────────────────────────────────────────────────────────

def test_evaluate_external_pass_valid_observation(knowledge_filter):
    """A valid observation with good confidence and sufficient text should PASS."""
    obs = _make_observation(
        obs_id="obs-1",
        source_type="text",
        extracted_text="The Federal Reserve is expected to maintain current interest rates "
                       "through Q3 based on latest inflation data and labor market strength.",
        confidence=0.9,
    )
    verdict = knowledge_filter.evaluate_external(obs)
    assert verdict.verdict == "PASS"
    assert verdict.confidence == 0.9
    assert verdict.evaluated_at != ""


def test_evaluate_external_pass_pdf_observation(knowledge_filter):
    """A valid PDF observation should PASS."""
    obs = _make_observation(
        obs_id="obs-2",
        source_type="pdf",
        extracted_text="Q2 earnings report shows revenue growth of 15% year-over-year "
                       "with expanding margins across all business segments.",
        confidence=0.85,
    )
    verdict = knowledge_filter.evaluate_external(obs)
    assert verdict.verdict == "PASS"
    assert verdict.confidence == 0.85


# ── DROP ──────────────────────────────────────────────────────────────────────

def test_evaluate_external_drop_empty_text(knowledge_filter):
    """Observation with empty extracted_text should be DROPPED."""
    obs = _make_observation(
        obs_id="obs-3",
        source_type="text",
        extracted_text="",
        confidence=0.9,
    )
    verdict = knowledge_filter.evaluate_external(obs)
    assert verdict.verdict == "DROP"
    assert "empty" in verdict.reason.lower()
    assert verdict.confidence == 1.0


def test_evaluate_external_drop_short_text(knowledge_filter):
    """Observation with too-short extracted_text should be DROPPED."""
    obs = _make_observation(
        obs_id="obs-4",
        source_type="text",
        extracted_text="Too short",
        confidence=0.9,
    )
    verdict = knowledge_filter.evaluate_external(obs)
    assert verdict.verdict == "DROP"
    assert "too short" in verdict.reason.lower()


def test_evaluate_external_drop_low_confidence(knowledge_filter):
    """Observation with confidence below 0.3 should be DROPPED."""
    obs = _make_observation(
        obs_id="obs-5",
        source_type="text",
        extracted_text="Some text that would otherwise be long enough to pass the length check",
        confidence=0.1,
    )
    verdict = knowledge_filter.evaluate_external(obs)
    assert verdict.verdict == "DROP"
    assert "confidence" in verdict.reason.lower()
    assert verdict.confidence == 1.0


def test_evaluate_external_drop_unrecognized_source_type(knowledge_filter):
    """Observation with unrecognized source_type should be DROPPED."""
    obs = _make_observation(
        obs_id="obs-6",
        source_type="video",
        extracted_text="Some meaningful text content that is sufficiently long to pass checks",
        confidence=0.9,
    )
    verdict = knowledge_filter.evaluate_external(obs)
    assert verdict.verdict == "DROP"
    assert "Unrecognized source_type" in verdict.reason


def test_evaluate_external_drop_gibberish_text(knowledge_filter):
    """Observation with mostly non-alphabetic text should be DROPPED."""
    obs = _make_observation(
        obs_id="obs-7",
        source_type="text",
        extracted_text="!@#$%^&*() 12345 67890 !!! ??? /// ... --- === [[[]]]",
        confidence=0.5,
    )
    verdict = knowledge_filter.evaluate_external(obs)
    assert verdict.verdict == "DROP"
    assert "alphabetic" in verdict.reason.lower()


# ── ISOLATE ───────────────────────────────────────────────────────────────────

def test_evaluate_external_isolate_contradiction(knowledge_filter):
    """Observation that contradicts existing knowledge should be ISOLATED."""
    existing = [
        _make_item("k1", "shadow_a", "insight",
                   "The Federal Reserve will raise interest rates in Q3"),
    ]
    obs = _make_observation(
        obs_id="obs-8",
        source_type="text",
        extracted_text="The Federal Reserve will not raise interest rates in Q3",
        confidence=0.8,
    )
    verdict = knowledge_filter.evaluate_external(obs, existing_knowledge=existing)
    assert verdict.verdict == "ISOLATE"
    assert "contradicts" in verdict.reason.lower()
    assert verdict.confidence == 0.7


def test_evaluate_external_no_contradiction_when_no_existing_knowledge(knowledge_filter):
    """With no existing knowledge, a valid observation should PASS (not ISOLATE)."""
    obs = _make_observation(
        obs_id="obs-9",
        source_type="text",
        extracted_text="The Federal Reserve will not raise interest rates in Q3",
        confidence=0.8,
    )
    verdict = knowledge_filter.evaluate_external(obs, existing_knowledge=None)
    assert verdict.verdict == "PASS"


def test_evaluate_external_no_contradiction_with_empty_existing(knowledge_filter):
    """With empty existing knowledge list, a valid observation should PASS."""
    obs = _make_observation(
        obs_id="obs-10",
        source_type="text",
        extracted_text="The Federal Reserve will not raise interest rates in Q3",
        confidence=0.8,
    )
    verdict = knowledge_filter.evaluate_external(obs, existing_knowledge=[])
    assert verdict.verdict == "PASS"


def test_evaluate_external_whitespace_only_text(knowledge_filter):
    """Observation with whitespace-only extracted_text should be DROPPED."""
    obs = _make_observation(
        obs_id="obs-11",
        source_type="text",
        extracted_text="   \n  \t  ",
        confidence=0.9,
    )
    verdict = knowledge_filter.evaluate_external(obs)
    assert verdict.verdict == "DROP"
    assert "empty" in verdict.reason.lower()
