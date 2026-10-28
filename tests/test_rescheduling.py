"""Changing one's mind: the guest moves or cancels, or the host calls it off."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from luach import booking, db, mailer
from luach.app import create_app
from luach.calendar import times

TZ = "America/New_York"


@pytest.fixture
async def client(tmp_path):
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        yield c


@pytest.fixture
def mailed(monkeypatch) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(
        mailer, "send", lambda to, subject, text, html=None: out.append((to, subject)) or True
    )
    monkeypatch.setattr(
        mailer, "send_digest", lambda to, subject, lines: out.append((to, subject)) or True
    )
    return out


def _weekday_ahead(days: int = 3) -> str:
    day = times.now_in(TZ).date() + timedelta(days=days)
    while day.weekday() > 4:
        day += timedelta(days=1)
    return day.isoformat()


def _publish(**changes) -> dict:
    from luach.auth import users

    users.update_profile(1, timezone=TZ)
    return booking.update(
        1,
        {
            "enabled": True,
            "slug": "robin",
            "slot_minutes": 30,
            "buffer_minutes": 0,
            "max_per_day": 1,
            "hours": {d: [["09:00", "12:00"]] for d in ("mon", "tue", "wed", "thu", "fri")},
            **changes,
        },
    )


def _slots(day: str) -> list[str]:
    return [s["start"] for d in booking.slots_for(1) if d["day"] == day for s in d["slots"]]


def _token(out: dict) -> str:
    return out["manage"].split("manage=")[1]


def test_a_guest_moves_their_own_meeting(calendar, mailed):
    _publish()
    day = _weekday_ahead(3)
    free = _slots(day)  # what is on offer before any of it is taken
    first, second = free[0], free[2]
    taken = booking.book("robin", first, "Dana", "dana@example.com")
    token = _token(taken)

    view = booking.manage_view("robin", token)
    assert view["name"] == "Dana" and view["start"] == first and view["cancelled"] is False

    mailed.clear()
    moved = booking.move("robin", token, second)
    assert moved["moved"] is True and moved["start"] == second
    event = next(e for e in calendar.events.values() if e.title == "Meeting with Dana")
    assert event.start.startswith(second[:16])
    assert [to for to, _ in mailed] == ["dana@example.com", "robin@example.com"]
    assert all("Moved" in subject for _, subject in mailed)

    # The day is still at its cap for anyone else…
    assert _slots(day) == []
    # …but the meeting does not block itself: the hour it left is free to it,
    # and the hour it now holds is not somewhere to move to.
    offered = {s["start"] for d in booking.manage_view("robin", token)["days"] for s in d["slots"]}
    assert first in offered and second not in offered
    with pytest.raises(ValueError, match="already is"):
        booking.move("robin", token, moved["start"])
    assert booking.move("robin", token, first)["start"] == first


def test_a_guest_cancels_and_the_day_opens_up(calendar, mailed):
    _publish()  # one a day
    day = _weekday_ahead(4)
    first = _slots(day)[0]
    taken = booking.book("robin", first, "Dana", "dana@example.com")
    assert _slots(day) == []  # the cap is reached

    mailed.clear()
    assert booking.cancel("robin", _token(taken))["cancelled"] is True
    assert booking.cancel("robin", _token(taken)) == {"cancelled": True, "already": True}
    assert [to for to, _ in mailed] == ["dana@example.com", "robin@example.com"]
    assert _slots(day)  # the day is bookable again
    assert calendar.deleted  # and it is off the calendar
    view = booking.manage_view("robin", _token(taken))
    assert view["cancelled"] is True and view["days"] == []
    with pytest.raises(ValueError, match="was cancelled"):
        booking.move("robin", _token(taken), _slots(day)[0])


def test_every_side_gets_a_card_and_the_host_a_notice_not_a_reminder(calendar, monkeypatch):
    """The guest's moved and cancelled mails were bare text, and the host's copies
    went out as a "Reminder" saying "Here is what is coming up"."""
    html_of: list[tuple[str, str, str]] = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(
        mailer,
        "send",
        lambda to, subject, text, html=None: html_of.append((to, subject, html or "")) or True,
    )
    _publish()
    day = _weekday_ahead(3)
    first, second = _slots(day)[0], _slots(day)[2]
    token = _token(booking.book("robin", first, "Dana", "dana@example.com"))
    booking.move("robin", token, second)
    booking.cancel("robin", token)
    assert [(to, subject.split(":")[0]) for to, subject, _ in html_of] == [
        ("dana@example.com", "Confirmed"),
        ("robin@example.com", "Booked"),
        ("dana@example.com", "Moved"),
        ("robin@example.com", "Moved"),
        ("dana@example.com", "Cancelled"),
        ("robin@example.com", "Cancelled"),
    ]
    for to, _, html in html_of:
        assert "<table" in html, f"{to} got bare text"
        assert "Here is what is coming up" not in html and ">Reminder<" not in html
    host = [html for to, _, html in html_of if to == "robin@example.com"]
    assert all("Dana &lt;dana@example.com&gt;" in h for h in host)


def test_the_host_calling_it_off_tells_the_guest(calendar, mailed):
    _publish()
    day = _weekday_ahead(5)
    taken = booking.book("robin", _slots(day)[0], "Dana", "dana@example.com")
    event_id = [e.id for e in calendar.events.values() if e.title == "Meeting with Dana"][0]
    mailed.clear()
    assert booking.cancel_by_event(event_id) is True
    assert [to for to, _ in mailed] == ["dana@example.com"]
    assert "Cancelled" in mailed[0][1]
    assert booking.manage_view("robin", _token(taken))["cancelled"] is True
    assert booking.cancel_by_event(event_id) is False  # only once
    assert booking.cancel_by_event("not-a-booking") is False


def test_a_zoom_meeting_moves_rather_than_being_replaced(calendar, monkeypatch, mailed):
    import requests

    from luach import meetings

    monkeypatch.setenv("LUACH_ZOOM_ACCOUNT_ID", "acct")
    monkeypatch.setenv("LUACH_ZOOM_CLIENT_ID", "id")
    monkeypatch.setenv("LUACH_ZOOM_CLIENT_SECRET", "secret")
    meetings.reset()
    patched: list[dict] = []
    deleted: list[str] = []

    class R:
        status_code = 200

        def __init__(self, payload=None):
            self._p = payload or {}

        def json(self):
            return self._p

    monkeypatch.setattr(
        requests,
        "post",
        lambda url, **kw: (
            R({"access_token": "t", "expires_in": 3600})
            if "oauth/token" in url
            else R({"id": 555, "join_url": "https://zoom.us/j/555", "password": "p"})
        ),
    )
    monkeypatch.setattr(requests, "patch", lambda url, **kw: patched.append(kw["json"]) or R())
    monkeypatch.setattr(requests, "delete", lambda url, **kw: deleted.append(url) or R())

    _publish(conferencing="zoom", max_per_day=2)
    day = _weekday_ahead(6)
    taken = booking.book("robin", _slots(day)[0], "Dana", "dana@example.com")
    token = _token(taken)
    booking.move("robin", token, _slots(day)[1])
    assert patched and patched[0]["duration"] == 30  # moved, not remade
    event = next(e for e in calendar.events.values() if e.title == "Meeting with Dana")
    assert event.location == "https://zoom.us/j/555"  # the same link still works

    booking.cancel("robin", token)
    assert any("/meetings/555" in url for url in deleted)  # and it is taken down


async def test_the_link_is_the_proof_and_only_for_that_meeting(client, calendar, mailed):
    _publish()
    day = _weekday_ahead(7)
    free = _slots(day)
    taken = booking.book("robin", free[0], "Dana", "dana@example.com")
    token = _token(taken)

    # No session anywhere in this: the token is what identifies the meeting.
    r = await client.get(f"/api/book/robin/manage/{token}")
    assert r.status_code == 200 and r.json()["name"] == "Dana"
    assert (await client.get("/api/book/robin/manage/not-a-token")).status_code == 404
    assert (await client.get(f"/api/book/nobody/manage/{token}")).status_code == 404
    r = await client.post(f"/api/book/robin/manage/{token}/move", json={"start": "nonsense"})
    assert r.status_code == 400
    r = await client.post(f"/api/book/robin/manage/{token}/move", json={"start": free[1]})
    assert r.status_code == 200 and r.json()["moved"] is True
    assert (await client.post(f"/api/book/robin/manage/{token}/cancel")).json()["cancelled"] is True
    with db.session() as s:
        from sqlalchemy import select

        row = s.execute(select(db.Booking)).scalars().one()
    assert row.cancelled_at is not None and row.token_hash and row.token_hash != token


def test_each_side_is_told_in_its_own_hours(calendar, monkeypatch):
    """The host lives in New York; the visitor booked from Madrid."""
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(
        mailer,
        "send",
        lambda to, subject, text, html=None: sent.append((to, subject, text)) or True,
    )
    monkeypatch.setattr(
        mailer,
        "send_digest",
        lambda to, subject, lines: sent.append((to, subject, " ".join(lines))) or True,
    )
    _publish(max_per_day=2)
    day = _weekday_ahead(3)
    free = _slots(day)
    taken = booking.book("robin", free[0], "Dana", "dana@example.com", timezone="Europe/Madrid")
    guest = next(m for m in sent if m[0] == "dana@example.com")
    host = next(m for m in sent if m[0] == "robin@example.com")

    # 09:00 in New York is 15:00 in Madrid -- 14:00 in the week between Europe's and North
    # America's clock changes, which a date three weekdays ahead can land in. Each reads their
    # own, and the guest is told the host's as well so nobody does the arithmetic.
    def in_madrid(new_york: str) -> str:
        return (
            datetime.fromisoformat(f"{day}T{new_york}")
            .replace(tzinfo=times.zone(TZ))
            .astimezone(times.zone("Europe/Madrid"))
            .strftime("%H:%M")
        )

    assert in_madrid("09:00") in guest[1] and "Europe/Madrid" in guest[2]
    assert "09:00" in guest[2] and "Robin" in guest[2]
    assert "09:00" in host[1] and "America/New_York" in host[2]

    sent.clear()
    booking.move("robin", _token(taken), free[1])
    guest = next(m for m in sent if m[0] == "dana@example.com")
    host = next(m for m in sent if m[0] == "robin@example.com")
    assert in_madrid("09:30") in guest[1] and "09:30" in host[2]

    # A zone the browser made up is ignored rather than trusted.
    assert booking.book("robin", free[2], "Ravi", "ravi@example.com", timezone="Mars/Olympus")[
        "booked"
    ]
    with db.session() as s:
        from sqlalchemy import select

        rows = {r.email: r.timezone for r in s.execute(select(db.Booking)).scalars()}
    assert rows["dana@example.com"] == "Europe/Madrid" and rows["ravi@example.com"] == ""
