"""Which model actually answered each LLM call, per asyncio task (docs/S9_DESIGN.md §2).

A caller opens `trace()` around one decision; every successful chat_flash / chat_pro
call inside it (same task, or tasks it spawns) appends the model that answered —
Claude, or DeepSeek after a Claude fallback. The ledger records `label(calls)`.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

_calls: ContextVar[list[str] | None] = ContextVar("marketmind_llm_calls", default=None)


@contextmanager
def trace() -> Iterator[list[str]]:
    calls: list[str] = []
    token = _calls.set(calls)
    try:
        yield calls
    finally:
        _calls.reset(token)


def note(result: dict[str, Any] | None) -> None:
    """Record the answering model of a completed call (no-op outside `trace()`)."""
    calls = _calls.get()
    if calls is None or not result or result.get("error") or not result.get("content"):
        return
    model = result.get("model")
    if model:
        calls.append(str(model))


def label(calls: list[str]) -> str | None:
    """Models in call order, deduplicated, joined with '+'; None when nothing answered."""
    return "+".join(dict.fromkeys(calls)) or None


def prompt_version(text: str) -> str:
    """Content fingerprint of a methodology prompt: sha256, first 12 hex digits."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]
