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
