"""The calendar luach keeps itself, for an environment with no Google account."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from luach.calendar import times
from luach.calendar.client import Draft, LocalCalendar


def _draft(title: str = "Tennis", hour: int = 16) -> Draft:
    day = (datetime.now(UTC) + timedelta(days=1)).date().isoformat()
    return Draft(title=title, span=times.span(f"{day}T{hour:02d}:00", None, "America/New_York"))


def test_an_event_outlives_the_process_that_made_it():
    """The whole point: dev restarts, and last week's dentist is still there."""
    first = LocalCalendar()
    made = first.insert(_draft(), "America/New_York")

    # A new process, a new object, the same database — as after a deploy.
    again = LocalCalendar()
    assert made.id in again.events
    assert again.get_event(made.id).title == "Tennis"


def test_changes_and_deletions_outlive_it_too():
    cal = LocalCalendar()
    made = cal.insert(_draft(), "America/New_York")
    cal.patch(made.id, {"title": "Tennis with Ana", "location": "The club"}, "America/New_York")

    after_restart = LocalCalendar()
    kept = after_restart.get_event(made.id)
    assert kept.title == "Tennis with Ana" and kept.location == "The club"

    after_restart.delete(made.id)
    assert LocalCalendar().get_event(made.id) is None


def test_it_reads_back_the_shape_the_rest_of_luach_expects():
    cal = LocalCalendar()
    made = cal.insert(_draft(title="Cena", hour=20), "America/New_York")
    read = LocalCalendar().get_event(made.id)
    assert read.start == made.start and read.end == made.end
    assert read.all_day is made.all_day
    assert isinstance(read.recurrence, list) and isinstance(read.attendees, list)
    assert cal.identity()["backend"] == "local"


def test_a_window_only_returns_what_falls_inside_it():
    cal = LocalCalendar()
    soon = cal.insert(_draft(title="Soon"), "America/New_York")
    now = datetime.now(UTC)
    inside = cal.list_events(now, now + timedelta(days=2))
    assert [e.id for e in inside] == [soon.id]
    assert cal.list_events(now + timedelta(days=30), now + timedelta(days=40)) == []


def test_a_repeating_event_is_on_every_day_it_repeats(monkeypatch):
    """Dev listed a repeat on its first day only: weekday breakfast was on
    Thursday and then never again."""
    monkeypatch.setenv("LUACH_TIMEZONE", "America/New_York")
    tz = "America/New_York"
    first = (times.now_in(tz) + timedelta(days=1)).replace(
        hour=7, minute=10, second=0, microsecond=0
    )
    draft = Draft(
        title="Breakfast",
        span=times.span(first.strftime("%Y-%m-%dT%H:%M"), None, tz),
        recurrence=["RRULE:FREQ=DAILY;COUNT=5"],
    )
    cal = LocalCalendar()
    ev = cal.insert(draft, tz)
    listed = cal.list_events(first - timedelta(hours=1), first + timedelta(days=10))
    assert len(listed) == 5
    assert all(e.recurring_event_id == ev.id and e.title == "Breakfast" for e in listed)
    assert listed[1].start.startswith((first + timedelta(days=1)).strftime("%Y-%m-%dT07:10"))
    # An occurrence's id reads that occurrence, with its series' rule, as Google's does.
    third = cal.get_event(listed[2].id)
    assert third is not None and third.id == listed[2].id and third.occurrence
    assert third.recurrence == ev.recurrence and third.recurring_event_id == ev.id
    # Deleting one occurrence deletes that one; deleting the series, them all.
    cal.delete(listed[3].id)
    left = cal.list_events(first - timedelta(hours=1), first + timedelta(days=10))
    assert [e.id for e in left] == [e.id for e in listed if e.id != listed[3].id]
    cal.delete(listed[0].id, scope="series")
    assert cal.list_events(first - timedelta(hours=1), first + timedelta(days=10)) == []
