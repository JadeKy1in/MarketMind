"""Centralized data cache with TTL freshness — prevents rate-limit storms."""
from __future__ import annotations
import time
import asyncio
from typing import Any


class DataCache:
    def __init__(self, ttl_seconds: int = 300):
        self._store: dict[str, tuple[float, Any]] = {}
        self._ttl = ttl_seconds
        self._hits = 0
        self._misses = 0
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            cached_at, data = entry
            if time.time() - cached_at > self._ttl:
                del self._store[key]
                self._misses += 1
                return None
            self._hits += 1
            return data

    async def set(self, key: str, data: Any) -> None:
        async with self._lock:
            self._store[key] = (time.time(), data)

    async def invalidate(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "size": len(self._store),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total * 100, 1) if total > 0 else 0.0,
        }

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()
