"""
test_ingestion_pipeline.py — Stage 2.5: Ingestion Pipeline Unit Tests
"""

import datetime
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from src.belief_types import (
    BeliefObservation,
    BeliefSource,
    BeliefSnapshot,
    BeliefStatus,
    BeliefNode,
)
from src.ingestion_pipeline import (
    DistilledEvent,
    IngestionResult,
    PRELOADED_PROPOSITIONS,
    Distiller,
    DistillerConfig,
    Instantiator,
    PatrolPipeline,
)
from src.scout_fetcher import RawEvent, ScoutConfig


class MockBeliefStateManager:
    def __init__(self):
        self.registered: Dict[str, str] = {}
        self.ingested: List[tuple] = []
        self._ingest_count = 0

    def register_proposition(self, proposition, *, proposition_id, source):
        if proposition_id in self.registered:
            from src.belief_state_manager import DuplicatePropositionError
            raise DuplicatePropositionError(f"Duplicate: {proposition_id}")
        self.registered[proposition_id] = proposition

    def ingest_observation(self, proposition_id, observation):
        self.ingested.append((proposition_id, observation))
        self._ingest_count += 1
        evidence = observation.value * observation.confidence
        node = BeliefNode(
            proposition=f"Belief about {proposition_id}",
            proposition_id=proposition_id,
            alpha=1.0 + evidence * 10,
            beta=1.0 + (1 - evidence) * 10,
            status=BeliefStatus.ACTIVE,
            source=observation.source,
        )
        exp = node.alpha / (node.alpha + node.beta)
        var = (node.alpha * node.beta) / ((node.alpha + node.beta) ** 2 * (node.alpha + node.beta + 1))
        score = exp / (1 + var)
        return BeliefSnapshot(
            node=node,
            observation_count=1,
            expectation=exp,
            uncertainty=var,
            score=score,
            status_label=BeliefStatus.ACTIVE.value,
        )


class TestDistilledEvent:
    def test_defaults(self):
        de = DistilledEvent(proposition_id="macro_fed_rate_path", direction="neutral")
        assert de.direction == "neutral"
        assert de.confidence == 0.5
        assert de.one_liner == ""
        assert de.tickers == []
        assert de.raw_event is None


class TestIngestionResult:
    def test_defaults(self):
        r = IngestionResult()
        assert r.total_raw == 0
        assert r.distilled_count == 0
        assert r.ingested_count == 0
        assert r.observations == []
        assert r.errors == []

    def test_with_data(self):
        obs = BeliefObservation(
            value=0.7,
            confidence=0.8,
            source=BeliefSource.MACRO_CALENDAR,
            timestamp="2026-05-07T09:00:00",
            observation_id="obs-1",
        )
        r = IngestionResult(
            total_raw=5,
            distilled_count=3,
            ingested_count=2,
            observations=[obs],
            errors=["net error"],
            proposition_updates={"macro_fed_rate_path": 0.65},
        )
        assert r.total_raw == 5
        assert r.distilled_count == 3
        assert r.ingested_count == 2
        assert len(r.observations) == 1
        assert r.errors == ["net error"]
        assert r.proposition_updates["macro_fed_rate_path"] == 0.65


class TestPreloadedPropositions:
    def test_has_expected_keys(self):
        assert "macro_us_recession_risk" in PRELOADED_PROPOSITIONS
        assert "macro_fed_rate_path" in PRELOADED_PROPOSITIONS
        assert "macro_inflation_trend" in PRELOADED_PROPOSITIONS
        assert "geo_us_china_tension" in PRELOADED_PROPOSITIONS
        assert "sentiment_market_greed" in PRELOADED_PROPOSITIONS
        assert "sector_tech_outperform" in PRELOADED_PROPOSITIONS
        assert "sector_energy_weakness" in PRELOADED_PROPOSITIONS
        assert "sector_financial_stress" in PRELOADED_PROPOSITIONS

    def test_all_propositions_have_non_empty_text(self):
        for prop_id, text in PRELOADED_PROPOSITIONS.items():
            assert text, f"Proposition {prop_id} has empty text"


class TestDistillerParseResponse:
    def test_valid_json_array(self):
        distiller = Distiller(config=DistillerConfig(api_key="test"))
        response = json.dumps([
            {
                "proposition_id": "macro_fed_rate_path",
                "direction": "bullish",
                "confidence": 0.75,
                "one_liner": "Fed expected to cut rates",
                "tickers": ["SPY", "QQQ"],
            },
            {
                "proposition_id": "macro_inflation_trend",
                "direction": "bullish",
                "confidence": 0.65,
                "one_liner": "Core CPI trending down",
                "tickers": ["XLV"],
            },
        ])
        raw_events = [
            RawEvent(title="Fed rate cut expected", body="The Fed is expected to cut rates in June", source_url="https://example.com/1", timestamp="2026-05-07T09:00:00"),
            RawEvent(title="CPI data released", body="Core inflation continues to moderate", source_url="https://example.com/2", timestamp="2026-05-07T09:00:00"),
        ]
        result = distiller._parse_llm_response(response, raw_events)
        assert len(result) == 2
        assert result[0].proposition_id == "macro_fed_rate_path"
        assert result[0].direction == "bullish"
        assert result[0].confidence == 0.75
        assert result[1].proposition_id == "macro_inflation_trend"

    def test_markdown_wrapped_json(self):
        distiller = Distiller(config=DistillerConfig(api_key="test"))
        response = "```json\n[\n  {\n    \"proposition_id\": \"macro_fed_rate_path\",\n    \"direction\": \"bearish\",\n    \"confidence\": 0.8,\n    \"one_liner\": \"Hawkish Fed comments\",\n    \"tickers\": [\"SPY\"]\n  }\n]\n```"
        result = distiller._parse_llm_response(response, [])
        assert len(result) == 1
        assert result[0].direction == "bearish"
        assert result[0].confidence == 0.8

    def test_wrapped_in_events_dict(self):
        distiller = Distiller(config=DistillerConfig(api_key="test"))
        response = json.dumps({"events": [{"proposition_id": "geo_us_china_tension", "direction": "bearish", "confidence": 0.6, "one_liner": "Tariff escalation risk", "tickers": ["XLF"]}]})
        result = distiller._parse_llm_response(response, [])
        assert len(result) == 1
        assert result[0].proposition_id == "geo_us_china_tension"

    def test_unknown_proposition_skipped(self):
        distiller = Distiller(config=DistillerConfig(api_key="test"))
        response = json.dumps([{"proposition_id": "nonexistent_proposition", "direction": "bullish", "confidence": 0.9, "one_liner": "Unknown signal", "tickers": []}])
        result = distiller._parse_llm_response(response, [])
        assert len(result) == 0

    def test_malformed_json_returns_empty(self):
        distiller = Distiller(config=DistillerConfig(api_key="test"))
        result = distiller._parse_llm_response("not valid json {{{", [])
        assert result == []

    def test_non_list_root_returns_empty(self):
        distiller = Distiller(config=DistillerConfig(api_key="test"))
        result = distiller._parse_llm_response('{"not_an_array": true}', [])
        assert result == []

    def test_clamp_confidence(self):
        distiller = Distiller(config=DistillerConfig(api_key="test"))
        response = json.dumps([{"proposition_id": "macro_fed_rate_path", "direction": "bullish", "confidence": 5.0, "one_liner": "Extreme", "tickers": []}])
        result = distiller._parse_llm_response(response, [])
        assert len(result) == 1
        assert result[0].confidence == 1.0

    def test_empty_raw_events(self):
        distiller = Distiller(config=DistillerConfig(api_key="test"))
        result = distiller.distill([])
        assert result == []


class TestDistillerSystemPrompt:
    def test_contains_proposition_ids(self):
        distiller = Distiller(config=DistillerConfig(api_key="test"))
        prompt = distiller._build_system_prompt()
        assert "macro_fed_rate_path" in prompt
        assert "geo_us_china_tension" in prompt
        assert "bullish" in prompt
        assert "bearish" in prompt


class TestInstantiatorRegister:
    def test_registers_all_propositions(self):
        mock = MockBeliefStateManager()
        instantiator = Instantiator(mock)
        count = instantiator.register_default_propositions()
        assert count == len(PRELOADED_PROPOSITIONS)
        for prop_id in PRELOADED_PROPOSITIONS:
            assert prop_id in mock.registered

    def test_register_twice_is_idempotent(self):
        mock = MockBeliefStateManager()
        instantiator = Instantiator(mock)
        count1 = instantiator.register_default_propositions()
        count2 = instantiator.register_default_propositions()
        assert count1 == len(PRELOADED_PROPOSITIONS)
        assert count2 == 0


class TestInstantiatorInstantiate:
    def test_bullish_mapping(self):
        mock = MockBeliefStateManager()
        instantiator = Instantiator(mock)
        instantiator.register_default_propositions()
        de = DistilledEvent(proposition_id="macro_fed_rate_path", direction="bullish", confidence=0.8, one_liner="Rate cut expected", tickers=["SPY"])
        result = instantiator.instantiate_and_ingest([de])
        assert result.ingested_count == 1
        assert result.distilled_count == 1
        obs = result.observations[0]
        assert obs.value == pytest.approx(0.9, abs=1e-6)
        assert obs.confidence == 0.8
        assert obs.source == BeliefSource.MACRO_CALENDAR
        assert obs.metadata["one_liner"] == "Rate cut expected"
        assert obs.metadata["tickers"] == ["SPY"]

    def test_bearish_mapping(self):
        mock = MockBeliefStateManager()
        instantiator = Instantiator(mock)
        instantiator.register_default_propositions()
        de = DistilledEvent(proposition_id="geo_us_china_tension", direction="bearish", confidence=0.7)
        result = instantiator.instantiate_and_ingest([de])
        obs = result.observations[0]
        assert obs.value == pytest.approx(0.15, abs=1e-6)

    def test_neutral_skipped(self):
        mock = MockBeliefStateManager()
        instantiator = Instantiator(mock)
        instantiator.register_default_propositions()
        de = DistilledEvent(proposition_id="macro_fed_rate_path", direction="neutral", confidence=0.5)
        result = instantiator.instantiate_and_ingest([de])
        assert result.ingested_count == 0
        assert result.observations == []

    def test_evidence_clamped(self):
        mock = MockBeliefStateManager()
        instantiator = Instantiator(mock)
        instantiator.register_default_propositions()
        de = DistilledEvent(proposition_id="macro_fed_rate_path", direction="bullish", confidence=1.0)
        result = instantiator.instantiate_and_ingest([de])
        obs = result.observations[0]
        assert obs.value == pytest.approx(0.95, abs=1e-6)
        de2 = DistilledEvent(proposition_id="macro_fed_rate_path", direction="bearish", confidence=1.0)
        result2 = instantiator.instantiate_and_ingest([de2])
        obs2 = result2.observations[0]
        assert obs2.value == pytest.approx(0.05, abs=1e-6)

    def test_ingestion_records_proposition_updates(self):
        mock = MockBeliefStateManager()
        instantiator = Instantiator(mock)
        instantiator.register_default_propositions()
        de = DistilledEvent(proposition_id="macro_fed_rate_path", direction="bullish", confidence=0.8)
        result = instantiator.instantiate_and_ingest([de])
        assert "macro_fed_rate_path" in result.proposition_updates
        assert result.proposition_updates["macro_fed_rate_path"] > 0.0

    def test_multiple_events(self):
        mock = MockBeliefStateManager()
        instantiator = Instantiator(mock)
        instantiator.register_default_propositions()
        events = [
            DistilledEvent(proposition_id="macro_fed_rate_path", direction="bullish", confidence=0.8),
            DistilledEvent(proposition_id="geo_us_china_tension", direction="bearish", confidence=0.6),
            DistilledEvent(proposition_id="sentiment_market_greed", direction="neutral", confidence=0.5),
        ]
        result = instantiator.instantiate_and_ingest(events)
        assert result.ingested_count == 2
        assert len(result.observations) == 2


class TestPatrolPipeline:
    def test_full_cycle_with_no_network(self):
        mock = MockBeliefStateManager()
        pipeline = PatrolPipeline(
            belief_manager=mock,
            distiller_config=DistillerConfig(api_key="test_api_key", api_url="https://0.0.0.0:1/"),
            scout_config=ScoutConfig(rate_limit_seconds=0.1),
        )
        result = pipeline.run()
        assert isinstance(result, IngestionResult)
        assert result.ingested_count >= 0
        assert result.errors is not None

    def test_mocked_distill_and_ingest(self):
        mock = MockBeliefStateManager()
        distiller = Distiller(config=DistillerConfig(api_key="test", api_url="https://0.0.0.0:1/"))
        pipeline = PatrolPipeline(
            belief_manager=mock,
            distiller=distiller,
            scout_config=ScoutConfig(rate_limit_seconds=0.1),
        )
        result = pipeline.run()
        assert isinstance(result, IngestionResult)
        for prop_id in PRELOADED_PROPOSITIONS:
            assert prop_id in mock.registered