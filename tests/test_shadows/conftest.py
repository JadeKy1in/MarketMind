"""Shared fixtures for shadow ecosystem tests."""
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

from marketmind.shadows.shadow_state import ShadowStateDB, ShadowConfig


@pytest.fixture
def temp_shadow_db():
    """Create a temporary ShadowStateDB for testing."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test_shadows.db"
        db = ShadowStateDB(str(db_path))
        db.init_schema()
        yield db
        db.close()


@pytest.fixture
def sample_expert_config():
    return ShadowConfig(
        shadow_id="expert:gold:test_gold_bug",
        shadow_type="expert",
        display_name="Test Gold Bug",
        methodology_prompt="You are a gold market expert.",
        virtual_capital=50000.0,
        domain="gold",
        temperature=0.3,
    )


@pytest.fixture
def sample_daredevil_config():
    return ShadowConfig(
        shadow_id="daredevil:intraday:test_scalper",
        shadow_type="daredevil",
        display_name="Test Scalper",
        methodology_prompt="You are an intraday direction trader.",
        virtual_capital=25000.0,
        temperature=0.5,
    )


@pytest.fixture
def populated_db(temp_shadow_db):
    """Database with 15 diverse shadows for ranking/aggregation tests."""
    domains = ["gold", "crypto", "energy", "bonds", "volatility", "emerging",
               "tech", "financials", "healthcare", "consumer", "metals",
               "agriculture", "real_estate", "fx", "rates"]
    for i, domain in enumerate(domains):
        config = ShadowConfig(
            shadow_id=f"expert:{domain}:agent_{i:02d}",
            shadow_type="expert",
            display_name=f"Expert {domain.title()}",
            methodology_prompt=f"You are a {domain} market expert.",
            virtual_capital=40000.0 + (i * 1000),
            domain=domain,
        )
        temp_shadow_db.create_shadow(config)
    return temp_shadow_db


@pytest.fixture
def mock_flash_call():
    """Mock a Flash API call returning structured content."""
    return AsyncMock(return_value={
        "content": '{"analysis": "mock shadow analysis"}',
        "usage": {"total_tokens": 300},
        "latency_ms": 600,
    })
