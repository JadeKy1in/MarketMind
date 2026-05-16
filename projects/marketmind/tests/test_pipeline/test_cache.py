"""Tests for centralized data cache."""
import pytest
from marketmind.pipeline.cache import DataCache


@pytest.mark.asyncio
async def test_get_returns_none_for_missing_key():
    cache = DataCache(ttl_seconds=300)
    result = await cache.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_set_and_get_roundtrip():
    cache = DataCache(ttl_seconds=300)
    await cache.set("key1", {"data": 42})
    result = await cache.get("key1")
    assert result == {"data": 42}


@pytest.mark.asyncio
async def test_expired_entry_returns_none():
    cache = DataCache(ttl_seconds=0)  # immediately expires
    await cache.set("key1", "value")
    import asyncio
    await asyncio.sleep(0.01)
    result = await cache.get("key1")
    assert result is None


@pytest.mark.asyncio
async def test_invalidate_removes_entry():
    cache = DataCache(ttl_seconds=300)
    await cache.set("key1", "value")
    await cache.invalidate("key1")
    result = await cache.get("key1")
    assert result is None


@pytest.mark.asyncio
async def test_stats_tracks_hits_and_misses():
    cache = DataCache(ttl_seconds=300)
    await cache.get("a")  # miss
    await cache.get("b")  # miss
    await cache.set("a", 1)
    await cache.get("a")  # hit
    await cache.get("a")  # hit
    await cache.get("c")  # miss
    s = cache.stats()
    assert s["hits"] == 2
    assert s["misses"] == 3
    assert s["size"] == 1
    assert 0 < s["hit_rate"] < 100


@pytest.mark.asyncio
async def test_clear_removes_all():
    cache = DataCache(ttl_seconds=300)
    await cache.set("a", 1)
    await cache.set("b", 2)
    await cache.clear()
    assert await cache.get("a") is None
    assert await cache.get("b") is None
    assert cache.stats()["size"] == 0
