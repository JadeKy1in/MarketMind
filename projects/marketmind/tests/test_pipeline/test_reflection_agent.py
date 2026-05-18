"""Tests for reflection_agent — Layer 3 post-mortem analysis."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from marketmind.pipeline.reflection_agent import (
    ROOT_CAUSE_TAXONOMY,
    StructuredLesson,
    _DECAY_FACTOR,
    _MAX_BATCH_SIZE,
    _RELEVANCE_BY_CAUSE,
    _extract_entity,
    _generate_lesson_id,
    _parse_reflection_response,
    run_batch_reflection,
    run_reflection,
)
from marketmind.pipeline.prediction_extractor import PredictableHypothesis


def _make_prediction(status="VERIFIED_FAILURE", **kwargs):
    defaults = {
        "hypothesis_id": "test_h_001",
        "hypothesis_text": "EUR/USD将突破1.10",
        "prediction": "EUR/USD将在7天内涨至1.10",
        "confidence": 0.75,
        "direction": "above",
        "success_value": 1.10,
        "verification_metric": "close price",
        "verification_source": "market_data:EUR/USD",
        "prediction_window_days": 7,
        "expiry_date": "2026-05-15",
        "status": status,
        "actual_value": 1.08 if status == "VERIFIED_FAILURE" else 1.12,
        "verified_at": "2026-05-16T00:00:00Z",
        "created_at": "2026-05-10T00:00:00Z",
    }
    defaults.update(kwargs)
    return PredictableHypothesis(**defaults)


class TestRootCauseTaxonomy:
    def test_taxonomy_complete(self):
        expected = {
            "MISSING_DATA", "FLAWED_CHAIN", "REGIME_CHANGE",
            "OVERCONFIDENCE", "CORRECT_REASONING", "BLACK_SWAN",
            "DATA_SOURCE_ERROR",
        }
        assert set(ROOT_CAUSE_TAXONOMY.keys()) == expected

    def test_taxonomy_descriptions_non_empty(self):
        for key, desc in ROOT_CAUSE_TAXONOMY.items():
            assert len(desc) > 0, f"Missing description for {key}"


class TestLessonDataclass:
    def test_lesson_created_with_required_fields(self):
        now = datetime.now(timezone.utc).isoformat()
        lesson = StructuredLesson(
            lesson_id="L001",
            prediction_id="P001",
            outcome="FAILURE",
            root_cause="FLAWED_CHAIN",
            updated_belief="检查因果链条中的隐含假设",
            entity="EUR/USD",
            relevance_score=0.7,
            created_at=now,
        )
        assert lesson.lesson_id == "L001"
        assert lesson.outcome == "FAILURE"
        assert lesson.decay_factor == 1.0

    def test_lesson_for_failure(self):
        now = datetime.now(timezone.utc).isoformat()
        lesson = StructuredLesson(
            lesson_id="L002",
            prediction_id="P002",
            outcome="FAILURE",
            root_cause="MISSING_DATA",
            updated_belief="需等待ECB声明后再做判断",
            entity="EUR/USD",
            relevance_score=0.5,
            created_at=now,
        )
        assert lesson.outcome == "FAILURE"
        assert lesson.root_cause in ROOT_CAUSE_TAXONOMY

    def test_lesson_for_success(self):
        now = datetime.now(timezone.utc).isoformat()
        lesson = StructuredLesson(
            lesson_id="L003",
            prediction_id="P003",
            outcome="SUCCESS",
            root_cause="CORRECT_REASONING",
            updated_belief="利率差驱动汇率的逻辑被验证，可提升该模式权重",
            entity="EUR/USD",
            relevance_score=0.8,
            created_at=now,
        )
        assert lesson.outcome == "SUCCESS"
        assert lesson.root_cause == "CORRECT_REASONING"
        assert lesson.relevance_score > 0.5

    def test_decay_factor_assigned(self):
        now = datetime.now(timezone.utc).isoformat()
        lesson = StructuredLesson(
            lesson_id="L004",
            prediction_id="P004",
            outcome="FAILURE",
            root_cause="BLACK_SWAN",
            updated_belief="",
            entity="XAU/USD",
            relevance_score=0.2,
            created_at=now,
        )
        assert 0 < lesson.decay_factor <= 1.0


class TestRelevanceScores:
    def test_relevance_score_by_cause(self):
        assert _RELEVANCE_BY_CAUSE["REGIME_CHANGE"] < _RELEVANCE_BY_CAUSE["CORRECT_REASONING"]

    def test_all_causes_have_relevance(self):
        for cause in ROOT_CAUSE_TAXONOMY:
            assert cause in _RELEVANCE_BY_CAUSE, f"Missing relevance for {cause}"
            assert 0 <= _RELEVANCE_BY_CAUSE[cause] <= 1.0

    def test_black_swan_lowest_relevance(self):
        min_cause = min(_RELEVANCE_BY_CAUSE, key=_RELEVANCE_BY_CAUSE.get)
        assert min_cause == "BLACK_SWAN"


class TestHelperFunctions:
    def test_generate_lesson_id_is_stable(self):
        id1 = _generate_lesson_id("pred_abc123")
        id2 = _generate_lesson_id("pred_abc123")
        assert id1 == id2

    def test_generate_lesson_id_different_for_different_inputs(self):
        id1 = _generate_lesson_id("pred_001")
        id2 = _generate_lesson_id("pred_002")
        assert id1 != id2

    def test_extract_entity_from_source(self):
        p = _make_prediction(verification_source="market_data:EUR/USD")
        assert _extract_entity(p) == "EUR/USD"

    def test_extract_entity_no_colon(self):
        p = _make_prediction(verification_source="market_data")
        assert _extract_entity(p) == "market_data"

    def test_parse_json_response(self):
        content = '{"root_cause": "FLAWED_CHAIN", "updated_belief": "test", "entity": "EUR/USD"}'
        result = _parse_reflection_response(content)
        assert result["root_cause"] == "FLAWED_CHAIN"

    def test_parse_markdown_wrapped_json(self):
        content = '```json\n{"root_cause": "MISSING_DATA", "updated_belief": "wait", "entity": "SPX"}\n```'
        result = _parse_reflection_response(content)
        assert result["root_cause"] == "MISSING_DATA"

    def test_parse_fallback_on_garbage(self):
        result = _parse_reflection_response("not json at all")
        assert result["root_cause"] == "FLAWED_CHAIN"
        assert "updated_belief" in result


class TestRunReflection:
    @pytest.mark.asyncio
    async def test_pending_prediction_skipped(self):
        p = _make_prediction(status="PENDING")
        result = await run_reflection(p, p.hypothesis_text)
        assert result is None

    @pytest.mark.asyncio
    async def test_unknown_status_skipped(self):
        p = _make_prediction(status="EXPIRED_UNVERIFIABLE")
        result = await run_reflection(p, p.hypothesis_text)
        assert result is None

    @pytest.mark.asyncio
    async def test_success_calls_flash_and_produces_lesson(self):
        mock_response = {
            "content": '{"root_cause": "CORRECT_REASONING", "updated_belief": "reinforce", "entity": "EUR/USD"}',
            "usage": {},
        }
        with patch(
            "marketmind.pipeline.reflection_agent.chat_flash",
            new=AsyncMock(return_value=mock_response),
        ) as mock_flash:
            p = _make_prediction(status="VERIFIED_SUCCESS", actual_value=1.12)
            result = await run_reflection(p, p.hypothesis_text)

            mock_flash.assert_called_once()
            assert result is not None
            assert result.outcome == "SUCCESS"
            assert result.prediction_id == "test_h_001"

    @pytest.mark.asyncio
    async def test_failure_calls_pro_and_produces_lesson(self):
        mock_response = {
            "content": '{"root_cause": "FLAWED_CHAIN", "updated_belief": "verify assumptions", "entity": "SPX"}',
            "usage": {},
        }
        with patch(
            "marketmind.pipeline.reflection_agent.chat_pro",
            new=AsyncMock(return_value=mock_response),
        ) as mock_pro:
            p = _make_prediction(status="VERIFIED_FAILURE", actual_value=1.08)
            result = await run_reflection(p, p.hypothesis_text)

            mock_pro.assert_called_once()
            assert result is not None
            assert result.outcome == "FAILURE"
            assert result.root_cause == "FLAWED_CHAIN"

    @pytest.mark.asyncio
    async def test_invalid_root_cause_falls_back(self):
        mock_response = {
            "content": '{"root_cause": "INVALID_CAUSE", "updated_belief": "test", "entity": "test"}',
            "usage": {},
        }
        with patch(
            "marketmind.pipeline.reflection_agent.chat_pro",
            new=AsyncMock(return_value=mock_response),
        ):
            p = _make_prediction(status="VERIFIED_FAILURE")
            result = await run_reflection(p, p.hypothesis_text)
            assert result.root_cause == "FLAWED_CHAIN"

    @pytest.mark.asyncio
    async def test_empty_llm_response_returns_none(self):
        with patch(
            "marketmind.pipeline.reflection_agent.chat_flash",
            new=AsyncMock(return_value={"content": "", "error": "budget_exhausted", "usage": {}}),
        ):
            p = _make_prediction(status="VERIFIED_SUCCESS")
            result = await run_reflection(p, p.hypothesis_text)
            assert result is None

    @pytest.mark.asyncio
    async def test_lesson_has_decay_factor(self):
        mock_response = {
            "content": '{"root_cause": "CORRECT_REASONING", "updated_belief": "good", "entity": "test"}',
            "usage": {},
        }
        with patch(
            "marketmind.pipeline.reflection_agent.chat_flash",
            new=AsyncMock(return_value=mock_response),
        ):
            p = _make_prediction(status="VERIFIED_SUCCESS")
            result = await run_reflection(p, p.hypothesis_text)
            assert result.decay_factor == _DECAY_FACTOR


class MockStore:
    def __init__(self):
        self.saved = []

    def save_lesson(self, data):
        self.saved.append(data)


class TestBatchReflection:
    @pytest.mark.asyncio
    async def test_batch_skips_pending(self):
        mock_response = {
            "content": '{"root_cause": "CORRECT_REASONING", "updated_belief": "ok", "entity": "test"}',
            "usage": {},
        }
        with patch(
            "marketmind.pipeline.reflection_agent.chat_flash",
            new=AsyncMock(return_value=mock_response),
        ):
            predictions = [
                _make_prediction(status="PENDING", hypothesis_id="p1"),
                _make_prediction(status="VERIFIED_SUCCESS", hypothesis_id="p2"),
            ]
            store = MockStore()
            lessons = await run_batch_reflection(predictions, store)

            assert len(lessons) == 1
            assert lessons[0].prediction_id == "p2"

    @pytest.mark.asyncio
    async def test_batch_respects_max_limit(self):
        mock_response = {
            "content": '{"root_cause": "CORRECT_REASONING", "updated_belief": "ok", "entity": "test"}',
            "usage": {},
        }
        with patch(
            "marketmind.pipeline.reflection_agent.chat_flash",
            new=AsyncMock(return_value=mock_response),
        ):
            predictions = [
                _make_prediction(status="VERIFIED_SUCCESS", hypothesis_id=f"p{i}")
                for i in range(15)
            ]
            store = MockStore()
            lessons = await run_batch_reflection(predictions, store)

            assert len(lessons) == _MAX_BATCH_SIZE
            assert len(store.saved) == _MAX_BATCH_SIZE

    @pytest.mark.asyncio
    async def test_batch_handles_mixed_statuses(self):
        flash_response = {
            "content": '{"root_cause": "CORRECT_REASONING", "updated_belief": "ok", "entity": "test"}',
            "usage": {},
        }
        pro_response = {
            "content": '{"root_cause": "FLAWED_CHAIN", "updated_belief": "fix", "entity": "test"}',
            "usage": {},
        }
        with patch(
            "marketmind.pipeline.reflection_agent.chat_flash",
            new=AsyncMock(return_value=flash_response),
        ), patch(
            "marketmind.pipeline.reflection_agent.chat_pro",
            new=AsyncMock(return_value=pro_response),
        ):
            predictions = [
                _make_prediction(status="PENDING", hypothesis_id="p1"),
                _make_prediction(status="VERIFIED_SUCCESS", hypothesis_id="p2"),
                _make_prediction(status="VERIFIED_FAILURE", hypothesis_id="p3"),
                _make_prediction(status="EXPIRED_UNVERIFIABLE", hypothesis_id="p4"),
            ]
            store = MockStore()
            lessons = await run_batch_reflection(predictions, store)

            assert len(lessons) == 2
            outcomes = {l.outcome for l in lessons}
            assert outcomes == {"SUCCESS", "FAILURE"}
