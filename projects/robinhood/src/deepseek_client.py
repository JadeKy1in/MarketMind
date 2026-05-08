"""
deepseek_client.py — Unified DeepSeek V4 API Client

Single entry point for all LLM calls in the Robinhood project.
Implements the Phase 7.5 specs:
  - V4 model IDs: deepseek-v4-flash / deepseek-v4-pro
  - Dynamic max_tokens (Flash=8192, Pro=128000)
  - X-DeepSeek-Reasoning-Effort via HTTP header
  - Input Repair Layer (validate-then-repair)
  - CoT injection & Chat-to-Tool boundary declarations
  - Structured error codes & _meta diagnostics
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Literal, Optional, Union

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_MODELS = frozenset({"deepseek-v4-flash", "deepseek-v4-pro"})
CALL_PROFILES = frozenset({"reasoning", "analysis", "creative"})
REASONING_EFFORTS = frozenset({"low", "medium", "high", "max"})

DEFAULT_TIMEOUT = 120.0

# Token limits per model (used when caller does not explicitly pass max_tokens)
MODEL_DEFAULT_MAX_TOKENS: Dict[str, int] = {
    "deepseek-v4-flash": 8192,
    "deepseek-v4-pro": 128_000,
}

# Temperature / top_p defaults per call profile
PROFILE_PARAMS: Dict[str, Dict[str, float]] = {
    "reasoning": {"temperature": 0.15, "top_p": 0.90},
    "analysis":  {"temperature": 0.25, "top_p": 0.90},
    "creative":  {"temperature": 0.35, "top_p": 0.95},
}

# ---------------------------------------------------------------------------
# System Prompt helpers (injected at the payload level)
# ---------------------------------------------------------------------------

def _default_role_declaration() -> str:
    return (
        "You are a senior quantitative analyst working on a "
        "proprietary financial analysis system."
    )


def _default_output_contract() -> str:
    return (
        "You MUST output valid JSON matching the following schema. "
        "Do NOT wrap your response in markdown code fences. "
        "All string values must be plain text. Do NOT use Markdown link "
        "syntax like [text](url) in JSON field values. Paths must be "
        "unadorned filesystem paths (e.g., /data/file.json), NOT rendered "
        "as hyperlinks."
    )


def _cot_instruction_profile(call_profile: Optional[str] = None) -> str:
    if call_profile == "reasoning":
        return (
            "Before responding, think step-by-step in <thinking> tags:\n"
            "1. What are the known facts?\n"
            "2. What are the causal chains linking these facts?\n"
            "3. What are the most likely scenarios (base case, bull case, bear case)?\n"
            "4. What is your final assessment?"
        )
    return (
        "Before responding, think step-by-step in <thinking> tags. "
        "Then provide your final answer."
    )


# ---------------------------------------------------------------------------
# Sanitization helpers (response pipeline)
# ---------------------------------------------------------------------------

def _strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` wrapping."""
    return re.sub(
        r"^```(?:json)?\s*\n?(.*?)\n?```\s*$",
        r"\1",
        text.strip(),
        flags=re.DOTALL,
    )


def _unwrap_auto_links(text: str) -> str:
    """
    Unwrap degenerate markdown auto-links like [path](path).
    Real markdown links [click](https://x.com) pass through untouched.
    """
    return re.sub(
        r"\[([^\]]+)\]\(((?!https?://)[^)]+)\)",
        r"\1",
        text,
    )


def _parse_llm_json(raw: str) -> Optional[Dict[str, Any]]:
    """Try to parse a dict from raw LLM output.  Returns None on failure."""
    step = raw.strip()
    # 1. Strip markdown fences
    step = _strip_markdown_fences(step)
    # 2. Unwrap auto-links
    step = _unwrap_auto_links(step)
    # 3. Direct parse
    try:
        return json.loads(step)
    except json.JSONDecodeError:
        pass
    # 4. Regex fallback — find first { ... } block with reasonable depth
    brace_match = re.search(r"\{[^{}]*(\{[^{}]*\}[^{}]*)*\}", step, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass
    return None


# ---------------------------------------------------------------------------
# Input Repair Layer — validate-then-repair
# ---------------------------------------------------------------------------

def _repair_json_payload(
    raw: str,
    schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Validate-then-repair entry point.
    Tries to parse the raw string.  On failure, walks a built-in repair
    sequence (P1→P4).  Returns the parsed dict or raises ValueError.
    """
    # Fast path: try direct parse
    parsed = _parse_llm_json(raw)
    if parsed is not None:
        return parsed

    # Repair sequence — apply heuristics to the original raw string
    text = raw.strip()
    text = _strip_markdown_fences(text)
    text = _unwrap_auto_links(text)

    repairs: List[Dict[str, Any]] = []

    # P1: null for optional field — handled at higher level by repairing dict
    # (already covered by _parse_llm_json / json.loads)

    # P2: stringified JSON array → parse as list
    # Example: '{"items": "["a","b"]"}'  →  '{"items": ["a","b"]}'
    text = re.sub(
        r':\s*"(\[.*?\])"',
        lambda m: ": " + m.group(1).replace('"', '"').replace('\\"', '"'),
        text,
    )

    # P3: {} wrapped single arg where array expected  →  try json.loads
    # and if the value is a dict, wrap in list (applied after the full parse)

    # P4: bare string where array expected
    # (applied at the schema envelope level below)

    # Attempt parse again after P2 remediation
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError(
            f"Repair exhausted: unable to parse LLM output after P1-P4.\n"
            f"Last 500 chars: {text[-500:]}"
        )

    # If caller provided a schema, apply field-level repairs (P3/P4)
    if schema:
        result = _repair_field_types(result, schema, repairs)

    # Log diagnostics (for _meta)
    result["_repair_count"] = len(repairs)
    result["_repair_details"] = repairs

    return result


def _repair_field_types(
    obj: Any,
    schema: Dict[str, Any],
    repairs: List[Dict[str, Any]],
    path: str = "$",
) -> Any:
    """Recursively repair field-level type mismatches (P3, P4)."""
    if isinstance(obj, dict) and isinstance(schema, dict):
        for key, expected_type in schema.items():
            current_path = f"{path}.{key}"
            if key not in obj:
                continue
            val = obj[key]
            expected = expected_type.get("type", "any") if isinstance(expected_type, dict) else "any"

            # P3: dict where list expected → wrap
            if expected == "array" and isinstance(val, dict) and not isinstance(val, list):
                obj[key] = [val]
                repairs.append({
                    "field_path": current_path,
                    "failure_mode": "P3",
                    "repair_applied": "dict→list wrapping",
                })
                continue

            # P4: bare string where list expected → wrap
            if expected == "array" and isinstance(val, str) and not isinstance(val, list):
                obj[key] = [val]
                repairs.append({
                    "field_path": current_path,
                    "failure_mode": "P4",
                    "repair_applied": "bare-string→list wrapping",
                })
                continue

            # Recursively repair nested objects
            if isinstance(val, (dict, list)) and isinstance(expected_type, dict):
                sub_schema = expected_type.get("properties", expected_type)
                if isinstance(val, dict):
                    obj[key] = _repair_field_types(val, sub_schema, repairs, current_path)
                elif isinstance(val, list) and "items" in expected_type:
                    items_schema = expected_type["items"]
                    obj[key] = [
                        _repair_field_types(item, items_schema, repairs, f"{current_path}[{i}]")
                        if isinstance(item, dict) else item
                        for i, item in enumerate(val)
                    ]

    return obj


# ---------------------------------------------------------------------------
# Relational inference
# ---------------------------------------------------------------------------

def _apply_relational_defaults(response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Infer missing relational invariants.  Returns the (possibly mutated) dict.
    All inferences are recorded in response["_meta"]["inferences"].
    """
    inferences: List[str] = []

    # Example: if reasoning_content is present but content is empty, merge
    if (
        response.get("reasoning_content")
        and not response.get("content")
    ):
        response["content"] = response["reasoning_content"]
        inferences.append(
            "reasoning_content → content (content was empty)"
        )

    if inferences:
        meta = response.setdefault("_meta", {})
        meta.setdefault("inferences", []).extend(inferences)

    return response


# ---------------------------------------------------------------------------
# System prompt assembly
# ---------------------------------------------------------------------------

def _assemble_system_prompt(
    user_system_prompt: str,
    template_name: Optional[str] = None,
    call_profile: Optional[str] = None,
    tool_use_prompt: Optional[str] = None,
    disable_cot: bool = False,
) -> str:
    """
    Build the final system prompt by stacking:
      1. (optional) template from config
      2. role declaration
      3. output contract
      4. system law summary
      5. (optional) chat-to-tool boundary declaration
      6. (optional) CoT instruction
      7. user-supplied system prompt (appended last for highest priority)
    """
    parts: List[str] = []
    # 1. Template (future: load from config/system_prompts.json)
    #    For now template_name is a placeholder; can load from a JSON registry.
    if template_name:
        parts.append(f"[Template: {template_name}]")

    # 2. Role
    parts.append(_default_role_declaration())

    # 3. Output contract
    parts.append(_default_output_contract())

    # 4. System law summary
    parts.append(
        "SYSTEM LAWS (non-negotiable): "
        "(1) Output ASCII-only plain text, no emoji. "
        "(2) You are a read-only analysis engine. Never suggest trade execution. "
        "(3) Signal requires >=3/4 dimension resonance. "
        "Empty positions are valid outcomes."
    )

    # 5. Chat-to-tool boundary declaration
    if tool_use_prompt:
        parts.append(
            "You are now issuing a tool call. Tool parameters are passed to "
            "programmatic functions, NOT rendered as chat messages. Do NOT "
            "use Markdown formatting in parameter values. Paths must be "
            "plain filesystem paths."
        )

    # 6. CoT (unless disabled)
    if not disable_cot:
        parts.append(_cot_instruction_profile(call_profile))

    # 7. User-supplied system prompt (highest priority)
    if user_system_prompt:
        parts.append(user_system_prompt)

    return "\n\n".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------

def dispatch_prompt(
    system_prompt: str,
    user_prompt: str,
    *,
    # Mock & Auth
    mock: bool = False,
    ticker: str = "UNKNOWN",
    api_key: Optional[str] = None,
    deepseek_url: Optional[str] = None,
    # Model selection (V4)
    model_name: Literal["deepseek-v4-flash", "deepseek-v4-pro"] = "deepseek-v4-flash",
    reasoning_effort: Optional[Literal["low", "medium", "high", "max"]] = None,
    # Sampling
    call_profile: Optional[Literal["reasoning", "analysis", "creative"]] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    presence_penalty: float = 0.0,
    frequency_penalty: float = 0.0,
    # Prompt control
    template_name: Optional[str] = None,
    tool_use_prompt: Optional[str] = None,
    disable_cot: bool = False,
    # Token control (None = auto-select by model)
    max_tokens: Optional[int] = None,
    timeout_seconds: float = DEFAULT_TIMEOUT,
    # Streaming (Phase 8+)
    stream: bool = False,
    # Expected response schema (for field-level repair)
    response_schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Dispatch a prompt to DeepSeek V4 and return the parsed JSON response.

    Parameters
    ----------
    system_prompt : str
        Custom system prompt from the caller.
    user_prompt : str
        The user / instruction message content.
    mock : bool
        If True, return a canned response without calling the API.
    ticker : str
        Ticker symbol for logging (default "UNKNOWN").
    api_key : str or None
        DeepSeek API key. If None, read from environment.
    deepseek_url : str or None
        Base URL for the DeepSeek API.  Defaults to the official endpoint.
    model_name : "deepseek-v4-flash" | "deepseek-v4-pro"
        V4 model to use.  Default "deepseek-v4-flash".
    reasoning_effort : "low" | "medium" | "high" | "max" | None
        Controls reasoning depth.  Passed via X-DeepSeek-Reasoning-Effort header.
        Only meaningful for deepseek-v4-pro.
    call_profile : "reasoning" | "analysis" | "creative" | None
        Preset for temperature / top_p defaults.
    temperature : float or None
        Override temperature.  If None and call_profile is set, uses profile default.
    top_p : float or None
        Override top_p.  If None and call_profile is set, uses profile default.
    presence_penalty : float
        Default 0.0.
    frequency_penalty : float
        Default 0.0.
    template_name : str or None
        Load a system prompt template from the config registry.
    tool_use_prompt : str or None
        If provided, injects the Chat-to-Tool boundary declaration.
    disable_cot : bool
        If True, skip CoT instruction injection.
    max_tokens : int or None
        Override max_tokens.  None → model-appropriate default.
    timeout_seconds : float
        HTTP request timeout.  Default 120.0.
    stream : bool
        Enable SSE streaming.  (Interface defined; full impl in Phase 8+.)
    response_schema : dict or None
        Optional schema for field-level repair (P3, P4).  If provided, the
        response will be recursively checked for type mismatches.

    Returns
    -------
    dict
        On success: parsed JSON dict with a ``_meta`` key containing diagnostics.
        On failure: ``{"error": {"code": ..., "message": ..., "retryable": ...}}``
        with a ``_meta`` key.
    """
    start_time = time.monotonic()
    meta: Dict[str, Any] = {}

    # ---- resolve parameters ----
    # Validate model_name
    if model_name not in VALID_MODELS:
        return _error_response(
            "INVALID_MODEL",
            f"Model '{model_name}' not in {sorted(VALID_MODELS)}",
            retryable=False,
            _start_time=start_time,
        )

    # Resolve max_tokens
    if max_tokens is None:
        resolved_max_tokens = MODEL_DEFAULT_MAX_TOKENS.get(model_name, 8192)
    else:
        resolved_max_tokens = max_tokens

    # Resolve temperature / top_p
    if call_profile is not None and call_profile not in CALL_PROFILES:
        return _error_response(
            "INVALID_PROFILE",
            f"call_profile '{call_profile}' not in {sorted(CALL_PROFILES)}",
            retryable=False,
            _start_time=start_time,
        )

    profile_defaults = PROFILE_PARAMS.get(call_profile, {})
    resolved_temperature = (
        temperature if temperature is not None
        else profile_defaults.get("temperature", 0.3)
    )
    resolved_top_p = (
        top_p if top_p is not None
        else profile_defaults.get("top_p", 0.9)
    )

    # Validate reasoning_effort
    if reasoning_effort is not None and reasoning_effort not in REASONING_EFFORTS:
        return _error_response(
            "INVALID_REASONING_EFFORT",
            f"reasoning_effort '{reasoning_effort}' not in {sorted(REASONING_EFFORTS)}",
            retryable=False,
            _start_time=start_time,
        )
    if (
        reasoning_effort is not None
        and model_name != "deepseek-v4-pro"
    ):
        logger.warning(
            "reasoning_effort=%s set on model=%s (only meaningful for deepseek-v4-pro)",
            reasoning_effort, model_name,
        )

    # ---- construct system prompt ----
    final_system_prompt = _assemble_system_prompt(
        user_system_prompt=system_prompt,
        template_name=template_name,
        call_profile=call_profile,
        tool_use_prompt=tool_use_prompt,
        disable_cot=disable_cot,
    )

    # ---- populate meta (before API call) ----
    meta.update({
        "model": model_name,
        "temperature": resolved_temperature,
        "top_p": resolved_top_p,
        "max_tokens": resolved_max_tokens,
        "call_profile": call_profile,
        "reasoning_effort": reasoning_effort,
    })

    # ---- mock path ----
    if mock:
        mock_response = {
            "ticker": ticker,
            "signal": "NEUTRAL",
            "confidence": 0.0,
            "rationale": "Mock response — no API call made.",
            "_meta": {**meta, "latency_ms": 0.0},
        }
        return mock_response

    # ---- resolve credentials ----
    from os import environ
    resolved_key = api_key or environ.get("DEEPSEEK_API_KEY")
    if not resolved_key:
        return _error_response(
            "API_KEY_MISSING",
            "No DeepSeek API key provided. Set DEEPSEEK_API_KEY env var or pass api_key.",
            retryable=False,
            _start_time=start_time,
        )

    resolved_url = deepseek_url or "https://api.deepseek.com/chat/completions"

    # ---- build HTTP request ----
    headers: Dict[str, str] = {
        "Authorization": f"Bearer {resolved_key}",
        "Content-Type": "application/json",
    }

    # V4 reasoning_effort is passed via HTTP header, NOT in JSON body
    if reasoning_effort is not None:
        headers["X-DeepSeek-Reasoning-Effort"] = reasoning_effort

    payload: Dict[str, Any] = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": final_system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": resolved_temperature,
        "top_p": resolved_top_p,
        "max_tokens": resolved_max_tokens,
        "stream": stream,
    }

    # Only include penalty params when non-zero (reduce payload size)
    if presence_penalty != 0.0:
        payload["presence_penalty"] = presence_penalty
    if frequency_penalty != 0.0:
        payload["frequency_penalty"] = frequency_penalty

    # ---- execute HTTP call ----
    try:
        logger.info(
            "Dispatching to %s | model=%s | temperature=%.2f | max_tokens=%d",
            resolved_url, model_name, resolved_temperature, resolved_max_tokens,
        )
        response = httpx.post(
            resolved_url,
            headers=headers,
            json=payload,
            timeout=timeout_seconds,
        )
    except httpx.TimeoutException:
        return _error_response(
            "TIMEOUT",
            f"Request to {resolved_url} timed out after {timeout_seconds}s",
            retryable=True,
            _start_time=start_time,
        )
    except httpx.HTTPError as exc:
        return _error_response(
            "HTTP_ERROR",
            f"HTTP request failed: {exc}",
            retryable=True,
            _start_time=start_time,
        )

    latency_ms = (time.monotonic() - start_time) * 1000
    meta["latency_ms"] = round(latency_ms, 1)

    # ---- handle HTTP status ----
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        try:
            retry_after_seconds = int(retry_after) if retry_after else None
        except (ValueError, TypeError):
            retry_after_seconds = None
        return _error_response(
            "RATE_LIMITED",
            f"Rate limited. Retry-After: {retry_after}",
            retryable=True,
            retry_after=retry_after_seconds,
            _start_time=start_time,
            _extra_meta=meta,
        )

    if response.status_code != 200:
        try:
            body = response.json()
        except Exception:
            body = response.text[:500]
        return _error_response(
            f"HTTP_{response.status_code}",
            f"Non-200 response: {body}",
            retryable=500 <= response.status_code < 600,
            _start_time=start_time,
            _extra_meta=meta,
        )

    # ---- parse response body ----
    try:
        body = response.json()
    except json.JSONDecodeError as exc:
        return _error_response(
            "PARSE_FAILURE",
            f"Failed to parse response JSON: {exc}",
            retryable=False,
            _start_time=start_time,
            _extra_meta=meta,
        )

    # Extract usage info
    usage = body.get("usage", {})
    meta["prompt_token_count"] = usage.get("prompt_tokens")
    meta["completion_token_count"] = usage.get("completion_tokens")

    # Extract assistant content
    choices = body.get("choices", [])
    if not choices:
        return _error_response(
            "NO_CHOICES",
            "Response contained no choices",
            retryable=False,
            _start_time=start_time,
            _extra_meta=meta,
        )

    choice = choices[0]
    message = choice.get("message", {})
    raw_content = message.get("content", "")
    reasoning_content = message.get("reasoning_content")

    if not raw_content and reasoning_content:
        raw_content = reasoning_content

    # ---- parse JSON from LLM output ----
    try:
        parsed = _repair_json_payload(raw_content, schema=response_schema)
    except ValueError as exc:
        return _error_response(
            "PARSE_FAILURE",
            f"Failed to parse LLM output: {exc}",
            retryable=False,
            _start_time=start_time,
            _extra_meta=meta,
        )

    # ---- surface repair diagnostics ----
    if "_repair_count" in parsed:
        meta["repair_count"] = parsed.pop("_repair_count", 0)
        meta["repair_details"] = parsed.pop("_repair_details", [])
    else:
        meta["repair_count"] = 0
        meta["repair_details"] = []

    # ---- relational inference ----
    parsed["_meta"] = meta
    parsed = _apply_relational_defaults(parsed)

    return parsed


# ---------------------------------------------------------------------------
# Error response builder
# ---------------------------------------------------------------------------

def _error_response(
    code: str,
    message: str,
    retryable: bool,
    *,
    retry_after: Optional[int] = None,
    _start_time: Optional[float] = None,
    _extra_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a standardized error dict with _meta."""
    meta: Dict[str, Any] = {}
    if _extra_meta:
        meta.update(_extra_meta)
    if _start_time is not None:
        meta["latency_ms"] = round((time.monotonic() - _start_time) * 1000, 1)

    result: Dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "retry_after_seconds": retry_after,
        },
        "_meta": meta,
    }
    logger.error("API error [%s]: %s", code, message)
    return result


# ---------------------------------------------------------------------------
# Convenience subclass for streaming (Phase 8+)
# ---------------------------------------------------------------------------

class AsyncDeepSeekClient:
    """Async wrapper for streaming / chunked responses (stub — Phase 8+)."""

    async def dispatch_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        **kwargs: Any,
    ) -> Any:
        raise NotImplementedError("Streaming support is planned for Phase 8+")