"""API key rotation with asyncio.Lock and per-key quota tracking.

Extracted from gateway/async_client.py for modular compliance (grandfather reduction).
"""
from __future__ import annotations
import asyncio
import logging

logger = logging.getLogger("marketmind.gateway.key_rotator")

KEY_ROTATE_THRESHOLD = 5  # Preemptively rotate when remaining below this
SHARED_POOL_WARNED = False


class KeyRotator:
    """API key rotation with asyncio.Lock and per-key quota tracking.

    Supports two rotation triggers:
      1. Quota-based: remaining quota from response headers < KEY_ROTATE_THRESHOLD
      2. Usage-based: request count for current key >= max_requests_per_key
         (disabled by default; set max_requests_per_key to enable preemptive rotation)
    """

    def __init__(self, keys: list[str], max_requests_per_key: int | None = None):
        if not keys:
            raise ValueError("At least one API key required")
        self._keys = keys
        self._idx = 0
        self._lock = asyncio.Lock()
        self._remaining: dict[int, int | None] = {i: None for i in range(len(keys))}
        self._request_counts: dict[int, int] = {i: 0 for i in range(len(keys))}
        self.max_requests_per_key = max_requests_per_key

    def current(self) -> str:
        return self._keys[self._idx]

    def update_remaining(self, remaining: int | None) -> None:
        """Update quota remaining for the current key from response headers."""
        self._remaining[self._idx] = remaining

    def current_remaining(self) -> int | None:
        return self._remaining[self._idx]

    def record_request(self) -> None:
        """Increment the request count for the current key."""
        self._request_counts[self._idx] += 1

    def key_status(self) -> dict:
        """Return per-key quota status for monitoring."""
        status = {}
        for i, key in enumerate(self._keys):
            status[f"key_{i}"] = {
                "in_use": i == self._idx,
                "remaining": self._remaining.get(i),
                "request_count": self._request_counts.get(i, 0),
            }
        # Detect shared quota pool
        non_none = [v for v in self._remaining.values() if v is not None]
        if len(non_none) >= 2 and len(set(non_none)) == 1:
            status["_shared_pool_warning"] = True
        return status

    async def rotate(self) -> str:
        async with self._lock:
            self._idx = (self._idx + 1) % len(self._keys)
            # Reset request count for the newly active key so preemptive
            # rotation based on max_requests_per_key starts fresh.
            self._request_counts[self._idx] = 0
            return self._keys[self._idx]

    def needs_rotation(self) -> bool:
        """Check if current key should be preemptively rotated.

        Returns True when:
          - Remaining quota (from API response headers) is below the threshold.
          - Request count for the current key meets or exceeds max_requests_per_key
            (disabled when max_requests_per_key is None, preserving backward compat).
        """
        # Quota-based: remaining below threshold
        rem = self._remaining.get(self._idx)
        if rem is not None and rem < KEY_ROTATE_THRESHOLD:
            return True
        # Usage-based: exceeded max requests per key (preemptive rotation)
        if self.max_requests_per_key is not None:
            count = self._request_counts.get(self._idx, 0)
            if count >= self.max_requests_per_key:
                return True
        return False

    def __len__(self) -> int:
        return len(self._keys)
