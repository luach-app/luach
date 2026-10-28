"""Zoom links on bookings: made when asked for, never at the booking's expense."""

from __future__ import annotations

from datetime import timedelta

import pytest

from luach import booking, meetings
from luach.calendar import times

TZ = "America/New_York"


@pytest.fixture(autouse=True)
def zoom_credentials(monkeypatch):
    monkeypatch.setenv("LUACH_ZOOM_ACCOUNT_ID", "acct")
    monkeypatch.setenv("LUACH_ZOOM_CLIENT_ID", "id")
    monkeypatch.setenv("LUACH_ZOOM_CLIENT_SECRET", "secret")
    meetings.reset()
    yield
    meetings.reset()


class FakeResponse:
    def __init__(self, status: int, payload: dict):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


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
            "location": "my office",
            "hours": {d: [["09:00", "12:00"]] for d in ("mon", "tue", "wed", "thu", "fri")},
            **changes,
        },
    )


def _first_slot() -> str:
    day = _weekday_ahead(4)
    return next(s["start"] for d in booking.slots_for(1) if d["day"] == day for s in d["slots"])


def test_a_zoom_link_replaces_the_written_location(calendar, monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_post(url, **kw):
        calls.append((url, kw))
        if "oauth/token" in url:
            return FakeResponse(200, {"access_token": "tok-1", "expires_in": 3600})
        return FakeResponse(
            201, {"id": 98765, "join_url": "https://acme.zoom.us/j/98765", "password": "abc"}
        )

    import requests

    monkeypatch.setattr(requests, "post", fake_post)
    _publish(conferencing="zoom")
    out = booking.book("robin", _first_slot(), "Dana", "dana@example.com")
    assert out["booked"] is True
    event = next(e for e in calendar.events.values() if e.title == "Meeting with Dana")
    assert event.location == "https://acme.zoom.us/j/98765"
    assert "Zoom: https://acme.zoom.us/j/98765" in event.description
    assert "passcode abc" in event.description
    # One token, then the meeting; the account id never rides in the body.
    assert "oauth/token" in calls[0][0] and calls[0][1]["params"]["account_id"] == "acct"
    assert calls[1][0].endswith("/users/me/meetings")
    body = calls[1][1]["json"]
    assert body["duration"] == 30 and body["timezone"] == TZ and body["type"] == 2

    # The token is reused while it is good.
    calls.clear()
    booking.book("robin", _first_slot(), "Ravi", "ravi@example.com")
    assert [u for u, _ in calls] == ["https://api.zoom.us/v2/users/me/meetings"]


def test_a_booking_survives_zoom_being_down(calendar, monkeypatch):
    import requests

    def fake_post(url, **kw):
        if "oauth/token" in url:
            return FakeResponse(200, {"access_token": "tok", "expires_in": 3600})
        raise requests.RequestException("zoom is having a day")

    monkeypatch.setattr(requests, "post", fake_post)
    _publish(conferencing="zoom")
    out = booking.book("robin", _first_slot(), "Dana", "dana@example.com")
    assert out["booked"] is True
    event = next(e for e in calendar.events.values() if e.title == "Meeting with Dana")
    assert event.location == "my office"  # what the member wrote, not an error
    assert "Zoom" not in event.description


def test_refused_credentials_make_no_meeting(calendar, monkeypatch):
    import requests

    monkeypatch.setattr(requests, "post", lambda url, **kw: FakeResponse(401, {"error": "nope"}))
    assert meetings.create_meeting("x", times.now_in(TZ), 30, TZ) is None
    _publish(conferencing="zoom")
    out = booking.book("robin", _first_slot(), "Dana", "dana@example.com")
    assert out["booked"] is True


def test_zoom_is_off_unless_asked_for(calendar, monkeypatch):
    import requests

    def explode(*a, **k):
        raise AssertionError("Zoom must not be called when conferencing is off")

    monkeypatch.setattr(requests, "post", explode)
    _publish()  # conferencing defaults to none
    booking.book("robin", _first_slot(), "Dana", "dana@example.com")
    event = next(e for e in calendar.events.values() if e.title == "Meeting with Dana")
    assert event.location == "my office"
    with pytest.raises(ValueError, match="'none' or 'zoom'"):
        booking.update(1, {"conferencing": "teams"})


def test_without_credentials_nothing_is_attempted(monkeypatch):
    for name in ("LUACH_ZOOM_ACCOUNT_ID", "LUACH_ZOOM_CLIENT_ID", "LUACH_ZOOM_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    meetings.reset()
    assert meetings.configured() is False
    assert meetings.create_meeting("x", times.now_in(TZ), 30, TZ) is None
    assert meetings.delete_meeting("123") is False
