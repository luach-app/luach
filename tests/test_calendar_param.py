"""A calendar named in a request must be one of the household's. The credential can
see others (someone's personal calendar); naming one reached it."""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from luach.app import create_app
from luach.calendar import client as cal
from luach.calendar import times

TZ = "America/New_York"


@pytest.fixture
async def client(tmp_path):
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        yield c


async def _login(c: AsyncClient, username: str, password: str) -> None:
    r = await c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


def _private_event(fake: cal.FakeCalendar) -> str:
    """An event on the calendar the household ignores ("school" in two_calendars)."""
    start = times.now_in(TZ) + timedelta(days=2)
    span = times.span(start.strftime("%Y-%m-%dT10:00"), None, TZ)
    return fake.insert(cal.Draft(title="Therapy", span=span, calendar_id="school"), TZ).id


async def test_a_calendar_the_household_does_not_use_is_refused(client, two_calendars):
    eid = _private_event(two_calendars)
    await _login(client, "ana", "another good password")
    for method, path in (
        ("GET", f"/api/calendar/events/{eid}?calendar=school"),
        ("PATCH", f"/api/calendar/events/{eid}?calendar=school"),
        ("DELETE", f"/api/calendar/events/{eid}?calendar=school"),
        ("GET", f"/api/board/events/{eid}?calendar=school"),
        ("PATCH", f"/api/board/events/{eid}?calendar=school"),
        ("DELETE", f"/api/board/events/{eid}?calendar=school"),
    ):
        r = await client.request(method, path, json={"title": "Mine now"})
        assert r.status_code == 400, f"{method} {path}: {r.status_code} {r.text}"
        assert r.json()["error"] == "that calendar is not one of the household's"
    assert two_calendars.events[eid].title == "Therapy", "untouched"


async def test_the_households_own_calendars_still_answer(client, two_calendars):
    await _login(client, "ana", "another good password")
    day = (times.now_in(TZ) + timedelta(days=3)).strftime("%Y-%m-%dT09:00")
    made = (
        await client.post(
            "/api/calendar/events", json={"title": "Dentist", "start": day, "calendar_id": "work"}
        )
    ).json()
    eid = made["id"]
    assert (await client.get(f"/api/calendar/events/{eid}?calendar=work")).status_code == 200
    r = await client.patch(f"/api/calendar/events/{eid}?calendar=work", json={"title": "Dr"})
    assert r.status_code == 200 and r.json()["title"] == "Dr"
    assert (await client.delete(f"/api/calendar/events/{eid}?calendar=work")).status_code == 200


async def test_only_the_owner_sees_the_calendars_the_household_does_not_use(client, two_calendars):
    await _login(client, "ana", "another good password")
    member = (await client.get("/api/household/calendars")).json()
    assert [c["id"] for c in member["available"]] == ["home", "work"]
    await client.post("/api/auth/logout")
    await _login(client, "robin", "correct horse battery")
    owner = (await client.get("/api/household/calendars")).json()
    assert [c["id"] for c in owner["available"]] == ["home", "work", "school"]
