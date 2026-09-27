"""Per-stage LLM token usage for one pipeline run.

@monitor sets the current stage in a ContextVar; chat_flash / chat_pro record
each call's usage under it. Calls outside a monitored stage (e.g. background
shadows) are counted under "other". The daily brief stores snapshot().
"""
from __future__ import annotations

import contextvars
from typing import Any

_current_stage: contextvars.ContextVar[str] = contextvars.ContextVar(
    "marketmind_llm_stage", default="other")

_usage: dict[str, dict[str, int]] = {}


def set_stage(stage: str) -> contextvars.Token:
    return _current_stage.set(stage)


def reset_stage(token: contextvars.Token) -> None:
    _current_stage.reset(token)


def reset() -> None:
    _usage.clear()


def record(result: Any) -> None:
    """Add one completed call's usage block to the current stage."""
    if not isinstance(result, dict) or result.get("error"):
        return
    usage = result.get("usage") or {}
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or 0) or prompt + completion
    row = _usage.setdefault(_current_stage.get(),
                            {"calls": 0, "prompt_tokens": 0,
                             "completion_tokens": 0, "total_tokens": 0})
    row["calls"] += 1
    row["prompt_tokens"] += prompt
    row["completion_tokens"] += completion
    row["total_tokens"] += total


def snapshot() -> dict[str, Any]:
    stages = {k: dict(v) for k, v in _usage.items()}
    total = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for row in stages.values():
        for k in total:
            total[k] += row[k]
    return {"stages": stages, "total": total}


def summary_line() -> str:
    snap = snapshot()
    if not snap["stages"]:
        return "LLM tokens: none"
    parts = [f"{k} {v['total_tokens']:,}" for k, v in
             sorted(snap["stages"].items(), key=lambda kv: -kv[1]["total_tokens"])]
    t = snap["total"]
    return (f"LLM tokens: {t['total_tokens']:,} total in {t['calls']} calls "
            f"(prompt {t['prompt_tokens']:,} / completion {t['completion_tokens']:,}) — "
            + ", ".join(parts))


def append_log(mode: str, path=None) -> None:
    """Append this run's snapshot to <data_dir>/token_usage.jsonl (read by the dashboard)."""
    import json
    import logging
    import os
    from datetime import datetime, timezone
    from pathlib import Path
    snap = snapshot()
    if not snap["stages"]:
        return
    path = Path(path) if path else Path(os.getenv("MARKETMIND_DATA_DIR", "data")) / "token_usage.jsonl"
    now = datetime.now(timezone.utc)
    row = {"date": now.strftime("%Y-%m-%d"), "at": now.isoformat(timespec="seconds"),
           "mode": mode, **snap}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        logging.getLogger("marketmind.gateway.usage_tracker").warning(
            "token usage log not written", exc_info=True)
