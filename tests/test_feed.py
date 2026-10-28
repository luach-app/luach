"""The calendar feed's content: what a member's phone calendar is given (luach.feed).

Rendered with ``now`` injected, read back with the icalendar parser, and expanded here
with dateutil, so a repeat is checked by what a calendar app would show, not by the text.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import icalendar
import pytest
from dateutil.rrule import rrulestr

from luach import db, family, feed
from luach.auth import users
from luach.calendar import client, times
from luach.calendar.client import Draft, Event, LocalCalendar

TZ = "America/New_York"
NY = ZoneInfo(TZ)
#: A Tuesday, a few days before the clocks go back (Sunday 1 Nov 2026, 02:00 → 01:00).
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=NY)


@pytest.fixture
def local(monkeypatch) -> LocalCalendar:
    monkeypatch.setenv("LUACH_TIMEZONE", TZ)
    cal = LocalCalendar()
    client.set_calendar(cal)
    return cal


@pytest.fixture
def robin() -> int:
    m = users.member_by_username("robin")
    assert m is not None
    return m.id


@pytest.fixture
def ana() -> int:
    m = users.member_by_username("ana")
    assert m is not None
    return m.id


def put(
    cal: Any,
    title: str,
    start: str,
    end: str | None = None,
    *,
    rule: str = "",
    who: list[str] | None = None,
    **extra: Any,
) -> Event:
    draft = Draft(title=title, span=times.span(start, end, TZ), recurrence=[rule] if rule else [])
    for k, v in extra.items():
        setattr(draft, k, v)
    family.stamp(draft, [family.resolve(n) for n in who or []])
    draft.attendees = list(extra.get("attendees", []))
    return cal.insert(draft, TZ)


def parse(ics: bytes) -> icalendar.Calendar:
    return icalendar.Calendar.from_ical(ics)


def vevents(ics: bytes) -> list[icalendar.Event]:
    return list(parse(ics).walk("VEVENT"))


def _as_dt(value: datetime | date) -> datetime:
    return value if isinstance(value, datetime) else datetime.combine(value, datetime.min.time())


def expand(ics: bytes) -> list[tuple[Any, str]]:
    """Every occurrence a calendar app would show: (start, summary), starts in UTC (or
    dates), RRULE expanded, EXDATEs removed, RECURRENCE-ID overrides applied."""
    masters, overrides = [], {}
    for ve in vevents(ics):
        if "RECURRENCE-ID" in ve:
            overrides[(str(ve["UID"]), _as_dt(ve.decoded("RECURRENCE-ID")))] = ve
        else:
            masters.append(ve)
    out: list[tuple[Any, str]] = []

    def norm(when: datetime | date) -> Any:
        return when.astimezone(UTC) if isinstance(when, datetime) else when

    for ve in masters:
        start = ve.decoded("DTSTART")
        if "RRULE" not in ve:
            out.append((norm(start), str(ve["SUMMARY"])))
            continue
        excluded = set()
        raw = ve.get("EXDATE")
        for prop in raw if isinstance(raw, list) else [raw] if raw is not None else []:
            excluded |= {_as_dt(d.dt) for d in prop.dts}
        rule = rrulestr(ve["RRULE"].to_ical().decode(), dtstart=_as_dt(start))
        for when in rule:
            if when in excluded:
                continue
            over = overrides.get((str(ve["UID"]), when))
            if over is not None:
                out.append((norm(over.decoded("DTSTART")), str(over["SUMMARY"])))
            elif isinstance(start, datetime):
                out.append((norm(when), str(ve["SUMMARY"])))
            else:
                out.append((when.date(), str(ve["SUMMARY"])))
    return sorted(out, key=lambda x: (str(x[0]), x[1]))


class TestTheCalendar:
    def test_it_is_a_calendar_a_parser_reads(self, local, robin):
        put(local, "Dentist", "2026-10-22T15:00", "2026-10-22T15:45")
        ics = feed.render(robin, feed.HOUSEHOLD, now=NOW)
        cal = parse(ics)
        assert str(cal["VERSION"]) == "2.0"
        assert str(cal["PRODID"]).startswith("-//luach//")
        assert str(cal["METHOD"]) == "PUBLISH"
        assert str(cal["X-WR-TIMEZONE"]) == TZ
        assert cal["REFRESH-INTERVAL"].to_ical() == b"PT15M"
        assert cal["X-PUBLISHED-TTL"].to_ical() == b"PT15M"
        (ve,) = vevents(ics)
        assert ve.decoded("DTSTART") == datetime(2026, 10, 22, 15, 0, tzinfo=NY)
        assert ve["DTSTART"].params["TZID"] == TZ
        assert ve.decoded("DTEND") == datetime(2026, 10, 22, 15, 45, tzinfo=NY)
        assert "DTSTAMP" in ve and "LAST-MODIFIED" in ve
        assert b"\r\n" in ics and ics.endswith(b"END:VCALENDAR\r\n")

    def test_the_zone_is_described_with_its_clock_change(self, local, robin):
        put(local, "Swim", "2026-10-30T09:00")
        cal = parse(feed.render(robin, feed.HOUSEHOLD, now=NOW))
        (tz,) = cal.walk("VTIMEZONE")
        assert str(tz["TZID"]) == TZ
        # The zone as the feed describes it, not as this machine's tz database has it.
        described = tz.to_tz()
        offsets = {
            day: datetime(*day, 12, 0, tzinfo=described).utcoffset()
            for day in ((2026, 10, 31), (2026, 11, 1), (2027, 3, 13), (2027, 3, 15))
        }
        assert offsets == {
            (2026, 10, 31): timedelta(hours=-4),
            (2026, 11, 1): timedelta(hours=-5),
            (2027, 3, 13): timedelta(hours=-5),
            (2027, 3, 15): timedelta(hours=-4),
        }

    def test_an_all_day_event_is_a_date(self, local, robin):
        put(local, "Half term", "2026-10-26", "2026-10-28")
        (ve,) = vevents(feed.render(robin, feed.HOUSEHOLD, now=NOW))
        assert ve.decoded("DTSTART") == date(2026, 10, 26)
        assert ve.decoded("DTEND") == date(2026, 10, 28)
        assert ve["DTSTART"].params.get("VALUE") == "DATE"

    def test_the_window_is_a_month_back_and_a_year_ahead(self, local, robin):
        put(local, "Too old", "2026-09-10T10:00")
        put(local, "Last month", "2026-09-25T10:00")
        put(local, "Next autumn", "2027-10-15T10:00")
        put(local, "Too far", "2027-11-01T10:00")
        got = {s for _, s in expand(feed.render(robin, feed.HOUSEHOLD, now=NOW))}
        assert got == {"Last month", "Next autumn"}

    def test_the_same_calendar_is_the_same_bytes(self, local, robin):
        """A stable ETag: nothing in it depends on the moment it was asked for."""
        put(local, "Dentist", "2026-10-22T15:00")
        put(local, "Football", "2026-10-21T17:00", rule="RRULE:FREQ=WEEKLY")
        first = feed.render(robin, feed.HOUSEHOLD, now=NOW)
        again = feed.render(robin, feed.HOUSEHOLD, now=NOW + timedelta(hours=3))
        assert first == again and feed.etag(first) == feed.etag(again)

    def test_uids_are_the_events_own_and_stay(self, local, robin):
        made = put(local, "Dentist", "2026-10-22T15:00")
        (ve,) = vevents(feed.render(robin, feed.HOUSEHOLD, now=NOW))
        assert str(ve["UID"]) == f"{made.id}@luach"
        local.patch(made.id, {"title": "Dentist (moved)", "start": "2026-10-23T15:00"}, TZ)
        (ve,) = vevents(feed.render(robin, feed.HOUSEHOLD, now=NOW))
        assert str(ve["UID"]) == f"{made.id}@luach"

    def test_last_modified_is_when_the_event_changed(self, robin, monkeypatch):
        monkeypatch.setenv("LUACH_TIMEZONE", TZ)
        fake = client.FakeCalendar()
        client.set_calendar(fake)
        ev = put(fake, "Dentist", "2026-10-22T15:00")
        ev.updated = "2026-10-01T08:30:15.123Z"
        (ve,) = vevents(feed.render(robin, feed.HOUSEHOLD, now=NOW))
        assert ve.decoded("LAST-MODIFIED") == datetime(2026, 10, 1, 8, 30, 15, tzinfo=UTC)
        assert ve.decoded("DTSTAMP") == ve.decoded("LAST-MODIFIED")


class TestWhoItIsFor:
    def test_the_people_are_in_the_title_and_the_notes(self, local, robin):
        family.add("Ruby", kind="kid")
        family.add("Lily", kind="kid")
        put(local, "Soccer", "2026-10-22T17:00", who=["Ruby", "Lily"], description="Bring water")
        (ve,) = vevents(feed.render(robin, feed.HOUSEHOLD, now=NOW))
        assert str(ve["SUMMARY"]) == "Ruby and Lily: Soccer"
        assert str(ve["DESCRIPTION"]) == "For Ruby and Lily\n\nBring water"

    def test_a_title_that_already_names_them_is_left_alone(self, local, robin):
        family.add("Ruby", kind="kid")
        put(local, "Ruby's recital", "2026-10-22T17:00", who=["Ruby"])
        (ve,) = vevents(feed.render(robin, feed.HOUSEHOLD, now=NOW))
        assert str(ve["SUMMARY"]) == "Ruby's recital"
        assert str(ve["DESCRIPTION"]) == "For Ruby"

    def test_in_the_members_language(self, local, robin):
        users.update_profile(robin, language="es")
        for name in ("Ruby", "Lily", "Noa"):
            family.add(name, kind="kid")
        put(local, "Fútbol", "2026-10-22T17:00", who=["Ruby", "Lily", "Noa"])
        (ve,) = vevents(feed.render(robin, feed.HOUSEHOLD, now=NOW))
        assert str(ve["DESCRIPTION"]) == "Para Ruby, Lily y Noa"

    def test_names_joined_as_the_app_joins_them(self):
        assert feed.join_names(["Ruby"], "en") == "Ruby"
        assert feed.join_names(["Ruby", "Lily", "Noa"], "en") == "Ruby, Lily, and Noa"
        assert feed.join_names(["רובי", "לילי"], "he") == "רובי ולילי"
        assert feed.join_names(["רובי", "Lily"], "he") == "רובי ו-Lily"

    def test_only_mine_is_mine_and_everyones(self, local, robin):
        family.add("Ruby", kind="kid")
        put(local, "Robin's run", "2026-10-22T07:00", who=["Robin"])
        put(local, "Ruby: soccer", "2026-10-22T17:00", who=["Ruby"])
        put(local, "Robin and Ruby: dentist", "2026-10-23T09:00", who=["Robin", "Ruby"])
        put(local, "Family dinner", "2026-10-24T19:00")
        mine = {s for _, s in expand(feed.render(robin, feed.MINE, now=NOW))}
        assert mine == {"Robin's run", "Robin and Ruby: dentist", "Family dinner"}
        cal = parse(feed.render(robin, feed.MINE, now=NOW))
        assert str(cal["X-WR-CALNAME"]) == "luach · Robin"

    def test_a_member_who_is_nobody_in_the_family_gets_everyones(self, local, ana):
        with db.session() as s:
            for p in s.query(db.Person).all():
                if p.user_id == ana:
                    s.delete(p)
        family.add("Ruby", kind="kid")
        put(local, "Ruby: soccer", "2026-10-22T17:00", who=["Ruby"])
        put(local, "Family dinner", "2026-10-24T19:00")
        assert {s for _, s in expand(feed.render(ana, feed.MINE, now=NOW))} == {"Family dinner"}


class TestRepeats:
    def test_a_weekly_event_is_one_rule_through_the_clock_change(self, local, robin):
        """Sunday swimming at 9:00 stays at 9:00 on the phone when the clocks go back."""
        put(local, "Swimming", "2026-10-18T09:00", "2026-10-18T10:00", rule="RRULE:FREQ=WEEKLY")
        ics = feed.render(robin, feed.HOUSEHOLD, now=NOW)
        (ve,) = vevents(ics)
        assert ve.decoded("DTSTART") == datetime(2026, 10, 18, 9, 0, tzinfo=NY)
        assert ve["RRULE"]["FREQ"] == ["WEEKLY"]
        got = [w for w, _ in expand(ics)][:4]
        assert got == [
            datetime(2026, 10, 18, 13, 0, tzinfo=UTC),
            datetime(2026, 10, 25, 13, 0, tzinfo=UTC),
            datetime(2026, 11, 1, 14, 0, tzinfo=UTC),  # 9:00 EST, an hour later in UTC
            datetime(2026, 11, 8, 14, 0, tzinfo=UTC),
        ]

    def test_a_deleted_and_a_changed_occurrence(self, local, robin):
        series = put(
            local, "Football", "2026-10-21T17:00", "2026-10-21T18:00", rule="RRULE:FREQ=WEEKLY"
        )
        local.delete(f"{series.id}_20261028T170000")
        local.patch(
            f"{series.id}_20261104T170000",
            {"title": "Football (final)", "start": "2026-11-05T18:00"},
            TZ,
        )
        ics = feed.render(robin, feed.HOUSEHOLD, now=NOW)
        master = [ve for ve in vevents(ics) if "RRULE" in ve]
        assert len(master) == 1
        assert [d.dt for d in master[0]["EXDATE"].dts] == [datetime(2026, 10, 28, 17, 0, tzinfo=NY)]
        (override,) = [ve for ve in vevents(ics) if "RECURRENCE-ID" in ve]
        assert str(override["UID"]) == str(master[0]["UID"])
        assert override.decoded("RECURRENCE-ID") == datetime(2026, 11, 4, 17, 0, tzinfo=NY)
        assert override.decoded("DTSTART") == datetime(2026, 11, 5, 18, 0, tzinfo=NY)
        shown = expand(ics)[:4]
        assert shown == [
            (datetime(2026, 10, 21, 21, 0, tzinfo=UTC), "Football"),
            (datetime(2026, 11, 5, 23, 0, tzinfo=UTC), "Football (final)"),
            (datetime(2026, 11, 11, 22, 0, tzinfo=UTC), "Football"),
            (datetime(2026, 11, 18, 22, 0, tzinfo=UTC), "Football"),
        ]

    def test_a_series_is_cut_to_the_window(self, local, robin):
        """Begun a year ago and never ending: the phone gets the window, and only it, so no
        occurrence it shows is one luach did not look at."""
        put(local, "Bins out", "2025-10-01T19:00", rule="RRULE:FREQ=WEEKLY;BYDAY=WE")
        ics = feed.render(robin, feed.HOUSEHOLD, now=NOW)
        (ve,) = vevents(ics)
        assert ve.decoded("DTSTART") == datetime(2026, 9, 23, 19, 0, tzinfo=NY)
        assert ve["RRULE"]["UNTIL"] == [datetime(2027, 10, 20, 23, 0, tzinfo=UTC)]
        shown = [w for w, _ in expand(ics)]
        assert shown[0] == datetime(2026, 9, 23, 23, 0, tzinfo=UTC)
        assert shown[-1] == datetime(2027, 10, 20, 23, 0, tzinfo=UTC)
        assert len(shown) == 57

    def test_a_count_becomes_an_end(self, local, robin):
        put(local, "Lessons", "2026-10-01T16:00", rule="RRULE:FREQ=WEEKLY;COUNT=6")
        ics = feed.render(robin, feed.HOUSEHOLD, now=NOW)
        (ve,) = vevents(ics)
        assert "COUNT" not in ve["RRULE"]
        assert [w.astimezone(NY).date() for w, _ in expand(ics)] == [
            date(2026, 10, 1),
            date(2026, 10, 8),
            date(2026, 10, 15),
            date(2026, 10, 22),
            date(2026, 10, 29),
            date(2026, 11, 5),
        ]

    def test_an_all_day_repeat(self, local, robin):
        series = put(local, "Bin day", "2026-10-20", rule="RRULE:FREQ=WEEKLY;COUNT=4")
        local.delete(f"{series.id}_20261027T000000")
        ics = feed.render(robin, feed.HOUSEHOLD, now=NOW)
        (ve,) = vevents(ics)
        assert ve["RRULE"]["UNTIL"] == [date(2026, 11, 10)]
        assert [d.dt for d in ve["EXDATE"].dts] == [date(2026, 10, 27)]
        assert [w for w, _ in expand(ics)] == [
            date(2026, 10, 20),
            date(2026, 11, 3),
            date(2026, 11, 10),
        ]

    def test_in_only_mine_anothers_occurrence_is_left_out(self, local, robin):
        family.add("Ruby", kind="kid")
        series = put(
            local, "School run", "2026-10-21T08:00", rule="RRULE:FREQ=WEEKLY;COUNT=3", who=["Robin"]
        )
        local.patch(f"{series.id}_20261028T080000", family.leading(family.resolve("Ruby")), TZ)
        ics = feed.render(robin, feed.MINE, now=NOW)
        assert [w.astimezone(NY).date() for w, _ in expand(ics)] == [
            date(2026, 10, 21),
            date(2026, 11, 4),
        ]
        household = feed.render(robin, feed.HOUSEHOLD, now=NOW)
        assert [s for _, s in expand(household)] == [
            "Robin: School run",
            "Ruby: School run",
            "Robin: School run",
        ]

    def test_a_rule_it_cannot_say_exactly_is_listed_one_by_one(self, local, robin):
        series = put(local, "Piano", "2026-10-21T16:00", rule="RRULE:FREQ=WEEKLY;COUNT=3")
        local.events[series.id].recurrence.append("RDATE:20261022T160000")
        ics = feed.render(robin, feed.HOUSEHOLD, now=NOW)
        assert all("RRULE" not in ve for ve in vevents(ics))
        # Its three weeks, and the extra Thursday the RDATE adds.
        assert len({str(ve["UID"]) for ve in vevents(ics)}) == 4


class _GoogleShaped(client.FakeCalendar):
    """A calendar that answers as Google does: occurrences listed one by one, with ids
    ``<series>_<UTC start>Z``, and their series read by its id."""

    def __init__(self, master: Event, occurrences: list[Event]) -> None:
        super().__init__()
        self.master = master
        self.occurrences = occurrences

    def list_events(self, start, end, query="", calendar_ids=None):  # type: ignore[override]
        return [o for o in self.occurrences if start <= times.parse_when(o.start, TZ) < end]

    def get_event(self, event_id, calendar_id=""):  # type: ignore[override]
        return self.master if event_id == self.master.id else None


def _google_occurrence(series: str, start: datetime, title: str = "Yoga") -> Event:
    utc = start.astimezone(UTC)
    return Event(
        id=f"{series}_{utc:%Y%m%dT%H%M%SZ}",
        title=title,
        start=start.isoformat(),
        end=(start + timedelta(hours=1)).isoformat(),
        recurring_event_id=series,
        occurrence=True,
        recurrence=["RRULE:FREQ=WEEKLY;UNTIL=20261115T045959Z"],
        calendar_id="family",
        attendees=["teacher@example.org"],
        organizer="teacher@example.org",
        html_link="https://www.google.com/calendar/event?eid=abc",
    )


class TestGoogleShaped:
    def test_occurrences_by_utc_id_rebuild_their_series(self, robin, monkeypatch):
        monkeypatch.setenv("LUACH_TIMEZONE", TZ)
        start = datetime(2026, 10, 19, 18, 30, tzinfo=NY)
        master = Event(
            id="g1",
            title="Yoga",
            start=start.isoformat(),
            end=(start + timedelta(hours=1)).isoformat(),
            recurrence=["RRULE:FREQ=WEEKLY;UNTIL=20261115T045959Z"],
            calendar_id="family",
            updated="2026-10-02T10:00:00.000Z",
        )
        # 19 Oct, 26 Oct, 2 Nov (after the change), 9 Nov; the 26th was deleted in Google.
        occs = [_google_occurrence("g1", start + timedelta(weeks=w)) for w in (0, 2, 3)]
        client.set_calendar(_GoogleShaped(master, occs))
        ics = feed.render(robin, feed.HOUSEHOLD, now=NOW)
        (ve,) = vevents(ics)
        assert [d.dt for d in ve["EXDATE"].dts] == [datetime(2026, 10, 26, 18, 30, tzinfo=NY)]
        assert [w for w, _ in expand(ics)] == [
            datetime(2026, 10, 19, 22, 30, tzinfo=UTC),
            datetime(2026, 11, 2, 23, 30, tzinfo=UTC),
            datetime(2026, 11, 9, 23, 30, tzinfo=UTC),
        ]
        assert b"teacher@example.org" not in ics and b"google.com" not in ics

    def test_a_series_written_in_another_zone_is_listed_one_by_one(self, robin, monkeypatch):
        """A series at 9:00 in London repeats on London's clock, which changes a week before
        New York's: read on New York's, its occurrences would be an hour out for a week."""
        monkeypatch.setenv("LUACH_TIMEZONE", TZ)
        london = ZoneInfo("Europe/London")
        start = datetime(2026, 10, 19, 9, 0, tzinfo=london)
        master = Event(
            id="g2",
            title="Call with Gran",
            start=start.astimezone(NY).isoformat(),
            end=(start + timedelta(hours=1)).astimezone(NY).isoformat(),
            recurrence=["RRULE:FREQ=WEEKLY;COUNT=3"],
        )
        occs = []
        for w in range(3):
            s = datetime.combine(date(2026, 10, 19) + timedelta(weeks=w), start.timetz())
            occ = _google_occurrence("g2", s, "Call with Gran")
            occ.recurrence = master.recurrence
            occs.append(occ)
        client.set_calendar(_GoogleShaped(master, occs))
        ics = feed.render(robin, feed.HOUSEHOLD, now=NOW)
        assert all("RRULE" not in ve for ve in vevents(ics))
        assert [w for w, _ in expand(ics)] == [
            datetime(2026, 10, 19, 8, 0, tzinfo=UTC),
            datetime(2026, 10, 26, 9, 0, tzinfo=UTC),
            datetime(2026, 11, 2, 9, 0, tzinfo=UTC),
        ]


class TestNothingPrivate:
    def test_no_addresses_links_or_organizers(self, robin, monkeypatch):
        monkeypatch.setenv("LUACH_TIMEZONE", TZ)
        fake = client.FakeCalendar()
        client.set_calendar(fake)
        ev = put(
            fake,
            "Parents' evening",
            "2026-10-22T18:00",
            attendees=["teacher@school.example", "robin@example.com"],
            location="Room 4",
        )
        ev.organizer = "head@school.example"
        ev.creator = "secretary@school.example"
        ev.html_link = "https://calendar.google.com/event?eid=secret"
        ics = feed.render(robin, feed.HOUSEHOLD, now=NOW)
        for private in (b"@school.example", b"robin@example.com", b"eid=secret", b"mailto"):
            assert private not in ics
        (ve,) = vevents(ics)
        for prop in ("ATTENDEE", "ORGANIZER", "URL", "CONTACT"):
            assert prop not in ve
        assert str(ve["LOCATION"]) == "Room 4"

    def test_held_proposals_and_work_calendars_stay_out(self, local, robin):
        put(local, "On the calendar", "2026-10-22T10:00")
        with db.session() as s:
            for status, source in (("pending", ""), ("pending", '{"kind": "email"}')):
                s.add(
                    db.PendingAction(
                        id=f"p-{len(source)}",
                        user_id=robin,
                        principal="robin",
                        tool="create_event",
                        args_json=db.dumps(
                            {"title": "Held dinner at Nonna's", "start": "2026-10-23T19:00"}
                        ),
                        summary="Held dinner at Nonna's",
                        status=status,
                        source_json=source,
                    )
                )
            src = db.BusySource(user_id=robin, name="Work", url="https://work.example/cal.ics")
            s.add(src)
            s.flush()
            s.add(
                db.BusyBlock(
                    source_id=src.id, start="2026-10-22T14:00:00Z", end="2026-10-22T15:00:00Z"
                )
            )
        ics = feed.render(robin, feed.HOUSEHOLD, now=NOW)
        assert [s for _, s in expand(ics)] == ["On the calendar"]
        assert b"Nonna" not in ics and b"work.example" not in ics and b"Busy" not in ics

    def test_text_is_escaped_and_folded_and_cannot_add_a_property(self, local, robin):
        sneaky = "Lunch, then; tea\\ \nATTENDEE:mailto:x@evil.example\r\nEND:VEVENT"
        long_note = "קפה עם סבתא ☕ " * 20
        put(local, sneaky, "2026-10-22T12:00", description=long_note, location="A, B; C")
        ics = feed.render(robin, feed.HOUSEHOLD, now=NOW)
        assert all(len(line) <= 75 for line in ics.split(b"\r\n"))
        (ve,) = vevents(ics)
        assert "ATTENDEE" not in ve
        assert str(ve["SUMMARY"]) == sneaky.replace("\r\n", "\n")
        assert str(ve["LOCATION"]) == "A, B; C"
        assert str(ve["DESCRIPTION"]) == long_note
        # Every line break in the text is written as \n: no line of it starts a property.
        assert b"\r\nATTENDEE" not in ics and ics.count(b"\r\nEND:VEVENT") == 1
