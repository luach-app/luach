"""Being told before it happens — once, to the right person."""

from __future__ import annotations

from datetime import timedelta

import pytest

from luach import reminders
from luach.auth import users
from luach.calendar import times
from luach.calendar.client import Draft

TZ = "America/New_York"


@pytest.fixture
def pushed(monkeypatch) -> list[tuple[int, str, str]]:
    sent: list[tuple[int, str, str]] = []
    monkeypatch.setattr(
        reminders.push,
        "notify_user",
        lambda uid, title, body, url="/": sent.append((uid, title, body)) or 1,
    )
    return sent


def _member():
    users.update_profile(1, timezone=TZ)
    m = users.member(1)
    assert m is not None
    return m


def test_settings_are_validated():
    assert reminders.settings_for(1)["lead_minutes"] == 0  # off until asked for
    assert reminders.update(1, {"lead_minutes": 120})["lead_minutes"] == 120
    assert reminders.update(1, {"evening_hour": 20, "by_email": True})["evening_hour"] == 20
    with pytest.raises(ValueError, match="between 0 and"):
        reminders.update(1, {"lead_minutes": -5})
    with pytest.raises(ValueError, match="between -1 and 23"):
        reminders.update(1, {"evening_hour": 25})
    with pytest.raises(ValueError, match="unknown setting"):
        reminders.update(1, {"loudness": 11})


def test_a_member_is_told_once_about_what_is_coming(calendar, pushed):
    member = _member()
    reminders.update(1, {"lead_minutes": 60})
    now = times.now_in(TZ)
    soon = now + timedelta(minutes=58)
    calendar.insert(
        Draft(
            title="Dentist appointment",
            span=times.span(soon.isoformat(), None, TZ),
            location="123 Main St",
        ),
        TZ,
    )
    assert reminders.run_once(now) == 1
    assert pushed[0][0] == 1 and pushed[0][1] == "Dentist appointment"
    assert "123 Main St" in pushed[0][2]
    # A second pass says nothing: the ledger remembers.
    assert reminders.run_once(now) == 0
    assert len(pushed) == 1
    assert member.timezone == TZ


def test_nothing_is_said_too_early_or_too_late(calendar, pushed):
    _member()
    reminders.update(1, {"lead_minutes": 60})
    now = times.now_in(TZ)
    calendar.insert(
        Draft(title="Far off", span=times.span((now + timedelta(hours=5)).isoformat(), None, TZ)),
        TZ,
    )
    calendar.insert(
        Draft(
            title="All day", span=times.span((now + timedelta(days=1)).date().isoformat(), None, TZ)
        ),
        TZ,
    )
    assert reminders.run_once(now) == 0
    assert pushed == []


def test_the_evening_list_goes_out_at_the_hour_asked_for(calendar, pushed):
    _member()
    reminders.update(1, {"evening_hour": 20})
    now = times.now_in(TZ).replace(hour=20, minute=1, second=0, microsecond=0)
    tomorrow = (now + timedelta(days=1)).date().isoformat()
    for title, hour in (("School trip", 9), ("Piano lesson", 16)):
        calendar.insert(
            Draft(title=title, span=times.span(f"{tomorrow}T{hour:02d}:00", None, TZ)), TZ
        )
    assert reminders.run_once(now) == 1
    assert pushed[0][1] == "Tomorrow: 2 things"
    assert "09:00 · School trip" in pushed[0][2] and "16:00 · Piano lesson" in pushed[0][2]
    assert reminders.run_once(now) == 0  # once per evening

    # An hour later it is not the evening hour any more.
    pushed.clear()
    assert reminders.run_once(now + timedelta(hours=1)) == 0


def test_a_member_who_asked_for_nothing_hears_nothing(calendar, pushed):
    _member()
    now = times.now_in(TZ)
    calendar.insert(
        Draft(
            title="Dentist", span=times.span((now + timedelta(minutes=30)).isoformat(), None, TZ)
        ),
        TZ,
    )
    assert reminders.run_once(now) == 0 and pushed == []


def test_email_goes_out_only_when_asked_for(calendar, pushed, monkeypatch):
    mailed: list[tuple[str, str, str]] = []
    monkeypatch.setattr(reminders.mailer, "configured", lambda: True)
    monkeypatch.setattr(
        reminders.mailer,
        "send",
        lambda to, subject, text, html=None: mailed.append((to, subject, html or "")) or True,
    )
    _member()
    reminders.update(1, {"lead_minutes": 30, "by_email": True})
    now = times.now_in(TZ)
    calendar.insert(
        Draft(
            title="Vet",
            location="Kitchen; then the car",
            span=times.span((now + timedelta(minutes=28)).isoformat(), None, TZ),
        ),
        TZ,
    )
    assert reminders.run_once(now) == 1
    to, subject, html = mailed[0]
    assert to == "robin@example.com" and subject.startswith("Vet, ")
    # One event is a card with its time and its place, each on a line of its
    # own — not a list whose "when" column held the date and the place.
    assert "Kitchen; then the car" in html and ">When<" in html and ">Where<" in html
    assert "Coming up" not in html


def test_a_title_with_a_semicolon_stays_one_line(calendar, pushed, monkeypatch):
    """The lines travelled joined by "; " and were split again for the mail."""
    mailed: list[list[str]] = []
    monkeypatch.setattr(reminders.mailer, "configured", lambda: True)
    monkeypatch.setattr(
        reminders.mailer, "send_digest", lambda to, subject, lines: mailed.append(lines) or True
    )
    _member()
    reminders.update(1, {"evening_hour": 20, "by_email": True})
    now = times.now_in(TZ).replace(hour=20, minute=1, second=0, microsecond=0)
    tomorrow = (now + timedelta(days=1)).date().isoformat()
    calendar.insert(
        Draft(title="Pack; then drive", span=times.span(f"{tomorrow}T09:00", None, TZ)), TZ
    )
    assert reminders.run_once(now) == 1
    assert mailed == [["09:00 · Pack; then drive"]]


def test_an_empty_week_says_so_rather_than_listing_nothing(calendar, pushed, monkeypatch):
    mailed: list[list[str]] = []
    monkeypatch.setattr(reminders.mailer, "configured", lambda: True)
    monkeypatch.setattr(
        reminders.mailer, "send_digest", lambda to, subject, lines: mailed.append(lines) or True
    )
    _member()
    reminders.update(1, {"weekly_day": 6, "weekly_hour": 18})
    now = times.now_in(TZ)
    while now.weekday() != 6:
        now += timedelta(days=1)
    now = now.replace(hour=18, minute=2, second=0, microsecond=0)
    assert reminders.run_once(now) == 1
    assert mailed == [[]], "no bullet reading 'Nothing…' under 'Here is what is coming up'"
    assert pushed[0][2] == "Nothing on the calendar yet."


async def test_the_routes_carry_the_settings():
    from httpx import ASGITransport, AsyncClient

    from luach.app import create_app

    app = create_app(static_dir="/nonexistent")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        assert (await c.get("/api/reminders")).status_code == 401
        await c.post(
            "/api/auth/login", json={"username": "robin", "password": "correct horse battery"}
        )
        assert (await c.get("/api/reminders")).json()["lead_minutes"] == 0
        r = await c.patch("/api/reminders", json={"lead_minutes": 90, "evening_hour": 19})
        assert r.status_code == 200 and r.json() == {
            "lead_minutes": 90,
            "evening_hour": 19,
            "weekly_day": -1,
            "weekly_hour": 18,
            "by_email": False,
        }
        assert (await c.patch("/api/reminders", json={})).status_code == 400
        assert (await c.patch("/api/reminders", json={"lead_minutes": "soon"})).status_code == 400


def test_the_week_ahead_goes_out_on_the_day_asked_for(calendar, pushed, monkeypatch):
    mailed: list[tuple[str, str, list[str]]] = []
    monkeypatch.setattr(reminders.mailer, "configured", lambda: True)
    monkeypatch.setattr(
        reminders.mailer,
        "send_digest",
        lambda to, subject, lines: mailed.append((to, subject, lines)) or True,
    )
    _member()
    reminders.update(1, {"weekly_day": 6, "weekly_hour": 18})  # Sunday evening
    now = times.now_in(TZ)
    while now.weekday() != 6:
        now += timedelta(days=1)
    now = now.replace(hour=18, minute=2, second=0, microsecond=0)
    monday = (now + timedelta(days=1)).date().isoformat()
    calendar.insert(
        Draft(title="Quarterly planning review", span=times.span(f"{monday}T15:00", None, TZ)), TZ
    )
    assert reminders.run_once(now) == 1
    assert pushed[0][1] == "The week ahead: 1 thing"
    assert "Quarterly planning review" in pushed[0][2]
    # It lands in the inbox too: a week's list is a read, not an alert.
    assert mailed and mailed[0][0] == "robin@example.com"
    assert reminders.run_once(now) == 0  # once a week

    # Saturday at the same hour is not the day.
    pushed.clear()
    assert reminders.run_once(now - timedelta(days=1)) == 0
