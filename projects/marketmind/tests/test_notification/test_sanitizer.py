"""Tests for alert content sanitization."""
from marketmind.notification.sanitizer import sanitize


def test_strips_api_key():
    assert sanitize("Key: sk-abcdefghijklmnopqrstuvwxyz123456") == "Key: sk-***"


def test_strips_windows_path():
    result = sanitize(r"Error at E:\AI_Studio_Workspace\projects\marketmind\file.py")
    assert "[path]" in result
    assert "E:" not in result


def test_truncates_long_detail():
    long_text = "x" * 300
    result = sanitize(long_text)
    assert len(result) == 203  # 200 + "..."


def test_empty_ok():
    assert sanitize("") == ""


def test_short_text_unchanged():
    assert sanitize("Stage completed successfully") == "Stage completed successfully"
