"""Repeating events: one occurrence changed or deleted on its own, or the whole series.

School on weekdays and football on Tuesdays are most of a family's calendar. An
occurrence was listed as if it did not repeat, so the form opened on it said
"Does not repeat" and sent that back, stopping the series; on the local calendar
changing or deleting one occurrence changed or deleted them all. Every path is
tried here — the calendar API, the agent's tools — on both backends: the local
calendar, and the real Google client against a stand-in for Google's API that
keeps Google's instance semantics.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from dateutil.rrule import rrulestr
from googleapiclient.errors import HttpError
from httpx import ASGITransport, AsyncClient

from luach import db
from luach.agent import context, tools
from luach.app import create_app
from luach.auth import users
from luach.calendar import client as cal
from luach.calendar import repeats, times

TZ = "America/New_York"
CID = "family@x"
SEPTEMBER = "/api/calendar/events?start=2026-09-01&end=2026-09-30"
TUESDAYS = ["2026-09-01", "2026-09-08", "2026-09-15", "2026-09-22", "2026-09-29"]


# -- Google, as far as repeating events go -------------------------------------------


class _Req:
    def __init__(self, fn: Any) -> None:
        self.fn = fn

    def execute(self) -> Any:
        return self.fn()


def _refused(status: int) -> _Req:
    def fail() -> Any:
        raise HttpError(SimpleNamespace(status=status, reason="x"), b"")

    return _Req(fail)


def _merge(into: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """A PATCH: nested objects merged, a None clears."""
    out = dict(into)
    for k, v in body.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            v = {**out[k], **v}
        if isinstance(v, dict):
            v = {kk: vv for kk, vv in v.items() if vv is not None}
        out[k] = v
    return out


class GoogleWithRepeats:
    """Google's events API for a household with repeating events.

    A series is listed (``singleEvents``) as its instances, each with the id
    ``<series>_<start in UTC>`` (``<series>_<YYYYMMDD>`` all day), its
    ``recurringEventId`` and no ``recurrence``. An instance's id reads that
    instance, patches it alone (Google keeps an exception) and deletes it alone
    (the instance is cancelled); an instance refuses a ``recurrence`` (400).
    """

    def __init__(self, tz: str = TZ) -> None:
        self.tz = ZoneInfo(tz)
        self.items: dict[str, dict[str, Any]] = {}
        self.exceptions: dict[str, Any] = {}
        self.made = 0
        self.patched: list[str] = []

    def events(self) -> GoogleWithRepeats:
        return self

    def calendarList(self) -> Any:  # noqa: N802 - Google's name
        page = {"items": [{"id": CID, "summary": "Family", "primary": True}]}
        return SimpleNamespace(list=lambda **kw: _Req(lambda: page))

    def _local(self, part: dict[str, Any]) -> datetime | date:
        if part.get("dateTime"):
            when = datetime.fromisoformat(part["dateTime"])
            if when.tzinfo is None:
                when = when.replace(tzinfo=self.tz)
            return when.astimezone(self.tz).replace(tzinfo=None)
        return date.fromisoformat(part["date"])

    def _instances(self, sid: str) -> dict[str, dict[str, Any]]:
        item = self.items[sid]
        s, e = self._local(item["start"]), self._local(item["end"])
        all_day = not isinstance(s, datetime)
        base = datetime.combine(s, time()) if all_day else s
        span = e - s  # type: ignore[operator]
        rule = rrulestr("\n".join(item["recurrence"]), dtstart=base)
        out = {}
        for when in rule.between(base, base + timedelta(days=400), inc=True):
            if all_day:
                iid = f"{sid}_{when:%Y%m%d}"
                st = {"date": when.date().isoformat()}
                en = {"date": (when.date() + span).isoformat()}
            else:
                aware = when.replace(tzinfo=self.tz)
                iid = f"{sid}_{aware.astimezone(UTC):%Y%m%dT%H%M%SZ}"
                st = {"dateTime": aware.isoformat(), "timeZone": str(self.tz)}
                en = {"dateTime": (aware + span).isoformat(), "timeZone": str(self.tz)}
            inst = {k: v for k, v in item.items() if k != "recurrence"}
            inst.update(id=iid, recurringEventId=sid, originalStartTime=dict(st), start=st, end=en)
            exc = self.exceptions.get(iid)
            if exc == "cancelled":
                inst = {"id": iid, "recurringEventId": sid, "status": "cancelled"}
            elif exc:
                inst = _merge(inst, exc)
            out[iid] = inst
        return out

    def _instance(self, iid: str) -> dict[str, Any] | None:
        sid = iid.rpartition("_")[0]
        if sid in self.items and self.items[sid].get("recurrence"):
            return self._instances(sid).get(iid)
        return None

    def _instant(self, part: dict[str, Any]) -> datetime:
        when = self._local(part)
        if not isinstance(when, datetime):
            when = datetime.combine(when, time())
        return when.replace(tzinfo=self.tz)

    def list(self, **kw: Any) -> _Req:
        lo = datetime.fromisoformat(kw["timeMin"].replace("Z", "+00:00"))
        hi = datetime.fromisoformat(kw["timeMax"].replace("Z", "+00:00"))
        found = []
        for eid, item in self.items.items():
            many = self._instances(eid).values() if item.get("recurrence") else [dict(item, id=eid)]
            for one in many:
                if one.get("status") == "cancelled":
                    continue
                if self._instant(one["start"]) < hi and self._instant(one["end"]) > lo:
                    found.append(one)
        found.sort(key=lambda i: self._instant(i["start"]))
        return _Req(lambda: {"items": found})

    def get(self, calendarId: str, eventId: str) -> _Req:  # noqa: N803 - Google's names
        if eventId in self.items:
            return _Req(lambda: dict(self.items[eventId], id=eventId))
        inst = self._instance(eventId)
        return _Req(lambda: inst) if inst is not None else _refused(404)

    def insert(self, calendarId: str, body: dict, sendUpdates: str | None = None) -> _Req:  # noqa: N803
        self.made += 1
        eid = f"ev{self.made}"
        self.items[eid] = dict(body)
        return _Req(lambda: dict(body, id=eid))

    def patch(
        self, calendarId: str, eventId: str, body: dict, sendUpdates: str | None = None
    ) -> _Req:  # noqa: N803
        self.patched.append(eventId)
        if eventId in self.items:
            self.items[eventId] = _merge(self.items[eventId], body)
            return _Req(lambda: dict(self.items[eventId], id=eventId))
        if self._instance(eventId) is None:
            return _refused(404)
        if "recurrence" in body:
            return _refused(400)  # an instance cannot repeat on its own
        self.exceptions[eventId] = _merge(self.exceptions.get(eventId) or {}, body)
        return _Req(lambda: self._instance(eventId))

    def delete(self, calendarId: str, eventId: str) -> _Req:  # noqa: N803
        if eventId in self.items:
            self.items.pop(eventId)
            return _Req(lambda: "")
        if self._instance(eventId) is None:
            return _refused(404)
        self.exceptions[eventId] = "cancelled"
        return _Req(lambda: "")


# -- fixtures --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def zone(monkeypatch):
    monkeypatch.setenv("LUACH_TIMEZONE", TZ)
    users.update_profile(1, timezone=TZ)


@pytest.fixture
def google(tmp_path) -> GoogleWithRepeats:
    key = tmp_path / "sa.json"
    key.write_text(json.dumps({"client_email": "sa@x"}))
    g = cal.GoogleCalendar(str(key), CID)
    service = GoogleWithRepeats()
    g._service = service
    cal.set_calendar(g)
    return service


@pytest.fixture(params=["local", "google"])
def backend(request) -> str:
    """Each test once on the local calendar and once on Google's."""
    if request.param == "local":
        cal.set_calendar(cal.LocalCalendar())
    else:
        request.getfixturevalue("google")
    return request.param


@pytest.fixture
async def http(tmp_path):
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        r = await c.post(
            "/api/auth/login", json={"username": "robin", "password": "correct horse battery"}
        )
        assert r.status_code == 200
        yield c


async def _tennis(http: AsyncClient, **extra: Any) -> dict[str, Any]:
    """Tennis, every Tuesday at 16:00 from 1 September."""
    r = await http.post(
        "/api/calendar/events",
        json={
            "title": "Tennis",
            "start": "2026-09-01T16:00",
            "end": "2026-09-01T17:00",
            "recurrence": "FREQ=WEEKLY;BYDAY=TU",
            "attendees": [],
            **extra,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _september(http: AsyncClient) -> list[dict[str, Any]]:
    r = await http.get(SEPTEMBER)
    assert r.status_code == 200, r.text
    return r.json()["events"]


def _when(ev: dict[str, Any]) -> tuple[str, str]:
    """(day, HH:MM) in New York."""
    s = times.parse_when(ev["start"], TZ)
    assert isinstance(s, datetime)
    return s.date().isoformat(), s.strftime("%H:%M")


def _form(ev: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """What the edit form sends: every field it shows, whether changed or not."""
    return {
        "title": ev["title"],
        "start": ev["start"][:16],
        "end": ev["end"][:16],
        "location": ev["location"],
        "description": ev["description"],
        "attendees": ev["attendees"],
        **changes,
    }


# -- the calendar API ------------------------------------------------------------------


class TestAnOccurrenceIsListedAsOne:
    async def test_it_carries_its_series_rule_and_says_it_is_an_occurrence(self, http, backend):
        series = await _tennis(http)
        assert series["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TU"]
        listed = await _september(http)
        assert [_when(e) for e in listed] == [(d, "16:00") for d in TUESDAYS]
        for e in listed:
            assert e["occurrence"] is True and e["recurring_event_id"] == series["id"]
            assert e["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TU"], "the form said 'never'"
        one = (await http.get(f"/api/calendar/events/{listed[2]['id']}")).json()
        assert one["id"] == listed[2]["id"] and one["occurrence"] is True
        assert one["recurrence"] == series["recurrence"] and _when(one) == (TUESDAYS[2], "16:00")


class TestThisEvent:
    async def test_editing_one_occurrence_leaves_the_others(self, http, backend):
        series = await _tennis(http)
        third = (await _september(http))[2]
        r = await http.patch(
            f"/api/calendar/events/{third['id']}?scope=this",
            json=_form(
                third, title="Tennis (Wednesday)", start="2026-09-16T17:00", end="2026-09-16T18:00"
            ),
        )
        assert r.status_code == 200, r.text
        listed = await _september(http)
        assert [(_when(e), e["title"]) for e in listed] == [
            ((TUESDAYS[0], "16:00"), "Tennis"),
            ((TUESDAYS[1], "16:00"), "Tennis"),
            (("2026-09-16", "17:00"), "Tennis (Wednesday)"),
            ((TUESDAYS[3], "16:00"), "Tennis"),
            ((TUESDAYS[4], "16:00"), "Tennis"),
        ]
        again = (await http.get(f"/api/calendar/events/{series['id']}")).json()
        assert again["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TU"], "the series still repeats"
        assert _when(again) == (TUESDAYS[0], "16:00") and again["title"] == "Tennis"

    async def test_an_older_client_sending_does_not_repeat_for_an_occurrence(self, http, backend):
        """The form that showed an occurrence as "Does not repeat" sent recurrence "",
        without a scope: the series stopped repeating."""
        series = await _tennis(http)
        second = (await _september(http))[1]
        r = await http.patch(
            f"/api/calendar/events/{second['id']}",
            json=_form(second, title="Tennis, bring water", recurrence=""),
        )
        assert r.status_code == 200, r.text
        listed = await _september(http)
        assert len(listed) == 5
        assert [e["title"] for e in listed].count("Tennis, bring water") == 1
        again = (await http.get(f"/api/calendar/events/{series['id']}")).json()
        assert again["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TU"]

    async def test_one_occurrence_cannot_repeat_differently(self, http, backend):
        await _tennis(http)
        second = (await _september(http))[1]
        r = await http.patch(
            f"/api/calendar/events/{second['id']}?scope=this", json={"recurrence": "daily"}
        )
        assert r.status_code == 400 and "whole series" in r.json()["error"]

    async def test_deleting_one_occurrence_leaves_the_others(self, http, backend):
        series = await _tennis(http)
        third = (await _september(http))[2]
        r = await http.delete(f"/api/calendar/events/{third['id']}")
        assert r.status_code == 200, r.text
        listed = await _september(http)
        assert [_when(e)[0] for e in listed] == [d for d in TUESDAYS if d != TUESDAYS[2]]
        assert (await http.get(f"/api/calendar/events/{third['id']}")).status_code == 404
        assert (await http.get(f"/api/calendar/events/{series['id']}")).status_code == 200


class TestAllEvents:
    async def test_a_change_from_one_occurrence_changes_every_one(self, http, backend):
        series = await _tennis(http)
        fourth = (await _september(http))[3]
        r = await http.patch(
            f"/api/calendar/events/{fourth['id']}?scope=series",
            json=_form(
                fourth,
                title="Tennis with Ana",
                start=f"{TUESDAYS[3]}T17:30",
                end=f"{TUESDAYS[3]}T18:30",
            ),
        )
        assert r.status_code == 200, r.text
        listed = await _september(http)
        assert [(_when(e), e["title"]) for e in listed] == [
            ((d, "17:30"), "Tennis with Ana") for d in TUESDAYS
        ]
        again = (await http.get(f"/api/calendar/events/{series['id']}")).json()
        assert _when(again) == (TUESDAYS[0], "17:30"), "the series starts where it did"

    async def test_moving_every_one_to_another_day_moves_its_weekday(self, http, backend):
        series = await _tennis(http)
        second = (await _september(http))[1]
        r = await http.patch(
            f"/api/calendar/events/{second['id']}?scope=series",
            json={"start": "2026-09-10T16:00"},  # Tuesday the 8th → Thursday the 10th
        )
        assert r.status_code == 200, r.text
        again = (await http.get(f"/api/calendar/events/{series['id']}")).json()
        assert again["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TH"]
        assert _when(again) == ("2026-09-03", "16:00")
        assert again["end"][11:16] == "17:00", "the hour it lasts is kept"
        listed = await _september(http)
        assert [_when(e)[0] for e in listed] == [
            "2026-09-03",
            "2026-09-10",
            "2026-09-17",
            "2026-09-24",
        ]

    async def test_a_new_repeat_from_one_occurrence(self, http, backend):
        series = await _tennis(http)
        second = (await _september(http))[1]
        r = await http.patch(
            f"/api/calendar/events/{second['id']}?scope=series", json={"recurrence": "biweekly"}
        )
        assert r.status_code == 200, r.text
        again = (await http.get(f"/api/calendar/events/{series['id']}")).json()
        assert again["recurrence"] == ["RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=TU"]
        assert [_when(e)[0] for e in await _september(http)] == TUESDAYS[::2]

    async def test_deleting_every_one(self, http, backend):
        series = await _tennis(http)
        third = (await _september(http))[2]
        r = await http.delete(f"/api/calendar/events/{third['id']}?scope=series")
        assert r.status_code == 200, r.text
        assert await _september(http) == []
        assert (await http.get(f"/api/calendar/events/{series['id']}")).status_code == 404

    async def test_the_house_board_takes_the_same_scope(self, http, backend):
        await _tennis(http)
        third = (await _september(http))[2]
        r = await http.delete(f"/api/board/events/{third['id']}?scope=this")
        assert r.status_code == 200, r.text
        assert len(await _september(http)) == 4
        second = (await _september(http))[1]
        r = await http.patch(
            f"/api/board/events/{second['id']}?scope=series", json={"title": "Tennis!"}
        )
        assert r.status_code == 200, r.text
        assert {e["title"] for e in await _september(http)} == {"Tennis!"}


async def test_a_scope_that_is_not_one_is_refused(http, backend):
    await _tennis(http)
    first = (await _september(http))[0]
    r = await http.patch(f"/api/calendar/events/{first['id']}?scope=all", json={"title": "x"})
    assert r.status_code == 400 and "scope" in r.json()["error"]
    r = await http.delete(f"/api/calendar/events/{first['id']}?scope=following")
    assert r.status_code == 400


# -- the weekday a weekly repeat falls on ----------------------------------------------


class TestTheWeekdayIsTheEventsOwn:
    """``new Date('2026-09-17').getDay()`` is UTC's Thursday, which is Wednesday in
    Los Angeles: a weekly all-day event made there repeated on Wednesdays. The
    server now anchors the day itself, in the member's zone."""

    @pytest.mark.parametrize(
        ("start", "end"),
        [("2026-09-17", "2026-09-18"), ("2026-09-17T20:00", "2026-09-17T21:00")],
        ids=["all-day", "evening (Friday in UTC)"],
    )
    async def test_weekly_falls_on_the_day_the_event_starts(self, http, start, end):
        users.update_profile(1, timezone="America/Los_Angeles")
        r = await http.post(
            "/api/calendar/events",
            json={
                "title": "Piano",
                "start": start,
                "end": end,
                "recurrence": "weekly",
                "attendees": [],
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TH"]  # 17 Sep 2026 is a Thursday

    async def test_on_a_change_it_falls_on_the_new_day(self, http):
        ev = (
            await http.post(
                "/api/calendar/events",
                json={"title": "Piano", "start": "2026-09-17", "attendees": []},
            )
        ).json()
        r = await http.patch(
            f"/api/calendar/events/{ev['id']}",
            json={"start": "2026-09-19", "recurrence": "biweekly"},
        )
        assert r.json()["recurrence"] == ["RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=SA"]

    def test_the_words_and_their_rules(self):
        thursday = date(2026, 9, 17)
        assert repeats.rule_for("daily", thursday) == ["RRULE:FREQ=DAILY"]
        assert repeats.rule_for("Weekly", thursday) == ["RRULE:FREQ=WEEKLY;BYDAY=TH"]
        assert repeats.rule_for("monthly", thursday) == ["RRULE:FREQ=MONTHLY"]
        assert repeats.rule_for("yearly", thursday) == ["RRULE:FREQ=YEARLY"]
        assert repeats.rule_for("none", thursday) == []
        assert repeats.shift_byday(["RRULE:FREQ=WEEKLY;BYDAY=SA,SU"], 2) == [
            "RRULE:FREQ=WEEKLY;BYDAY=MO,TU"
        ]
        # Not a weekly rule, or days with a position: left alone.
        assert repeats.shift_byday(["RRULE:FREQ=MONTHLY;BYDAY=2TU"], 1) == [
            "RRULE:FREQ=MONTHLY;BYDAY=2TU"
        ]
        assert repeats.shift_byday(["RRULE:FREQ=DAILY"], 1) == ["RRULE:FREQ=DAILY"]


# -- a start or an end alone -----------------------------------------------------------


class TestAStartOrAnEndAlone:
    async def _dentist(self, http) -> dict[str, Any]:
        r = await http.post(
            "/api/calendar/events",
            json={
                "title": "Dentist",
                "start": "2026-09-16T15:00",
                "end": "2026-09-16T15:45",
                "attendees": [],
            },
        )
        return r.json()

    @pytest.mark.parametrize("on", ["fake", "local", "google"])
    async def test_a_new_start_alone_keeps_the_length(self, http, request, on):
        """The UI's PATCH reset it to an hour; the agent's tool kept it."""
        if on == "local":
            cal.set_calendar(cal.LocalCalendar())
        elif on == "google":
            request.getfixturevalue("google")
        ev = await self._dentist(http)
        r = await http.patch(f"/api/calendar/events/{ev['id']}", json={"start": "2026-09-17T10:00"})
        assert r.status_code == 200, r.text
        moved = r.json()
        assert moved["start"][:16] == "2026-09-17T10:00" and moved["end"][:16] == "2026-09-17T10:45"

    @pytest.mark.parametrize("on", ["fake", "local", "google"])
    async def test_a_new_end_alone_keeps_the_start(self, http, request, on):
        """Google's PATCH read changes["start"] and raised: a 500."""
        if on == "local":
            cal.set_calendar(cal.LocalCalendar())
        elif on == "google":
            request.getfixturevalue("google")
        ev = await self._dentist(http)
        r = await http.patch(f"/api/calendar/events/{ev['id']}", json={"end": "2026-09-16T16:30"})
        assert r.status_code == 200, r.text
        longer = r.json()
        assert (
            longer["start"][:16] == "2026-09-16T15:00" and longer["end"][:16] == "2026-09-16T16:30"
        )

    def test_an_all_day_move_keeps_its_days(self):
        sp = repeats.resolved_span("2026-09-16", "2026-09-19", {"start": "2026-09-20"}, TZ)
        assert (sp.start, sp.end) == (date(2026, 9, 20), date(2026, 9, 23))


# -- the agent's tools -----------------------------------------------------------------


def _tool(name: str, **kwargs: Any) -> dict[str, Any]:
    fn = getattr(tools, name)
    context.set_turn(
        context.Turn(calendar=cal.get_calendar(), user_id=1, principal="robin", timezone=TZ)
    )
    try:
        return getattr(fn, "fn", fn)(**kwargs)
    finally:
        context.set_turn(None)


class TestTheAgentsTools:
    async def test_update_event_on_an_occurrence_changes_that_one(self, http, backend):
        series = await _tennis(http)
        third = (await _september(http))[2]
        out = _tool("update_event", event_id=third["id"], start=f"{TUESDAYS[2]}T18:00")
        assert "updated" in out, out
        listed = await _september(http)
        assert [_when(e) for e in listed] == [
            (d, "18:00" if d == TUESDAYS[2] else "16:00") for d in TUESDAYS
        ]
        assert listed[2]["end"][11:16] == "19:00", "the tool keeps the length"
        again = (await http.get(f"/api/calendar/events/{series['id']}")).json()
        assert again["recurrence"] == series["recurrence"] and _when(again)[1] == "16:00"

    async def test_update_event_with_a_new_rule_changes_the_series(self, http, backend):
        series = await _tennis(http)
        third = (await _september(http))[2]
        out = _tool(
            "update_event", event_id=third["id"], recurrence="RRULE:FREQ=WEEKLY;BYDAY=TU;COUNT=2"
        )
        assert "updated" in out, out
        again = (await http.get(f"/api/calendar/events/{series['id']}")).json()
        assert again["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TU;COUNT=2"]
        assert [_when(e)[0] for e in await _september(http)] == TUESDAYS[:2]

    async def test_delete_event_on_an_occurrence_deletes_that_one(self, http, backend):
        await _tennis(http)
        fourth = (await _september(http))[3]
        out = _tool("delete_event", event_id=fourth["id"])
        assert out["deleted"] == fourth["id"] and out["title"] == "Tennis"
        assert [_when(e)[0] for e in await _september(http)] == [
            d for d in TUESDAYS if d != TUESDAYS[3]
        ]

    async def test_get_event_on_an_occurrence_shows_how_it_repeats(self, http, backend):
        await _tennis(http)
        first = (await _september(http))[0]
        out = _tool("get_event", event_id=first["id"])
        assert out["recurring"] is True and out["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TU"]


# -- each backend on its own -----------------------------------------------------------


class TestTheLocalCalendar:
    def _series(self, c: cal.LocalCalendar) -> cal.Event:
        return c.insert(
            cal.Draft(
                title="Swim",
                span=times.span("2026-09-01T16:00", "2026-09-01T17:00", TZ),
                recurrence=["RRULE:FREQ=WEEKLY;BYDAY=TU"],
            ),
            TZ,
        )

    def _september(self, c: cal.LocalCalendar) -> list[cal.Event]:
        s, _ = times.day_bounds("2026-09-01", TZ)
        _, e = times.day_bounds("2026-09-30", TZ)
        return c.list_events(s, e)

    def test_its_exceptions_outlive_the_process(self):
        c = cal.LocalCalendar()
        series = self._series(c)
        listed = self._september(c)
        c.delete(listed[1].id)
        c.patch(listed[3].id, {"title": "Swim gala", "start": "2026-09-23T09:00"}, TZ)
        again = cal.LocalCalendar()
        after = self._september(again)
        assert [(e.title, e.start[:16]) for e in after] == [
            ("Swim", "2026-09-01T16:00"),
            ("Swim", "2026-09-15T16:00"),
            ("Swim gala", "2026-09-23T09:00"),
            ("Swim", "2026-09-29T16:00"),
        ]
        assert after[2].end[:16] == "2026-09-23T10:00"
        assert again.get_event(listed[1].id) is None
        assert again.get_event(f"{series.id}_20260902T160000") is None, "not one of its days"

    def test_a_series_moved_takes_its_exceptions_with_it(self):
        """A Tuesday deleted stays deleted when every Tuesday moves to 17:00."""
        c = cal.LocalCalendar()
        series = self._series(c)
        c.delete(self._september(c)[2].id)
        c.patch(series.id, {"start": "2026-09-01T17:00"}, TZ)
        listed = self._september(cal.LocalCalendar())
        assert [e.start[:16] for e in listed] == [
            f"{d}T17:00" for d in TUESDAYS if d != TUESDAYS[2]
        ]

    def test_a_series_that_stops_repeating_drops_its_exceptions(self):
        c = cal.LocalCalendar()
        series = self._series(c)
        c.delete(self._september(c)[2].id)
        c.patch(series.id, {"recurrence": []}, TZ)
        with db.session() as s:
            assert s.query(db.LocalEventException).count() == 0
        assert [e.id for e in self._september(c)] == [series.id]

    def test_deleting_the_series_deletes_its_exceptions(self):
        c = cal.LocalCalendar()
        series = self._series(c)
        c.delete(self._september(c)[2].id)
        c.delete(series.id)
        with db.session() as s:
            assert s.query(db.LocalEventException).count() == 0
        assert self._september(cal.LocalCalendar()) == []

    def test_an_occurrence_moved_into_a_window_is_in_it(self):
        c = cal.LocalCalendar()
        self._series(c)
        first = self._september(c)[0]
        c.patch(first.id, {"start": "2026-08-31T08:00"}, TZ)
        s, _ = times.day_bounds("2026-08-31", TZ)
        _, e = times.day_bounds("2026-08-31", TZ)
        assert [x.id for x in c.list_events(s, e)] == [first.id]


class TestGoogle:
    def test_a_series_rule_is_read_once_for_all_its_occurrences(self, google):
        g = cal.get_calendar()
        assert isinstance(g, cal.GoogleCalendar)
        made = g.insert(
            cal.Draft(
                title="Swim",
                span=times.span("2026-09-01T16:00", None, TZ),
                recurrence=["RRULE:FREQ=WEEKLY;BYDAY=TU"],
            ),
            TZ,
        )
        reads: list[str] = []
        get = google.get
        google.get = lambda calendarId, eventId: reads.append(eventId) or get(calendarId, eventId)  # type: ignore[method-assign]
        s, _ = times.day_bounds("2026-09-01", TZ)
        _, e = times.day_bounds("2026-09-30", TZ)
        listed = g.list_events(s, e)
        assert len(listed) == 5 and all(x.recurrence == made.recurrence for x in listed)
        assert reads == [made.id]
        g.list_events(s, e)
        assert reads == [made.id], "cached"

    def test_an_occurrence_is_patched_by_its_own_id(self, google):
        g = cal.get_calendar()
        made = g.insert(
            cal.Draft(
                title="Swim",
                span=times.span("2026-09-01T16:00", None, TZ),
                recurrence=["RRULE:FREQ=WEEKLY;BYDAY=TU"],
            ),
            TZ,
        )
        s, _ = times.day_bounds("2026-09-01", TZ)
        _, e = times.day_bounds("2026-09-30", TZ)
        second = g.list_events(s, e)[1]
        g.patch(second.id, {"title": "Swim gala"}, TZ)
        g.patch(second.id, {"title": "Swim, every one"}, TZ, scope=repeats.SERIES)
        assert google.patched == [second.id, made.id]
        with pytest.raises(ValueError, match="whole series"):
            g.patch(second.id, {"recurrence": []}, TZ)
