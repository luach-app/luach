"""luach's skills: loaded as tulip skills, named from the household's own family."""

from __future__ import annotations

import re
from pathlib import Path

from luach import family
from luach.agent import runtime, skills
from tests.doubles import ScriptedModel, call, say

TZ = "America/New_York"
SKILL_DIR = Path(skills.__file__).parent


def test_every_skill_file_parses_and_names_no_one():
    """A colon in a description once made a skill vanish; and no family member's
    name belongs in the source — the examples come from the family list."""
    loaded = skills.load([])
    assert {s.name for s in loaded} == {
        "whose-it-is",
        "tasks-and-chores",
        "repeating-events",
        "forwarded-mail",
        "your-email",
        "remembering",
    }
    for s in loaded:
        assert s.description.startswith("Use when"), s.name
    source = "\n".join(
        p.read_text()
        for p in [*SKILL_DIR.glob("*/SKILL.md"), Path(runtime.__file__).with_name("prompt.py")]
    )
    assert not re.search(r"\b(Ruby|Lily|Alex|Theo)\b", source)


def test_the_examples_are_this_familys():
    family.add("Iris", kind="kid")
    family.add("Tomer", kind="kid")
    whose = next(s for s in skills.load() if s.name == "whose-it-is")
    assert '"breakfast for Iris and Tomer"' in whose.description
    assert "{a}" not in whose.instructions and "{b}" not in whose.description


def test_remembering_is_offered_only_where_there_is_memory(monkeypatch):
    monkeypatch.delenv("LUACH_MEMORY_DSN", raising=False)
    names = {s.name for s in runtime.build_agent("robin").config.skills}
    assert "remembering" not in names and "whose-it-is" in names
    monkeypatch.setenv("LUACH_MEMORY_DSN", "postgresql://luach@127.0.0.1/luach")
    assert "remembering" in {s.name for s in runtime.build_agent("robin").config.skills}


async def test_loading_a_skill_is_not_doing_something(calendar):
    """The first call must be a tool; a skill loaded first does not lift that,
    and a turn that only read up on how cannot count as having acted."""
    model = ScriptedModel(
        [
            [call("skills", skill_name="whose-it-is")],
            [call("just_talking", about="hi")],
            [say("Hi!")],
        ]
    )
    runtime.set_model(model)
    r = await runtime.run_turn("hey", user_id=1, principal="robin", timezone=TZ)
    assert r.reply == "Hi!"
    assert [t["tool"] for t in r.tool_calls] == ["just_talking"]
    # tool_choice held through the skill, and only then let go.
    required = [c.get("tool_choice") for c in model.calls]
    assert required[:2] == ["required", "required"] and required[2] is None


async def test_a_turn_that_only_loaded_a_skill_did_nothing(calendar):
    runtime.set_model(
        ScriptedModel([[call("skills", skill_name="tasks-and-chores")], [say("Added the task.")]])
    )
    r = await runtime.run_turn("lily has to pack", user_id=1, principal="robin", timezone=TZ)
    assert "did not actually do anything" in r.reply


async def test_the_chat_is_told_which_guide_was_followed(calendar):
    """A skill is shown as a step of its own — named, never as a tool call —
    so the work trace can say why the next step is the one it is."""
    runtime.set_model(
        ScriptedModel(
            [
                [call("skills", skill_name="repeating-events")],
                [call("just_talking", about="hi")],
                [say("Hi!")],
            ]
        )
    )
    frames = [
        f async for f in runtime.stream_turn("hey", user_id=1, principal="robin", timezone=TZ)
    ]
    assert {"type": "skill", "name": "repeating-events"} in frames
    assert not any(f.get("type") == "tool_start" and f.get("tool") == "skills" for f in frames)
    done = next(f for f in frames if f.get("type") == "done")
    assert [t["tool"] for t in done["tool_calls"]] == ["just_talking"]
