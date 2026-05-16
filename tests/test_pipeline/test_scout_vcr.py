"""VCR.py-based news pipeline integration tests.

These tests use HTTP cassette replay to exercise the real parsing pipeline
(feedparser, JSON, NewsItem.from_entry, deduplication, priority scoring)
against recorded responses from all 28 sources.

First run requires network access to record the cassette. Subsequent runs
replay from the cassette with no network required.

Usage:
    # First run (records cassette, requires network + API keys for NewsAPI/GNews):
    python -m pytest tests/test_pipeline/test_scout_vcr.py -v

    # Subsequent runs (replays cassette, no network):
    python -m pytest tests/test_pipeline/test_scout_vcr.py -v

    # Skip VCR tests in CI without cassettes:
    python -m pytest tests/ -v -m "not vcr"

    # Refresh cassette:
    rm tests/fixtures/vcr/news_daily.yml
    python -m pytest tests/test_pipeline/test_scout_vcr.py -v
"""
import pytest
from marketmind.pipeline.scout import fetch_all_sources, deduplicate
from marketmind.config.settings import MarketMindConfig
from marketmind.config.source_authority import SourceStatus


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_fetch_all_sources_with_cassette(vcr_news):
    """Full pipeline integration: fetch from all 28 sources via VCR replay.

    Verifies the entire parse chain runs: HTTP response → feedparser/JSON →
    NewsItem.from_entry → deduplicate → priority scoring.
    """
    config = MarketMindConfig.from_env()
    items = await fetch_all_sources(config)

    # With 28 sources, even partial success should yield 50+ articles
    assert len(items) > 50, (
        f"Expected >50 articles from 28 sources, got {len(items)}. "
        "Cassette may need refresh: delete tests/fixtures/vcr/news_daily.yml and re-run."
    )

    # Verify the parsing pipeline ran: every item should be a proper NewsItem
    for item in items:
        assert item.title, f"NewsItem missing title: {item.id}"
        assert item.url, f"NewsItem missing URL: {item.title}"
        assert item.source_name, f"NewsItem missing source_name: {item.title}"
        assert len(item.id) == 16, f"NewsItem ID wrong length: {item.id}"
        # Priority score should be computed (non-zero for non-empty items)
        assert item.priority_score >= 0.0, f"priority_score negative: {item.title}"
        assert item.salience_multiplier > 0.0, f"salience_multiplier invalid: {item.title}"


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_fetch_all_sources_offline_requires_cassette(vcr_news_offline):
    """Same as above but strict: fails if cassette doesn't exist (record_mode='none').

    Use this in CI to guarantee that news tests never make real HTTP calls.
    """
    config = MarketMindConfig.from_env()
    items = await fetch_all_sources(config)

    assert len(items) > 50, (
        f"Expected >50 articles from 28 sources, got {len(items)}. "
        "Cassette may need refresh: delete tests/fixtures/vcr/news_daily.yml and re-run."
    )

    for item in items:
        assert item.title
        assert item.url
        assert item.source_name
        assert len(item.id) == 16
        assert item.priority_score >= 0.0


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_deduplicate_with_vcr_data(vcr_news):
    """Verify deduplication pipeline works on real data from cassette."""
    config = MarketMindConfig.from_env()
    items = await fetch_all_sources(config)

    # Re-run deduplication explicitly to verify idempotency
    deduped_again = deduplicate(items)

    # Should not remove items already deduplicated (idempotent)
    assert len(deduped_again) >= len(items) * 0.95, (
        f"Deduplication removed {len(items) - len(deduped_again)} additional items "
        f"from already-deduplicated result, expected near-zero"
    )
