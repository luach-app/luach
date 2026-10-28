"""Every way to give Ruby something, each checked where it matters: Ruby's
column on the board.

In luach: by chat (an event, a chore, a to-do, a tick), in the event form, in
the Tasks tab, on the board. In Google Calendar, with no luach in the loop:
invite Ruby, give it Ruby's colour, or name Ruby in the title — through the
real GoogleCalendar client, against a stand-in for Google's API.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from luach import config, family, tasks
from luach.agent import runtime
from luach.app import create_app
from luach.calendar import client as cal
from luach.calendar import times
from tests.doubles import ScriptedModel, call, say
from tests.test_units import _fake_google_service

TZ = config.DEFAULT_TIMEZONE


def _today() -> str:
    return times.now_in(TZ).date().isoformat()


def _at(hour: int) -> str:
    """Tomorrow at `hour`. It was tonight, and after 11pm in New York "tonight at
    11" was in the past — held for approval, never on the board — so these
    tests failed or passed by the clock."""
    return (
        (times.now_in(TZ) + timedelta(days=1))
        .replace(hour=hour, minute=0, second=0, microsecond=0)
        .strftime("%Y-%m-%dT%H:%M")
    )


def _tomorrow() -> str:
    return (times.now_in(TZ) + timedelta(days=1)).date().isoformat()


@pytest.fixture(autouse=True)
def zone(monkeypatch):
    monkeypatch.setenv("LUACH_TIMEZONE", TZ)


@pytest.fixture
def harpers():
    """Robin (from his account), Alex, and the two children — Ruby in Sage."""
    family.roster()  # Robin and the test's second account, seeded from the accounts
    family.add("Alex", email="alex@example.com", color="4")
    family.add("Ruby", kind="kid", email="ruby@example.com", color="2")
    family.add("Lily", kind="kid", color="3")


@pytest.fixture
async def http(tmp_path):
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        r = await c.post(
            "/api/auth/login", json={"username": "robin", "password": "correct horse battery"}
        )
        assert r.status_code == 200
        yield c


async def rubys_column(http: AsyncClient) -> tuple[list[str], list[tuple[str, bool]]]:
    """What the board shows under Ruby: event titles, and (task, done)."""
    # Events are made for tomorrow (see _at), so they are read off tomorrow's
    # page; tasks are ticked today, so they are read off today's.
    ahead = (await http.get(f"/api/board/today?day={_tomorrow()}")).json()
    day = (await http.get("/api/board/today")).json()
    events = [e["title"] for e in ahead["events"] if e["leader"] == "ruby"]
    todo = [(t["title"], t["done"]) for t in day["tasks"] if t["person"] == "ruby"]
    return events, todo


def chat(*steps):
    runtime.set_model(ScriptedModel([*steps]))


class TestInLuach:
    async def test_by_chat_an_event(self, http, calendar, harpers):
        chat(
            [call("create_event", title="Football", start=_at(23), for_whom="Ruby")],
            [say("Added: Football for Ruby.")],
        )
        await runtime.run_turn(
            "ruby has football tonight at 11", user_id=1, principal="robin", timezone=TZ
        )
        assert (await rubys_column(http))[0] == ["Football"]
        (ev,) = calendar.events.values()
        assert ev.attendees[-1] == "ruby@example.com", "Ruby is invited"

    async def test_by_chat_a_chore_and_a_to_do(self, http, harpers):
        weekday = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][times.now_in(TZ).weekday()]
        chat(
            [call("add_task", title="Bins out", for_whom="Ruby", repeats=weekday)],
            [call("add_task", title="Library book", for_whom="Ruby", due=_today())],
            [say("Done.")],
        )
        await runtime.run_turn(
            "ruby: bins, and the library book", user_id=1, principal="robin", timezone=TZ
        )
        assert sorted((await rubys_column(http))[1]) == [
            ("Bins out", False),
            ("Library book", False),
        ]

    async def test_by_chat_a_tick(self, http, harpers):
        t = tasks.add("Dishes", by=1, person="ruby", days="daily")
        chat(
            [call("list_tasks", for_whom="Ruby")],
            [call("complete_task", task_id=t.id)],
            [say("Ticked.")],
        )
        await runtime.run_turn("ruby did the dishes", user_id=1, principal="robin", timezone=TZ)
        assert (await rubys_column(http))[1] == [("Dishes", True)]

    async def test_in_the_event_form(self, http, harpers):
        r = await http.post(
            "/api/calendar/events",
            json={"title": "Dentist", "start": _at(23), "leader": "ruby", "attendees": []},
        )
        assert r.json()["attendees"] == ["ruby@example.com"]
        assert (await rubys_column(http))[0] == ["Dentist"]

    async def test_handing_an_existing_event_to_ruby(self, http, harpers):
        ev = (
            await http.post(
                "/api/calendar/events", json={"title": "Haircut", "start": _at(23), "attendees": []}
            )
        ).json()
        assert (await rubys_column(http))[0] == []
        await http.patch(f"/api/calendar/events/{ev['id']}", json={"leader": "ruby"})
        assert (await rubys_column(http))[0] == ["Haircut"]

    async def test_in_the_tasks_tab(self, http, harpers):
        await http.post(
            "/api/tasks",
            json={
                "title": "Feed the cat",
                "person": "ruby",
                "days": ["MO", "TU", "WE", "TH", "FR", "SA", "SU"],
            },
        )
        assert (await rubys_column(http))[1] == [("Feed the cat", False)]

    async def test_on_the_board_and_back_in_the_tasks_tab(self, http, harpers):
        t = tasks.add("Feed the cat", by=1, person="ruby", days="daily")
        await http.post(f"/api/board/tasks/{t.id}/done", json={})
        day = (await http.get("/api/tasks")).json()
        assert [(x["title"], x["done"]) for x in day["tasks"]] == [("Feed the cat", True)]


@pytest.fixture
def google(tmp_path, harpers):
    """The family calendar in Google, reached through luach's real client."""
    key = tmp_path / "sa.json"
    key.write_text(json.dumps({"client_email": "sa@x"}))
    g = cal.GoogleCalendar(str(key), "family@x")
    store: dict = {}
    g._service = _fake_google_service(
        store, [{"id": "family@x", "summary": "Harper", "primary": True}]
    )
    cal.set_calendar(g)
    return store


def made_in_google(store: dict, eid: str, title: str, **extra) -> None:
    """An event someone added in the Google Calendar app on their phone."""
    store[eid] = {
        "summary": title,
        "start": {"dateTime": times.to_utc_iso(times.parse_when(_at(23), TZ))},
        "end": {
            "dateTime": times.to_utc_iso(times.parse_when(_at(23), TZ) + timedelta(minutes=30))
        },
        "_cal": "family@x",
        **extra,
    }


class TestInGoogleCalendar:
    async def test_invite_ruby(self, http, google):
        made_in_google(
            google,
            "g1",
            "Football",
            attendees=[{"email": "ruby@example.com"}, {"email": "coach@club.org"}],
        )
        assert (await rubys_column(http))[0] == ["Football"]

    async def test_give_it_rubys_colour(self, http, google):
        made_in_google(google, "g1", "Swimming", colorId="2")  # Sage
        assert (await rubys_column(http))[0] == ["Swimming"]

    @pytest.mark.parametrize(
        "title",
        [
            "Ruby: football",
            "Ruby - football",
            "Football (Ruby)",
            "Ruby's football",
            "ruby: FOOTBALL",
        ],
    )
    async def test_name_ruby_in_the_title(self, http, google, title):
        made_in_google(google, "g1", title)
        assert (await rubys_column(http))[0] == [title]

    @pytest.mark.parametrize(
        "title", ["Rubyanne's party", "Football with Ruby and Lily (Lily) (Ruby)", "Struby: x"]
    )
    async def test_a_title_that_does_not_clearly_name_ruby(self, http, google, title):
        made_in_google(google, "g1", title)
        assert (await rubys_column(http))[0] == []

    async def test_what_luach_marked_wins_over_the_colour(self, http, google):
        made_in_google(
            google,
            "g1",
            "Ruby: piano",
            colorId="3",
            extendedProperties={"shared": {"luach_leader": "alex"}},
        )
        day = (await http.get("/api/board/today")).json()
        assert [e["leader"] for e in day["events"]] == ["alex"]

    async def test_colour_wins_over_the_title_and_the_title_over_the_invite(self, http, google):
        made_in_google(
            google, "g1", "Ruby: piano", colorId="3", attendees=[{"email": "ruby@example.com"}]
        )
        made_in_google(google, "g2", "Lily's recital", attendees=[{"email": "ruby@example.com"}])
        day = (await http.get("/api/board/today")).json()
        assert sorted((e["title"], e["leader"]) for e in day["events"]) == [
            ("Lily's recital", "lily"),
            ("Ruby: piano", "lily"),
        ]

    async def test_made_nobodys_in_luach_stays_nobodys(self, http, google):
        made_in_google(
            google,
            "g1",
            "Ruby: dinner",
            colorId="2",
            extendedProperties={"shared": {"luach_leader": "-"}},
        )
        assert (await rubys_column(http))[0] == []

    async def test_a_colour_that_is_nobodys_says_nothing(self, http, google):
        made_in_google(google, "g1", "Groceries", colorId="11")
        day = (await http.get("/api/board/today")).json()
        assert [e["leader"] for e in day["events"]] == [""]

    async def test_made_in_luach_it_reaches_google_in_rubys_colour(self, http, google):
        r = await http.post(
            "/api/calendar/events",
            json={"title": "Judo", "start": _at(23), "leader": "ruby", "attendees": []},
        )
        assert r.status_code == 200, r.text
        body = google["new"]
        assert body["colorId"] == "2"
        assert body["extendedProperties"]["shared"]["luach_leader"] == "ruby"
        assert body["attendees"] == [{"email": "ruby@example.com"}]
        assert (await rubys_column(http))[0] == ["Judo"]

    async def test_luach_says_whose_it_is_when_asked(self, google):
        made_in_google(google, "g1", "Swimming", colorId="2")
        chat(
            [call("list_events", start_date=_today(), end_date=_today())],
            [say("Ruby has swimming.")],
        )
        result = await runtime.run_turn(
            "what's on today", user_id=1, principal="robin", timezone=TZ
        )
        # What the model read back names Ruby, so it can answer "whose is it".
        assert '"for": "Ruby"' in json.dumps(result.tool_calls + result.widgets)


class TestColoursStayOnePersonEach:
    def test_a_colour_someone_has_is_refused(self, harpers):
        with pytest.raises(ValueError, match="Ruby already has Sage"):
            family.update("lily", color="2")
        with pytest.raises(ValueError, match="already has"):
            family.add("Oma", color="2")

    def test_keeping_your_own_colour_is_fine(self, harpers):
        assert family.update("ruby", color="2").color == "2"
