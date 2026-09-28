"""Scrub credentials from every log record before any handler sees it.

httpx errors embed the full request URL, so a failed call to e.g. GNews logs
`...?apikey=<secret>` verbatim (seen in live run 5, 2026-09-27). Redacting at
record creation covers every logger and every handler, including Python's
last-resort stderr handler that daily mode relies on.
"""
from __future__ import annotations

import logging
import re

_SECRET_PARAM = re.compile(
    r"(?i)\b((?:api[_-]?key|apikey|access[_-]?key|access[_-]?token|token|secret|password|auth|key)=)"
    r"[^&\s'\"<>]+"
)
_BEARER = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._\-]{8,}")
# push webhooks that carry the key in the URL path (alerts/notify.py)
_PATH_SECRET = re.compile(r"(?i)(sctapi\.ftqq\.com/|/bot/v2/hook/|\.push\.ft07\.com/send/)"
                          r"[^/\s?&'\"<>]+")

_installed = False


def redact(text: str) -> str:
    text = _SECRET_PARAM.sub(r"\1***", text)
    text = _PATH_SECRET.sub(r"\1***", text)
    return _BEARER.sub(r"\1***", text)


def install() -> None:
    """Wrap the log record factory once per process (idempotent)."""
    global _installed
    if _installed:
        return
    base = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = base(*args, **kwargs)
        try:
            message = record.getMessage()
        except Exception:  # malformed format args: leave the record for logging to report
            return record
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, None
        return record

    logging.setLogRecordFactory(factory)
    _installed = True
