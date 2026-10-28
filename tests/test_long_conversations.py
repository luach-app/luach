"""A conversation is many turns: each starts fresh on tulip's per-run counters."""

from __future__ import annotations

from luach.agent import runtime
from tests.doubles import ScriptedModel, call, say

TZ = "America/New_York"


async def test_small_talk_turn_after_turn_is_answered_every_time(calendar):
    # The same just_talking call on four turns in a row read to tulip as a tool
    # loop, because a resumed thread kept the steps of the turns before it: the
    # fourth turn ended with no answer and every later one with nothing at all
    # (the fourth was "well i yell when im tired").
    said = ["Hey!", "Sorry to hear that.", "That sounds hard.", "A hard evening.", "Okay."]
    runtime.set_model(
        ScriptedModel([step for s in said for step in ([call("just_talking")], [say(s)])])
    )
    thread = None
    for expected in said:
        result = await runtime.run_turn(
            "hi", user_id=1, principal="robin", timezone=TZ, thread_id=thread
        )
        thread = result.thread_id
        assert result.reply == expected


async def test_a_long_conversation_keeps_its_steps_per_turn(calendar):
    # tulip counts iterations on the thread, not the run: with 16 allowed, a
    # conversation of two-step turns ran out at the eighth.
    turns = 12
    runtime.set_model(
        ScriptedModel(
            [
                step
                for n in range(turns)
                for step in ([call("just_talking", about=f"turn {n}")], [say(f"reply {n}")])
            ]
        )
    )
    thread = None
    for n in range(turns):
        result = await runtime.run_turn(
            f"message {n}", user_id=1, principal="robin", timezone=TZ, thread_id=thread
        )
        thread = result.thread_id
        assert result.reply == f"reply {n}", f"turn {n}: {result.reply}"


def test_a_personal_conversation_is_judged_by_fact():
    from luach.agent.evals import personal_problems

    good = ["Hey!", "That sounds like a hard evening.", "That is a heavy thing to carry."]
    assert personal_problems(good, [["just_talking"]] * 3) == []
    bad = [
        "Do you want to talk about it?",
        "Do you want to talk about it?",
        "I went round in circles on that one.",
    ]
    found = personal_problems(bad, [["just_talking"], ["just_talking"], ["create_event"]])
    assert "turn 1: probes: 'Do you want to talk about it?'" in found
    assert "turn 2: repeats an earlier reply" in found
    assert "turn 3: no answer" in found and "turn 3: wrote ['create_event']" in found


def _asked(messages) -> list[str]:
    return [m.content for m in messages if m.role == "user"]


async def test_turn_ten_still_sees_turn_one_whole(calendar):
    # A model whose window tulip did not know got the last 32 messages: by the
    # tenth turn of tool-using turns "add the dentist" was gone, and the request
    # opened on a tool call whose question had been cut away.
    turns = 10
    model = ScriptedModel(
        [
            step
            for n in range(turns)
            for step in (
                [call("list_events", start_date="2026-11-02", end_date="2026-11-03")],
                [call("just_talking", about=f"turn {n}")],
                [say(f"reply {n}")],
            )
        ]
    )
    runtime.set_model(model)
    thread = None
    for n in range(turns):
        result = await runtime.run_turn(
            f"message {n}", user_id=1, principal="robin", timezone=TZ, thread_id=thread
        )
        thread = result.thread_id
    sent = model.calls[-1]["messages"]
    asked = _asked(sent)
    assert [a.splitlines()[-1] for a in asked] == [f"message {n}" for n in range(turns)]
    first = next(m for m in sent if m.role != "system")
    assert first.role == "user"


async def test_only_the_newest_question_carries_the_household_state(calendar, monkeypatch):
    """A fact forgotten in turn two was replayed, as it had been, inside turn
    one's question for the rest of the thread."""
    from tulip.memory.store import InMemoryStore

    from luach import memory

    monkeypatch.setenv("LUACH_MEMORY_DSN", "postgresql://luach@127.0.0.1/luach")
    memory.set_store(InMemoryStore())
    await memory.remember(1, "robin", "I only book appointments in the morning", "mornings")
    model = ScriptedModel(
        [
            [call("just_talking", about="hi")],
            [say("Hi.")],
            [call("forget", what="mornings")],
            [say("Forgotten.")],
            [call("just_talking", about="thanks")],
            [say("Any time.")],
        ]
    )
    runtime.set_model(model)
    thread = None
    for text in ("hi", "forget that I only book mornings", "thanks"):
        result = await runtime.run_turn(
            text, user_id=1, principal="robin", timezone=TZ, thread_id=thread
        )
        thread = result.thread_id
    asked = _asked(model.calls[-1]["messages"])
    assert not any("morning" in a for a in asked[:-1] if "<memory-context>" in a)
    assert all("<memory-context>" not in a and "next 7 days" not in a for a in asked[:-1])
    assert asked[0].startswith("[context] asked ") and asked[0].endswith("\nhi")
    assert "next 7 days" in asked[-1]


def test_a_long_thread_slides_by_whole_turns():
    from tulip.core.messages import Message, ToolCall

    from luach.agent.history import TurnWindow

    messages = [Message.system("prompt")]
    for n in range(12):
        tc = ToolCall(id=f"c{n}", name="list_events", arguments={})
        messages += [
            Message.user(f"[context] now=Mon | x\nq{n}"),
            Message.assistant(content=None, tool_calls=[tc]),
            Message(role="tool", tool_call_id=f"c{n}", content="{}"),
            Message.assistant(content=f"a{n}"),
        ]
    window = TurnWindow(keep=8, slide=3)
    sent = window.apply(messages)
    asked = [m.content.splitlines()[-1] for m in sent if m.role == "user"]
    # 12 turns, 8 kept at most, dropped 3 at a time: 6 left, from a question.
    assert asked == [f"q{n}" for n in range(6, 12)]
    assert [m.role for m in sent[:2]] == ["system", "user"]
    # One more turn and the start does not move (the prompt cache keeps it).
    more = messages + [Message.user("[context] now=Tue | x\nq12")]
    assert window.apply(more)[1] == sent[1]
