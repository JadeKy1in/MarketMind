"""Claude provider via the local CLI (docs/LLM_PROVIDER.md); no real calls here."""
import json

import pytest

from marketmind.gateway import async_client, claude_cli


def test_models_per_tier(monkeypatch):
    monkeypatch.delenv("MARKETMIND_CLAUDE_PRO_MODEL", raising=False)
    monkeypatch.delenv("MARKETMIND_CLAUDE_FLASH_MODEL", raising=False)
    assert claude_cli.model_for("pro") == "opus" and claude_cli.model_for("flash") == "sonnet"
    monkeypatch.setenv("MARKETMIND_CLAUDE_FLASH_MODEL", "haiku")
    assert claude_cli.model_for("flash") == "haiku"


def test_args_disable_tools_settings_and_persistence():
    args = claude_cli.build_args("claude", "opus", "sys.txt")
    for flag in ("-p", "--no-session-persistence", "--strict-mcp-config"):
        assert flag in args
    assert args[args.index("--tools") + 1] == "" and args[args.index("--setting-sources") + 1] == ""
    assert args[args.index("--system-prompt-file") + 1] == "sys.txt"
    assert "--bare" not in args            # --bare ignores the subscription login


def test_parse_output_maps_usage_and_errors():
    ok = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": '{"a":1}',
                     "usage": {"input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 5},
                     "modelUsage": {"claude-opus-5-5": {}}})
    r = claude_cli.parse_output(ok, "opus")
    assert r["content"] == '{"a":1}' and r["model"] == "claude-opus-5-5"
    assert r["usage"] == {"prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105}
    bad = claude_cli.parse_output(json.dumps({"subtype": "error_max_turns", "is_error": True,
                                              "result": "usage limit reached"}), "opus")
    assert "usage limit" in bad["error"]
    assert "unreadable" in claude_cli.parse_output("not json", "opus")["error"]


def test_default_provider_is_deepseek(monkeypatch):
    monkeypatch.delenv("MARKETMIND_LLM", raising=False)
    assert claude_cli.provider() == "deepseek"


@pytest.mark.asyncio
async def test_gateway_uses_claude_then_falls_back(monkeypatch):
    monkeypatch.setenv("MARKETMIND_LLM", "claude")
    monkeypatch.setattr(async_client, "_claude_failures", 0)
    calls = []

    async def fake_call(system, user, tier):
        calls.append(tier)
        return {"content": "hi", "usage": {"total_tokens": 3}, "provider": "claude"}
    monkeypatch.setattr(claude_cli, "call", fake_call)
    assert (await async_client.chat_pro("s", "u"))["provider"] == "claude"
    assert (await async_client.chat_flash("s", "u"))["content"] == "hi"
    assert calls == ["pro", "flash"]

    async def failing(system, user, tier):
        return {"content": "", "error": "claude: usage limit"}
    monkeypatch.setattr(claude_cli, "call", failing)
    fell_back = []

    async def deepseek_gateway():
        fell_back.append(1)
        raise RuntimeError("deepseek path reached")
    monkeypatch.setattr(async_client, "get_gateway", deepseek_gateway)
    for _ in range(3):
        with pytest.raises(RuntimeError, match="deepseek path"):
            await async_client.chat_flash("s", "u")
    assert len(fell_back) == 3 and async_client._claude_failures == 3
    # after three failures in a row Claude is not tried again this run
    monkeypatch.setattr(claude_cli, "call", fake_call)
    with pytest.raises(RuntimeError):
        await async_client.chat_flash("s", "u")
    assert calls == ["pro", "flash"]


@pytest.mark.asyncio
async def test_deepseek_selected_never_calls_claude(monkeypatch):
    monkeypatch.setenv("MARKETMIND_LLM", "deepseek")

    async def boom(*a):
        raise AssertionError("claude must not be called")
    monkeypatch.setattr(claude_cli, "call", boom)
    assert await async_client._try_claude("s", "u", "flash") is None
