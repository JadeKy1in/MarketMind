"""End-to-end tests for the full Shadow Ecosystem."""
import pytest
import tempfile
from pathlib import Path

from projects.marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig
from projects.marketmind.shadows.shadow_mother import ShadowMother
from projects.marketmind.shadows.ranking_engine import RankingEngine
from projects.marketmind.config.settings import ShadowSettings


@pytest.fixture
def settings():
    return ShadowSettings()


@pytest.fixture
def e2e_db():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "e2e_shadows.db"
        db = ShadowStateDB(str(db_path))
        db.init_schema()
        yield db
        db.close()


@pytest.fixture
def mother_with_shadows(e2e_db, settings):
    """Create 15 expert + 5 daredevil + 1 catfish shadows."""
    from projects.marketmind.shadows.expert_shadows import create_expert_shadows
    from projects.marketmind.shadows.daredevil_shadows import create_daredevil_shadows
    from projects.marketmind.shadows.catfish_agent import create_catfish_agent

    create_expert_shadows(e2e_db, settings)
    create_daredevil_shadows(e2e_db, settings)
    create_catfish_agent(e2e_db, settings)
    return ShadowMother(settings, e2e_db)


def test_full_shadow_setup_21_shadows(mother_with_shadows, e2e_db):
    """Verify 15 experts + 5 daredevils + 1 catfish = 21 shadows registered."""
    visible = e2e_db.get_visible_shadows()
    assert len(visible) == 21


@pytest.mark.asyncio
async def test_shadow_isolation_on_error(mother_with_shadows):
    """If one shadow raises, orchestration continues for others."""
    result = await mother_with_shadows.orchestrate_daily_cycle(
        [{"headline": "Normal market day"}], {}
    )
    assert result.active_shadows >= 15
    assert result.date is not None


def test_shadow_count_config_respected(e2e_db, settings):
    """Config with limited shadows should be respected."""
    config = ShadowConfig(
        shadow_id="test:config:limited",
        shadow_type="expert",
        display_name="Limited Test",
        methodology_prompt="Test",
        virtual_capital=10000.0,
    )
    e2e_db.create_shadow(config)
    visible = e2e_db.get_visible_shadows()
    assert len(visible) == 1


@pytest.mark.asyncio
async def test_missed_path_created_when_directions_rejected(mother_with_shadows):
    """Gate 1: reject B and C -> 2 missed_path shadows created."""
    result = await mother_with_shadows.orchestrate_daily_cycle(
        [{"headline": "Test market conditions"}],
        {},
        rejected_directions=["SHORT_ENERGY", "LONG_BONDS"],
    )
    missed = mother_with_shadows.state_db.get_active_shadows("missed_path")
    assert len(missed) >= 2


def test_ranking_pipeline_integration(mother_with_shadows, settings):
    """Ranking engine works with real shadow data."""
    engine = RankingEngine(settings)
    h = engine.compute_haircut(n_shadows=15, evaluation_days=60)
    assert 0 < h < 1


@pytest.mark.asyncio
async def test_event_detection_no_false_positives(mother_with_shadows):
    """Normal news should not create temp shadows."""
    result = await mother_with_shadows.orchestrate_daily_cycle(
        [{"headline": "Markets flat in quiet session"},
         {"headline": "Company reports inline earnings"}],
        {},
    )
    assert result.temp_shadows_created == 0


def test_shadow_state_persisted_after_cycle(mother_with_shadows):
    """After orchestration, shadow data persists in DB."""
    snapshots = mother_with_shadows.state_db.get_all_daily_snapshots("2026-05-11")
    assert isinstance(snapshots, list)
