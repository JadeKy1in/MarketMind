"""Shared fixtures for pipeline tests, including VCR cassette support."""
import os

import pytest
from pathlib import Path
import vcr


def pytest_configure(config):
    config.addinivalue_line("markers", "vcr: mark test as using VCR cassette replay")


VCR_CASSETTE_DIR = Path(__file__).parent.parent / "fixtures" / "vcr"


@pytest.fixture
def vcr_news():
    """VCR fixture: replay only by default; records new interactions only when
    MARKETMIND_LIVE_TESTS=1 (network + API keys).

    Replay-only keeps the default suite offline: sources added after the
    cassette was recorded fail inside fetch_source and are skipped.
    """
    live = os.environ.get("MARKETMIND_LIVE_TESTS") == "1"
    my_vcr = vcr.VCR(
        cassette_library_dir=str(VCR_CASSETTE_DIR),
        record_mode="new_episodes" if live else "none",
        # Never write API keys into a committed cassette (a GNews and a NewsAPI
        # key were found recorded here on 2026-09-27).
        filter_query_parameters=["apiKey", "apikey", "api_key", "key", "token"],
        filter_headers=["authorization", "x-api-key"],
        # Request bodies can carry credentials (a Bluesky app password was recorded in
        # a createSession body); matching never uses the body, so it is not recorded.
        before_record_request=_drop_request_body,
        match_on=["method", "scheme", "host", "port", "path", "query"],
    )
    with my_vcr.use_cassette("news_daily.yml"):
        yield


def _drop_request_body(request):
    request.body = None
    return request


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
