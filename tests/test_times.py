from __future__ import annotations

from datetime import date, datetime

import pytest

from luach.calendar import times

TZ = "America/New_York"


def test_date_only_is_all_day_with_exclusive_end():
    sp = times.span("2026-09-20", None, TZ)
    assert sp.all_day and sp.start == date(2026, 9, 20) and sp.end == date(2026, 9, 21)
    s, e = sp.as_google(TZ)
    assert s == {"date": "2026-09-20"} and e == {"date": "2026-09-21"}


def test_naive_datetime_gets_the_member_zone_and_default_length():
    sp = times.span("2026-09-16T15:00", None, TZ)
    assert isinstance(sp.start, datetime) and sp.start.tzinfo is not None
    assert sp.start.isoformat() == "2026-09-16T15:00:00-04:00"
    assert sp.end.isoformat() == "2026-09-16T16:00:00-04:00"


def test_end_before_start_is_refused():
    with pytest.raises(ValueError):
        times.span("2026-09-16T15:00", "2026-09-16T14:00", TZ)


def test_describe_reads_like_a_person():
    sp = times.span("2026-09-16T15:00", "2026-09-16T15:45", TZ)
    assert times.describe(sp.start, sp.end, TZ) == "Wed 16 Sep 2026, 15:00–15:45"
    assert times.describe(date(2026, 9, 20), None, TZ) == "Sun 20 Sep 2026 (all day)"


def test_day_bounds():
    s, e = times.day_bounds("2026-09-16", TZ)
    assert s.isoformat() == "2026-09-16T00:00:00-04:00"
    assert e.isoformat() == "2026-09-16T23:59:59-04:00"


def test_bad_zone_falls_back_to_new_york():
    assert str(times.zone("Nowhere/Land")) == "America/New_York"
