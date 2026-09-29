"""Credentials in URLs must never reach log output."""
import logging

import marketmind  # noqa: F401  (installs the redacting record factory)
from marketmind.notification.log_redaction import redact


def test_redact_query_params():
    url = "https://gnews.io/api/v4/top-headlines?category=business&apikey=abc123&lang=en"
    assert redact(url) == "https://gnews.io/api/v4/top-headlines?category=business&apikey=***&lang=en"
    assert "s3cr3t" not in redact("x?api_key=s3cr3t&token=t0k and key=k1")
    assert redact("Authorization: Bearer abcdefghijkl") == "Authorization: Bearer ***"
    assert redact("nothing to hide") == "nothing to hide"


def test_log_records_are_redacted(caplog):
    err = RuntimeError("429 for url 'https://gnews.io/api?apikey=f44f5f5c&x=1'")
    with caplog.at_level(logging.WARNING):
        logging.getLogger("marketmind.test").warning("fetch failed for '%s': %s", "GNews", err)
    assert "f44f5f5c" not in caplog.text
    assert "apikey=***" in caplog.text


def test_redact_key_value_and_token_shapes():
    cases = {
        '{"api_key": "FAKEVALUE123", "n": 1}': '{"api_key": "***", "n": 1}',
        "{'password': 'hunter2-fake'}": "{'password': '***'}",
        "x-api-key: FAKEHEADER99": "x-api-key: ***",
        "X-Api-Key:FAKEHEADER99, next": "X-Api-Key:***, next",
        "key sk-ant-FAKE0123456789abcdef used": "key sk-*** used",
        "sk-proj-FAKE_0123456789abcdef": "sk-***",
        '"authorization": "Bearer FAKE+tok/en=="': '"authorization": "Bearer ***"',
        "client(token='FAKETOKEN')": "client(token='***')",
    }
    for raw, want in cases.items():
        assert redact(raw) == want, raw
    # ordinary text is left alone
    for text in ("risk-adjusted return", "tokens: 523", "max_tokens: 100", "task-scheduler ok"):
        assert redact(text) == text


def test_tracebacks_are_redacted(caplog):
    with caplog.at_level(logging.ERROR):
        try:
            raise RuntimeError('call failed: {"api_key": "FAKETRACE42"} Bearer FAKEBEARER123')
        except RuntimeError:
            logging.getLogger("marketmind.test").exception("upstream error")
    assert "FAKETRACE42" not in caplog.text and "FAKEBEARER123" not in caplog.text
    assert "RuntimeError" in caplog.text and "Traceback" in caplog.text


def test_traceback_redacted_through_plain_handler():
    import io
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    log = logging.getLogger("marketmind.test.plain")
    log.addHandler(handler)
    try:
        try:
            raise ValueError("https://gnews.io/api?apikey=FAKEPLAIN77")
        except ValueError:
            log.error("boom", exc_info=True, stack_info=True)
    finally:
        log.removeHandler(handler)
    assert "FAKEPLAIN77" not in buf.getvalue() and "apikey=***" in buf.getvalue()
