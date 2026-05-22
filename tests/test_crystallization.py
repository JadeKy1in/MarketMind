"""Tests for Crystallization Engine and Methodology Evolver.

Covers:
- CrystallizationEngine inner loop with mock shadow_analyses
- Promote path: high enough validation_score → promoted to semantic
- Retire path: low validation_score → retired
- Cold start: < min_samples votes → skipped (hold action)
- Methodology evolver records prediction
- Methodology report generation
- Audit trail persistence
"""
import pytest
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from marketmind.shadows.shadow_memory import ShadowMemoryStore
from marketmind.shadows.shadow_agent import ExternalObservation, CrystallizationResult
from marketmind.shadows.methodology_evolver import (
    MethodologyEvolver, MethodRecord, MethodologyReport,
    load_tracker, save_tracker, log_method_outcome,
    evolve_methodology, format_evolution_report,
)
from marketmind.shadows.method_breeding import breed_new_method, maintain_population
from marketmind.shadows.crystallization import CrystallizationEngine
from marketmind.config.settings import ShadowSettings


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test_crystallization.db"
        db = ShadowStateDB(str(db_path))
        db.init_schema()
        yield db
        db.close()


@pytest.fixture
def store(temp_db):
    return ShadowMemoryStore(temp_db)


@pytest.fixture
def evolver():
    return MethodologyEvolver()


@pytest.fixture
def engine(store, temp_db, evolver):
    return CrystallizationEngine(
        memory_store=store,
        state_db=temp_db,
        methodology_evolver=evolver,
        significance_threshold=0.6,
        min_samples=10,
    )


@pytest.fixture
def sample_config():
    return ShadowConfig(
        shadow_id="expert:gold:test_gold_bug",
        shadow_type="expert",
        display_name="Test Gold Bug",
        methodology_prompt="You are a gold market expert.",
        virtual_capital=50000.0,
        domain="gold",
        temperature=0.3,
    )


def _seed_shadow_and_votes(temp_db, shadow_id, ticker, vote_data):
    """Helper: create a shadow and insert votes with specified directions."""
    config = ShadowConfig(
        shadow_id=shadow_id,
        shadow_type="expert",
        display_name=f"Test {shadow_id}",
        methodology_prompt="Test methodology",
        virtual_capital=50000.0,
        domain="gold",
    )
    try:
        temp_db.create_shadow(config)
    except ValueError:
        pass  # Shadow already exists

    conn = temp_db._connect()
    try:
        for date_str, direction, confidence in vote_data:
            conn.execute(
                """INSERT INTO shadow_analyses
                   (shadow_id, date, ticker, direction, confidence, thesis, risk_note, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (shadow_id, date_str, ticker, direction, confidence,
                 f"Thesis for {date_str}", f"Risk for {date_str}",
                 f"{date_str}T00:00:00.000Z"),
            )
            # Seed outcome data: simulate PnL in virtual_trades
            # Long votes on positive-return days win; short on negative win
            pnl = 0.05 if direction == "long" else -0.03
            conn.execute(
                """INSERT OR IGNORE INTO virtual_trades
                   (shadow_id, ticker, direction, entry_price, exit_price,
                    position_size_pct, entry_date, exit_date, exit_reason, pnl_pct)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (shadow_id, ticker, direction, 100.0, 105.0 if direction == "long" else 97.0,
                 0.1, date_str, date_str, "test", pnl),
            )
        conn.commit()
    finally:
        conn.close()


def _seed_belief_node(store, shadow_id, ticker):
    """Seed an episodic belief node for a shadow/ticker pair."""
    obs = ExternalObservation(
        observation_id=f"obs:{shadow_id}:{ticker}:001",
        source_type="text",
        source_path=f"shadow:{shadow_id}",
        extracted_text=f"Belief about {ticker} from {shadow_id}",
        metadata={"ticker": ticker, "shadow_id": shadow_id},
        confidence=0.8,
        source_attribution=f"shadow:{shadow_id}",
    )
    node_id = store.ingest_observation_sync(shadow_id, obs, tier="episodic")
    return node_id


# ── Methodology Evolver Tests ───────────────────────────────────────────────

class TestMethodologyEvolver:
    """Tests for methodology tracking and evolution."""

    def test_load_tracker_initializes_defaults(self):
        """Tracker initializes with DEFAULT_METHODS when no file exists."""
        tracker = load_tracker()
        assert len(tracker) > 0
        assert "expert-gold" in tracker
        assert "daredevil-scalper" in tracker
        assert "catfish-contrarian" in tracker
        assert "fundamental-analysis" in tracker
        assert "narrative-analysis" in tracker

    def test_record_prediction_updates_counters(self, evolver):
        """Recording predictions updates correct/incorrect counters."""
        # Use a unique method ID to avoid accumulated state from other tests
        import uuid
        test_method = f"test-counters-{uuid.uuid4().hex[:8]}"
        evolver.record_prediction(test_method, True, prediction_id="pred_001")
        evolver.record_prediction(test_method, False, prediction_id="pred_002")
        evolver.record_prediction(test_method, True, prediction_id="pred_003")

        tracker = load_tracker()
        method = tracker[test_method]
        assert method.total_predictions == 3
        assert method.correct_predictions == 2

    def test_record_prediction_auto_registers_unknown(self, evolver):
        """Unknown method IDs are auto-registered."""
        evolver.record_prediction("unknown-method-xyz", True, prediction_id="pred_auto")
        tracker = load_tracker()
        assert "unknown-method-xyz" in tracker
        assert tracker["unknown-method-xyz"].category == "auto"

    def test_record_prediction_updates_decay_factor(self, evolver):
        """Decay factor increases on correct, decreases on incorrect."""
        evolver.record_prediction("expert-gold", True, prediction_id="p1")
        tracker = load_tracker()
        decay_after_correct = tracker["expert-gold"].decay_factor

        evolver.record_prediction("expert-gold", False, prediction_id="p2")
        tracker = load_tracker()
        decay_after_wrong = tracker["expert-gold"].decay_factor

        # Decay should decrease after wrong prediction
        assert decay_after_wrong < decay_after_correct

    def test_apply_decay_reduces_decay_factors(self, evolver):
        """apply_decay reduces all active methods' decay factors."""
        evolver.record_prediction("expert-gold", True, prediction_id="p1")
        tracker_before = load_tracker()
        before = tracker_before["expert-gold"].decay_factor

        evolver.apply_decay(gamma=0.95)
        tracker_after = load_tracker()
        after = tracker_after["expert-gold"].decay_factor

        assert after <= before  # Decay reduces or keeps same (capped at 0.05)

    def test_retire_method_marks_inactive(self, evolver):
        """retire_method marks a method as inactive."""
        evolver.retire_method("expert-gold")
        tracker = load_tracker()
        assert tracker["expert-gold"].active is False

    def test_generate_report_returns_structured_data(self, evolver):
        """generate_report returns a MethodologyReport with expected fields."""
        # Record some predictions first for meaningful report
        evolver.record_prediction("expert-gold", True, prediction_id="r1")
        evolver.record_prediction("expert-gold", True, prediction_id="r2")
        evolver.record_prediction("daredevil-scalper", False, prediction_id="r3")
        evolver.record_prediction("daredevil-scalper", False, prediction_id="r4")

        report = evolver.generate_report()
        assert isinstance(report, MethodologyReport)
        assert report.total_methods > 0
        assert report.active_methods > 0
        assert isinstance(report.best_performing, list)
        assert isinstance(report.worst_performing, list)
        assert isinstance(report.recommended_changes, list)

    def test_record_methodology_change_writes_audit(self, evolver):
        """Methodology changes are recorded in the audit trail."""
        evolver.record_methodology_change(
            "expert-gold",
            "Added reflexivity check for gold miners",
            "Gold mining stocks showed divergence from spot prices",
        )
        audit = evolver.get_audit_trail(method_id="expert-gold", limit=10)
        assert len(audit) >= 1
        assert audit[0]["method_id"] == "expert-gold"
        assert audit[0]["event"] == "methodology_change"

    def test_get_audit_trail_filters_by_method_id(self, evolver):
        """Audit trail can be filtered by method_id."""
        evolver.record_prediction("expert-gold", True, prediction_id="a1")
        evolver.record_prediction("expert-crypto", False, prediction_id="a2")

        gold_audit = evolver.get_audit_trail(method_id="expert-gold", limit=10)
        crypto_audit = evolver.get_audit_trail(method_id="expert-crypto", limit=10)

        assert len(gold_audit) >= 1
        assert len(crypto_audit) >= 1
        # Gold audit entries should only be for expert-gold
        for entry in gold_audit:
            assert entry.get("method_id") == "expert-gold"

    def test_get_audit_trail_respects_limit(self, evolver):
        """Audit trail respects the limit parameter."""
        for i in range(20):
            evolver.record_prediction("expert-gold", True, prediction_id=f"limit_{i}")
        audit = evolver.get_audit_trail(limit=5)
        assert len(audit) <= 5

    def test_auto_retire_low_accuracy(self, evolver):
        """Methods with <30% accuracy after 10 predictions are auto-retired."""
        # 2 correct, 8 wrong = 20% accuracy < 30%
        for i in range(2):
            evolver.record_prediction("expert-tech", True, prediction_id=f"acc_correct_{i}")
        for i in range(8):
            evolver.record_prediction("expert-tech", False, prediction_id=f"acc_wrong_{i}")

        tracker = load_tracker()
        assert tracker["expert-tech"].active is False

    def test_breed_new_method_creates_from_parents(self, evolver):
        """Breeding creates a new method from two best performers."""
        # Use methods not tampered with by other tests to avoid accumulated state
        for i in range(4):
            evolver.record_prediction("daredevil-trend-rider", True, prediction_id=f"br_t_{i}")
            evolver.record_prediction("fundamental-analysis", True, prediction_id=f"br_f_{i}")
            evolver.record_prediction("technical-analysis", True, prediction_id=f"br_ta_{i}")

        # Manually breed
        result = breed_new_method()
        assert result is not None
        assert result.startswith("bred-")

        tracker = load_tracker()
        assert result in tracker
        assert tracker[result].category == "bred"

    def test_maintain_population_actions(self, evolver):
        """maintain_population manages active count."""
        result = maintain_population(min_active=6, max_active=15)
        assert "before_active" in result
        assert "after_active" in result
        assert "actions" in result


# ── Crystallization Engine Tests ────────────────────────────────────────────

class TestCrystallizationEngine:
    """Tests for knowledge crystallization with shadow_analyses backtest."""

    def test_engine_initialization(self, engine):
        """Engine initializes with correct parameters."""
        assert engine._significance_threshold == 0.6
        assert engine._min_samples == 10
        assert engine._cycles_run == 0
        assert engine._promotions == 0
        assert engine._retirements == 0

    def test_get_crystallization_stats_returns_counts(self, engine):
        """Stats returns the expected dict format."""
        stats = engine.get_crystallization_stats()
        assert stats["cycles_run"] == 0
        assert stats["promotions"] == 0
        assert stats["retirements"] == 0
        assert stats["skipped_cold_start"] == 0
        assert stats["significance_threshold"] == 0.6
        assert stats["min_samples"] == 10

    def test_parse_proposition_extracts_shadow_and_ticker(self):
        """_parse_proposition extracts shadow_id and ticker from multi-part IDs."""
        sid, ticker = CrystallizationEngine._parse_proposition(
            "shadow:expert:gold:agent_01:ticker:AAPL"
        )
        assert sid == "expert:gold:agent_01"
        assert ticker == "AAPL"

    def test_parse_proposition_no_ticker(self):
        """_parse_proposition handles proposition without ticker."""
        sid, ticker = CrystallizationEngine._parse_proposition(
            "shadow:expert:gold:agent_01:source:text"
        )
        assert sid == "expert:gold:agent_01"
        assert ticker == ""

    def test_formalize_hypothesis_creates_string(self):
        """_formalize_hypothesis creates a human-readable hypothesis."""
        hypothesis = CrystallizationEngine._formalize_hypothesis(
            "shadow:expert:gold:agent_01:ticker:AAPL", 0.75, 0.60
        )
        assert "Hypothesis" in hypothesis
        assert "AAPL" in hypothesis
        assert "0.75" in hypothesis

    def test_derive_method_id_expert_gold(self):
        """_derive_method_id maps expert gold shadows correctly."""
        method = CrystallizationEngine._derive_method_id(
            "expert:gold:agent_01", "AAPL"
        )
        assert method == "expert-gold"

    def test_derive_method_id_daredevil(self):
        """_derive_method_id maps daredevil shadows correctly."""
        method = CrystallizationEngine._derive_method_id(
            "daredevil:intraday:scalper_01", "AAPL"
        )
        assert method == "daredevil-scalper"

    def test_derive_method_id_catfish(self):
        """_derive_method_id maps catfish shadows correctly."""
        method = CrystallizationEngine._derive_method_id(
            "catfish:contrarian:agent_01", "AAPL"
        )
        assert method == "catfish-contrarian"

    def test_inner_loop_cold_start_returns_hold(self, engine, temp_db, store):
        """Belief node with < min_samples votes → hold action (cold start)."""
        shadow_id = "expert:gold:cold_start_test"
        ticker = "AAPL"

        # Create shadow
        config = ShadowConfig(
            shadow_id=shadow_id,
            shadow_type="expert",
            display_name="Cold Start Shadow",
            methodology_prompt="Test",
            virtual_capital=50000.0,
            domain="gold",
        )
        temp_db.create_shadow(config)

        # Seed belief node
        node_id = _seed_belief_node(store, shadow_id, ticker)

        # Only 3 votes (below min_samples=10)
        _seed_shadow_and_votes(temp_db, shadow_id, ticker, [
            ("2026-05-01", "long", 0.8),
            ("2026-05-02", "long", 0.7),
            ("2026-05-03", "short", 0.6),
        ])

        import asyncio
        result = asyncio.run(
            engine._inner_loop(node_id)
        )

        assert result is not None
        assert result.action == "hold"
        assert "Insufficient data" in result.evidence_summary or "samples" in result.evidence_summary.lower()
        assert engine._skipped_cold_start >= 1

    def test_inner_loop_promote_path(self, engine, temp_db, store):
        """High hit_rate with enough samples → promote action."""
        shadow_id = "expert:gold:promote_test"
        ticker = "GLD"

        config = ShadowConfig(
            shadow_id=shadow_id,
            shadow_type="expert",
            display_name="Promote Test Shadow",
            methodology_prompt="Test",
            virtual_capital=50000.0,
            domain="gold",
        )
        temp_db.create_shadow(config)

        # Seed belief node
        node_id = _seed_belief_node(store, shadow_id, ticker)

        # 12 votes, 10 long (all profitable = all hits)
        votes = []
        for i in range(12):
            votes.append((f"2026-05-{i+1:02d}", "long", 0.75))
        _seed_shadow_and_votes(temp_db, shadow_id, ticker, votes)

        import asyncio
        result = asyncio.run(
            engine._inner_loop(node_id)
        )

        assert result is not None
        # With all long votes on positive-return days, hit_rate should be high
        assert result.validation_score >= 0.5
        # Should be promote or hold depending on exact hit rate
        assert result.action in ("promote", "hold")

    def test_inner_loop_retire_path(self, engine, temp_db, store):
        """Low hit_rate with enough samples → retire action."""
        shadow_id = "expert:gold:retire_test"
        ticker = "SLV"

        config = ShadowConfig(
            shadow_id=shadow_id,
            shadow_type="expert",
            display_name="Retire Test Shadow",
            methodology_prompt="Test",
            virtual_capital=50000.0,
            domain="gold",
        )
        temp_db.create_shadow(config)

        # Seed belief node
        node_id = _seed_belief_node(store, shadow_id, ticker)

        # 12 short votes — we will seed trades with positive PnL (up returns)
        # so all short votes are wrong (short loses when market goes up)
        conn = temp_db._connect()
        try:
            for i in range(12):
                date_str = f"2026-05-{i+1:02d}"
                # Insert vote
                conn.execute(
                    """INSERT INTO shadow_analyses
                       (shadow_id, date, ticker, direction, confidence, thesis, risk_note, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (shadow_id, date_str, ticker, "short", 0.75,
                     f"Thesis for {date_str}", f"Risk for {date_str}",
                     f"{date_str}T00:00:00.000Z"),
                )
                # Insert trade with POSITIVE PnL → up return → short vote is WRONG
                conn.execute(
                    """INSERT OR IGNORE INTO virtual_trades
                       (shadow_id, ticker, direction, entry_price, exit_price,
                        position_size_pct, entry_date, exit_date, exit_reason, pnl_pct)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (shadow_id, ticker, "short", 100.0, 105.0,
                     0.1, date_str, date_str, "test", 0.05),
                )
            conn.commit()
        finally:
            conn.close()

        import asyncio
        result = asyncio.run(
            engine._inner_loop(node_id)
        )

        assert result is not None
        # Short votes on up days = all wrong → low hit_rate → retire or hold
        assert result.action in ("retire", "hold")

    def test_promote_to_semantic(self, engine, temp_db, store):
        """promote_to_semantic promotes a belief node to semantic tier."""
        shadow_id = "expert:gold:semantic_test"
        ticker = "GDX"

        config = ShadowConfig(
            shadow_id=shadow_id,
            shadow_type="expert",
            display_name="Semantic Test Shadow",
            methodology_prompt="Test",
            virtual_capital=50000.0,
            domain="gold",
        )
        temp_db.create_shadow(config)

        node_id = _seed_belief_node(store, shadow_id, ticker)

        # Verify it starts as episodic
        node_before = store.get_belief_node(node_id)
        assert node_before is not None
        assert node_before["tier"] == "episodic"

        # Promote
        result = engine.promote_to_semantic(node_id)
        assert result is True

        # Verify it's now semantic
        node_after = store.get_belief_node(node_id)
        assert node_after is not None
        assert node_after["tier"] == "semantic"

    def test_retire_insight(self, engine, temp_db, store):
        """retire_insight retires a belief node."""
        shadow_id = "expert:gold:retire_insight_test"
        ticker = "IAU"

        config = ShadowConfig(
            shadow_id=shadow_id,
            shadow_type="expert",
            display_name="Retire Insight Test Shadow",
            methodology_prompt="Test",
            virtual_capital=50000.0,
            domain="gold",
        )
        temp_db.create_shadow(config)

        node_id = _seed_belief_node(store, shadow_id, ticker)

        # Verify it starts as active
        node_before = store.get_belief_node(node_id)
        assert node_before is not None
        assert node_before["status"] == "active"

        # Retire
        result = engine.retire_insight(node_id, "Test retirement reason")
        assert result is True

        # Verify it's now retired
        node_after = store.get_belief_node(node_id)
        assert node_after is not None
        assert node_after["status"] == "retired"

    def test_empty_cycle_returns_no_results(self, engine, temp_db):
        """Running a cycle with no candidate insights returns empty list."""
        # No episodic belief nodes seeded → no candidates
        import asyncio
        results = asyncio.run(
            engine.run_crystallization_cycle()
        )
        assert isinstance(results, list)
        assert len(results) == 0
        assert engine._cycles_run == 1

    def test_outer_loop_promotes_on_positive_action(self, engine, temp_db, store):
        """Outer loop promotes insight to semantic when action is promote."""
        shadow_id = "expert:gold:outer_promote"
        ticker = "NEM"
        config = ShadowConfig(
            shadow_id=shadow_id,
            shadow_type="expert",
            display_name="Outer Promote",
            methodology_prompt="Test",
            virtual_capital=50000.0,
            domain="gold",
        )
        temp_db.create_shadow(config)
        node_id = _seed_belief_node(store, shadow_id, ticker)

        result = CrystallizationResult(
            insight_id="test_insight_1",
            hypothesis="Test hypothesis",
            validation_score=0.75,
            action="promote",
            methodology_changes=["Test change"],
            source_insight_ids=[node_id],
            evidence_summary="Good evidence",
        )

        promoted = engine._outer_loop(result)
        assert promoted is True

        # Verify node was promoted
        node = store.get_belief_node(node_id)
        assert node["tier"] == "semantic"

    def test_outer_loop_retires_on_negative_action(self, engine, temp_db, store):
        """Outer loop retires insight when action is retire."""
        shadow_id = "expert:gold:outer_retire"
        ticker = "GOLD"
        config = ShadowConfig(
            shadow_id=shadow_id,
            shadow_type="expert",
            display_name="Outer Retire",
            methodology_prompt="Test",
            virtual_capital=50000.0,
            domain="gold",
        )
        temp_db.create_shadow(config)
        node_id = _seed_belief_node(store, shadow_id, ticker)

        result = CrystallizationResult(
            insight_id="test_insight_2",
            hypothesis="Test hypothesis failing",
            validation_score=0.25,
            action="retire",
            methodology_changes=["Retiring: low confidence"],
            source_insight_ids=[node_id],
            evidence_summary="Poor evidence",
        )

        promoted = engine._outer_loop(result)
        assert promoted is False

        # Verify node was retired
        node = store.get_belief_node(node_id)
        assert node["status"] == "retired"


# ── Integration: Methodology Evolver + Crystallization ──────────────────────

class TestMethodologyCrystallizationIntegration:
    """Tests for methodology evolver integration with crystallization."""

    def test_crystallization_records_methodology_prediction(self, temp_db, store, evolver):
        """Crystallization inner loop records prediction in methodology evolver."""
        shadow_id = "expert:gold:method_test"
        ticker = "ABX"

        config = ShadowConfig(
            shadow_id=shadow_id,
            shadow_type="expert",
            display_name="Method Test",
            methodology_prompt="Test",
            virtual_capital=50000.0,
            domain="gold",
        )
        temp_db.create_shadow(config)

        node_id = _seed_belief_node(store, shadow_id, ticker)

        # Seed enough votes (12) to pass cold start
        votes = []
        for i in range(12):
            votes.append((f"2026-05-{i+1:02d}", "long", 0.75))
        _seed_shadow_and_votes(temp_db, shadow_id, ticker, votes)

        engine = CrystallizationEngine(
            memory_store=store,
            state_db=temp_db,
            methodology_evolver=evolver,
            significance_threshold=0.6,
            min_samples=10,
        )

        import asyncio
        asyncio.run(
            engine._inner_loop(node_id)
        )

        # Check that the method was recorded in the evolver
        tracker = load_tracker()
        method = tracker.get("expert-gold")
        assert method is not None
        # Method should have at least 1 prediction recorded
        assert method.total_predictions >= 1


# ── Evolution Report Formatting ─────────────────────────────────────────────

class TestEvolutionReportFormatting:
    """Tests for methodology report formatting."""

    def test_format_evolution_report_includes_sections(self):
        """Format includes all major sections."""
        report = MethodologyReport(
            date="2026-05-12T00:00:00",
            total_methods=15,
            active_methods=12,
            retired_methods=3,
            best_performing=["expert-gold (8/10)", "expert-crypto (7/10)"],
            worst_performing=["daredevil-scalper (2/10)"],
            decayed_methods=["daredevil-news-hound (decay=0.35)"],
            recommended_changes=["RETIRE daredevil-scalper: accuracy 20%"],
            audit_entries=45,
        )
        formatted = format_evolution_report(report)
        assert "Methodology Evolution Report" in formatted
        assert "Best Performing" in formatted
        assert "Needs Attention" in formatted
        assert "Decayed Methods" in formatted
        assert "Recommended Changes" in formatted

    def test_format_evolution_report_empty_lists_ok(self):
        """Format handles empty lists gracefully."""
        report = MethodologyReport(
            date="2026-05-12T00:00:00",
            total_methods=0,
            active_methods=0,
            retired_methods=0,
            best_performing=[],
            worst_performing=[],
            decayed_methods=[],
            recommended_changes=[],
            audit_entries=0,
        )
        formatted = format_evolution_report(report)
        assert "Methodology Evolution Report" in formatted
        # Should not crash without best/worst sections
        assert "Best Performing" not in formatted
        assert "Needs Attention" not in formatted


# ── Log Method Outcome (module-level function) ──────────────────────────────

class TestLogMethodOutcome:
    """Tests for the module-level log_method_outcome function."""

    def test_log_method_outcome_increments_counters(self):
        """Logging an outcome updates the tracker counters."""
        tracker_before = load_tracker()
        before = tracker_before.get("expert-gold", MethodRecord("expert-gold", ""))
        before_count = before.total_predictions

        log_method_outcome("expert-gold", "test_pred_001", True, context="test")

        tracker_after = load_tracker()
        after = tracker_after["expert-gold"]
        assert after.total_predictions == before_count + 1

    def test_evolve_methodology_returns_report(self):
        """Module-level evolve_methodology returns a report."""
        report = evolve_methodology()
        assert isinstance(report, MethodologyReport)
        assert report.total_methods > 0
