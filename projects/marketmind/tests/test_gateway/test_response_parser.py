"""Tests for shared response_parser — JSON extraction from LLM output."""
import json
import pytest
from marketmind.gateway.response_parser import extract_json, _strip_fences


def test_extract_json_clean_object():
    data = json.dumps({"key": "value"})
    result = extract_json(data)
    assert result == {"key": "value"}


def test_extract_json_clean_array():
    data = json.dumps([1, 2, 3])
    result = extract_json(data)
    assert result == [1, 2, 3]


def test_extract_json_json_fence():
    data = "```json\n" + json.dumps({"a": 1}) + "\n```"
    result = extract_json(data)
    assert result == {"a": 1}


def test_extract_json_bare_fence():
    data = "```\n" + json.dumps({"a": 1}) + "\n```"
    result = extract_json(data)
    assert result == {"a": 1}


def test_extract_json_with_leading_text():
    data = "Here is your analysis:\n\n" + json.dumps({"result": "ok"})
    result = extract_json(data)
    assert result == {"result": "ok"}


def test_extract_json_bracket_extraction():
    data = "Some text... {\"key\": \"value\"} trailing text"
    result = extract_json(data)
    assert result == {"key": "value"}


def test_extract_json_nested_brackets():
    data = json.dumps({"outer": {"inner": [1, 2, 3]}})
    result = extract_json(data)
    assert result == {"outer": {"inner": [1, 2, 3]}}


def test_extract_json_raises_on_invalid():
    with pytest.raises(ValueError):
        extract_json("This is not JSON at all.")


def test_extract_json_array_with_text():
    data = "Results:\n" + json.dumps([{"a": 1}, {"b": 2}]) + "\nDone."
    result = extract_json(data)
    assert result == [{"a": 1}, {"b": 2}]


def test_strip_fences_no_fence():
    assert _strip_fences("plain text") == "plain text"


def test_strip_fences_full_wrap():
    result = _strip_fences("```\nhello\nworld\n```")
    assert result.strip() == "hello\nworld"
