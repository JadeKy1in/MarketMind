"""Token budget manager with priority queue and 429 backoff."""
from __future__ import annotations
import time
import enum
from dataclasses import dataclass, field


class Priority(enum.IntEnum):
    CRITICAL = 1
    HIGH = 2
    NORMAL = 3
    SHADOW = 4   # Shadow ecosystem — below NORMAL, above LOW
    LOW = 5


@dataclass
class TokenBudget:
    daily_limit: int
    pro_call_limit: int
    flash_call_limit: int
    tokens_remaining: int = 0
    pro_calls_remaining: int = 0
    flash_calls_remaining: int = 0
    last_reset: float = field(default_factory=time.time)
    _backoff_until: float = 0.0

    def __post_init__(self):
        self.tokens_remaining = self.daily_limit
        self.pro_calls_remaining = self.pro_call_limit
        self.flash_calls_remaining = self.flash_call_limit

    def _maybe_reset(self) -> None:
        now = time.time()
        if now - self.last_reset > 86400:
            self.tokens_remaining = self.daily_limit
            self.pro_calls_remaining = self.pro_call_limit
            self.flash_calls_remaining = self.flash_call_limit
            self.last_reset = now

    def can_call_pro(self) -> bool:
        self._maybe_reset()
        return self.pro_calls_remaining > 0 and self.tokens_remaining > 0

    def can_call_flash(self) -> bool:
        self._maybe_reset()
        return self.flash_calls_remaining > 0 and self.tokens_remaining > 0

    def is_backing_off(self) -> bool:
        return time.time() < self._backoff_until

    def reserve_pro(self, estimated_tokens: int) -> bool:
        self._maybe_reset()
        if self.pro_calls_remaining <= 0 or self.tokens_remaining < estimated_tokens:
            return False
        self.pro_calls_remaining -= 1
        self.tokens_remaining -= estimated_tokens
        return True

    def reserve_flash(self, estimated_tokens: int) -> bool:
        self._maybe_reset()
        if self.flash_calls_remaining <= 0 or self.tokens_remaining < estimated_tokens:
            return False
        self.flash_calls_remaining -= 1
        self.tokens_remaining -= estimated_tokens
        return True

    def release_pro(self, actual_tokens: int) -> None:
        """Full refund of a reservation (call never ran). Use settle_pro after a call."""
        self.tokens_remaining += actual_tokens
        self.pro_calls_remaining += 1

    def release_flash(self, actual_tokens: int) -> None:
        """Full refund of a reservation (call never ran). Use settle_flash after a call."""
        self.tokens_remaining += actual_tokens
        self.flash_calls_remaining += 1

    def settle_pro(self, reserved_tokens: int, used_tokens: int | None) -> None:
        self._settle(reserved_tokens, used_tokens, "pro")

    def settle_flash(self, reserved_tokens: int, used_tokens: int | None) -> None:
        self._settle(reserved_tokens, used_tokens, "flash")

    def _settle(self, reserved: int, used: int | None, kind: str) -> None:
        """Close a reservation after the call.

        used is None -> the call failed and consumed nothing: refund all.
        Otherwise the call counts, and only the unused part of the token
        reservation is returned. (Previously every call was refunded in full,
        so the daily limits could never trigger.)
        """
        if used is None:
            self.tokens_remaining += reserved
            if kind == "pro":
                self.pro_calls_remaining += 1
            else:
                self.flash_calls_remaining += 1
            return
        # refund the unused part, or charge the overrun if the call used more
        self.tokens_remaining += reserved - max(0, used)

    def handle_429(self, retry_after: int) -> float:
        self._backoff_until = time.time() + retry_after + 1.0
        return self._backoff_until

    def reserve_emergency_quota(self, estimated_tokens: int) -> bool:
        """Emergency quota for shadows — bypasses normal limits with cap."""
        self._maybe_reset()
        if self.tokens_remaining < estimated_tokens:
            return False
        self.tokens_remaining -= estimated_tokens
        return True

    def report(self) -> dict:
        self._maybe_reset()
        return {
            "tokens_remaining": self.tokens_remaining,
            "tokens_pct_used": round((1 - self.tokens_remaining / self.daily_limit) * 100, 1),
            "pro_calls_remaining": self.pro_calls_remaining,
            "flash_calls_remaining": self.flash_calls_remaining,
            "backoff_active": self.is_backing_off(),
            "backoff_seconds_left": max(0, self._backoff_until - time.time()),
        }
