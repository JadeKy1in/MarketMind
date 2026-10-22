"""Feed dates with US timezone abbreviations (2026-10-22: dateutil warned
"UnknownTimezoneWarning: tzname EDT" every run and returned a naive time read as UTC)."""
import warnings
from datetime import datetime, timedelta, timezone

from marketmind.pipeline.scout_content import parse_published_at


def test_edt_is_understood_without_warning():
    with warnings.catch_warnings():
        warnings.simplefilter("error")                 # UnknownTimezoneWarning would raise
        dt = parse_published_at("Tue, 21 Oct 2026 08:30:00 EDT")
    assert dt == datetime(2026, 10, 21, 12, 30, tzinfo=timezone.utc)
    assert dt.utcoffset() == timedelta(hours=-4)


def test_other_abbreviations_and_existing_forms():
    assert parse_published_at("Mon, 05 Jan 2026 09:00:00 EST").astimezone(timezone.utc).hour == 14
    assert parse_published_at("Mon, 05 Jan 2026 09:00:00 PST").astimezone(timezone.utc).hour == 17
    assert parse_published_at("Mon, 05 Jan 2026 09:00:00 GMT").astimezone(timezone.utc).hour == 9
    assert parse_published_at("2026-10-21T08:30:00Z") == datetime(2026, 10, 21, 8, 30, tzinfo=timezone.utc)
    assert parse_published_at("not a date") is None
    assert parse_published_at("") is None
