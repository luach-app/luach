"""Household settings: the calendars luach watches, the default one, and
who is always invited — and how the UI and the agent honour them."""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from luach import household
from luach.agent import context, runtime
from luach.agent.tools import create_event, resolve_attendees, resolve_calendar
from luach.app import create_app
from luach.calendar import client as cal
from luach.calendar import times
from tests.doubles import ScriptedModel, call, confirm_address, say

TZ = "America/New_York"


@pytest.fixture
async def client(tmp_path):
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        yield c


async def login(c: AsyncClient, username="robin", password="correct horse battery"):
    r = await c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


def _tomorrow(hour: int) -> str:
    return (
        (times.now_in(TZ) + timedelta(days=1))
        .replace(hour=hour, minute=0)
        .strftime("%Y-%m-%dT%H:%M")
    )


def test_defaults_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("LUACH_GOOGLE_CALENDAR_ID", "env@cal")
    snap = household.snapshot()
    assert snap == {
        "calendars": ["env@cal"],
        "default_calendar": "env@cal",
        "default_attendees": [],
    }
    monkeypatch.delenv("LUACH_GOOGLE_CALENDAR_ID")
    assert household.snapshot()["calendars"] == []


def test_update_validates_and_normalises():
    snap = household.update(default_attendees=["Alex@Example.com", "alex@example.com", " a@b.co "])
    assert snap["default_attendees"] == ["alex@example.com", "a@b.co"]
    with pytest.raises(ValueError):
        household.update(default_attendees=["not an email"])
    with pytest.raises(ValueError):
        household.update(default_attendees=[f"p{i}@x.io" for i in range(21)])
    with pytest.raises(ValueError):
        household.update(calendars=["", "  "])
    snap = household.update(calendars=["b", "a", "b"])
    assert snap["calendars"] == ["b", "a"] and snap["default_calendar"] == ""
    snap = household.update(default_calendar="c")
    assert snap["default_calendar"] == "c" and snap["calendars"][0] == "c"
    with pytest.raises(ValueError):
        household.update(default_calendar=" ")
    assert household.resolve_attendees(None) == ["alex@example.com", "a@b.co"]
    assert household.resolve_attendees(["X@Y.com", "junk", "x@y.com"]) == ["x@y.com"]


async def test_household_routes(client, two_calendars):
    await login(client, "ana", "another good password")
    r = await client.get("/api/household")
    assert r.status_code == 200 and r.json()["default_calendar"] == "home"
    r = await client.get("/api/household/calendars")
    avail = {c["id"]: c for c in r.json()["available"]}
    assert avail["home"]["default"] and avail["home"]["enabled"]
    assert avail["work"]["enabled"] and "school" not in avail, "not the household's: owner only"
    assert (
        await client.patch("/api/household", json={"default_attendees": ["m@x.io"]})
    ).status_code == 403

    await login(client)
    avail = {c["id"]: c for c in (await client.get("/api/household/calendars")).json()["available"]}
    assert not avail["school"]["enabled"]
    r = await client.patch(
        "/api/household", json={"default_attendees": ["m@x.io"], "default_calendar": "work"}
    )
    assert r.status_code == 200 and r.json()["default_attendees"] == ["m@x.io"]
    assert r.json()["default_calendar"] == "work"
    assert (await client.patch("/api/household", json={})).status_code == 400
    assert (await client.patch("/api/household", json={"calendars": "home"})).status_code == 400
    assert (await client.patch("/api/household", json={"default_calendar": 3})).status_code == 400
    assert (
        await client.patch("/api/household", json={"default_attendees": ["nope"]})
    ).status_code == 400
    audit = (await client.get("/api/control/audit")).json()
    assert audit["entries"][-1]["event_type"] == "household.updated"


async def test_ui_events_honour_defaults_and_calendars(client, two_calendars):
    await login(client)
    household.update(default_attendees=["alex@x.io"])
    r = await client.post("/api/calendar/events", json={"title": "Piano", "start": _tomorrow(17)})
    ev = r.json()
    assert ev["calendar_id"] == "home" and ev["attendees"] == ["alex@x.io"]
    r = await client.post(
        "/api/calendar/events",
        json={"title": "Standup", "start": _tomorrow(9), "calendar_id": "work", "attendees": []},
    )
    assert r.json()["calendar_id"] == "work" and r.json()["attendees"] == []
    r = await client.post(
        "/api/calendar/events", json={"title": "X", "start": _tomorrow(9), "calendar_id": "school"}
    )
    assert r.status_code == 400
    r = await client.post(
        "/api/calendar/events", json={"title": "X", "start": _tomorrow(9), "attendees": "a@b.c"}
    )
    assert r.status_code == 400
    r = await client.patch(
        f"/api/calendar/events/{ev['id']}?calendar=home", json={"attendees": ["b@x.io"]}
    )
    assert r.json()["attendees"] == ["b@x.io"]
    assert (await client.get(f"/api/calendar/events/{ev['id']}?calendar=work")).status_code == 404
    day = ev["start"][:10]
    listed = (await client.get(f"/api/calendar/events?start={day}&end={day}")).json()["events"]
    assert {e["calendar_id"] for e in listed} == {"home", "work"}
    household.update(calendars=["work"], default_calendar="work")
    listed = (await client.get(f"/api/calendar/events?start={day}&end={day}")).json()["events"]
    assert [e["calendar_id"] for e in listed] == ["work"]
    # home is no longer the household's: naming it reaches nothing.
    assert (
        await client.delete(f"/api/calendar/events/{ev['id']}?calendar=home")
    ).status_code == 400
    ident = (await client.get("/api/calendar/identity")).json()
    assert ident["calendar"] == "work" and ident["calendars"] == ["work"]


def test_tool_resolvers(two_calendars):
    context.set_turn(
        context.Turn(calendar=two_calendars, user_id=1, principal="robin", timezone=TZ)
    )
    try:
        assert resolve_calendar("") == ""
        assert resolve_calendar("work") == "work"
        assert resolve_calendar("the Harper calendar") == "home"
        assert resolve_calendar("HARPER") == "home"
        with pytest.raises(ValueError, match="School|Work"):
            resolve_calendar("school")  # known to Google, not enabled for the household
        household.update(default_attendees=["m@x.io"])
        assert resolve_attendees("", 1) == ["m@x.io"]
        assert resolve_attendees("none") == []
        assert resolve_attendees("A@b.io; c@d.io,junk") == ["a@b.io", "c@d.io"]
        out = create_event(title="Sync", start=_tomorrow(10), calendar="nowhere")
        assert "no calendar called" in out["error"]
    finally:
        context.set_turn(None)


async def test_agent_creates_on_the_named_calendar_with_named_people(two_calendars):
    household.update(default_attendees=["m@x.io"])
    runtime.set_model(
        ScriptedModel(
            [
                [
                    call(
                        "create_event",
                        title="Standup",
                        start=_tomorrow(9),
                        calendar="Work",
                        attendees="p@q.io",
                    )
                ],
                [say("Added.")],
            ]
        )
    )
    result = await runtime.run_turn(
        "standup tomorrow 9 on work, invite p@q.io", user_id=1, principal="robin", timezone=TZ
    )
    assert result.error is None, result
    # An address outside the household waits for a tap on the card that names it.
    (card,) = result.held
    assert card["reason"] == ["outside-the-house"] and "p@q.io" in card["summary"]
    from luach.agent import pending

    done = pending.approve(card["id"], by="robin", timezone=TZ, calendar=two_calendars)
    assert done["status"] == "approved"
    result.created = [done["result"]["created"]]
    ev = next(iter(two_calendars.events.values()))
    assert ev.calendar_id == "work" and ev.attendees == ["p@q.io"]
    assert result.created[0]["calendar"] == "Work" and result.created[0]["invited"] == ["p@q.io"]
    runtime.set_model(
        ScriptedModel([[call("create_event", title="Lunch", start=_tomorrow(12))], [say("ok")]])
    )
    result = await runtime.run_turn(
        "lunch tomorrow at noon", user_id=1, principal="robin", timezone=TZ
    )
    assert result.error is None, result
    lunch = [e for e in two_calendars.events.values() if e.title == "Lunch"][0]
    assert lunch.calendar_id == "home" and lunch.attendees == ["m@x.io"]


def test_find_events_understands_what_a_doctor_is(two_calendars):
    from luach.agent.tools import find_events, matches_query

    context.set_turn(
        context.Turn(calendar=two_calendars, user_id=1, principal="robin", timezone=TZ)
    )
    try:
        for title in (
            "Dr. Okafor with Lily",
            "Appointment at Dr. Hannah Lindqvist, MD's office",
            "Podiatrist appointment with Dr. Priya N. Raman, D.P.M.",
            "Jordan Pike Therapy",
        ):
            two_calendars.insert(
                cal.Draft(title=title, span=times.span(_tomorrow(10), None, TZ)), TZ
            )
        two_calendars.insert(
            cal.Draft(title="Sukkot at Bernsteins", span=times.span(_tomorrow(18), None, TZ)), TZ
        )
        found = {e["title"] for e in find_events("doctor")["events"]}
        assert "Sukkot at Bernsteins" not in found and len(found) == 4
        assert {e["title"] for e in find_events("médico")["events"]} == found
        assert [e["title"] for e in find_events("podiatric")["events"]] == [
            "Podiatrist appointment with Dr. Priya N. Raman, D.P.M."
        ]
        assert find_events("vuelo")["count"] == 0
        ev = two_calendars.insert(
            cal.Draft(title="Sukkot", span=times.span(_tomorrow(18), None, TZ)), TZ
        )
        assert not matches_query(ev, "doctor")
    finally:
        context.set_turn(None)


async def test_member_notify_emails_ride_along_on_their_events(client, two_calendars):
    await login(client)
    household.update(default_attendees=["alex@x.io"])
    r = await client.patch(
        "/api/auth/me", json={"notify_emails": ["Work@Corp.com", "work@corp.com", "me@x.io"]}
    )
    # Added, but each address confirms it wants the mail before it gets any.
    assert r.status_code == 200 and r.json()["notify_emails"] == []
    assert r.json()["notify_pending"] == ["work@corp.com", "me@x.io"]
    for address in ("work@corp.com", "me@x.io"):
        confirm_address(1, address)
    assert (await client.get("/api/auth/me")).json()["notify_emails"] == [
        "work@corp.com",
        "me@x.io",
    ]
    assert (await client.get("/api/auth/me")).json()["notify_emails"] == [
        "work@corp.com",
        "me@x.io",
    ]
    assert (await client.patch("/api/auth/me", json={"notify_emails": ["nope"]})).status_code == 400
    assert (await client.patch("/api/auth/me", json={"notify_emails": "a@b.io"})).status_code == 400

    # The UI omits attendees → household defaults plus the member's own list.
    ev = (
        await client.post("/api/calendar/events", json={"title": "Piano", "start": _tomorrow(17)})
    ).json()
    assert ev["attendees"] == ["alex@x.io", "work@corp.com", "me@x.io"]
    # An explicit list is what the form showed; nothing is added behind it.
    ev = (
        await client.post(
            "/api/calendar/events",
            json={"title": "Solo", "start": _tomorrow(8), "attendees": ["work@corp.com"]},
        )
    ).json()
    assert ev["attendees"] == ["work@corp.com"]

    context.set_turn(
        context.Turn(calendar=two_calendars, user_id=1, principal="robin", timezone=TZ)
    )
    try:
        assert resolve_attendees("", 1) == ["alex@x.io", "work@corp.com", "me@x.io"]
        assert resolve_attendees("p@q.io", 1) == ["p@q.io", "work@corp.com", "me@x.io"]
        assert resolve_attendees("none", 1) == []
        created = create_event(title="Dentist", start=_tomorrow(15))
        assert created["created"]["invited"] == ["alex@x.io", "work@corp.com", "me@x.io"]
    finally:
        context.set_turn(None)
    # Ana has none of her own, and robin's list does not follow her.
    context.set_turn(context.Turn(calendar=two_calendars, user_id=2, principal="ana", timezone=TZ))
    try:
        assert resolve_attendees("", 2) == ["alex@x.io"]
    finally:
        context.set_turn(None)

    assert (await client.patch("/api/auth/me", json={"notify_emails": []})).json()[
        "notify_emails"
    ] == []
