"""Extra data sections for shadow contexts (owner decision 2026-09-28: add sources).

Each module in this package may define `FEEDS = [Feed(...), ...]`. A feed names
the shadows it serves by roster short name (`vega_trader`); trial variants of a
shadow (`trial_vega_trader_ab12`) get the same feeds. The runner fetches every
needed feed once per run; the lines appear in the shadow's context under the
feed's title. A feed that fails shows one explicit "unavailable" line, never
silence and never invented numbers. Feeds must compute their lines in code.
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import pkgutil
from dataclasses import dataclass, field
from typing import Awaitable, Callable

logger = logging.getLogger("marketmind.shadow_feeds")

FEED_TIMEOUT_S = 90


@dataclass(frozen=True)
class Feed:
    name: str
    title: str                                   # section heading in the context
    shadows: tuple[str, ...]                     # roster short names
    fetch: Callable[[str], Awaitable[list[str]]] = field(compare=False)   # (today) -> lines


def discover() -> list[Feed]:
    feeds: list[Feed] = []
    for mod in pkgutil.iter_modules(__path__):
        if mod.name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"{__name__}.{mod.name}")
        except Exception:
            logger.warning("shadow feed module %s failed to import", mod.name, exc_info=True)
            continue
        feeds.extend(getattr(module, "FEEDS", []))
    return feeds


def serves(feed: Feed, entry_name: str) -> bool:
    return any(entry_name == n or entry_name.startswith(f"trial_{n}_") for n in feed.shadows)


async def _run(feed: Feed, today: str) -> list[str]:
    try:
        lines = await asyncio.wait_for(feed.fetch(today), timeout=FEED_TIMEOUT_S)
        return list(lines) or [f"- {feed.title}: no data today"]
    except Exception as e:
        logger.warning("shadow feed %s failed: %s", feed.name, e)
        return [f"- {feed.title}: data unavailable today ({type(e).__name__})"]


async def gather(entry_names: list[str], today: str,
                 feeds: list[Feed] | None = None) -> dict[str, dict[str, list[str]]]:
    """entry name -> {section title: lines} for the entries that have feeds."""
    feeds = discover() if feeds is None else feeds
    needed = [f for f in feeds if any(serves(f, n) for n in entry_names)]
    results = await asyncio.gather(*(_run(f, today) for f in needed))
    out: dict[str, dict[str, list[str]]] = {}
    for feed, lines in zip(needed, results):
        for n in entry_names:
            if serves(feed, n):
                out.setdefault(n, {})[feed.title] = lines
    return out
