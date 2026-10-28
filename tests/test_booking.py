"""The booking link: what a stranger is offered, what they may take, and the
rules that keep a day from filling up."""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from luach import booking, db, household
from luach.app import create_app
from luach.calendar import times
from luach.calendar.client import Draft
from tests.doubles import confirm_address

TZ = "America/New_York"


@pytest.fixture
async def client(tmp_path):
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        yield c


async def login(c: AsyncClient, username="robin", password="correct horse battery"):
    r = await c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


def _weekday_ahead(days: int = 3) -> str:
    """A day far enough out to clear the notice period, never a weekend."""
    day = times.now_in(TZ).date() + timedelta(days=days)
    while day.weekday() > 4:
        day += timedelta(days=1)
    return day.isoformat()


def _publish(user_id: int = 1, **changes) -> dict:
    return booking.update(
        user_id,
        {
            "enabled": True,
            "slug": "robin",
            "slot_minutes": 30,
            "max_per_day": 2,
            "buffer_minutes": 15,
            "lead_hours": 12,
            "horizon_days": 21,
            "hours": {d: [["09:00", "12:00"]] for d in ("mon", "tue", "wed", "thu", "fri")},
            **changes,
        },
    )


def test_settings_are_validated():
    with pytest.raises(ValueError, match="link name"):
        booking.update(1, {"slug": "Not A Slug"})
    with pytest.raises(ValueError, match="HH:MM"):
        booking.update(1, {"hours": {"mon": [["9", "17:00"]]}})
    with pytest.raises(ValueError, match="ends before"):
        booking.update(1, {"hours": {"mon": [["17:00", "09:00"]]}})
    with pytest.raises(ValueError, match="between 1 and 20"):
        booking.update(1, {"max_per_day": 0})
    with pytest.raises(ValueError, match="unknown setting"):
        booking.update(1, {"colour": "red"})
    with pytest.raises(ValueError, match="at least one window"):
        booking.update(1, {"enabled": True, "hours": {d: [] for d in booking.DAYS}})
    conf = _publish()
    assert conf["slug"] == "robin" and conf["hours"]["sat"] == []
    # A second member cannot claim the same link name.
    with pytest.raises(ValueError, match="another member"):
        booking.update(2, {"slug": "robin"})


def test_slots_respect_hours_notice_and_busy_time(calendar):
    _publish()
    day = _weekday_ahead(3)
    start, _ = times.day_bounds(day, TZ)
    calendar.insert(Draft(title="Standup", span=times.span(f"{day}T10:00", f"{day}T10:30", TZ)), TZ)
    days = {d["day"]: [s["start"][11:16] for s in d["slots"]] for d in booking.slots_for(1)}
    assert day in days
    offered = days[day]
    assert offered[0] == "09:00" and offered[-1] == "11:30"  # 09:00–12:00 in 30-minute slots
    # The 10:00 event and its 15-minute buffer take 09:30, 10:00 and 10:30 out.
    assert "09:30" not in offered and "10:00" not in offered and "10:30" not in offered
    assert "09:00" in offered and "11:00" in offered
    # Nothing inside the notice period is ever offered.
    earliest = (times.now_in(TZ) + timedelta(hours=12)).isoformat()
    assert all(s["start"] >= earliest for d in booking.slots_for(1) for s in d["slots"])
    assert start.date().isoformat() == day


async def test_a_stranger_books_and_the_day_then_fills_up(client, calendar, monkeypatch):
    _publish()
    household.update(default_attendees=[])
    from luach.auth import users

    users.set_notify_emails(1, ["work@corp.com"])
    confirm_address(1, "work@corp.com")
    day = _weekday_ahead(4)

    r = await client.get("/api/book/robin")
    assert r.status_code == 200
    page = r.json()
    assert page["host"] == "Robin" and page["slot_minutes"] == 30
    slot = next(s["start"] for d in page["days"] if d["day"] == day for s in d["slots"])

    r = await client.post(
        "/api/book/robin",
        json={"start": slot, "name": "Dana", "email": "Dana@Example.com", "note": "30 min chat"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["booked"] is True
    event = next(e for e in calendar.events.values() if e.title == "Meeting with Dana")
    assert event.attendees == ["dana@example.com", "work@corp.com"]
    assert "Dana <dana@example.com>" in event.description and "30 min chat" in event.description
    with db.session() as s:
        from sqlalchemy import select

        rows = s.execute(select(db.Booking)).scalars().all()
    assert len(rows) == 1 and rows[0].day == day and rows[0].email == "dana@example.com"

    # That slot is gone now.
    r = await client.post(
        "/api/book/robin", json={"start": slot, "name": "Dana", "email": "dana@example.com"}
    )
    assert r.status_code == 400 and "just been taken" in r.json()["error"]

    # A second booking fills the day; the third finds no slots left on it.
    page = (await client.get("/api/book/robin")).json()
    other = next(s["start"] for d in page["days"] if d["day"] == day for s in d["slots"])
    assert (
        await client.post(
            "/api/book/robin", json={"start": other, "name": "Ravi", "email": "ravi@example.com"}
        )
    ).status_code == 200
    page = (await client.get("/api/book/robin")).json()
    assert day not in [d["day"] for d in page["days"]]

    await login(client)
    audit = [e["event_type"] for e in (await client.get("/api/control/audit")).json()["entries"]]
    assert "booking.created" in audit


async def test_the_page_is_public_but_only_when_published(client):
    assert (await client.get("/api/book/robin")).status_code == 404  # not enabled yet
    _publish()
    assert (await client.get("/api/book/robin")).status_code == 200  # no cookie needed
    assert (await client.get("/api/book/nobody")).status_code == 404
    assert (await client.get("/api/booking")).status_code == 401  # settings still need a member
    booking.update(1, {"enabled": False})
    assert (await client.get("/api/book/robin")).status_code == 404
    r = await client.post(
        "/api/book/robin",
        json={"start": f"{_weekday_ahead()}T09:00", "name": "A", "email": "a@b.co"},
    )
    assert r.status_code == 404


async def test_owner_manages_the_link_from_settings(client, calendar):
    await login(client)
    r = await client.get("/api/booking")
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert r.json()["slug"] == "robin" and r.json()["link"].endswith("/book/robin")
    r = await client.patch(
        "/api/booking",
        json={"enabled": True, "slug": "robin-k", "slot_minutes": 45, "max_per_day": 1},
    )
    assert r.status_code == 200 and r.json()["link"].endswith("/book/robin-k")
    assert (await client.patch("/api/booking", json={"slot_minutes": 4})).status_code == 400
    assert (await client.patch("/api/booking", json={})).status_code == 400

    day = _weekday_ahead(5)
    page = (await client.get("/api/book/robin-k")).json()
    slot = next(s["start"] for d in page["days"] if d["day"] == day for s in d["slots"])
    await client.post(
        "/api/book/robin-k", json={"start": slot, "name": "Dana", "email": "dana@example.com"}
    )
    upcoming = (await client.get("/api/booking/upcoming")).json()["bookings"]
    assert [b["name"] for b in upcoming] == ["Dana"] and upcoming[0]["day"] == day


def test_bookings_can_land_on_their_own_calendar(two_calendars):
    """Work meetings need not sit on the family calendar."""
    _publish()
    with pytest.raises(ValueError, match="not one of the household"):
        booking.update(1, {"calendar_id": "school"})
    booking.update(1, {"calendar_id": "work"})
    day = _weekday_ahead(6)
    slot = next(s["start"] for d in booking.slots_for(1) if d["day"] == day for s in d["slots"])
    booking.book("robin", slot, "Dana", "dana@example.com")
    event = next(e for e in two_calendars.events.values() if e.title == "Meeting with Dana")
    assert event.calendar_id == "work"


def test_bad_bookings_are_refused(calendar):
    _publish()
    day = _weekday_ahead(7)
    slot = next(s["start"] for d in booking.slots_for(1) if d["day"] == day for s in d["slots"])
    with pytest.raises(KeyError):
        booking.book("nobody", slot, "Dana", "dana@example.com")
    with pytest.raises(ValueError, match="not an email"):
        booking.book("robin", slot, "Dana", "dana@")
    with pytest.raises(ValueError, match="who you are"):
        booking.book("robin", slot, "  ", "dana@example.com")
    with pytest.raises(ValueError, match="not a whole day"):
        booking.book("robin", day, "Dana", "dana@example.com")
    # A time inside the hours but off the slot grid is not on offer either.
    with pytest.raises(ValueError, match="just been taken"):
        booking.book("robin", f"{day}T09:07", "Dana", "dana@example.com")
    # An hour nobody published is refused even when the calendar is empty.
    with pytest.raises(ValueError, match="just been taken"):
        booking.book("robin", f"{day}T22:00", "Dana", "dana@example.com")


def test_both_sides_are_mailed_when_resend_is_configured(calendar, monkeypatch):
    from luach import mailer

    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(
        mailer, "send", lambda to, subject, text, html=None: sent.append((to, subject)) or True
    )
    _publish(location="Google Meet")
    day = _weekday_ahead(8)
    slot = next(s["start"] for d in booking.slots_for(1) if d["day"] == day for s in d["slots"])
    booking.book("robin", slot, "Dana", "dana@example.com")
    assert [to for to, _ in sent] == ["dana@example.com", "robin@example.com"]
    assert all("Dana" in s or "Confirmed" in s for _, s in sent)


def test_an_all_day_event_does_not_block_the_day(calendar):
    """A birthday is not a reason to refuse every meeting on that day."""
    _publish()
    day = _weekday_ahead(9)
    calendar.insert(Draft(title="Sara's birthday", span=times.span(day, None, TZ)), TZ)
    free = [d for d in booking.slots_for(1) if d["day"] == day]
    assert free and len(free[0]["slots"]) == 6  # 09:00–12:00 in 30-minute slots
