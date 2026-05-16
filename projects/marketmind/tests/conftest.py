"""Shared fixtures for MarketMind tests."""
import pytest
import tempfile
from pathlib import Path


def pytest_configure(config):
    config.addinivalue_line(
        "filterwarnings",
        "ignore::DeprecationWarning:feedparser.*"
    )


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def mock_flash_response():
    return {
        "content": "Mock Flash analysis result.",
        "usage": {"total_tokens": 200, "prompt_tokens": 80, "completion_tokens": 120},
        "latency_ms": 450,
    }


@pytest.fixture
def mock_pro_response():
    return {
        "content": "Mock Pro deep analysis result with more detail.",
        "usage": {"total_tokens": 500, "prompt_tokens": 100, "completion_tokens": 400},
        "latency_ms": 3200,
    }
