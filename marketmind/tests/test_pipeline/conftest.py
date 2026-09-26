"""Shared fixtures for pipeline tests, including VCR cassette support."""
import pytest
from pathlib import Path
import vcr


def pytest_configure(config):
    config.addinivalue_line("markers", "vcr: mark test as using VCR cassette replay")


VCR_CASSETTE_DIR = Path(__file__).parent.parent / "fixtures" / "vcr"


@pytest.fixture
def vcr_news():
    """VCR fixture configured with record_mode='new_episodes'.

    Replays from the existing cassette for known requests. Records new
    interactions for unknown requests (requires network + API keys).
    After initial recording, subsequent runs replay from cassette.
    """
    my_vcr = vcr.VCR(
        cassette_library_dir=str(VCR_CASSETTE_DIR),
        record_mode="new_episodes",
        match_on=["method", "scheme", "host", "port", "path", "query"],
    )
    with my_vcr.use_cassette("news_daily.yml"):
        yield


@pytest.fixture
def vcr_news_offline():
    """VCR fixture configured with record_mode='none'.

    Fails immediately if the cassette does not exist — no network calls ever.
    Use this in CI to guarantee that news tests never make real HTTP calls.
    """
    my_vcr = vcr.VCR(
        cassette_library_dir=str(VCR_CASSETTE_DIR),
        record_mode="none",
        match_on=["method", "scheme", "host", "port", "path", "query"],
    )
    with my_vcr.use_cassette("news_daily.yml"):
        yield
