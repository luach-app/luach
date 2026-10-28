"""The multi-turn conversations are code like any other: their shape and their
checks here, their verdicts against a live model only when someone runs them."""

from __future__ import annotations

from datetime import date

import pytest
from tulip.memory.store import InMemoryStore

from luach import memory
from luach.agent import chat_evals, runtime
from luach.calendar.client import FakeCalendar
from tests.doubles import ScriptedModel, call, say

TODAY = date(2026, 10, 28)  # a Wednesday; nothing below reads the wall clock


def _world(**seeded) -> chat_evals.World:
    return chat_evals.World(calendar=FakeCalendar(), today=TODAY, **seeded)


def test_every_conversation_is_several_turns_with_a_check():
    names = [c.name for c in chat_evals.CONVERSATIONS]
    assert len(names) == len(set(names)) >= 8
    for c in chat_evals.CONVERSATIONS:
        assert len(c.turns) >= 3 and callable(c.check), c.name
    # Two of them are about a second thread: memory is what crosses it.
    assert sum(any(s.new_thread for s in c.turns) for c in chat_evals.CONVERSATIONS) >= 2


def test_days_are_the_ones_the_context_line_names():
    w = _world()
    assert w.day(1) == date(2026, 11, 3)  # "tuesday", asked on a Wednesday
    assert w.day(3) == date(2026, 10, 29)  # "thursday" is tomorrow
    assert w.day(0, weeks=1) == date(2026, 11, 9)


def test_a_check_passes_the_calendar_it_wants_and_fails_any_other():
    w = _world()
    chat_evals._seed_move_it(w)
    assert chat_evals._check_move_it(w) == [
        "dentist: 0 events, wanted 1 ([])",
    ]
    chat_evals._seed(w, "Dentist", w.day(1), "16:30")
    next(iter(w.events("dentist"))).description = "bring the insurance card"
    assert chat_evals._check_move_it(w) == []
    chat_evals._seed(w, "Dentist", w.day(1), "15:00")  # the move made a second one
    assert chat_evals._check_move_it(w)[0].startswith("dentist: 2 events")


def test_the_memory_checks_read_the_facts_left_behind():
    w = _world(facts={"robin": ["I only book appointments in the morning"], "ana": []})
    chat_evals._seed(w, "Vet", w.day(3), "15:00")
    chat_evals._seed(w, "Dentist", w.day(4), "11:00")
    assert chat_evals._check_memory_change(w) == [
        "still remembers mornings-only: ['I only book appointments in the morning']"
    ]
    w.facts["robin"] = ["I book appointments mornings and afternoons"]
    assert chat_evals._check_memory_change(w) == []


@pytest.fixture
def facts(monkeypatch):
    monkeypatch.setenv("LUACH_MEMORY_DSN", "postgresql://luach@127.0.0.1/luach")
    memory.set_store(InMemoryStore())


async def test_a_conversation_runs_through_the_real_turn_and_is_scored(facts):
    # A model that adds the dentist again instead of moving it. luach holds the
    # second as a likely duplicate and the harness turns it down, as a person
    # would: the dentist is still at 3, and the harness says so.
    from luach.calendar import times

    tue = chat_evals.World(None, times.now_in(chat_evals.TZ).date()).day(1).isoformat()
    runtime.set_model(
        ScriptedModel(
            [
                [call("create_event", title="רופא שיניים", start=f"{tue}T15:00")],
                [say("נוסף.")],
                [call("just_talking", about="thanks")],
                [say("בכיף!")],
                [call("create_event", title="רופא שיניים", start=f"{tue}T17:00")],
                [say("הוזז.")],
            ]
        )
    )
    hebrew = next(c for c in chat_evals.CONVERSATIONS if c.name == "hebrew")
    scored = await chat_evals.run_conversation(hebrew, {"robin": 1, "ana": 2})
    assert not scored.passed
    assert scored.tools == [["create_event"], ["just_talking"], ["create_event", "denied"]]
    assert scored.problems == [f"dentist: at {tue} 15:00, wanted {tue} 17:00"]
    assert scored.replies[2].startswith("Waiting for your approval")
    text = chat_evals.report([scored])
    assert "FAIL hebrew" in text and "conversations 0/1 passed" in text


@pytest.mark.parametrize("conv", chat_evals.CONVERSATIONS, ids=lambda c: c.name)
def test_every_check_fails_a_conversation_that_changed_nothing(conv):
    w = _world(facts={"robin": [], "ana": []})
    if conv.seed:
        conv.seed(w)
    assert conv.check(w), f"{conv.name} passes a calendar nobody touched"


async def test_the_command_runs_the_named_conversations(facts, monkeypatch, capsys):
    monkeypatch.setattr(chat_evals, "_isolate", lambda dsn: {"robin": 1, "ana": 2})
    runtime.set_model(ScriptedModel([[call("just_talking", about="x")], [say("Okay.")]] * 3))
    results = await chat_evals.run(only="hebrew", verbose=True)
    assert [r.conversation.name for r in results] == ["hebrew"]
    out = capsys.readouterr().out
    assert "> תודה" in out and "conversations 0/1 passed" in out
