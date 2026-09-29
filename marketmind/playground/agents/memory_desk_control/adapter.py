"""memory_desk_control: the no-memory control twin of memory_desk.

Same universe, same cached daily fact sheet, same system prompt (same
prompt_version), same code rules for stops, hold and confidence; the only difference
is that it gets NO memory section and keeps no memory store. Recorded as its own
Playground source (playground:memory_desk_control) so the promotion ladder can
compare the twins on the same days (docs/PLAYGROUND_AGENTS.md §5; the legacy AEL
experiment required such a replica control group).
"""
from __future__ import annotations

from marketmind.playground.agents.memory_desk.adapter import CONTROL_ID, MOCK_OUTPUT, run_desk

AGENT_ID = CONTROL_ID


async def analyze(context: dict, *, mock: bool = False, **kw) -> dict:
    if mock:
        return dict(MOCK_OUTPUT)
    return await run_desk(context, agent_id=CONTROL_ID, use_memory=False, **kw)
