"""Per-stage LLM token usage: @monitor names the stage, chat_flash records it."""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from marketmind.gateway import usage_tracker
from marketmind.gateway.async_client import chat_flash, init_gateway
from marketmind.notification.monitor_decorator import monitor


def _mock_http(prompt, completion):
    resp = MagicMock()
    resp.json.return_value = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion,
                  "total_tokens": prompt + completion},
    }
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    return client


@pytest.fixture(autouse=True)
def _clean():
    usage_tracker.reset()
    yield
    usage_tracker.reset()


def test_record_accumulates_under_default_stage():
    usage_tracker.record({"content": "x", "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    usage_tracker.record({"content": "y", "usage": {"total_tokens": 7}})
    snap = usage_tracker.snapshot()
    assert snap["stages"]["other"] == {"calls": 2, "prompt_tokens": 10,
                                       "completion_tokens": 5, "total_tokens": 22}
    assert snap["total"]["total_tokens"] == 22


def test_failed_or_missing_results_are_not_counted():
    usage_tracker.record(None)
    usage_tracker.record({"content": "", "error": "budget_exhausted", "usage": {}})
    assert usage_tracker.snapshot()["stages"] == {}
    assert usage_tracker.summary_line() == "LLM tokens: none"


def test_fallback_notice_marks_claude_calls_that_ran_on_deepseek():
    assert usage_tracker.fallback_notice() == ""
    usage_tracker.note_fallback("额度用完")
    usage_tracker.note_fallback("")
    notice = usage_tracker.fallback_notice()
    assert "额度用完" in notice and "2 次" in notice and "DeepSeek Flash" in notice
    usage_tracker.record({"content": "x", "usage": {"total_tokens": 1}})
    assert "fallback 2" in usage_tracker.summary_line()
    usage_tracker.reset()
    assert usage_tracker.fallback_notice() == ""


@pytest.mark.asyncio
async def test_empty_truncated_reply_is_retried_once_with_a_bigger_cap():
    def reply(content, finish):
        r = MagicMock()
        r.status_code = 200
        r.raise_for_status.return_value = None
        r.headers = {}
        r.json.return_value = {"choices": [{"message": {"content": content, "reasoning_content": "thinking"},
                                            "finish_reason": finish}],
                               "usage": {"total_tokens": 5}}
        return r

    client = MagicMock()
    client.post = AsyncMock(side_effect=[reply("", "length"), reply("ok", "stop")])
    with patch("httpx.AsyncClient", return_value=client):
        init_gateway("test-key")
        result = await chat_flash("s", "u")
    assert result["content"] == "ok"
    caps = [c.kwargs["json"]["max_tokens"] for c in client.post.call_args_list]
    assert caps[1] == 2 * caps[0]


@pytest.mark.asyncio
async def test_monitored_stage_attributes_calls_including_subtasks():
    @monitor(source="flash_triage")
    async def triage():
        # batches run as child tasks; they inherit the stage
        await asyncio.gather(chat_flash("s", "a"), chat_flash("s", "b"))
        return "done"

    @monitor(source="decision")
    async def decide():
        await chat_flash("s", "c")
        return "done"

    with patch("httpx.AsyncClient", return_value=_mock_http(100, 20)):
        init_gateway("test-key")
        await triage()
        await decide()
        await chat_flash("s", "outside")

    stages = usage_tracker.snapshot()["stages"]
    assert stages["flash_triage"]["calls"] == 2
    assert stages["flash_triage"]["total_tokens"] == 240
    assert stages["decision"]["calls"] == 1
    assert stages["other"]["calls"] == 1
    line = usage_tracker.summary_line()
    assert line.startswith("LLM tokens: 480 total in 4 calls")
    assert "flash_triage 240" in line


def test_calls_are_counted_per_provider():
    from marketmind.gateway import usage_tracker as u
    u.reset()
    u.record({"content": "a", "provider": "claude", "model": "claude-sonnet-5-5", "usage": {"total_tokens": 3}})
    u.record({"content": "b", "model": "deepseek-flash", "usage": {"total_tokens": 2}})
    u.record({"content": "", "error": "x", "model": "deepseek-flash"})        # failed: not counted
    assert u.snapshot()["providers"] == {"claude": 1, "deepseek": 1}
    assert "[claude 1, deepseek 1]" in u.summary_line()
    u.reset()
    assert u.snapshot()["providers"] == {}
