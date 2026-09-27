"""Smoke tests for the AEL evolution engine (weekly/quarterly review modules removed 2026-09-28, dead code)."""
import pytest
from marketmind.shadows.ael_evolution import AELEvolutionEngine, AELDebriefResult


class TestAELEvolution:
    def test_elite_consolidation_mode(self):
        """ELITE shadows get consolidation note field."""
        engine = AELEvolutionEngine()
        # Verify MAX_ACTIVE_LESSONS documented
        assert engine.MAX_ACTIVE_LESSONS == 5

    def test_debrief_result_has_consolidation(self):
        """AELDebriefResult supports consolidation_note field."""
        result = AELDebriefResult(
            shadow_id="test", month="2026-06",
            win_rate=0.6, cumulative_return=0.1, total_trades=20,
            failure_patterns=[], success_patterns=["momentum"],
            lessons_learned="test", consolidation_note="ELITE consolidation",
        )
        assert result.consolidation_note == "ELITE consolidation"
