"""Alert content sanitization — strip secrets before broadcast."""
from __future__ import annotations
import re

_API_KEY_RE = re.compile(r'sk-[a-zA-Z0-9]{20,}')
_PATH_RE = re.compile(r'[A-Z]:[\\/][^\s"]+', re.IGNORECASE)
_MAX_DETAIL_LEN = 200


def sanitize(text: str) -> str:
    if not text:
        return text
    text = _API_KEY_RE.sub("sk-***", text)
    text = _PATH_RE.sub("[path]", text)
    if len(text) > _MAX_DETAIL_LEN:
        text = text[:_MAX_DETAIL_LEN] + "..."
    return text
