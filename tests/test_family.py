"""The family, and events that belong to one of them."""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from luach import family
from luach.agent import pending, runtime
from luach.app import create_app
from luach.calendar import client as cal
from luach.calendar import times
from tests.doubles import ScriptedModel, call, say

TZ = "America/New_York"


@pytest.fixture
async def http(tmp_path):
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


@pytest.fixture
def harpers():
    family.add("Alex", email="alex@example.com")
    family.add("Ruby", kind="kid", email="ruby@example.com")
    family.add("Lily", kind="kid")


class TestTheRoster:
    def test_it_starts_as_the_accounts_the_box_has(self):
        people = family.roster()
        assert [p.name for p in people] == ["Robin", "ana"]
        assert people[0].email == "robin@example.com" and people[0].user_id is not None

    def test_emptied_by_the_owner_it_stays_empty(self):
        for p in family.roster():
            family.remove(p.key)
        assert family.roster() == []

    def test_children_need_no_account(self, harpers):
        lily = family.find("lily")
        assert lily is not None and lily.kind == "kid" and lily.user_id is None

    def test_everyone_gets_a_different_colour(self, harpers):
        colours = [p.color for p in family.roster()]
        assert len(set(colours)) == len(colours)
        assert all(c in family.COLORS for c in colours)

    def test_a_name_is_found_however_it_is_written(self, harpers):
        assert family.find("LILY").key == "lily"  # type: ignore[union-attr]
        assert family.find("Rub").key == "ruby"  # type: ignore[union-attr]
        # "A" could be Ruby, Lily or ana: nobody is guessed.
        assert family.find("A") is None

    def test_an_unknown_name_says_who_there_is(self, harpers):
        with pytest.raises(ValueError, match="Alex, Ruby, Lily"):
            family.resolve("Theo")

    def test_a_person_is_linked_to_the_account_that_shares_their_address(self):
        p = family.add("Ana B", email="ana@example.com")
        assert p.user_id is not None

    def test_the_model_is_told_who_the_children_are(self, harpers):
        assert "Ruby (kid)" in family.describe() and "Alex" in family.describe()


class TestAnEventsLeader:
    def test_it_rides_on_the_google_event_with_their_colour(self):
        draft = cal.Draft(title="Math test", span=times.span(_tomorrow(9), None, TZ))
        draft.leader, draft.color_id = "lily", "6"
        body = cal._body_from_draft(draft, TZ)
        assert body["extendedProperties"] == {"shared": {"luach_leader": "lily"}}
        assert body["colorId"] == "6"
        ev = cal._from_google({"id": "x", **body, "start": {"date": "2026-10-01"}, "end": {}})
        assert ev.leader == "lily"

    def test_taking_the_leader_away_takes_their_colour_too(self):
        body = cal._body_from_changes({"leader": "", "color_id": ""}, TZ)
        assert body["extendedProperties"]["shared"]["luach_leader"] == ""
        assert body["colorId"] is None

    def test_an_event_made_elsewhere_belongs_to_its_one_family_invitee(self, harpers):
        assert family.leader_of("", ["ruby@example.com", "coach@club.org"]).key == "ruby"  # type: ignore[union-attr]
        # Two of the family invited: it is not one person's.
        assert family.leader_of("", ["ruby@example.com", "alex@example.com"]) is None


class TestTheCalendarApi:
    async def test_the_owner_marks_an_event_and_the_leader_is_invited(self, http, harpers):
        await login(http)
        r = await http.post(
            "/api/calendar/events",
            json={"title": "Football", "start": _tomorrow(17), "leader": "ruby", "attendees": []},
        )
        assert r.status_code == 200, r.text
        ev = r.json()
        assert ev["leader"] == "ruby"
        assert ev["attendees"] == ["ruby@example.com"]

    async def test_moving_an_event_to_someone_else(self, http, harpers):
        await login(http)
        ev = (
            await http.post(
                "/api/calendar/events",
                json={"title": "Dentist", "start": _tomorrow(10), "attendees": []},
            )
        ).json()
        assert ev["leader"] == ""
        r = await http.patch(f"/api/calendar/events/{ev['id']}", json={"leader": "alex"})
        assert r.status_code == 200, r.text
        assert r.json()["leader"] == "alex" and "alex@example.com" in r.json()["attendees"]
        # Made nobody's, it stays nobody's even though Alex is still invited.
        r = await http.patch(f"/api/calendar/events/{ev['id']}", json={"leader": ""})
        assert r.json()["leader"] == "" and "alex@example.com" in r.json()["attendees"]

    async def test_a_stranger_cannot_lead(self, http, harpers):
        await login(http)
        r = await http.post(
            "/api/calendar/events", json={"title": "x", "start": _tomorrow(9), "leader": "theo"}
        )
        assert r.status_code == 400

    async def test_the_list_says_whose_each_event_is(self, http, harpers):
        await login(http)
        await http.post(
            "/api/calendar/events",
            json={"title": "Math test", "start": _tomorrow(9), "leader": "lily", "attendees": []},
        )
        day = _tomorrow(9)[:10]
        events = (await http.get(f"/api/calendar/events?start={day}&end={day}")).json()["events"]
        assert [(e["title"], e["leader"]) for e in events] == [("Math test", "lily")]


class TestTheFamilyApi:
    async def test_the_owner_builds_the_family(self, http):
        await login(http)
        r = await http.post("/api/family", json={"name": "Lily", "kind": "kid"})
        assert r.status_code == 200, r.text
        assert r.json()["hex"].startswith("#")
        r = await http.patch("/api/family/lily", json={"color": "3"})
        assert r.json()["color"] == "3"
        shown = (await http.get("/api/family")).json()
        assert "Lily" in [p["name"] for p in shown["people"]] and len(shown["colors"]) == 11
        assert (await http.delete("/api/family/lily")).status_code == 200

    async def test_only_the_owner_changes_it(self, http):
        await login(http, "ana", "another good password")
        assert (await http.get("/api/family")).status_code == 200
        assert (await http.post("/api/family", json={"name": "X"})).status_code == 403

    async def test_nonsense_is_refused(self, http):
        await login(http)
        assert (await http.post("/api/family", json={"name": ""})).status_code == 400
        assert (
            await http.post("/api/family", json={"name": "Z", "color": "99"})
        ).status_code == 400
        assert (await http.post("/api/family", json={"name": "Robin"})).status_code == 400
        assert (await http.patch("/api/family/nobody", json={"name": "Q"})).status_code == 404


class TestTheAgent:
    async def test_lily_s_math_test_is_lily_s(self, calendar, harpers):
        runtime.set_model(
            ScriptedModel(
                [
                    [call("create_event", title="Math test", start=_tomorrow(9), for_whom="Lily")],
                    [say("Added: Math test for Lily.")],
                ]
            )
        )
        await runtime.run_turn(
            "lily has a math test tomorrow at 9", user_id=1, principal="robin", timezone=TZ
        )
        (ev,) = calendar.events.values()
        assert ev.leader == "lily"

    async def test_it_can_hand_an_event_to_someone_else(self, calendar, harpers):
        draft = cal.Draft(title="Pickup", span=times.span(_tomorrow(15), None, TZ))
        ev = calendar.insert(draft, TZ)
        runtime.set_model(
            ScriptedModel(
                [
                    [call("update_event", event_id=ev.id, for_whom="Alex")],
                    [say("Alex has the pickup now.")],
                ]
            )
        )
        result = await runtime.run_turn(
            "alex does the pickup", user_id=1, principal="robin", timezone=TZ
        )
        # Changing an event this thread did not make waits for a person.
        (held,) = result.held
        assert "Alex" in held["summary"]
        pending.approve(held["id"], by="robin", timezone=TZ)
        assert calendar.events[ev.id].leader == "alex"
        assert "alex@example.com" in calendar.events[ev.id].attendees

    async def test_a_name_nobody_has_writes_nothing(self, calendar, harpers):
        runtime.set_model(
            ScriptedModel(
                [
                    [call("create_event", title="Judo", start=_tomorrow(16), for_whom="Theo")],
                    [say("There is nobody called Theo in the family.")],
                ]
            )
        )
        await runtime.run_turn("theo has judo", user_id=1, principal="robin", timezone=TZ)
        assert calendar.events == {}


def test_the_local_calendar_keeps_the_leader(harpers):
    local = cal.LocalCalendar()
    draft = cal.Draft(title="Recital", span=times.span(_tomorrow(18), None, TZ), leader="lily")
    ev = local.insert(draft, TZ)
    assert cal.LocalCalendar().events[ev.id].leader == "lily"


class TestTheFamilyFromConfig:
    def test_whoever_is_missing_is_added_once(self):
        assert family.ensure("Alex; Ruby:kid; Lily:kid:lily@example.com") == [
            "Alex",
            "Ruby",
            "Lily",
        ]
        assert family.find("lily").kind == "kid"  # type: ignore[union-attr]
        assert family.find("lily").email == "lily@example.com"  # type: ignore[union-attr]
        # Every start runs it again: nothing is added twice, nothing is changed.
        family.update("ruby", color="11")
        assert family.ensure("Alex;Ruby:kid;Lily:kid") == []
        assert family.get("ruby").color == "11"  # type: ignore[union-attr]

    def test_someone_the_box_already_has_is_left_alone(self):
        assert family.ensure("robin; Alex") == ["Alex"]


class TestWhatTheModelActuallySends:
    """Measured against qwen3.6-35b: asked to "add jordan pike for tomorrow at
    6:30" it calls create_event with calendar="Robin" a
    third of the time, and the member was told there was a technical issue."""

    async def test_a_person_in_the_calendar_field_is_taken_as_whose_it_is(self, calendar, harpers):
        runtime.set_model(
            ScriptedModel(
                [
                    [
                        call(
                            "create_event",
                            title="Jordan Pike",
                            start=_tomorrow(18),
                            calendar="Alex",
                        )
                    ],
                    [say("Added: Jordan Pike, tomorrow 18:00.")],
                ]
            )
        )
        result = await runtime.run_turn(
            "add jordan pike for tomorrow at 6:30", user_id=1, principal="robin", timezone=TZ
        )
        (ev,) = calendar.events.values()
        assert ev.title == "Jordan Pike" and ev.leader == "alex"
        assert not result.error

    async def test_a_calendar_that_is_neither_still_says_so(self, calendar, harpers):
        runtime.set_model(
            ScriptedModel(
                [
                    [call("create_event", title="X", start=_tomorrow(18), calendar="Narnia")],
                    [say("There is no calendar called Narnia.")],
                ]
            )
        )
        await runtime.run_turn("add x", user_id=1, principal="robin", timezone=TZ)
        assert calendar.events == {}

    async def test_a_start_it_cannot_parse_is_said_not_raised(self, calendar, harpers):
        """Approved, so it runs rather than being held for being ambiguous."""
        runtime.set_model(
            ScriptedModel(
                [
                    [call("create_event", title="X", start="tomorrow evening")],
                    [say("I need the date and the time.")],
                ]
            )
        )
        result = await runtime.run_turn(
            "yes", user_id=1, principal="robin", timezone=TZ, approved=True
        )
        assert calendar.events == {} and not result.error
        assert result.reply == "I need the date and the time."


class TestSeveralPeople:
    """An event can be more than one person's: "breakfast for Ruby and Lily" had
    nowhere to go but the title, and was in neither of their board columns."""

    @pytest.mark.parametrize("said", ["Ruby and Lily", "Ruby, Lily", "ruby & lily", "Ruby y Lily"])
    def test_however_the_names_are_joined(self, harpers, said):
        assert [p.key for p in family.resolve_many(said)] == ["ruby", "lily"]

    def test_hebrew_joins_with_a_letter(self):
        family.add("רובי", kind="kid")
        family.add("לילי", kind="kid")
        assert [p.name for p in family.resolve_many("רובי ולילי")] == ["רובי", "לילי"]

    def test_one_name_that_starts_like_another_phrase_is_still_one(self, harpers):
        # find() matches the start of a name; "Ruby and Lily" must not be Ruby alone.
        assert [p.key for p in family.resolve_many("Ruby")] == ["ruby"]
        assert len(family.resolve_many("Ruby and Lily")) == 2

    def test_a_name_nobody_has_among_them_is_refused(self, harpers):
        with pytest.raises(ValueError, match="nobody in the family is called 'Bob'"):
            family.resolve_many("Ruby and Bob")

    async def test_by_chat_it_is_on_both_boards(self, http, calendar, harpers):
        runtime.set_model(
            ScriptedModel(
                [
                    [
                        call(
                            "create_event",
                            title="Breakfast",
                            start=_tomorrow(7),
                            for_whom="Ruby and Lily",
                        )
                    ],
                    [say("Added.")],
                ]
            )
        )
        await runtime.run_turn(
            "breakfast for ruby and lily tomorrow at 7", user_id=1, principal="robin", timezone=TZ
        )
        (ev,) = calendar.events.values()
        assert ev.title == "Breakfast" and ev.leader == "ruby,lily"
        assert "ruby@example.com" in ev.attendees  # the one with an address is invited
        from luach.routes import board

        (shown,) = board._events(_tomorrow(7)[:10], TZ, family.roster())
        assert shown["leaders"] == ["ruby", "lily"] and shown["leader"] == "ruby"

    async def test_by_hand_the_api_takes_a_list(self, http, harpers):
        await login(http)
        made = await http.post(
            "/api/calendar/events",
            json={"title": "Dentist", "start": _tomorrow(9), "leaders": ["lily", "ruby"]},
        )
        assert made.status_code == 200 and made.json()["leaders"] == ["lily", "ruby"]
        eid = made.json()["id"]
        back = await http.patch(f"/api/calendar/events/{eid}", json={"leader": "lily"})
        assert back.json()["leaders"] == ["lily"]
        bad = await http.post(
            "/api/calendar/events",
            json={"title": "x", "start": _tomorrow(9), "leaders": ["lily", "bob"]},
        )
        assert bad.status_code == 400

    def test_a_google_title_can_name_both(self, harpers):
        ev = cal.Event(id="g", title="Ruby and Lily: breakfast", start="", end="", all_day=False)
        assert [p.key for p in family.leaders_for(ev)] == ["ruby", "lily"]

    async def test_handing_it_to_two_people_leaves_the_title_alone(self, calendar, harpers):
        ev = calendar.insert(
            cal.Draft(title="Breakfast", span=times.span(_tomorrow(7), None, TZ)), TZ
        )
        runtime.set_model(
            ScriptedModel(
                [
                    [call("update_event", event_id=ev.id, for_whom="Lily and Ruby")],
                    [say("Done.")],
                ]
            )
        )
        await runtime.run_turn(
            "this is for lily and ruby, on their board too",
            user_id=1,
            principal="robin",
            timezone=TZ,
            approved=True,
        )
        after = calendar.events[ev.id]
        assert after.title == "Breakfast" and after.leader == "lily,ruby"


def test_the_first_account_joins_a_family_that_came_from_config(emptied, monkeypatch):
    """LUACH_FAMILY filled the family before anyone signed up, so the owner was
    nobody in their own family and "for Robin" meant no one."""
    from luach import db
    from luach.auth import users

    db.init_db(emptied)
    family.ensure("Alex; Ruby:kid; Lily:kid")
    owner = users.create_user(
        "robin", "f@example.com", "a long enough password", display_name="Robin"
    )
    family.welcome(owner.id, "Robin")
    robin = family.find("Robin")
    assert robin is not None and robin.user_id == owner.id and robin.kind == "adult"
    family.welcome(owner.id, "Robin")  # once
    assert [p.name for p in family.roster()].count("Robin") == 1
