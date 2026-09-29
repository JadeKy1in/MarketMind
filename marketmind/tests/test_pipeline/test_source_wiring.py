"""Every registered source must have a fetch path in scout.fetch_source."""
from marketmind.config.source_authority import SOURCES
from marketmind.pipeline.scout import DATA_FETCHERS

# feed types handled by explicit branches in scout.fetch_source
BRANCH_FEED_TYPES = {"congress_api", "sec_form4", "sec_13f", "sec_api", "api", "rss", "html"}


def test_every_source_feed_type_is_dispatched():
    unknown = [(s.name, s.feed_type) for s in SOURCES
               if s.feed_type not in BRANCH_FEED_TYPES and s.feed_type not in DATA_FETCHERS]
    assert unknown == []


def test_source_names_are_unique():
    names = [s.name for s in SOURCES]
    assert len(names) == len(set(names))


def test_data_fetchers_are_coroutines():
    import inspect
    for feed_type, fn in DATA_FETCHERS.items():
        assert inspect.iscoroutinefunction(fn), feed_type


def test_bluesky_source_is_removed():
    # Abandoned 2026-09-29: never had credentials; no source, fetcher or schema entry.
    import importlib.util
    from marketmind.config.flash_output_schema import TOOL_ALLOWLIST
    assert not [s.name for s in SOURCES if "bluesky" in s.name.lower() or "bsky" in s.url]
    assert importlib.util.find_spec("marketmind.pipeline.social_sources") is None
    assert not [v for vs in TOOL_ALLOWLIST.values() for v in vs if "bluesky" in v]
