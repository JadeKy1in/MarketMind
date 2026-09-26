"""Tests for pipeline/entity_memory.py — pure logic, no LLM calls."""

import json
from unittest.mock import MagicMock

import pytest

from marketmind.pipeline.entity_memory import (
    EntityMemory,
    decay_memories,
    identify_entities,
    load_entity_memories,
    update_entity_memory,
)


# ── Mock store helpers ────────────────────────────────────────────────────────

def _make_store(get_return=None):
    """Build a mock LearningStore with configurable get_entity_memory return."""
    store = MagicMock()
    store.get_entity_memory = MagicMock(return_value=get_return)
    store.update_entity_memory = MagicMock()
    return store


def _existing_row(**overrides):
    """Minimal row dict matching entity_memories schema."""
    defaults = {
        "entity_id": "AAPL",
        "entity_type": "asset",
        "analysis_count": 5,
        "avg_accuracy": 0.7,
        "recurring_patterns": json.dumps(["earnings_drift"]),
        "key_levels": json.dumps([{"level": 195.0, "type": "support"}]),
        "best_shadows": json.dumps(["tech_analyst"]),
        "common_blind_spots": json.dumps(["MISSING_DATA"]),
        "last_analyzed": "2026-05-15T00:00:00Z",
        "memory_freshness": 0.8,
    }
    defaults.update(overrides)
    return defaults


# ── identify_entities ─────────────────────────────────────────────────────────

class TestIdentifyEntities:
    def test_identify_central_bank(self):
        """'ECB remains hawkish' → [('ECB', 'central_bank')]."""
        result = identify_entities("ECB remains hawkish on inflation")
        assert ("ECB", "central_bank") in result

    def test_identify_central_bank_chinese(self):
        """'美联储维持利率不变' → [('Fed', 'central_bank')]."""
        result = identify_entities("美联储维持利率不变，市场预期降息推迟")
        assert ("Fed", "central_bank") in result

    def test_identify_sector(self):
        """'Tech earnings beat' → [('tech_sector', 'sector')]."""
        result = identify_entities("Tech earnings beat expectations this quarter")
        assert ("tech_sector", "sector") in result

    def test_identify_sector_chinese(self):
        """'能源板块反弹' → [('energy_sector', 'sector')]."""
        result = identify_entities("能源板块反弹，原油价格上涨")
        assert ("energy_sector", "sector") in result

    def test_identify_macro_indicator(self):
        """'CPI data surprises' → [('CPI', 'macro_indicator')]."""
        result = identify_entities("CPI data surprises to the upside")
        assert ("CPI", "macro_indicator") in result

    def test_identify_multiple_entities(self):
        """Fed + tech mentions → both central_bank and sector."""
        result = identify_entities("The Fed's hawkish stance hits tech stocks hard")
        entities_set = set(result)
        assert ("Fed", "central_bank") in entities_set
        assert ("tech_sector", "sector") in entities_set

    def test_identify_returns_empty_for_no_match(self):
        """No known entities → empty list."""
        result = identify_entities("Markets are volatile today")
        assert result == []

    @pytest.mark.asyncio
    async def test_identify_tickers_as_assets(self):
        """Tickers passed in → 'asset' type entries."""
        result = identify_entities(
            "S&P 500 rallies on tech strength", tickers=["SPY", "QQQ"]
        )
        asset_ids = [eid for eid, etype in result if etype == "asset"]
        assert "SPY" in asset_ids
        assert "QQQ" in asset_ids


# ── load_entity_memories ──────────────────────────────────────────────────────

class TestLoadEntityMemories:
    @pytest.mark.asyncio
    async def test_new_entity_initializes_empty(self):
        """First analysis → EntityMemory with analysis_count=0 and empty defaults."""
        store = _make_store(get_return=None)

        memories = await load_entity_memories(
            [("AAPL", "asset")], store
        )
        assert "AAPL" in memories
        mem = memories["AAPL"]
        assert mem.entity_id == "AAPL"
        assert mem.entity_type == "asset"
        assert mem.analysis_count == 0
        assert mem.avg_prediction_accuracy == 0.0
        assert mem.recurring_patterns == []
        assert mem.key_levels == []
        assert mem.best_performing_shadows == []
        assert mem.common_blind_spots == []
        assert mem.recent_lessons == []

    @pytest.mark.asyncio
    async def test_existing_entity_loaded_with_data(self):
        """Existing row → EntityMemory populated from store data."""
        store = _make_store(get_return=_existing_row())

        memories = await load_entity_memories(
            [("AAPL", "asset")], store
        )
        mem = memories["AAPL"]
        assert mem.analysis_count == 5
        assert mem.avg_prediction_accuracy == 0.7
        assert mem.recurring_patterns == ["earnings_drift"]
        assert mem.key_levels == [{"level": 195.0, "type": "support"}]
        assert mem.best_performing_shadows == ["tech_analyst"]
        assert mem.common_blind_spots == ["MISSING_DATA"]

    @pytest.mark.asyncio
    async def test_multiple_entities_mixed_new_and_existing(self):
        """Mix of new and existing entities — all returned."""

        def _get_entity_memory(eid):
            if eid == "AAPL":
                return _existing_row()
            return None

        store = MagicMock()
        store.get_entity_memory = MagicMock(side_effect=_get_entity_memory)

        memories = await load_entity_memories(
            [("AAPL", "asset"), ("EUR/USD", "asset")], store
        )
        assert len(memories) == 2
        assert memories["AAPL"].analysis_count == 5
        assert memories["EUR/USD"].analysis_count == 0


# ── update_entity_memory ──────────────────────────────────────────────────────

class TestUpdateEntityMemory:
    @pytest.mark.asyncio
    async def test_update_increments_count(self):
        """After update → analysis_count increments by 1."""
        store = _make_store(get_return=_existing_row(analysis_count=5, avg_accuracy=0.7))

        mem = await update_entity_memory(
            "AAPL", "asset",
            {"outcome": "SUCCESS", "root_cause": "CORRECT_REASONING"},
            store,
        )
        assert mem.analysis_count == 6

    @pytest.mark.asyncio
    async def test_blind_spot_accumulation(self):
        """MISSING_DATA root_cause → added to common_blind_spots."""
        store = _make_store(get_return=_existing_row(
            common_blind_spots=json.dumps(["FLAWED_CHAIN"])
        ))

        mem = await update_entity_memory(
            "AAPL", "asset",
            {"outcome": "FAILURE", "root_cause": "MISSING_DATA"},
            store,
        )
        assert "MISSING_DATA" in mem.common_blind_spots
        assert "FLAWED_CHAIN" in mem.common_blind_spots

    @pytest.mark.asyncio
    async def test_correct_reasoning_not_added_to_blind_spots(self):
        """CORRECT_REASONING root_cause is NOT a blind spot."""
        store = _make_store(get_return=_existing_row(
            common_blind_spots=json.dumps(["MISSING_DATA"])
        ))

        mem = await update_entity_memory(
            "AAPL", "asset",
            {"outcome": "SUCCESS", "root_cause": "CORRECT_REASONING"},
            store,
        )
        assert mem.common_blind_spots == ["MISSING_DATA"]

    @pytest.mark.asyncio
    async def test_black_swan_not_added_to_blind_spots(self):
        """BLACK_SWAN root_cause is NOT a blind spot."""
        store = _make_store(get_return=_existing_row(
            common_blind_spots=json.dumps([])
        ))

        mem = await update_entity_memory(
            "AAPL", "asset",
            {"outcome": "FAILURE", "root_cause": "BLACK_SWAN"},
            store,
        )
        assert "BLACK_SWAN" not in mem.common_blind_spots

    @pytest.mark.asyncio
    async def test_blind_spots_capped_at_10(self):
        """After 11 unique blind spots → only 10 retained."""
        existing_spots = [f"cause_{i}" for i in range(10)]
        store = _make_store(get_return=_existing_row(
            common_blind_spots=json.dumps(existing_spots)
        ))

        mem = await update_entity_memory(
            "AAPL", "asset",
            {"outcome": "FAILURE", "root_cause": "NEW_CAUSE"},
            store,
        )
        assert len(mem.common_blind_spots) == 10
        assert "NEW_CAUSE" in mem.common_blind_spots
        assert "cause_0" not in mem.common_blind_spots

    @pytest.mark.asyncio
    async def test_recent_lessons_capped_at_20(self):
        """After 25 updates → only 20 recent lessons retained."""
        # Simulate persistence: mutable state dict shared by get + update
        state = _existing_row(common_blind_spots=json.dumps([]), recent_lessons=json.dumps([]))

        def _get_entity_memory(eid):
            return dict(state)

        def _update_entity_memory(eid, data):
            state["analysis_count"] = state.get("analysis_count", 0) + 1
            state["recent_lessons"] = json.dumps(data.get("recent_lessons", []))
            state["common_blind_spots"] = json.dumps(data.get("common_blind_spots", []))

        store = MagicMock()
        store.get_entity_memory = MagicMock(side_effect=_get_entity_memory)
        store.update_entity_memory = MagicMock(side_effect=_update_entity_memory)

        mem = None
        for i in range(25):
            mem = await update_entity_memory(
                "AAPL", "asset",
                {"lesson_id": f"L{i:03d}", "outcome": "SUCCESS"},
                store,
            )
        assert mem is not None
        assert len(mem.recent_lessons) == 20
        assert mem.recent_lessons[0]["lesson_id"] == "L005"
        assert mem.recent_lessons[-1]["lesson_id"] == "L024"

    @pytest.mark.asyncio
    async def test_accuracy_rolling_update_success(self):
        """Success outcome → accuracy updates as rolling average."""
        # Old: count=4, acc=0.5 → (0.5*4 + 1.0)/5 = 0.6
        store = _make_store(get_return=_existing_row(
            analysis_count=4, avg_accuracy=0.5
        ))

        mem = await update_entity_memory(
            "AAPL", "asset",
            {"outcome": "SUCCESS"},
            store,
        )
        assert mem.avg_prediction_accuracy == 0.6
        assert mem.analysis_count == 5

    @pytest.mark.asyncio
    async def test_accuracy_rolling_update_failure(self):
        """Failure outcome → accuracy drops."""
        # Old: count=9, acc=0.8 → (0.8*9 + 0.0)/10 = 0.72
        store = _make_store(get_return=_existing_row(
            analysis_count=9, avg_accuracy=0.8
        ))

        mem = await update_entity_memory(
            "AAPL", "asset",
            {"outcome": "FAILURE"},
            store,
        )
        assert mem.avg_prediction_accuracy == 0.72

    @pytest.mark.asyncio
    async def test_save_passes_correct_data_to_store(self):
        """Verify store.update_entity_memory receives the right fields."""
        store = _make_store(get_return=_existing_row(analysis_count=5))

        await update_entity_memory(
            "AAPL", "asset",
            {"outcome": "SUCCESS", "root_cause": "CORRECT_REASONING"},
            store,
        )
        call_args = store.update_entity_memory.call_args
        assert call_args is not None
        entity_id_arg, data_arg = call_args[0]
        assert entity_id_arg == "AAPL"
        assert "avg_accuracy" in data_arg
        assert "recurring_patterns" in data_arg
        assert "key_levels" in data_arg
        assert "best_shadows" in data_arg
        assert "common_blind_spots" in data_arg
        assert "memory_freshness" in data_arg

    @pytest.mark.asyncio
    async def test_first_update_initializes_new_entity(self):
        """No existing data → EntityMemory created with count=1."""
        store = _make_store(get_return=None)

        mem = await update_entity_memory(
            "EUR/USD", "asset",
            {"outcome": "SUCCESS"},
            store,
        )
        assert mem.entity_id == "EUR/USD"
        assert mem.analysis_count == 1
        assert len(mem.recent_lessons) == 1

    @pytest.mark.asyncio
    async def test_duplicate_blind_spot_not_added(self):
        """Same root_cause → not duplicated in common_blind_spots."""
        store = _make_store(get_return=_existing_row(
            common_blind_spots=json.dumps(["MISSING_DATA", "FLAWED_CHAIN"])
        ))

        mem = await update_entity_memory(
            "AAPL", "asset",
            {"outcome": "FAILURE", "root_cause": "MISSING_DATA"},
            store,
        )
        assert mem.common_blind_spots.count("MISSING_DATA") == 1

    @pytest.mark.asyncio
    async def test_no_outcome_preserves_old_accuracy(self):
        """Lesson without outcome → accuracy unchanged."""
        store = _make_store(get_return=_existing_row(
            analysis_count=5, avg_accuracy=0.7
        ))

        mem = await update_entity_memory(
            "AAPL", "asset",
            {"root_cause": "MISSING_DATA"},
            store,
        )
        assert mem.avg_prediction_accuracy == 0.7


# ── decay_memories ────────────────────────────────────────────────────────────

class TestDecayMemories:
    @pytest.mark.asyncio
    async def test_decay_returns_zero_placeholder(self):
        """Placeholder returns 0 until store.list_all_entities is available."""
        store = MagicMock()
        result = await decay_memories(store)
        assert result == 0
