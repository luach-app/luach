from __future__ import annotations

from datetime import timedelta

import pytest

from luach import family, model_menu, tasks
from luach.agent import control, pending, runtime, tools
from luach.calendar import times
from tests.doubles import ScriptedModel, call, say

TZ = "America/New_York"


def _today() -> str:
    return times.now_in(TZ).date().isoformat()


def _tomorrow_at(hour: int) -> str:
    now = times.now_in("America/New_York")
    return (now + timedelta(days=1)).replace(hour=hour, minute=0).strftime("%Y-%m-%dT%H:%M")


async def test_certain_future_event_is_created(calendar):
    runtime.set_model(
        ScriptedModel(
            [
                [
                    call(
                        "create_event",
                        title="Dentist",
                        start=_tomorrow_at(15),
                        end="",
                        certainty="high",
                    )
                ],
                [say("Added: Dentist tomorrow 15:00.")],
            ]
        )
    )
    result = await runtime.run_turn(
        "dentist tomorrow at 3pm", user_id=1, principal="robin", timezone="America/New_York"
    )
    assert result.error is None, result
    assert len(calendar.events) == 1
    assert result.created and result.created[0]["title"] == "Dentist"
    assert result.reply.startswith("Added")
    kinds = [r.event_type for r in control.trail().records()]
    assert "event.created" in kinds and kinds[0] == "turn.start" and kinds[-1] == "turn.end"
    assert control.trail().verify()


async def test_low_certainty_event_is_held_then_approved(calendar):
    runtime.set_model(
        ScriptedModel(
            [
                [
                    call(
                        "create_event",
                        title="Lunch with Ana",
                        start=_tomorrow_at(12),
                        certainty="low",
                    )
                ],
                [say("I held it for your approval.")],
            ]
        )
    )
    result = await runtime.run_turn(
        "lunch with ana sometime tomorrow",
        user_id=1,
        principal="robin",
        timezone="America/New_York",
    )
    assert calendar.events == {}
    assert len(result.held) == 1
    held = result.held[0]
    assert held["reason"] == ["ambiguous"]
    assert "Lunch with Ana" in held["summary"]
    rows = pending.list_pending()
    assert rows and rows[0]["status"] == "pending"
    done = pending.approve(held["id"], by="robin", timezone="America/New_York")
    assert done["status"] == "approved"
    assert len(calendar.events) == 1
    assert pending.list_pending() == []


def _next(day: int, hour: int, minute: int = 0) -> str:
    """The next weekday `day` (0=Mon) at hour:minute that is still ahead, within a week."""
    now = times.now_in(TZ)
    at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    at += timedelta(days=(day - now.weekday()) % 7)
    return (at if at > now else at + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M")


async def _weekly(text: str, start: str, rule: str = "RRULE:FREQ=WEEKLY;BYDAY=TH"):
    runtime.set_model(
        ScriptedModel(
            [
                [
                    call(
                        "create_event",
                        title="Swimming",
                        start=start,
                        recurrence=rule,
                        certainty="low",
                    )
                ],
                [say("ok")],
            ]
        )
    )
    return await runtime.run_turn(text, user_id=1, principal="robin", timezone=TZ)


class TestWhatThePersonPinnedIsNotAmbiguous:
    """The model marked "every Thursday at 6pm" low twice, because
    it picked the first Thursday itself. The rule picked it; the time was theirs."""

    async def test_every_thursday_at_6pm_is_saved(self, calendar):
        result = await _weekly(
            "swimming for Ruby every thursday at 6pm until the end of october", _next(3, 18)
        )
        assert result.held == [] and len(calendar.events) == 1

    async def test_the_ways_a_time_is_typed(self, calendar):
        for text, (h, m) in [
            ("swimming every thursday at 6", (18, 0)),
            ("swimming every thursday 18:00", (18, 0)),
            ("swimming thursdays 4:30", (16, 30)),
            ("swimming every thursday 7.30am", (7, 30)),
        ]:
            assert (h, m) in control._said_times(text), text

    async def test_a_time_they_did_not_say_is_held(self, calendar):
        result = await _weekly("swimming every thursday afternoon", _next(3, 15))
        assert [h["reason"] for h in result.held] == [["ambiguous"]]

    async def test_a_different_time_from_the_one_they_said_is_held(self, calendar):
        result = await _weekly("swimming every thursday at 6pm", _next(3, 17))
        assert result.held

    async def test_a_start_off_the_rules_days_is_held(self, calendar):
        result = await _weekly("swimming every thursday at 6pm", _next(2, 18))
        assert result.held

    async def test_a_start_weeks_away_is_held(self, calendar):
        later = (times.parse_when(_next(3, 18), TZ) + timedelta(days=21)).strftime("%Y-%m-%dT%H:%M")
        result = await _weekly("swimming every thursday at 6pm", later)
        assert result.held

    async def test_a_one_off_on_a_day_and_time_they_named_is_saved(self, calendar):
        # Held three times running: the smoke check's own breakfast.
        result = await _weekly(
            "add breakfast for Ruby and Lily tomorrow at 7:10am",
            _tomorrow_at(7)[:-2] + "10",
            rule="",
        )
        assert result.held == [] and len(calendar.events) == 1

    async def test_a_one_off_on_a_weekday_they_named_is_saved(self, calendar):
        result = await _weekly("swimming thursday at 6pm", _next(3, 18), rule="")
        assert result.held == []

    def test_todays_weekday_after_its_time_means_next_week(self, monkeypatch):
        """ "Thursday at 6pm" said on a Thursday evening is next Thursday. It held, and the
        test above failed every Thursday after six."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from luach.agent import context

        tz = ZoneInfo(TZ)
        thursday = datetime(2026, 10, 1, tzinfo=tz)  # a Thursday
        turn = context.Turn(
            calendar=None,
            user_id=1,
            principal="robin",
            timezone=TZ,
            text="swimming thursday at 6pm",
        )
        next_week = datetime(2026, 10, 8, 18, 0, tzinfo=tz)

        monkeypatch.setattr(times, "now_in", lambda _tz: thursday.replace(hour=19))
        assert control.pinned_by_their_words({}, next_week, turn)

        monkeypatch.setattr(times, "now_in", lambda _tz: thursday.replace(hour=17))
        assert not control.pinned_by_their_words({}, next_week, turn), (
            "today's six o'clock is still ahead: next week is a guess"
        )
        assert control.pinned_by_their_words({}, thursday.replace(hour=18), turn)

    async def test_next_weekday_is_left_to_the_person(self, calendar):
        result = await _weekly("swimming next thursday at 6pm", _next(3, 18), rule="")
        assert result.held

    async def test_a_one_off_on_another_day_is_held(self, calendar):
        result = await _weekly("swimming tomorrow at 6pm", _next(3, 18), rule="")
        if _next(3, 18)[:10] != _tomorrow_at(18)[:10]:
            assert result.held

    def test_a_bare_hour_is_read_the_family_way(self):
        assert control._said_times("dinner at 6") == {(18, 0)}
        assert control._said_times("breakfast at 7") == {(7, 0)}

    def test_the_days_a_message_names(self):
        from datetime import date

        thu = date(2026, 9, 24)
        assert control._said_days("tomorrow", thu) == {date(2026, 9, 25)}
        assert control._said_days("on tuesday", thu) == {date(2026, 9, 29)}
        assert control._said_days("Oct 3", thu) == {date(2026, 10, 3)}
        assert control._said_days("the 3rd of october", thu) == {date(2026, 10, 3)}
        assert control._said_days("next tuesday", thu) == set()
        assert control._said_days("sometime next week", thu) == set()

    def test_numbers_that_are_not_times(self):
        assert control._said_times("2 kids, 3 lessons, until 31 october, on 9/24") == set()


async def test_past_event_is_held(calendar):
    yesterday = (times.now_in("America/New_York") - timedelta(days=1)).strftime("%Y-%m-%dT10:00")
    runtime.set_model(
        ScriptedModel([[call("create_event", title="Old thing", start=yesterday)], [say("held")]])
    )
    result = await runtime.run_turn("x", user_id=1, principal="robin", timezone="America/New_York")
    assert result.held[0]["reason"] == ["past"]
    assert calendar.events == {}


async def test_duplicate_is_held(calendar):
    first = ScriptedModel(
        [[call("create_event", title="Dentist", start=_tomorrow_at(15))], [say("ok")]]
    )
    runtime.set_model(first)
    await runtime.run_turn("a", user_id=1, principal="robin", timezone="America/New_York")
    runtime.set_model(
        ScriptedModel(
            [
                [call("create_event", title="dentist appointment", start=_tomorrow_at(16))],
                [say("held")],
            ]
        )
    )
    result = await runtime.run_turn("b", user_id=1, principal="robin", timezone="America/New_York")
    assert result.held and result.held[0]["reason"] == ["possible-duplicate"]
    assert len(calendar.events) == 1


async def test_deleting_a_foreign_event_is_held_but_own_thread_event_is_not(calendar):
    runtime.set_model(
        ScriptedModel([[call("create_event", title="Gym", start=_tomorrow_at(7))], [say("ok")]])
    )
    r1 = await runtime.run_turn("gym", user_id=1, principal="robin", timezone="America/New_York")
    event_id = r1.created[0]["id"]
    # same thread: allowed
    runtime.set_model(ScriptedModel([[call("delete_event", event_id=event_id)], [say("gone")]]))
    r2 = await runtime.run_turn(
        "delete it",
        user_id=1,
        principal="robin",
        timezone="America/New_York",
        thread_id=r1.thread_id,
    )
    assert r2.held == [] and calendar.events == {}
    # another thread on a pre-existing event: held
    from luach.calendar import times as t
    from luach.calendar.client import Draft

    ev = calendar.insert(
        Draft(title="Family dinner", span=t.span(_tomorrow_at(19), None, "America/New_York")),
        "America/New_York",
    )
    runtime.set_model(ScriptedModel([[call("delete_event", event_id=ev.id)], [say("held")]]))
    r3 = await runtime.run_turn(
        "delete dinner", user_id=1, principal="robin", timezone="America/New_York"
    )
    assert r3.held and r3.held[0]["reason"] == ["mutation-existing"]
    assert ev.id in calendar.events


async def test_the_service_keys_approval_clears_the_hold(calendar):
    yesterday = (times.now_in("America/New_York") - timedelta(days=1)).strftime("%Y-%m-%dT10:00")
    runtime.set_model(
        ScriptedModel([[call("create_event", title="Backfill", start=yesterday)], [say("ok")]])
    )
    result = await runtime.run_turn(
        "add it", user_id=1, principal="robin", timezone="America/New_York", approved=True
    )
    assert result.held == [] and len(calendar.events) == 1


async def test_a_yes_in_words_clears_no_hold_of_its_own(calendar):
    """A yes approves the cards it was shown (test_gate_hardening); with none, the
    calls it is followed by keep their tags."""
    yesterday = (times.now_in("America/New_York") - timedelta(days=1)).strftime("%Y-%m-%dT10:00")
    runtime.set_model(
        ScriptedModel([[call("create_event", title="Backfill", start=yesterday)], [say("ok")]])
    )
    result = await runtime.run_turn(
        "yes", user_id=1, principal="robin", timezone="America/New_York"
    )
    assert [h["reason"] for h in result.held] == [["past"]] and calendar.events == {}


async def test_model_failure_ends_with_an_error_frame():
    from tests.doubles import FailingModel

    runtime.set_model(FailingModel())
    result = await runtime.run_turn("hi", user_id=1, principal="robin", timezone="America/New_York")
    assert result.error and "problem" in result.error


async def test_thread_is_private_to_its_member():
    runtime.set_model(ScriptedModel([[say("hello")]]))
    r1 = await runtime.run_turn("hi", user_id=1, principal="robin", timezone="America/New_York")
    r2 = await runtime.run_turn(
        "hi", user_id=2, principal="ana", timezone="America/New_York", thread_id=r1.thread_id
    )
    assert r2.error and "someone else" in r2.error


async def test_first_model_call_requires_a_tool_and_later_calls_do_not(calendar):
    model = ScriptedModel(
        [
            [call("list_events", start_date="2026-09-14", end_date="2026-09-20")],
            [say("Monday is the busy day.")],
        ]
    )
    runtime.set_model(model)
    r = await runtime.run_turn(
        "what is on next week?", user_id=1, principal="robin", timezone="America/New_York"
    )
    assert r.error is None and r.reply == "Monday is the busy day."
    assert model.calls[0].get("tool_choice") == "required"
    assert "tool_choice" not in model.calls[1]


def test_a_looping_model_is_stopped_and_explained():
    """litellm cuts the stream when a model repeats itself, but only after a
    page of the same fragment has reached the member. luach stops it first."""
    from luach.agent.runtime import MAX_REPEATED_CHUNKS, StuckModel, explain_failure

    assert "repeating itself" in explain_failure(
        RuntimeError("litellm.InternalServerError: The model is repeating the same chunk = ```")
    )
    assert "repeating itself" in explain_failure(
        StuckModel("the model is repeating the same chunk")
    )
    assert "took too long" in explain_failure(TimeoutError("request timed out"))
    assert "busy" in explain_failure(RuntimeError("rate limit exceeded"))
    assert "could not reach" in explain_failure(RuntimeError("failed to connect to the router"))
    # Anything luach has no sentence for still names itself rather than guessing.
    assert explain_failure(ValueError("something else")) == "luach hit a problem: ValueError"
    assert MAX_REPEATED_CHUNKS >= 3  # a real answer may legitimately repeat a word or two


async def test_a_greeting_calls_just_talking_and_reads_nothing(calendar):
    """Saying hello came back as the whole week: the first tool call of a turn is
    obliged to happen, so a greeting had to read the calendar. The model now has
    a tool for "this is a conversation", and it is the model that chooses it."""
    from luach.agent.tools import just_talking

    runtime.set_model(
        ScriptedModel(
            [
                [call("just_talking", about="greeting")],
                [say("I am well, thank you. What can I add for you?")],
            ]
        )
    )
    result = await runtime.run_turn("how are you?", user_id=1, principal="robin", timezone=TZ)
    assert result.error is None, result
    assert "well" in result.reply
    # Nothing was read, nothing was drawn, nothing was created.
    assert result.widgets == [] and result.created == []
    assert calendar.events == {}

    # The tool itself is honest about doing nothing.
    assert just_talking.fn(about="greeting") == {"calendar": "not needed", "about": "greeting"}


async def test_the_chat_is_not_told_about_a_tool_that_did_nothing(calendar):
    """`just_talking` draws no "checking the calendar…" chip and no card: it did
    not check anything, and saying otherwise would be a lie in the transcript."""
    runtime.set_model(ScriptedModel([[call("just_talking", about="thanks")], [say("Any time.")]]))
    frames = [
        f async for f in runtime.stream_turn("thanks!", user_id=1, principal="robin", timezone=TZ)
    ]
    kinds = {f["type"] for f in frames}
    assert "tool_start" not in kinds and "tool_result" not in kinds and "widget" not in kinds
    assert any(f.get("type") == "done" for f in frames)


async def test_a_calendar_question_still_has_to_read_first(calendar):
    """The rule that stops invented events is untouched: a real question reads."""
    runtime.set_model(
        ScriptedModel(
            [
                [call("list_events", start_date=_today(), end_date=_today())],
                [say("Nothing today.")],
            ]
        )
    )
    result = await runtime.run_turn("what is on today?", user_id=1, principal="robin", timezone=TZ)
    assert result.error is None, result
    assert any(w["kind"] == "agenda" for w in result.widgets)


async def test_a_turn_that_called_nothing_cannot_claim_a_write(calendar):
    """Asked to "add tennis for tomorrow at 4", the model came back with
    "Added: Tennis, Sat 19 Sep 16:00" having called no tool at all."""
    runtime.set_model(ScriptedModel([[say("Added: Tennis, Sat 19 Sep 16:00–17:00.")]]))
    result = await runtime.run_turn(
        "add tennis tomorrow afternoon", user_id=1, principal="robin", timezone=TZ
    )
    assert calendar.events == {}
    assert "Added" not in result.reply
    assert "did not actually do anything" in result.reply
    assert "turn.no_tool" in [r.event_type for r in control.trail().records()]


async def test_a_held_write_is_never_reported_as_done(calendar):
    runtime.set_model(
        ScriptedModel(
            [
                [call("create_event", title="Tennis", start=_tomorrow_at(16), certainty="low")],
                [say("Added: Tennis, Sat 19 Sep 16:00–17:00.")],
            ]
        )
    )
    result = await runtime.run_turn(
        "add tennis tomorrow afternoon", user_id=1, principal="robin", timezone=TZ
    )
    assert calendar.events == {}
    assert len(result.held) == 1
    assert not result.reply.startswith("Added")
    assert "nothing is on the calendar yet" in result.reply
    assert "Tennis" in result.reply


async def test_small_talk_is_a_tool_so_it_passes_the_guard(calendar):
    runtime.set_model(
        ScriptedModel([[call("just_talking", about="greeting")], [say("Hi! All good here.")]])
    )
    result = await runtime.run_turn("hello", user_id=1, principal="robin", timezone=TZ)
    assert result.reply == "Hi! All good here."
    assert result.created == []


async def test_running_out_of_steps_says_so_rather_than_blaming_the_model(calendar, monkeypatch):
    """ "mark the Brazil game and find who streams it" burned
    the iteration budget on search and ended saying nothing had been read or
    written — true, but it sent the person round the same loop."""
    monkeypatch.setenv("LUACH_MAX_ITERATIONS", "2")
    runtime.set_model(
        ScriptedModel(
            [
                [call("search_the_web", query="brazil morocco world cup")],
                [say("I cannot create calendar events as the system has reached its limit.")],
            ]
        )
    )
    result = await runtime.run_turn(
        "mark the brazil game and find who streams it",
        user_id=1,
        principal="robin",
        timezone=TZ,
    )
    assert calendar.events == {}
    assert "more steps than I have" in result.reply
    assert "one piece at a time" in result.reply
    assert "turn.out_of_steps" in [r.event_type for r in control.trail().records()]


async def test_only_the_first_call_of_a_turn_is_forced_to_use_a_tool(calendar):
    """`tool_choice="required"` on every call leaves the model no way to answer
    in words: it must keep calling tools until the budget runs out. It once
    answered "hello" with thirty-three reads of the calendar."""
    model = ScriptedModel(
        [
            [call("list_events", start=_today(), end=_today())],
            [call("list_events", start=_today(), end=_today())],
            [say("Nothing on today.")],
        ]
    )
    runtime.set_model(model)
    await runtime.run_turn("what's on today?", user_id=1, principal="robin", timezone=TZ)

    choices = [c.get("tool_choice") for c in model.calls]
    assert choices[0] == "required", choices
    assert all(c is None for c in choices[1:]), (
        f"the requirement outlived the first call: {choices}"
    )


async def test_the_same_call_twice_over_is_refused(calendar):
    """ "hello" read the calendar thirty-three times and then
    summarised a week nobody asked for. Every read returned the same thing."""
    reads = []
    original = calendar.list_events
    calendar.list_events = lambda *a, **k: (reads.append(1), original(*a, **k))[1]

    same = {"start_date": _today(), "end_date": _today()}
    runtime.set_model(
        ScriptedModel(
            [
                [call("list_events", **same)],
                [call("list_events", **same)],
                [call("list_events", **same)],
                [call("list_events", **same)],
                [say("Nothing on today.")],
            ]
        )
    )
    result = await runtime.run_turn("what's on today?", user_id=1, principal="robin", timezone=TZ)

    # The model may ask as often as it likes; the calendar answers once and the
    # repeats are met with "you already asked this". tulip ends a run that keeps
    # repeating itself, and it ends it silently — so the person still gets a
    # sentence rather than an empty bubble.
    assert len(reads) == tools.MAX_IDENTICAL_CALLS, reads
    assert result.reply and "circles" in result.reply


async def test_a_search_reworded_again_and_again_is_stopped(calendar, monkeypatch):
    """Asked for Brazil's next games, the model searched the
    web over and over, a little differently each time, so the identical-call
    guard never fired. Searches are counted by tool, not by wording."""
    monkeypatch.setenv("LUACH_SEARCH_URL", "http://searxng:8080")
    from luach import websearch

    asked: list[str] = []
    monkeypatch.setattr(websearch, "search", lambda q, limit=6: (asked.append(q), [])[1])
    queries = [
        "brazil next match",
        "brazil national team fixtures 2026",
        "brazil upcoming games schedule",
        "when does brazil play next",
        "brazil football calendar",
    ]
    model = ScriptedModel(
        [*([call("search_the_web", query=q)] for q in queries), [say("Their next games are…")]]
    )
    runtime.set_model(model)
    result = await runtime.run_turn(
        "when are brazil's next games?", user_id=1, principal="robin", timezone=TZ
    )

    budget = tools.SEARCH_BUDGET["search_the_web"]
    # The model's own searches stop at the budget. Each may be followed by luach's
    # one retry by name (websearch.search_focused), which is not the model asking.
    assert [q for q in asked if q in queries] == queries[:budget], asked
    assert len(asked) <= 2 * budget
    assert result.reply == "Their next games are…"
    # What the model was told past the budget: stop, and answer.
    told = [m for c in model.calls for m in c["messages"] if "search_budget_spent" in str(m)]
    assert told, "the model was never told to stop searching"


async def test_a_different_question_is_never_mistaken_for_a_repeat(calendar):
    runtime.set_model(
        ScriptedModel(
            [
                [call("list_events", start_date=_today(), end_date=_today())],
                [call("list_events", start_date=_today(), end_date="2026-12-31")],
                [say("Here is the week.")],
            ]
        )
    )
    reads = []
    original = calendar.list_events
    calendar.list_events = lambda *a, **k: (reads.append(1), original(*a, **k))[1]
    result = await runtime.run_turn("what's on?", user_id=1, principal="robin", timezone=TZ)
    assert result.reply == "Here is the week."
    assert len(reads) == 2, "different arguments are different questions"


class TestToolSyntaxNeverReachesAPerson:
    """ "how are you?" came back with a visible <tool_call>
    block. The turn was fine — just_talking had run — and only the relay was
    wrong, which is the worst version: nothing failed, so nothing said so."""

    def test_a_marker_split_across_chunks_is_still_caught(self):
        gate = runtime._HidesToolSyntax()
        out = "".join(
            gate.feed(c)
            for c in ["I'm doing well! <tool_c", 'all>{"name": "just_talking"}</tool_', "call> Bye"]
        )
        assert (out + gate.flush()) == "I'm doing well!  Bye"

    def test_text_that_only_looks_like_the_start_of_one_is_not_eaten(self):
        gate = runtime._HidesToolSyntax()
        out = gate.feed("dinner at 7 <") + gate.feed("br> and then")
        assert (out + gate.flush()) == "dinner at 7 <br> and then"

    def test_an_unclosed_block_hides_the_rest_rather_than_leaking_it(self):
        assert runtime.strip_tool_syntax('ok <tool_call>{"name": "x"') == "ok"

    def test_a_stray_marker_before_plain_text_takes_only_itself(self):
        """And "hello" was answered "<tool_call>" and then
        "Hello! How are you doing today?" — no payload, nothing closing it."""
        text = "<tool_call>\nHello! How are you doing today?"
        assert runtime.strip_tool_syntax(text) == "Hello! How are you doing today?"
        gate = runtime._HidesToolSyntax()
        out = "".join(gate.feed(c) for c in ["<tool_call>", "\n", "Hello! How", " are you?"])
        assert (out + gate.flush()).strip() == "Hello! How are you?"

    def test_a_stray_closing_marker_is_dropped_too(self):
        assert runtime.strip_tool_syntax("Sure thing.</tool_call>") == "Sure thing."

    def test_a_lone_marker_is_not_a_reply(self):
        assert runtime.strip_tool_syntax("<tool_call>") == ""
        assert runtime.strip_tool_syntax("<tool_call>\n  ") == ""

    def test_ordinary_prose_is_untouched(self):
        for text in ["Added: Dentist, Tue 16 Sep 15:00.", "מה יש מחר?", "3 < 5 and 5 > 3"]:
            assert runtime.strip_tool_syntax(text) == text

    async def test_the_stream_shows_none_of_it(self, calendar):
        """The token frames a browser receives, not just the final reply."""
        runtime.set_model(
            ScriptedModel(
                [
                    [call("just_talking", about="greeting")],
                    [say('I am well! <tool_call>{"name": "list_events"}</tool_call>')],
                ]
            )
        )
        frames = [
            f
            async for f in runtime.stream_turn(
                "how are you?", user_id=1, principal="robin", timezone="America/New_York"
            )
        ]
        tokens = "".join(f["text"] for f in frames if f["type"] == "token")
        assert "tool_call" not in tokens, tokens
        assert tokens.strip() == "I am well!"
        done = next(f for f in frames if f["type"] == "done")
        assert "tool_call" not in done["reply"]

    async def test_tulips_own_iteration_report_is_not_an_answer(self, calendar):
        """It is a note about the machinery addressed to nobody. Now that the
        server's reply is what the browser shows, it would be on screen."""
        assert runtime.is_machine_summary("Completed 3 iterations with 2 tool calls.\n- x")
        assert not runtime.is_machine_summary("Completed the booking for Tuesday.")


class TestWhenTheModelGoesQuiet:
    """Two turns in a row said nothing. One had already run a
    tool; the other answered with no tool call and no words at all."""

    async def test_an_event_it_wrote_is_reported_even_if_it_says_nothing(self, calendar):
        runtime.set_model(
            ScriptedModel(
                [
                    [
                        call(
                            "create_event",
                            title="Football",
                            start=_tomorrow_at(17),
                            certainty="high",
                        )
                    ],
                    [],  # and then the model says nothing at all
                ]
            )
        )
        result = await runtime.run_turn(
            "football today at 5", user_id=1, principal="robin", timezone=TZ
        )
        assert len(calendar.events) == 1, "the event is on the calendar"
        assert result.reply.startswith("Added: Football"), result.reply
        assert "circles" not in result.reply

    async def test_a_turn_with_nothing_in_it_at_all_is_asked_again(self, calendar):
        runtime.set_model(
            ScriptedModel(
                [
                    [],  # the model answers with neither a tool call nor a word
                    [],  # tulip's grace call, which it makes before giving up
                    [call("just_talking", about="greeting")],
                    [say("I am well, thank you!")],
                ]
            )
        )
        result = await runtime.run_turn("how are you?", user_id=1, principal="robin", timezone=TZ)
        assert result.reply == "I am well, thank you!"

    async def test_asked_again_and_still_nothing_it_says_so(self, calendar):
        runtime.set_model(ScriptedModel([[], [], [], []]))  # nothing, twice over
        result = await runtime.run_turn(
            "what's on today?", user_id=1, principal="robin", timezone=TZ
        )
        assert "did not actually do anything" in result.reply
        assert calendar.events == {}


async def test_the_model_that_served_the_turn_is_the_one_named(calendar):
    """Behind the router a fallback can answer for the model that was asked, and
    a person who picked one should see when another answered instead."""
    from tulip.core.events import ModelChunkEvent

    runtime.set_model(
        ScriptedModel(
            [
                [call("just_talking", about="greeting")],
                [ModelChunkEvent(content="Hi!", model="fallback-model")],
            ]
        )
    )
    frames = [
        f async for f in runtime.stream_turn("hey", user_id=1, principal="robin", timezone=TZ)
    ]
    named = [f["name"] for f in frames if f["type"] == "model"]
    assert named[-1] == "fallback-model" and len(named) == 2
    assert frames[-1]["type"] == "done" and frames[-1]["model"] == "fallback-model"


async def test_a_stopped_turn_keeps_what_it_did(calendar):
    """Stop, or a closed tab, cancels the turn mid-way. What was written before
    that is on the calendar, so the thread must not forget the turn."""
    import asyncio
    import contextlib

    from sqlalchemy import select

    from luach import db

    started = asyncio.Event()

    class SlowModel(ScriptedModel):
        async def stream(self, messages, tools=None, **kwargs):
            if not self.turns:
                yield say("Added ")
                started.set()
                await asyncio.sleep(30)
            async for c in super().stream(messages, tools, **kwargs):
                yield c

    runtime.set_model(SlowModel([[call("create_event", title="Picnic", start=_tomorrow_at(12))]]))
    tid = ""

    async def consume() -> None:
        nonlocal tid
        async for f in runtime.stream_turn(
            "picnic tomorrow noon", user_id=1, principal="robin", timezone=TZ
        ):
            if f["type"] == "session":
                tid = f["thread_id"]

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 5)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert [e.title for e in calendar.events.values()] == ["Picnic"]
    with db.session() as s:
        turns = s.scalars(select(db.Turn).where(db.Turn.thread_id == tid)).all()
        assert [t.role for t in turns] == ["user", "assistant"]
        assert turns[1].content.endswith("(stopped)") and "Picnic" in turns[1].events_json


async def test_an_added_that_added_nothing_is_asked_again(calendar):
    """It searched, found nothing, and answered "Added:
    Swimming, every Thu…" without calling create_event. Nothing was saved."""
    runtime.set_model(
        ScriptedModel(
            [
                [call("find_events", query="swimming")],
                [say("No swimming yet.\n\nAdded: Swimming, every Thu 18:00.")],
                [call("create_event", title="Swimming", start=_tomorrow_at(18))],
                [say("Added: Swimming.")],
            ]
        )
    )
    r = await runtime.run_turn("swimming tomorrow at 6", user_id=1, principal="robin", timezone=TZ)
    assert [e.title for e in calendar.events.values()] == ["Swimming"]
    assert r.created and "Added" in r.reply


async def test_a_claim_made_twice_without_a_write_is_told_as_it_is(calendar):
    runtime.set_model(
        ScriptedModel(
            [
                [call("find_events", query="swimming")],
                [say("Added: Swimming.")],
                [call("find_events", query="swimming")],
                [say("Added: Swimming, really.")],
            ]
        )
    )
    r = await runtime.run_turn("swimming tomorrow at 6", user_id=1, principal="robin", timezone=TZ)
    assert calendar.events == {}
    assert r.reply.startswith("I did not save that")


def test_what_counts_as_saying_it_was_written():
    claims = runtime.claims_a_write
    assert claims("No existing swimming event found.\n\nAdded: Swimming, every Thu")
    assert claims("I've added it for her") and claims("Añadido: natación") and claims("הוספתי")
    assert not claims("Nothing was added.") and not claims("Here is Friday.")
    assert not claims("Waiting for your approval — nothing is on the calendar yet: Add x")


@pytest.fixture
def harpers():
    family.roster()
    family.add("Ruby", kind="kid", color="2")
    family.add("Lily", kind="kid", color="3")


class TestAnAppointmentAtATimeIsAnEvent:
    """ "add a dentist appointment for Lily on Tuesday at 4:30pm" was a
    to-do due Tuesday, three times of three, and the reply claimed the 16:30."""

    async def test_a_one_off_at_a_time_is_refused_as_a_task_then_made_an_event(
        self, calendar, harpers
    ):
        tue = _next(1, 16, 30)
        runtime.set_model(
            ScriptedModel(
                [
                    [call("add_task", title="Dentist", for_whom="Lily", due=tue[:10])],
                    [call("create_event", title="Dentist", start=tue, for_whom="Lily")],
                    [say("Added: Dentist, Tue 16:30.")],
                ]
            )
        )
        r = await runtime.run_turn(
            "add a dentist appointment for Lily on tuesday at 4:30pm",
            user_id=1,
            principal="robin",
            timezone=TZ,
        )
        assert tasks.every(_today()) == []
        (ev,) = calendar.events.values()
        assert ev.title == "Dentist" and r.reply.startswith("Added")

    async def test_claiming_the_refused_task_was_added_is_asked_again(self, calendar, harpers):
        tue = _next(1, 16, 30)
        runtime.set_model(
            ScriptedModel(
                [
                    [call("add_task", title="Dentist", for_whom="Lily", due=tue[:10])],
                    [say("Added: Dentist, Tue 16:30.")],
                    [call("create_event", title="Dentist", start=tue, for_whom="Lily")],
                    [say("Added: Dentist, Tue 16:30.")],
                ]
            )
        )
        await runtime.run_turn(
            "add a dentist appointment for Lily on tuesday at 4:30pm",
            user_id=1,
            principal="robin",
            timezone=TZ,
        )
        assert len(calendar.events) == 1
        assert "turn.claimed_unwritten" in [r.event_type for r in control.trail().records()]

    @pytest.mark.parametrize(
        "text, repeats",
        [
            ("Ruby has to finish homework by 5pm", ""),
            ("Lily feeds the fish every day at 7", "daily"),
            ("Ruby and Lily tidy their room by saturday", ""),
        ],
    )
    async def test_deadlines_and_chores_stay_tasks(self, calendar, harpers, text, repeats):
        runtime.set_model(
            ScriptedModel(
                [[call("add_task", title="x", for_whom="Ruby", repeats=repeats)], [say("ok")]]
            )
        )
        await runtime.run_turn(text, user_id=1, principal="robin", timezone=TZ)
        assert len(tasks.every(_today())) == 1


class TestWhoseItIsIsSaidOutLoud:
    """With the memory tools on offer, "Ruby has soccer practice on Tuesday at 5pm"
    was saved as "Ruby has soccer practice" for nobody — on no one's board — 2 runs
    of 4."""

    async def test_a_named_person_with_no_for_whom_is_asked_then_theirs(self, calendar, harpers):
        tue = _next(1, 17)
        runtime.set_model(
            ScriptedModel(
                [
                    [call("create_event", title="Ruby has soccer practice", start=tue)],
                    [call("create_event", title="Soccer practice", start=tue, for_whom="Ruby")],
                    [say("Added.")],
                ]
            )
        )
        await runtime.run_turn(
            "Ruby has soccer practice on Tuesday at 5pm", user_id=1, principal="robin", timezone=TZ
        )
        (ev,) = calendar.events.values()
        assert ev.title == "Soccer practice"
        assert [p.key for p in family.leaders_for(ev)] == ["ruby"]

    async def test_nobody_is_an_answer(self, calendar, harpers):
        runtime.set_model(
            ScriptedModel(
                [
                    [call("create_event", title="Pizza", start=_next(4, 18), for_whom="nobody")],
                    [say("Added.")],
                ]
            )
        )
        await runtime.run_turn(
            "pizza night friday at 6, Ruby picks", user_id=1, principal="robin", timezone=TZ
        )
        (ev,) = calendar.events.values()
        assert family.leaders_for(ev) == []

    async def test_the_owners_name_leaves_the_title(self, calendar, harpers):
        runtime.set_model(
            ScriptedModel(
                [
                    [
                        call(
                            "create_event",
                            title="Ruby's soccer practice",
                            start=_next(1, 17),
                            for_whom="Ruby",
                        )
                    ],
                    [say("Added.")],
                ]
            )
        )
        await runtime.run_turn(
            "Ruby has soccer practice on Tuesday at 5pm", user_id=1, principal="robin", timezone=TZ
        )
        (ev,) = calendar.events.values()
        assert ev.title == "Soccer practice"

    def test_who_a_message_names(self, harpers):
        assert [p.key for p in family.mentioned("Ruby's soccer, and lily too")] == [
            "ruby",
            "lily",
        ]
        assert family.mentioned("Rubyanne's party") == []


def _on_screen(frames: list[dict]) -> str:
    """What a client shows for the turn's words while it streams, by the stream's own
    rules: tokens add up, and a `retract` takes back what came before it."""
    shown = ""
    for f in frames:
        if f["type"] == "token":
            shown += f["text"]
        elif f["type"] == "retract":
            shown = ""
    return shown


async def _turn_frames(model: ScriptedModel, text: str = "hello") -> list[dict]:
    runtime.set_model(model)
    return [f async for f in runtime.stream_turn(text, user_id=1, principal="robin", timezone=TZ)]


class TestAnAnswerIsShownOnce:
    """The chat repeated its answer, word for word, two to six times. A model may
    write its answer and call a tool in the same reply (just_talking, a read), then
    write the answer again once the tool has answered. Every model call's words were
    relayed into the one reply as they came, while the reply in `done` held only the
    last: the iPhone, which keeps what streamed, showed every copy."""

    async def test_words_said_again_after_a_tool_replace_the_first(self, calendar):
        frames = await _turn_frames(
            ScriptedModel(
                [
                    [say("Hi there!"), call("just_talking", about="greeting")],
                    [say("Hi there!")],
                ]
            )
        )
        done = frames[-1]
        assert done["type"] == "done" and done["reply"] == "Hi there!"
        assert _on_screen(frames) == "Hi there!"

    async def test_a_model_that_keeps_calling_says_it_once(self, calendar):
        frames = await _turn_frames(
            ScriptedModel(
                [[say("Hi there!"), call("just_talking", about=f"g{i}")] for i in range(5)]
            )
        )
        assert _on_screen(frames) == frames[-1]["reply"] == "Hi there!"

    async def test_a_claim_asked_again_is_not_left_beside_the_second_answer(self, calendar):
        frames = await _turn_frames(
            ScriptedModel(
                [
                    [call("find_events", query="swimming")],
                    [say("Added: Swimming.")],
                    [call("create_event", title="Swimming", start=_tomorrow_at(18))],
                    [say("Added: Swimming, tomorrow at 18:00.")],
                ]
            ),
            "swimming tomorrow at 6",
        )
        assert [e.title for e in calendar.events.values()] == ["Swimming"]
        assert _on_screen(frames) == frames[-1]["reply"] == "Added: Swimming, tomorrow at 18:00."

    async def test_words_before_a_tool_stay_when_nothing_comes_after(self, calendar):
        """The answer, then a call, then silence: the answer is still the answer."""
        frames = await _turn_frames(
            ScriptedModel(
                [
                    [say("Nothing on today."), call("list_events", start_date=_today())],
                    [],
                ]
            ),
            "anything today?",
        )
        assert not [f for f in frames if f["type"] == "retract"]
        assert _on_screen(frames) == frames[-1]["reply"] == "Nothing on today."


async def test_a_picked_model_its_provider_refuses_is_named(calendar, monkeypatch):
    """The router sent the DeepSeek pick to a model its provider no longer serves, and
    every turn ended "luach hit a problem: BadRequestError". A person who picked a model
    is told that model is the one not answering, and where to choose another."""
    import json

    monkeypatch.setenv(
        "LUACH_MODELS",
        json.dumps(
            [
                {"id": "qwen3.6-35b", "name": "Home", "about": ""},
                {"id": "cloud-deepseek-v4-flash", "name": "DeepSeek V4 Flash", "about": ""},
            ]
        ),
    )
    model_menu.seed()

    class Refused(Exception):
        status_code = 400

    class RefusingModel:
        async def stream(self, messages, tools=None, **kwargs):
            raise Refused("Endpoint has no deployments configured for routing.")
            yield  # pragma: no cover

    runtime.set_model(RefusingModel())
    picked = await runtime.run_turn(
        "hi", user_id=1, principal="robin", timezone=TZ, model="cloud-deepseek-v4-flash"
    )
    assert picked.error and picked.error.startswith("DeepSeek V4 Flash did not answer")
    assert "Settings" in picked.error
    # The household's own model refusing is not a pick to change.
    own = await runtime.run_turn("hi", user_id=1, principal="robin", timezone=TZ)
    assert own.error and own.error.startswith("The household's model did not answer")
    assert "owner has been told" in own.error
