"""Shared fixtures for pipeline fixture-based tests."""
import json
import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent


def _fixture_path(stage: str, name: str) -> Path:
    return FIXTURES_DIR / f"{stage}_{name}.json"


def fixture_available(stage: str, name: str = "normal") -> bool:
    return _fixture_path(stage, name).exists()


def load_json_fixture(stage: str, name: str = "normal") -> dict | list:
    """Load a pipeline fixture, skipping scrub validation for testing."""
    path = _fixture_path(stage, name)
    if not path.exists():
        pytest.skip(f"Fixture {stage}/{name} not found. Run --regenerate-fixtures --force first.")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def scout_fixture():
    """Load scout output fixture if available."""
    return load_json_fixture("stage1_scout", "normal")


@pytest.fixture
def flash_fixture():
    """Load flash triage output fixture if available."""
    return load_json_fixture("stage2_flash", "normal")
