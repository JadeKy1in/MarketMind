"""Scrub credentials from every log record before any handler sees it.

httpx errors embed the full request URL, so a failed call to e.g. GNews logs
`...?apikey=<secret>` verbatim (seen in live run 5, 2026-09-27). Redacting at
record creation covers every logger and every handler, including Python's
last-resort stderr handler that daily mode relies on. Tracebacks (exc_info) and
stack dumps are formatted and redacted at creation too; formatters reuse the
cached exc_text instead of formatting the raw exception again.
"""
from __future__ import annotations

import logging
import re

_SECRET_PARAM = re.compile(
    r"(?i)\b((?:api[_-]?key|apikey|access[_-]?key|access[_-]?token|token|secret|password|auth|key)=)"
    r"[^&\s'\"<>]+"
)
_BEARER = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=\-]{8,}")
# "api_key": "...", 'password': '...', token="..." (JSON, dict reprs, kwargs)
_QUOTED_SECRET = re.compile(
    r"""(?i)(["']?\b(?:api[_-]?key|apikey|access[_-]?key|access[_-]?token|auth[_-]?token|"""
    r"""refresh[_-]?token|client[_-]?secret|app[_-]?password|secret|password|token)["']?"""
    r"""\s*[:=]\s*)(["'])[^"'\n]*\2"""
)
# header style: x-api-key: ..., api_key: ...
_COLON_SECRET = re.compile(
    r"(?i)(\b(?:api[_-]?key|apikey|access[_-]?key|access[_-]?token|auth[_-]?token|"
    r"client[_-]?secret|app[_-]?password|secret|password)\s*:\s*)(?![\"'*])[^\s,;\"'}&]+"
)
# provider keys (OpenAI / Anthropic style sk-..., sk-ant-..., sk-proj-...)
_SK_TOKEN = re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")
# push webhooks that carry the key in the URL path (alerts/notify.py)
_PATH_SECRET = re.compile(r"(?i)(sctapi\.ftqq\.com/|/bot/v2/hook/|\.push\.ft07\.com/send/)"
                          r"[^/\s?&'\"<>]+")

_installed = False
_formatter = logging.Formatter()


def redact(text: str) -> str:
    text = _QUOTED_SECRET.sub(r"\1\2***\2", text)
    text = _SECRET_PARAM.sub(r"\1***", text)
    text = _COLON_SECRET.sub(r"\1***", text)
    text = _PATH_SECRET.sub(r"\1***", text)
    text = _SK_TOKEN.sub("sk-***", text)
    return _BEARER.sub(r"\1***", text)


def _redact_traceback(record: logging.LogRecord) -> None:
    try:
        if record.exc_info and record.exc_info[0] is not None and not record.exc_text:
            record.exc_text = redact(_formatter.formatException(record.exc_info))
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
    except Exception:  # fail closed: never emit a traceback we could not scrub
        record.exc_text = "(traceback withheld: redaction failed)"
        record.stack_info = None


def install() -> None:
    """Wrap the log record factory once per process (idempotent)."""
    global _installed
    if _installed:
        return
    base = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = base(*args, **kwargs)
        _redact_traceback(record)
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
