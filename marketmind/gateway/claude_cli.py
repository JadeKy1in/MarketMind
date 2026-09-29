"""Claude backend through the local Claude Code CLI (docs/LLM_PROVIDER.md).

Owner decision 2026-09-28: while the owner has a Claude Max subscription, the
tool runs on Claude; `MARKETMIND_LLM=deepseek` switches back. Claude Code's
headless mode (`claude -p`) is the subscription-backed path (the Anthropic API
and the Agent SDK need a separately billed API key).

Each call is one non-interactive `claude -p` process with every tool disabled,
no session saved, no user/project settings or MCP servers loaded, run from a
neutral working directory so no CLAUDE.md is picked up. The system prompt goes
through a temporary file and the user prompt through stdin (cmd.exe limits a
command line to ~8K characters). Returns the gateway's result shape:
{"content", "usage": {prompt_tokens, completion_tokens, total_tokens}, "model",
"provider"} or {"content": "", "error": ...}.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger("marketmind.gateway.claude_cli")

TIMEOUT_S = float(os.environ.get("MARKETMIND_CLAUDE_TIMEOUT", "600"))
MAX_CONCURRENCY = int(os.environ.get("MARKETMIND_CLAUDE_CONCURRENCY", "4"))
_sem: asyncio.Semaphore | None = None


def provider() -> str:
    return os.environ.get("MARKETMIND_LLM", "deepseek").strip().lower() or "deepseek"


def model_for(tier: str) -> str:
    """Owner decision 2026-09-28: main-pipeline (pro) calls on Opus, the rest on Sonnet."""
    if tier == "pro":
        return os.environ.get("MARKETMIND_CLAUDE_PRO_MODEL", "opus")
    return os.environ.get("MARKETMIND_CLAUDE_FLASH_MODEL", "sonnet")


def _executable() -> str | None:
    return os.environ.get("MARKETMIND_CLAUDE_BIN") or shutil.which("claude")


def _workdir() -> Path:
    d = Path(tempfile.gettempdir()) / "marketmind_claude_cwd"
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_args(exe: str, model: str, system_file: str) -> list[str]:
    return [exe, "-p", "--model", model, "--output-format", "json",
            "--system-prompt-file", system_file, "--tools", "", "--no-session-persistence",
            "--setting-sources", "", "--strict-mcp-config", "--permission-prompts", "none"]


def parse_output(raw: str, model: str) -> dict:
    try:
        data = json.loads(raw)
    except ValueError:
        return {"content": "", "error": f"claude: unreadable output: {raw.strip()[:200]}"}
    if data.get("is_error") or data.get("subtype") != "success":
        return {"content": "", "error": f"claude: {str(data.get('result') or data.get('subtype'))[:200]}"}
    u = data.get("usage") or {}
    prompt = int(u.get("input_tokens") or 0) + int(u.get("cache_read_input_tokens") or 0) \
        + int(u.get("cache_creation_input_tokens") or 0)
    completion = int(u.get("output_tokens") or 0)
    used = list((data.get("modelUsage") or {}).keys())
    return {"content": data.get("result") or "", "provider": "claude",
            "model": used[0] if used else model,
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion,
                      "total_tokens": prompt + completion}}


def _kill(proc) -> None:
    """Kill a child that may already have exited."""
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass


async def call(system_prompt: str, user_prompt: str, tier: str) -> dict:
    global _sem
    exe = _executable()
    if not exe:
        return {"content": "", "error": "claude: CLI not found on PATH"}
    if _sem is None:
        _sem = asyncio.Semaphore(MAX_CONCURRENCY)
    model = model_for(tier)
    fd, system_file = tempfile.mkstemp(prefix="mm_sys_", suffix=".txt", dir=_workdir())
    ufd, user_file = tempfile.mkstemp(prefix="mm_usr_", suffix=".txt", dir=_workdir())
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(system_prompt)
        with os.fdopen(ufd, "wb") as f:
            f.write(user_prompt.encode("utf-8"))
        async with _sem:
            # The prompt is the child's stdin as a FILE, not a pipe we write to: `claude -p`
            # gives up after 3 s without stdin data, and a busy event loop (seen on
            # 2026-09-29, every call fell back to DeepSeek) could not write it in time.
            with open(user_file, "rb") as stdin:
                proc = await asyncio.create_subprocess_exec(
                    *build_args(exe, model, system_file), cwd=str(_workdir()),
                    stdin=stdin, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE)
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT_S)
            except asyncio.TimeoutError:
                _kill(proc)
                await proc.wait()
                return {"content": "", "error": f"claude: timed out after {TIMEOUT_S:.0f}s"}
            except BaseException:
                # Outer cancellation (CancelledError is a BaseException) or an interrupt:
                # never leave an orphaned `claude -p` child running and billing.
                _kill(proc)
                raise
        text = out.decode("utf-8", errors="replace")
        if proc.returncode != 0 and not text.strip():
            return {"content": "", "error": f"claude: exit {proc.returncode}: "
                                            f"{err.decode('utf-8', errors='replace').strip()[:200]}"}
        return parse_output(text, model)
    except Exception as e:
        return {"content": "", "error": f"claude: {type(e).__name__}: {e}"}
    finally:
        for path in (system_file, user_file):
            try:
                os.unlink(path)
            except OSError:
                pass
