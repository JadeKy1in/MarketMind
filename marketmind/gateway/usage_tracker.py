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
_providers: dict[str, int] = {}          # completed calls per provider (claude / deepseek)


def set_stage(stage: str) -> contextvars.Token:
    return _current_stage.set(stage)


def reset_stage(token: contextvars.Token) -> None:
    _current_stage.reset(token)


_fallbacks: dict[str, Any] = {"calls": 0, "reason": ""}   # Claude selected but DeepSeek answered


# Claude CLI errors meaning the login is gone (2026-10-27..11-19: "Failed to authenticate:
# OAuth session expired and could not be refreshed"); only `claude /login` fixes them.
_AUTH_MARKERS = ("failed to authenticate", "oauth", "not logged in", "/login",
                 "invalid api key", "authentication")
LOGIN_HINT = "请在终端运行 `claude /login`（或在 Claude Code 里输入 /login）重新登录"


def is_auth_error(reason: str | None) -> bool:
    return bool(reason) and any(m in str(reason).lower() for m in _AUTH_MARKERS)


def note_fallback(reason: str) -> None:
    """Count one call that was meant for Claude but ran on DeepSeek Flash.
    Keeps the first reason, except that a login failure replaces an earlier other one."""
    _fallbacks["calls"] += 1
    if reason and (not _fallbacks["reason"]
                   or (is_auth_error(reason) and not is_auth_error(_fallbacks["reason"]))):
        _fallbacks["reason"] = str(reason)[:120]


def fallback_notice() -> str:
    """One-line mark for reports / pushes; empty when every call ran on the chosen provider."""
    n = _fallbacks["calls"]
    if not n:
        return ""
    why = f"（{_fallbacks['reason']}）" if _fallbacks["reason"] else ""
    fix = f"{LOGIN_HINT}。" if is_auth_error(_fallbacks["reason"]) else ""
    return f"⚠ Claude 不可用{why}，{n} 次调用已改用 DeepSeek Flash 代跑，结论质量可能低于平时。{fix}"


def fallback_alert(snap: dict) -> tuple[str, str, str] | None:
    """(kind, title, body) of the owner push for one run's snapshot(), or None.

    "auth": any call fell back because Claude is logged out (retrying cannot help).
    "transient": other errors, alerted only when most Claude calls of the run fell back.
    """
    fb = (snap or {}).get("fallback") or {}
    n = int(fb.get("calls") or 0)
    if not n:
        return None
    reason = str(fb.get("reason") or "")
    ok = int(((snap.get("providers") or {}).get("claude")) or 0)
    if is_auth_error(reason):
        return ("auth", "MarketMind：Claude 登录已失效",
                f"本次运行 {n} 次 Claude 调用因登录失效改用 DeepSeek 代跑（{reason}）。"
                f"{LOGIN_HINT}，否则之后每次运行都会降级。")
    if n > ok:
        return ("transient", "MarketMind：Claude 调用大面积失败",
                f"本次运行 {n + ok} 次 Claude 调用中 {n} 次失败、改用 DeepSeek 代跑"
                f"（{reason or '原因未记录'}）。若明天仍出现，请检查 Claude 额度或网络。")
    return None


def reset() -> None:
    _usage.clear()
    _providers.clear()
    _fallbacks.update(calls=0, reason="")


def _provider(result: dict) -> str:
    if result.get("provider"):
        return str(result["provider"])
    model = str(result.get("model") or "").lower()
    return "deepseek" if "deepseek" in model or not model else model


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
    prov = _provider(result)
    _providers[prov] = _providers.get(prov, 0) + 1
    row["prompt_tokens"] += prompt
    row["completion_tokens"] += completion
    row["total_tokens"] += total


def snapshot() -> dict[str, Any]:
    stages = {k: dict(v) for k, v in _usage.items()}
    total = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for row in stages.values():
        for k in total:
            total[k] += row[k]
    return {"stages": stages, "total": total, "providers": dict(_providers),
            "fallback": dict(_fallbacks)}


def summary_line() -> str:
    snap = snapshot()
    if not snap["stages"]:
        return "LLM tokens: none"
    parts = [f"{k} {v['total_tokens']:,}" for k, v in
             sorted(snap["stages"].items(), key=lambda kv: -kv[1]["total_tokens"])]
    t = snap["total"]
    # which provider actually answered: a DeepSeek count here means Claude fell back
    providers = ", ".join(f"{k} {v}" for k, v in sorted(snap["providers"].items()))
    if snap["fallback"]["calls"]:
        providers += f"; Claude->DeepSeek fallback {snap['fallback']['calls']}"
    return (f"LLM tokens: {t['total_tokens']:,} total in {t['calls']} calls "
            f"[{providers}] (prompt {t['prompt_tokens']:,} / completion {t['completion_tokens']:,}) — "
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
