"""Tasks by person: to-dos and chores. Anyone ticks; the grown-ups decide."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from luach import family, tasks
from luach.agent import runtime
from luach.app import create_app
from luach.auth import users
from tests.doubles import ScriptedModel, call, say

TZ = "America/New_York"
MON, TUE, WED = "2026-09-21", "2026-09-22", "2026-09-23"


@pytest.fixture
async def http(tmp_path):
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        yield c


async def login(c: AsyncClient, username="robin", password="correct horse battery"):
    r = await c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


@pytest.fixture
def harpers():
    family.add("Ruby", kind="kid")
    family.add("Lily", kind="kid", email="lily@example.com")
    # She accepts her invitation later, and is linked by the address.
    users.create_user("lily", "lily@example.com", "lily's own password", display_name="Lily")
    return 1  # robin, the owner


@pytest.mark.parametrize(
    ("said", "due"),
    [
        ("return the library book by friday", "2026-09-25"),
        ("finish the project by Monday", "2026-09-28"),
        ("bring the slip tomorrow", "2026-09-24"),
        ("hoy", "2026-09-23"),
        ("para el viernes", "2026-09-25"),
        ("עד יום שלישי", "2026-09-29"),
        ("מחר", "2026-09-24"),
        ("the second task", ""),  # "שני"-style ordinals are not days
        ("by friday or saturday", ""),  # two days: say nothing rather than guess
        ("go to the mar", ""),  # "mar" is Spanish for Tuesday and also the sea
        ("feed the fish", ""),
    ],
)
def test_the_day_a_person_names(said, due):
    assert tasks.due_in_words(said, "2026-09-23") == due  # a Wednesday


class TestChoresAndToDos:
    def test_a_chore_falls_on_its_weekdays_only(self, harpers):
        tasks.add("Bins out", by=1, person="ruby", days="tue", today=MON)
        assert [t.title for t in tasks.for_day(TUE)] == ["Bins out"]
        assert tasks.for_day(WED) == []

    def test_a_chore_is_done_for_a_day_not_for_ever(self, harpers):
        t = tasks.add("Dishes", by=1, person="lily", days="daily", today=MON)
        tasks.tick(t.id, TUE, by="lily")
        assert tasks.for_day(TUE)[0].done
        assert not tasks.for_day(WED)[0].done

    def test_a_to_do_stays_until_it_is_done_and_says_when_it_is_late(self, harpers):
        t = tasks.add("Library book", by=1, person="lily", due=MON, today=MON)
        (late,) = tasks.for_day(WED)
        assert late.overdue and not late.done
        tasks.tick(t.id, WED)
        # Ticked on Wednesday: it shows there, done, and is gone from Thursday.
        assert tasks.for_day(WED)[0].done
        assert tasks.for_day("2026-09-24") == []

    def test_a_future_to_do_waits_for_its_day(self, harpers):
        tasks.add("Permission slip", by=1, due=WED, today=MON)
        assert tasks.for_day(MON) == []
        assert len(tasks.for_day(WED)) == 1

    def test_one_persons_list(self, harpers):
        tasks.add("Bins", by=1, person="ruby", days="daily", today=MON)
        tasks.add("Piano", by=1, person="lily", days="daily", today=MON)
        assert [t.title for t in tasks.for_day(TUE, "lily")] == ["Piano"]

    @pytest.mark.parametrize(
        ("spec", "days"),
        [
            ("mon,thu", ("MO", "TH")),
            ("Tuesday and Thursday", ("TU", "TH")),
            ("weekdays", ("MO", "TU", "WE", "TH", "FR")),
            ("martes", ("TU",)),
            ("SA,SU", ("SA", "SU")),
            ("יום שלישי", ("TU",)),
            ("שני ורביעי", ("MO", "WE")),
            ("כל יום", ("MO", "TU", "WE", "TH", "FR", "SA", "SU")),
            ("lunes y jueves", ("MO", "TH")),
            ("", ()),
        ],
    )
    def test_weekdays_however_they_are_said(self, spec, days):
        assert tasks.parse_days(spec) == days

    def test_a_weekday_nobody_has_is_refused(self):
        with pytest.raises(ValueError, match="not a weekday"):
            tasks.parse_days("someday")

    def test_the_list_of_everything_leaves_out_what_is_finished(self, harpers):
        a = tasks.add("A", by=1, today=MON)
        tasks.add("B", by=1, days="daily", today=MON)
        tasks.tick(a.id, MON)
        assert [t.title for t in tasks.every(MON)] == ["B"]


class TestWhoDecides:
    def test_a_child_ticks_but_does_not_assign(self, harpers):
        lily_id = family.find("lily").user_id  # type: ignore[union-attr]
        assert lily_id is not None  # linked by the address she signs in with
        t = tasks.add("Homework", by=1, person="lily", today=MON)
        with pytest.raises(tasks.NotAllowed):
            tasks.add("Nothing", by=lily_id, today=MON)
        with pytest.raises(tasks.NotAllowed):
            tasks.remove(t.id, by=lily_id)
        assert tasks.tick(t.id, MON, by="lily").done

    def test_another_adult_may_assign(self, harpers):
        # ana has an account and no family entry marking her a child.
        assert tasks.may_assign(2)

    def test_the_board_decides_nothing(self):
        assert not tasks.may_assign(None)


class TestTheApi:
    async def test_the_owner_hands_out_a_chore_and_it_is_ticked(self, http, harpers):
        await login(http)
        r = await http.post(
            "/api/tasks", json={"title": "Bins out", "person": "ruby", "days": ["TU"]}
        )
        assert r.status_code == 200, r.text
        tid = r.json()["id"]
        assert r.json()["chore"] is True
        day = (await http.get(f"/api/tasks?day={TUE}")).json()
        assert day["may_assign"] is True
        assert [t["title"] for t in day["tasks"]] == ["Bins out"]
        r = await http.post(f"/api/tasks/{tid}/done", json={"day": TUE})
        assert r.json()["done"] is True
        r = await http.post(f"/api/tasks/{tid}/done", json={"day": TUE, "done": False})
        assert r.json()["done"] is False

    async def test_a_child_is_told_no_rather_than_ignored(self, http, harpers):
        await login(http, "lily", "lily's own password")
        r = await http.post("/api/tasks", json={"title": "Skip school"})
        assert r.status_code == 403
        assert (await http.get("/api/tasks")).json()["may_assign"] is False

    async def test_editing_and_removing(self, http, harpers):
        await login(http)
        tid = (await http.post("/api/tasks", json={"title": "Call dentist"})).json()["id"]
        r = await http.patch(f"/api/tasks/{tid}", json={"person": "lily", "due": WED})
        assert r.json()["person"] == "lily" and r.json()["due"] == WED
        assert [t["id"] for t in (await http.get("/api/tasks/all")).json()["tasks"]] == [tid]
        assert (await http.delete(f"/api/tasks/{tid}")).status_code == 200
        assert (await http.delete(f"/api/tasks/{tid}")).status_code == 404

    async def test_nonsense_is_refused(self, http, harpers):
        await login(http)
        assert (await http.post("/api/tasks", json={"title": ""})).status_code == 400
        assert (
            await http.post("/api/tasks", json={"title": "x", "person": "theo"})
        ).status_code == 400
        assert (
            await http.post("/api/tasks", json={"title": "x", "due": "friday"})
        ).status_code == 400
        assert (await http.post("/api/tasks", json={"title": "x", "days": 3})).status_code == 400
        assert (await http.patch("/api/tasks/999", json={"title": "y"})).status_code == 404
        assert (await http.post("/api/tasks/999/done", json={})).status_code == 404


class TestTheAgent:
    async def test_a_chore_by_chat(self, harpers):
        runtime.set_model(
            ScriptedModel(
                [
                    [call("add_task", title="Bins out", for_whom="Ruby", repeats="tue")],
                    [say("Ruby takes the bins out every Tuesday.")],
                ]
            )
        )
        await runtime.run_turn(
            "ruby takes the bins out on tuesdays", user_id=1, principal="robin", timezone=TZ
        )
        (t,) = tasks.every(MON)
        assert (t.title, t.person, t.days) == ("Bins out", "ruby", ("TU",))

    async def test_a_day_the_person_named_is_saved_when_the_model_leaves_it_out(self, harpers):
        """6 turns in 9 saved no day for "by friday" while saying "due Friday"."""
        from datetime import date, timedelta

        from luach.calendar import times

        runtime.set_model(
            ScriptedModel(
                [
                    [call("add_task", title="Library book", for_whom="Lily", repeats="none")],
                    [say("Added.")],
                ]
            )
        )
        await runtime.run_turn(
            "lily has to return the library book by friday",
            user_id=1,
            principal="robin",
            timezone=TZ,
        )
        today = times.now_in(TZ).date()
        friday = today + timedelta(days=(4 - today.weekday()) % 7)
        (t,) = tasks.every(today.isoformat())
        assert t.due == friday.isoformat() and date.fromisoformat(t.due).weekday() == 4

    async def test_the_same_task_asked_twice_is_there_once(self, harpers):
        runtime.set_model(
            ScriptedModel(
                [
                    [call("add_task", title="Feed the fish", for_whom="Lily", repeats="daily")],
                    [say("Added.")],
                    [call("add_task", title="feed the fish ", for_whom="Lily", repeats="daily")],
                    [say("Already there.")],
                ]
            )
        )
        for _ in range(2):
            await runtime.run_turn(
                "lily feeds the fish every day", user_id=1, principal="robin", timezone=TZ
            )
        assert [t.title for t in tasks.every(MON)] == ["Feed the fish"]

    async def test_changing_a_task_someone_else_made_waits_for_a_yes(self, harpers):
        """ "put it on her board" reassigned a parent's own task, silently."""
        from luach.agent import pending

        t = tasks.add("Bins out", by=1, person="ruby", days="tue", today=MON)
        runtime.set_model(
            ScriptedModel(
                [
                    [call("change_task", task_id=t.id, for_whom="Lily", repeats="tue,fri")],
                    [say("That needs your yes.")],
                ]
            )
        )
        r = await runtime.run_turn(
            "the bins are lily's now, tuesdays and fridays",
            user_id=1,
            principal="robin",
            timezone=TZ,
        )
        assert tasks.every(MON)[0].person == "ruby", "nothing changes before the yes"
        (held,) = r.held
        assert "“Bins out”" in held["summary"]
        pending.approve(held["id"], by="robin", timezone=TZ)
        (after,) = tasks.every(MON)
        assert (after.person, after.days) == ("lily", ("TU", "FR"))

    async def test_dropping_a_task_someone_else_made_waits_too(self, harpers):
        t = tasks.add("Bins out", by=1, person="ruby", days="tue", today=MON)
        runtime.set_model(
            ScriptedModel([[call("remove_task", task_id=t.id)], [say("Waiting for your yes.")]])
        )
        r = await runtime.run_turn(
            "ruby doesn't do the bins any more", user_id=1, principal="robin", timezone=TZ
        )
        assert [x.title for x in tasks.every(MON)] == ["Bins out"]
        assert r.held and r.held[0]["summary"] == "Remove the task “Bins out”"

    async def test_a_task_made_in_this_conversation_changes_at_once(self, harpers):
        runtime.set_model(
            ScriptedModel(
                [
                    [call("add_task", title="Pack", for_whom="Ruby")],
                    [say("Added.")],
                ]
            )
        )
        r = await runtime.run_turn("ruby has to pack", user_id=1, principal="robin", timezone=TZ)
        (t,) = tasks.every(MON)
        runtime.set_model(
            ScriptedModel([[call("change_task", task_id=t.id, for_whom="Lily")], [say("Done.")]])
        )
        r2 = await runtime.run_turn(
            "no, it's lily's", user_id=1, principal="robin", timezone=TZ, thread_id=r.thread_id
        )
        assert not r2.held and tasks.every(MON)[0].person == "lily"

    async def test_a_vague_follow_up_does_not_touch_someone_elses_task(self, harpers):
        """The incident, end to end: the model reached for the wrong task."""
        mine = tasks.add("Breakfast", by=1, person="ruby", today=MON)
        runtime.set_model(
            ScriptedModel(
                [[call("change_task", task_id=mine.id, for_whom="Lily")], [say("Moved.")]]
            )
        )
        r = await runtime.run_turn(
            "this is for lily, put it on her board", user_id=1, principal="robin", timezone=TZ
        )
        assert tasks.every(MON)[0].person == "ruby" and r.held

    async def test_a_child_cannot_change_or_drop_a_chore(self, harpers):
        lily_id = family.find("lily").user_id  # type: ignore[union-attr]
        t = tasks.add("Bins out", by=1, person="lily", days="tue", today=MON)
        runtime.set_model(
            ScriptedModel(
                [
                    [call("remove_task", task_id=t.id)],
                    [call("change_task", task_id=t.id, for_whom="Ruby")],
                    [say("I can't.")],
                ]
            )
        )
        await runtime.run_turn(
            "no more bins for me, give them to ruby",
            user_id=lily_id,
            principal="lily",
            timezone=TZ,
        )
        (still,) = tasks.every(MON)
        assert still.person == "lily"

    async def test_a_task_for_two_is_one_each(self, harpers):
        """ "Ruby and Lily" was read as Ruby, and the task went to her alone."""
        runtime.set_model(
            ScriptedModel(
                [
                    [call("add_task", title="Tidy the room", for_whom="Ruby and Lily")],
                    [say("Added for both.")],
                ]
            )
        )
        await runtime.run_turn(
            "ruby and lily have to tidy their room", user_id=1, principal="robin", timezone=TZ
        )
        mine = sorted((t.person, t.title) for t in tasks.every(MON))
        assert mine == [("lily", "Tidy the room"), ("ruby", "Tidy the room")]

    def test_a_phrase_with_two_names_is_not_the_first_of_them(self, harpers):
        assert family.find("Ruby and Lily") is None
        with pytest.raises(ValueError, match="more than one person"):
            family.resolve("Ruby and Lily")

    async def test_done_by_chat(self, harpers):
        t = tasks.add("Dishes", by=1, person="ruby", days="daily", today=MON)
        runtime.set_model(
            ScriptedModel(
                [
                    [call("list_tasks", for_whom="Ruby")],
                    [call("complete_task", task_id=t.id)],
                    [say("Ticked: Ruby did the dishes.")],
                ]
            )
        )
        await runtime.run_turn("ruby did the dishes", user_id=1, principal="robin", timezone=TZ)
        from luach.calendar import times

        assert tasks.for_day(times.now_in(TZ).date().isoformat())[0].done

    async def test_a_child_asking_luach_to_assign_is_refused(self, harpers):
        lily_id = family.find("lily").user_id  # type: ignore[union-attr]
        runtime.set_model(
            ScriptedModel(
                [
                    [call("add_task", title="Ruby does my dishes", for_whom="Ruby")],
                    [say("Only a grown-up can hand out tasks.")],
                ]
            )
        )
        await runtime.run_turn(
            "give ruby my dishes", user_id=lily_id, principal="lily", timezone=TZ
        )
        assert tasks.every(MON) == []


class TestOneTurnOneTaskEach:
    """ "Ruby and Lily have to …" became a task for anyone and
    then one each — three where there were two."""

    async def test_anyone_first_then_each_is_just_each(self, harpers):
        runtime.set_model(
            ScriptedModel(
                [
                    [call("add_task", title="Tidy up", due="")],
                    [call("add_task", title="Tidy up", for_whom="Ruby")],
                    [call("add_task", title="tidy up", for_whom="Lily")],
                    [say("Added for both.")],
                ]
            )
        )
        await runtime.run_turn("ruby and lily tidy up", user_id=1, principal="robin", timezone=TZ)
        assert sorted(t.person for t in tasks.every(MON)) == ["lily", "ruby"]

    async def test_each_first_then_anyone_is_still_each(self, harpers):
        runtime.set_model(
            ScriptedModel(
                [
                    [call("add_task", title="Tidy up", for_whom="Ruby and Lily")],
                    [call("add_task", title="Tidy up")],
                    [say("Added.")],
                ]
            )
        )
        await runtime.run_turn("ruby and lily tidy up", user_id=1, principal="robin", timezone=TZ)
        assert sorted(t.person for t in tasks.every(MON)) == ["lily", "ruby"]
