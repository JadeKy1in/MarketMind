"""Shared fixtures for MarketMind tests."""
import pytest
import tempfile
from pathlib import Path

import vcr


def pytest_configure(config):
    config.addinivalue_line(
        "filterwarnings",
        "ignore::DeprecationWarning:feedparser.*"
    )
    config.addinivalue_line(
        "markers",
        "vcr: mark test as using VCR.py cassette (may require network for first recording)",
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


# ── VCR.py News Cassette Fixtures ──────────────────────────────────────────
# Record/replay HTTP calls for 28 news sources at the transport layer so the
# real parsing pipeline (feedparser, JSON, NewsItem.from_entry, deduplication,
# priority scoring) is exercised during replay.
#
# First run (cassette missing): records all sources. Requires network + API keys
# for NewsAPI/GNews. Subsequent runs: replays from cassette, no network needed.
#
# Refresh procedure:
#   1. Delete tests/fixtures/vcr/news_daily.yml
#   2. Run tests again with network access
#   3. Verify cassette was created and tests pass
#
# Edge cases:
#   - If redirect chains change (source moves HTTP→HTTPS, CDN changes),
#     the cassette will fail to match. Delete and re-record.
#   - feedparser may produce slightly different timestamps for RSS entries
#     without published dates. This is pre-existing non-determinism from
#     feedparser filling in datetime.now(), not a VCR.py issue.
#   - API keys (NewsAPI/GNews in query strings) are filtered from the cassette
#     via filter_query_parameters. The cassette NEVER contains real API keys.


@pytest.fixture
def vcr_news():
    """Record/replay news HTTP calls via VCR.py.

    First run (cassette missing): records all 28 sources. Requires network.
    Subsequent runs: replays from cassette. No network required.

    To refresh: delete tests/fixtures/vcr/news_daily.yml and re-run.

    NOTE: If redirect chains change (source moves HTTP→HTTPS, CDN changes),
    the cassette will fail to match. Delete and re-record in that case.

    NOTE: feedparser may produce slightly different timestamps for RSS
    entries without published dates. This is pre-existing non-determinism,
    not a VCR.py issue.
    """
    import os as _os
    from marketmind.config.source_authority import SOURCES

    # Snapshot SOURCES state before recording (prevents mutation leakage)
    saved_state = [
        (s.status, s.consecutive_failures, s.last_checked)
        for s in SOURCES
    ]

    # Clear Z1 content hash cache so cross-run dedup doesn't zero out results
    # when replaying the same cassette twice. The cache file is repopulated by
    # fetch_all_sources() and is safe to delete (it's a 72h dedup tracker).
    _cache_backup = None
    from marketmind.pipeline.scout import _CACHE_PATH as _z1_cache_path
    if _os.path.exists(_z1_cache_path):
        with open(_z1_cache_path, "r", encoding="utf-8") as _f:
            _cache_backup = _f.read()
        _os.remove(_z1_cache_path)

    try:
        with vcr.use_cassette(
            'tests/fixtures/vcr/news_daily.yml',
            record_mode='once',
            decode_compressed_response=True,
            filter_headers=['authorization', 'cookie'],
            filter_query_parameters=['apiKey', 'apikey', 'key'],  # CRITICAL: strip API keys from URLs
            match_on=['method', 'scheme', 'host', 'port', 'path', 'query'],
        ) as cassette:
            yield cassette
    finally:
        # Restore SOURCES state so recording side-effects don't leak
        for i, (status, failures, last_checked) in enumerate(saved_state):
            if i < len(SOURCES):
                SOURCES[i].status = status
                SOURCES[i].consecutive_failures = failures
                SOURCES[i].last_checked = last_checked
        # Restore Z1 cache if it existed before the test
        if _cache_backup is not None:
            _os.makedirs(_os.path.dirname(_z1_cache_path), exist_ok=True)
            with open(_z1_cache_path, "w", encoding="utf-8") as _f:
                _f.write(_cache_backup)


@pytest.fixture
def vcr_news_offline():
    """Offline-only: replay existing cassette, fail if missing.

    Use this variant in CI or offline environments where network access
    is not available and a pre-recorded cassette is expected.
    """
    import os as _os
    from marketmind.config.source_authority import SOURCES

    saved_state = [
        (s.status, s.consecutive_failures, s.last_checked)
        for s in SOURCES
    ]

    # Clear Z1 content hash cache (same rationale as vcr_news fixture)
    _cache_backup = None
    from marketmind.pipeline.scout import _CACHE_PATH as _z1_cache_path
    if _os.path.exists(_z1_cache_path):
        with open(_z1_cache_path, "r", encoding="utf-8") as _f:
            _cache_backup = _f.read()
        _os.remove(_z1_cache_path)

    try:
        with vcr.use_cassette(
            'tests/fixtures/vcr/news_daily.yml',
            record_mode='none',  # fail if cassette doesn't exist
            filter_headers=['authorization', 'cookie'],
            filter_query_parameters=['apiKey', 'apikey', 'key'],
            match_on=['method', 'scheme', 'host', 'port', 'path', 'query'],
        ) as cassette:
            yield cassette
    finally:
        for i, (status, failures, last_checked) in enumerate(saved_state):
            if i < len(SOURCES):
                SOURCES[i].status = status
                SOURCES[i].consecutive_failures = failures
                SOURCES[i].last_checked = last_checked
        if _cache_backup is not None:
            _os.makedirs(_os.path.dirname(_z1_cache_path), exist_ok=True)
            with open(_z1_cache_path, "w", encoding="utf-8") as _f:
                _f.write(_cache_backup)
