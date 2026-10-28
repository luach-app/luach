"""What probing every route turned up: the answers a caller gets
when it asks for something wrong. Each one used to be a 500, a second error
shape, or a 200 for a request that did nothing it said."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from luach import booking
from luach.agent import runtime
from luach.app import create_app
from luach.calendar import times
from tests.doubles import ScriptedModel, call, say

TZ = "America/New_York"
HUGE = "99999999999999999999999"


@pytest.fixture
async def app(tmp_path):
    return create_app(static_dir=tmp_path / "nope")


@asynccontextmanager
async def _signed_in(
    app, username="robin", password="correct horse battery"
) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        r = await c.post("/api/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200, r.text
        yield c


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("DELETE", f"/api/members/{HUGE}"),
        ("PATCH", f"/api/tasks/{HUGE}"),
        ("DELETE", f"/api/tasks/{HUGE}"),
        ("POST", f"/api/tasks/{HUGE}/done"),
        ("POST", f"/api/board/tasks/{HUGE}/done"),
        ("DELETE", f"/api/boards/{HUGE}"),
        ("PATCH", f"/api/busy/{HUGE}"),
        ("DELETE", f"/api/busy/{HUGE}"),
        ("DELETE", "/api/members/abc"),
        ("PATCH", "/api/tasks/abc"),
    ],
)
async def test_an_id_that_cannot_be_one_is_not_found(app, method, path):
    """A number past SQLite's integers was a 500; a word was FastAPI's own 422."""
    async with _signed_in(app) as c:
        r = await c.request(method, path, json={"title": "x"})
    assert r.status_code == 404, r.text
    assert set(r.json()) == {"error"} and r.json()["error"].startswith("there is no ")


async def test_a_bad_query_is_a_sentence_not_a_validation_dump(app):
    async with _signed_in(app) as c:
        missing = await c.get("/api/calendar/events")
        wrong = await c.get("/api/control/audit?limit=lots")
    assert missing.status_code == 400 and missing.json() == {"error": "start is required"}
    assert wrong.status_code == 400 and wrong.json() == {"error": "limit must be a whole number"}


async def test_a_busy_feed_takes_only_what_a_person_may_change(app, monkeypatch):
    """The body was splatted into the call: {"user_id": 1} was a TypeError, a 500."""
    from luach import busy

    monkeypatch.setattr(busy, "fetch_feed", lambda url: "BEGIN:VCALENDAR\nEND:VCALENDAR\n")
    monkeypatch.setattr(busy, "_not_public", lambda url: None)  # no DNS in a test
    async with _signed_in(app) as c:
        made = await c.post("/api/busy", json={"name": "Work", "url": "https://example.com/w.ics"})
        sid = made.json()["sources"][0]["id"]
        hijack = await c.patch(f"/api/busy/{sid}", json={"user_id": 2, "name": "Job"})
        r = await c.patch(f"/api/busy/{sid}", json={"name": "Job"})
    assert hijack.status_code == 400 and hijack.json() == {"error": "unknown setting user_id"}
    assert r.status_code == 200 and r.json()["sources"][0]["name"] == "Job"


async def test_a_board_error_is_the_sentence_without_quotes(app):
    async with _signed_in(app) as c:
        r = await c.post("/api/boards", json={"code": "NOPE99"})
    assert r.status_code == 404
    assert r.json()["error"] == "no screen is waiting with that code"


async def test_an_event_refuses_a_rule_or_an_address_it_cannot_use(app, calendar):
    start = (times.now_in(TZ) + timedelta(days=2)).strftime("%Y-%m-%dT10:00")
    async with _signed_in(app) as c:
        rule = await c.post(
            "/api/calendar/events", json={"title": "x", "start": start, "recurrence": "FREQ=NOPE"}
        )
        who = await c.post(
            "/api/calendar/events",
            json={"title": "x", "start": start, "attendees": ["not-an-email", "a@example.com"]},
        )
        good = await c.post(
            "/api/calendar/events",
            json={"title": "Piano", "start": start, "recurrence": "FREQ=WEEKLY;BYDAY=TU"},
        )
    assert rule.status_code == 400 and "repeat rule" in rule.json()["error"]
    assert who.status_code == 400 and who.json()["error"] == "not-an-email is not an email address"
    assert good.status_code == 200 and good.json()["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TU"]
    assert [e.title for e in calendar.events.values()] == ["Piano"]


async def test_the_household_uses_only_calendars_luach_can_see(app, two_calendars):
    """An unknown id was stored, and new events went where no listing reads."""
    async with _signed_in(app) as c:
        unknown = await c.patch("/api/household", json={"calendars": ["home", "nope"]})
        default = await c.patch("/api/household", json={"default_calendar": "nope"})
        seen = await c.patch("/api/household", json={"calendars": ["home", "school"]})
    assert unknown.status_code == 400 and "nope" in unknown.json()["error"]
    assert default.status_code == 400
    assert seen.status_code == 200 and seen.json()["calendars"] == ["home", "school"]


async def test_booking_hours_that_are_not_windows_do_not_wipe_the_day(app):
    async with _signed_in(app) as c:
        await c.patch("/api/booking", json={"hours": {"mon": [["09:00", "12:00"]]}})
        r = await c.patch("/api/booking", json={"hours": {"mon": "9-5"}})
        typo = await c.patch("/api/booking", json={"hours": {"monday": [["09:00", "12:00"]]}})
        after = await c.get("/api/booking")
    assert r.status_code == 400 and typo.status_code == 400
    assert after.json()["hours"]["mon"] == [["09:00", "12:00"]]


async def test_a_family_name_is_text(app):
    async with _signed_in(app) as c:
        r = await c.post("/api/family", json={"name": {"a": 1}})
    assert r.status_code == 400 and r.json() == {"error": "name must be text"}


async def test_someone_elses_thread_is_refused_with_a_status(app):
    """It was a 200 whose body carried the refusal."""
    runtime.set_model(ScriptedModel([[call("just_talking", about="hi")], [say("Hi.")]]))
    async with _signed_in(app) as robin:
        tid = (await robin.post("/api/agent", json={"text": "hi"})).json()["thread_id"]
    async with _signed_in(app, "ana", "another good password") as ana:
        sync = await ana.post("/api/agent", json={"text": "hi", "thread_id": tid})
        stream = await ana.post("/api/agent/stream", json={"text": "hi", "thread_id": tid})
    assert sync.status_code == 403 and stream.status_code == 403
    assert sync.json() == {"error": "that thread belongs to someone else"}


async def test_failed_bookings_do_not_lock_a_visitor_out_of_cancelling(app, calendar):
    """Booking, moving and cancelling shared one cap per visitor."""
    booking.update(
        1,
        {
            "enabled": True,
            "slug": "robin",
            "lead_hours": 0,
            "hours": {d: [["09:00", "17:00"]] for d in booking.DAYS},
        },
    )
    slot = next(s["start"] for d in booking.slots_for(1) for s in d["slots"])
    visitor = AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test")
    async with visitor:
        made = await visitor.post(
            "/api/book/robin", json={"start": slot, "name": "Dana", "email": "dana@example.com"}
        )
        token = made.json()["manage"].split("manage=")[1]
        for _ in range(12):
            r = await visitor.post("/api/book/robin", json={"start": "garbage", "name": "D"})
        assert r.status_code == 429 and r.json()["retry_after"] > 0
        cancelled = await visitor.post(f"/api/book/robin/manage/{token}/cancel")
    assert cancelled.status_code == 200, cancelled.text


async def test_signing_out_needs_no_session(app):
    """A stale cookie could not be cleared: logout itself asked to sign in first."""
    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test")
    async with c:
        r = await c.post("/api/auth/logout")
    assert r.status_code == 200 and r.json() == {"ok": True}


# -- the shape itself -----------------------------------------------------------


async def test_a_stored_time_says_it_is_utc(app):
    """Without an offset a browser reads UTC as its own local time."""
    runtime.set_model(ScriptedModel([[call("just_talking", about="hi")], [say("Hi.")]]))
    async with _signed_in(app) as c:
        await c.post("/api/agent", json={"text": "hi"})
        listed = (await c.get("/api/threads")).json()["threads"][0]
        me = (await c.get("/api/auth/me")).json()
    assert listed["created_at"].endswith("+00:00") and listed["updated_at"].endswith("+00:00")
    assert me["last_seen"] is None or me["last_seen"].endswith("+00:00")


async def test_a_hold_is_decided_at_its_own_path_and_the_old_one_still_works(app, calendar):
    start = (times.now_in(TZ) + timedelta(days=2)).strftime("%Y-%m-%dT10:00")
    runtime.set_model(
        ScriptedModel(
            [
                [call("create_event", title="A", start=start, certainty="low")],
                [say("held")],
                [call("create_event", title="B", start=start, certainty="low")],
                [say("held")],
            ]
        )
    )
    async with _signed_in(app) as c:
        await c.post("/api/agent", json={"text": "a"})
        await c.post("/api/agent", json={"text": "b"})
        held = (await c.get("/api/control/pending")).json()["pending"]
        new = await c.post(f"/api/control/pending/{held[0]['id']}/deny")
        old = await c.post(f"/api/control/deny/{held[1]['id']}")
    assert new.status_code == 200 and new.json()["status"] == "denied"
    assert old.status_code == 200 and old.json()["status"] == "denied"


async def test_every_delete_says_ok_and_a_missing_thing_is_not_found(app):
    async with _signed_in(app) as c:
        email = await c.delete("/api/auth/emails/nobody@example.com")
        passkey = await c.delete("/api/auth/passkeys/nope")
        invite = await c.delete("/api/members/invite/nobody@example.com")
        await c.post("/api/members/invite", json={"email": "new@example.com"})
        revoked = await c.delete("/api/members/invite/new@example.com")
    assert (email.status_code, passkey.status_code, invite.status_code) == (404, 404, 404)
    assert revoked.status_code == 200 and revoked.json() == {"ok": True, "revoked": 1}


async def test_conversations_come_a_page_at_a_time(app):
    from luach import db

    with db.session() as s:
        for i in range(5):
            s.add(db.Thread(id=f"t{i}", user_id=1, title=f"n{i}", door="web"))
    async with _signed_in(app) as c:
        first = (await c.get("/api/threads?limit=3")).json()
        rest = (
            await c.get("/api/threads", params={"before": first["threads"][-1]["updated_at"]})
        ).json()
        bad = await c.get("/api/threads?before=yesterday")
    assert len(first["threads"]) == 3 and first["more"] is True
    assert rest["more"] is False
    assert {t["id"] for t in first["threads"]} | {t["id"] for t in rest["threads"]} >= {
        f"t{i}" for i in range(5)
    }
    assert bad.status_code == 400


async def test_a_thread_id_is_an_id(app):
    async with _signed_in(app) as c:
        r = await c.post("/api/agent", json={"text": "hi", "thread_id": "../../etc"})
    assert r.status_code == 400


async def test_tasks_for_someone_not_in_the_family_is_a_mistake(app):
    async with _signed_in(app) as c:
        r = await c.get("/api/tasks?person=nobody")
    assert r.status_code == 400 and r.json() == {"error": "that is not someone in the family"}
