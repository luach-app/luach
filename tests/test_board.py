"""The house board: paired, not signed in; reads today and ticks, nothing else."""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from luach import board, config, db, family, tasks
from luach.calendar import client as cal
from luach.calendar import times


@pytest.fixture
async def http(tmp_path):
    app = create_app_for(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        yield c


@pytest.fixture
async def wall(tmp_path):
    """A second client with no cookies: the tablet on the wall."""
    app = create_app_for(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        yield c


def create_app_for(tmp_path):
    from luach.app import create_app

    return create_app(static_dir=tmp_path / "nope")


async def login(c: AsyncClient, username="robin", password="correct horse battery"):
    r = await c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


async def paired(http: AsyncClient, wall: AsyncClient) -> str:
    """Run the whole handshake; the board's token."""
    started = (await wall.post("/api/board/pair")).json()
    await login(http)
    r = await http.post("/api/boards", json={"code": started["code"].lower(), "name": "Kitchen"})
    assert r.status_code == 200, r.text
    got = await wall.get(
        f"/api/board/pair/{started['code']}", headers={board.PAIR_HEADER: started["secret"]}
    )
    return str(got.json()["token"])


class TestPairing:
    async def test_the_screen_waits_until_the_owner_types_its_code(self, http, wall):
        started = (await wall.post("/api/board/pair")).json()
        assert len(started["code"]) == board.CODE_LEN
        headers = {board.PAIR_HEADER: started["secret"]}
        assert (await wall.get(f"/api/board/pair/{started['code']}", headers=headers)).json() == {
            "waiting": True
        }
        await login(http)
        await http.post("/api/boards", json={"code": started["code"]})
        token = (await wall.get(f"/api/board/pair/{started['code']}", headers=headers)).json()
        assert token["token"]
        # Collected once; the code is gone after that.
        again = await wall.get(f"/api/board/pair/{started['code']}", headers=headers)
        assert again.status_code == 404

    async def test_only_the_screen_that_asked_can_collect(self, http, wall):
        started = (await wall.post("/api/board/pair")).json()
        await login(http)
        await http.post("/api/boards", json={"code": started["code"]})
        stolen = await wall.get(
            f"/api/board/pair/{started['code']}", headers={board.PAIR_HEADER: "a guess"}
        )
        assert stolen.status_code == 404

    async def test_a_code_nobody_is_showing_is_refused(self, http):
        await login(http)
        assert (await http.post("/api/boards", json={"code": "ZZZZZZ"})).status_code == 404

    async def test_only_the_owner_pairs_a_board(self, http, wall):
        started = (await wall.post("/api/board/pair")).json()
        await login(http, "ana", "another good password")
        assert (await http.post("/api/boards", json={"code": started["code"]})).status_code == 403

    def test_a_code_does_not_outlive_ten_minutes(self):
        started = board.start_pairing()
        with db.session() as s:
            s.get(db.BoardPairing, started["code"]).expires_at = db.utcnow() - timedelta(seconds=1)
        with pytest.raises(KeyError):
            board.claim(started["code"], "late")

    def test_codes_are_easy_to_read_off_a_wall(self):
        for _ in range(50):
            code = board.start_pairing()["code"]
            assert not set(code) & set("01OIL")
            with db.session() as s:
                s.delete(s.get(db.BoardPairing, code))


class TestWhatABoardSees:
    async def test_the_day_by_person(self, http, wall):
        token = await paired(http, wall)
        family.add("Lily", kind="kid")
        tz = config.timezone()
        now = times.now_in(tz)
        start = now.replace(hour=23, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")
        d = cal.Draft(title="Math homework check", span=times.span(start, None, tz))
        d.leader = "lily"
        cal.get_calendar().insert(d, tz)
        tasks.add("Feed the cat", by=1, person="lily", days="daily")
        r = await wall.get("/api/board/today", headers={board.HEADER: token})
        assert r.status_code == 200, r.text
        day = r.json()
        assert day["board"] == "Kitchen"
        assert "Lily" in [p["name"] for p in day["people"]]
        assert [(e["title"], e["leader"]) for e in day["events"]] == [
            ("Math homework check", "lily")
        ]
        assert [t["title"] for t in day["tasks"]] == ["Feed the cat"]

    async def test_it_says_which_events_a_finger_may_move(self, http, wall):
        """The board lets a hand drag an event to someone else or another day; it
        needs to know which are someone else's, and which repeat."""
        token = await paired(http, wall)
        tz = config.timezone()
        day = times.now_in(tz).date().isoformat()
        fake = cal.get_calendar()
        assert isinstance(fake, cal.FakeCalendar)
        for eid, extra in (
            ("ours", {}),
            ("theirs", {"organizer": "coach@club.test", "read_only": True}),
            ("weekly", {"recurring_event_id": "series"}),
        ):
            fake.events[eid] = cal.Event(
                id=eid,
                title=eid,
                start=f"{day}T23:00:00",
                end=f"{day}T23:30:00",
                calendar_id="fake",
                **extra,
            )
        r = await wall.get("/api/board/today", headers={board.HEADER: token})
        got = {
            e["id"]: (e["read_only"], e["organizer"], e["recurring"], e["calendar_id"])
            for e in r.json()["events"]
        }
        assert got == {
            "ours": (False, "", False, "fake"),
            "theirs": (True, "coach@club.test", False, "fake"),
            "weekly": (False, "", True, "fake"),
        }

    async def test_a_child_at_the_wall_ticks_a_task(self, http, wall):
        token = await paired(http, wall)
        t = tasks.add("Feed the cat", by=1, days="daily")
        r = await wall.post(f"/api/board/tasks/{t.id}/done", json={}, headers={board.HEADER: token})
        assert r.json()["done"] is True
        r = await wall.post(
            f"/api/board/tasks/{t.id}/done", json={"done": False}, headers={board.HEADER: token}
        )
        assert r.json()["done"] is False

    async def test_a_board_token_opens_nothing_else(self, http, wall):
        token = await paired(http, wall)
        h = {board.HEADER: token}
        assert (await wall.get("/api/tasks", headers=h)).status_code == 401
        assert (await wall.get("/api/family", headers=h)).status_code == 401
        assert (await wall.get("/api/threads", headers=h)).status_code == 401
        assert (await wall.post("/api/tasks", json={"title": "x"}, headers=h)).status_code == 401

    async def test_without_a_token_the_board_door_is_shut(self, wall):
        assert (await wall.get("/api/board/today")).status_code == 401
        assert (
            await wall.get("/api/board/today", headers={board.HEADER: "made up"})
        ).status_code == 401
        assert (await wall.post("/api/board/tasks/1/done", json={})).status_code == 401

    async def test_the_owner_takes_a_board_away(self, http, wall):
        token = await paired(http, wall)
        (b,) = (await http.get("/api/boards")).json()["boards"]
        assert b["name"] == "Kitchen" and b["last_seen"] is None
        await wall.get("/api/board/today", headers={board.HEADER: token})
        assert (await http.get("/api/boards")).json()["boards"][0]["last_seen"]
        assert (await http.delete(f"/api/boards/{b['id']}")).status_code == 200
        assert (
            await wall.get("/api/board/today", headers={board.HEADER: token})
        ).status_code == 401
        assert (await http.delete(f"/api/boards/{b['id']}")).status_code == 404


class TestAMemberSeesTheBoardAnywhere:
    async def test_signed_in_there_is_nothing_to_pair(self, http):
        await login(http)
        t = tasks.add("Feed the cat", by=1, days="daily")
        r = await http.get("/api/board/today")
        assert r.status_code == 200, r.text
        assert r.json()["board"] == "" and r.json()["viewer"] == "Robin"
        r = await http.post(f"/api/board/tasks/{t.id}/done", json={})
        assert r.json()["done"] is True

    async def test_a_tick_from_a_phone_says_who_ticked(self, http):
        await login(http, "ana", "another good password")
        t = tasks.add("Bins", by=1, days="daily")
        await http.post(f"/api/board/tasks/{t.id}/done", json={})
        with db.session() as s:
            (row,) = s.query(db.TaskDone).filter_by(task_id=t.id).all()
        assert row.by == "ana"


class TestATouchBoard:
    """The board pages through the coming days, and — on a screen the owner left
    able to — adds, changes and removes, through the same checks as the app."""

    async def test_it_pages_through_the_coming_days(self, http, wall):
        token = await paired(http, wall)
        h = {board.HEADER: token}
        today = times.now_in(config.timezone()).date()
        ahead = (today + timedelta(days=3)).isoformat()
        r = (await wall.get(f"/api/board/today?day={ahead}", headers=h)).json()
        assert r["day"] == ahead and r["today"] == today.isoformat()
        assert r["can_edit"] is True
        too_far = (today + timedelta(days=40)).isoformat()
        assert (await wall.get(f"/api/board/today?day={too_far}", headers=h)).status_code == 400
        assert (await wall.get("/api/board/today?day=yesterday", headers=h)).status_code == 400

    async def test_an_editable_screen_adds_moves_and_removes(self, http, wall, calendar):
        family.add("Lily", kind="kid")
        token = await paired(http, wall)
        h = {board.HEADER: token}
        start = (times.now_in(config.timezone()) + timedelta(days=1)).strftime("%Y-%m-%dT16:00")
        made = await wall.post(
            "/api/board/events",
            headers=h,
            json={"title": "Piano", "start": start, "leaders": ["lily"], "attendees": []},
        )
        assert made.status_code == 200 and made.json()["leaders"] == ["lily"]
        eid = made.json()["id"]
        moved = await wall.patch(
            f"/api/board/events/{eid}", headers=h, json={"start": start[:11] + "17:00"}
        )
        assert moved.json()["start"].startswith(start[:11] + "17:00")
        t = (
            await wall.post("/api/board/tasks", headers=h, json={"title": "Pack", "person": "lily"})
        ).json()
        assert t["person"] == "lily"
        changed = await wall.patch(
            f"/api/board/tasks/{t['id']}", headers=h, json={"title": "Pack the bag"}
        )
        assert changed.json()["title"] == "Pack the bag"
        assert (await wall.delete(f"/api/board/tasks/{t['id']}", headers=h)).json() == {"ok": True}
        assert (await wall.delete(f"/api/board/events/{eid}", headers=h)).json()["ok"] is True
        assert calendar.events == {}
        trail = {e["event_type"] for e in (await http.get("/api/control/audit")).json()["entries"]}
        assert {"event.created", "event.updated", "task.added", "task.removed"} <= trail

    async def test_a_screen_invites_nobody_and_links_nowhere(self, http, wall, calendar):
        """The kiosk acts with the owner's authority: an address typed at the wall
        would get an invitation from the owner's calendar."""
        from luach import household

        household.update(default_attendees=["grandma@example.com"])
        token = await paired(http, wall)
        h = {board.HEADER: token}
        start = (times.now_in(config.timezone()) + timedelta(days=1)).strftime("%Y-%m-%dT16:00")
        made = await wall.post(
            "/api/board/events",
            headers=h,
            json={"title": "Party", "start": start, "attendees": ["stranger@evil.test"]},
        )
        assert made.status_code == 200, made.text
        eid = made.json()["id"]
        assert calendar.events[eid].attendees == [], "neither the typed nor the usual guests"
        assert "attendees" not in made.json() and "html_link" not in made.json()
        await wall.patch(
            f"/api/board/events/{eid}", headers=h, json={"attendees": ["stranger@evil.test"]}
        )
        assert calendar.events[eid].attendees == []
        calendar.events[eid].html_link = "https://calendar.google.com/event?eid=x"
        seen = (await wall.get(f"/api/board/events/{eid}", headers=h)).json()
        assert "html_link" not in seen and "attendees" not in seen
        # A member on their own device still sees the event whole.
        mine = (await http.get(f"/api/board/events/{eid}")).json()
        assert mine["html_link"].startswith("https://calendar.google.com/")

    async def test_the_board_has_its_own_list_of_calendars(self, http, wall, two_calendars):
        token = await paired(http, wall)
        h = {board.HEADER: token}
        got = (await wall.get("/api/board/calendars", headers=h)).json()
        assert [c["id"] for c in got["available"]] == ["home", "work"], "only those in use"
        assert got["default_calendar"] == "home" and got["default_attendees"] == []
        assert (await wall.get("/api/board/calendars")).status_code == 401
        assert (await http.get("/api/board/calendars")).status_code == 200

    async def test_the_owner_can_make_a_screen_show_only(self, http, wall):
        token = await paired(http, wall)
        h = {board.HEADER: token}
        (b,) = (await http.get("/api/boards")).json()["boards"]
        assert b["can_edit"] is True
        r = await http.patch(f"/api/boards/{b['id']}", json={"can_edit": False})
        assert r.json()["boards"][0]["can_edit"] is False
        assert (await wall.get("/api/board/today", headers=h)).json()["can_edit"] is False
        refused = await wall.post("/api/board/tasks", headers=h, json={"title": "x"})
        assert refused.status_code == 403
        # Ticking is still anyone's.
        t = tasks.add(
            "Bins", by=1, days="daily", today=times.now_in(config.timezone()).date().isoformat()
        )
        assert (
            await wall.post(f"/api/board/tasks/{t.id}/done", headers=h, json={})
        ).status_code == 200

    async def test_each_board_speaks_the_language_the_owner_gives_it(self, http, wall):
        token = await paired(http, wall)
        h = {board.HEADER: token}
        (b,) = (await http.get("/api/boards")).json()["boards"]
        # Until the owner says otherwise, the screen follows its own browser.
        assert b["language"] == "auto"
        assert (await wall.get("/api/board/today", headers=h)).json()["language"] == "auto"
        r = await http.patch(f"/api/boards/{b['id']}", json={"language": "he"})
        assert r.status_code == 200
        assert r.json()["boards"][0]["language"] == "he"
        assert r.json()["boards"][0]["can_edit"] is True
        assert (await wall.get("/api/board/today", headers=h)).json()["language"] == "he"
        for bad in ("fr", "", "HE", 3, None):
            r = await http.patch(f"/api/boards/{b['id']}", json={"language": bad})
            assert r.status_code == 400, bad
        assert (await http.get("/api/boards")).json()["boards"][0]["language"] == "he"
        # Only the owner chooses it; the screen cannot.
        assert (
            await wall.patch(f"/api/boards/{b['id']}", headers=h, json={"language": "es"})
        ).status_code in (401, 403)

    async def test_a_member_looking_at_the_board_follows_their_own_browser(self, http, wall):
        await login(http)
        assert (await http.get("/api/board/today")).json()["language"] == "auto"

    async def test_a_chore_ticked_on_another_days_page_is_that_days(self, http, wall):
        token = await paired(http, wall)
        h = {board.HEADER: token}
        today = times.now_in(config.timezone()).date()
        t = tasks.add("Bins", by=1, days="daily", today=today.isoformat())
        later = (today + timedelta(days=2)).isoformat()
        await wall.post(f"/api/board/tasks/{t.id}/done", headers=h, json={"day": later})
        assert not tasks.get(t.id, today.isoformat()).done  # type: ignore[union-attr]
        assert tasks.get(t.id, later).done  # type: ignore[union-attr]
