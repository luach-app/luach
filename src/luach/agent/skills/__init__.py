"""luach's skills: the procedures the model loads when a turn needs one.

The system prompt used to carry every procedure — whose an event is, tasks and
chores, repeats, forwarded mail, memory — on every turn, whether the turn was
"hello" or a flight itinerary. Each is now a tulip skill (a SKILL.md here, in
the AgentSkills.io shape): the model sees a one-line catalogue and calls the
`skills` tool to load the one it needs.

No family member is named in these files. Where an example needs a name the
text says {a} or {b}, and those are filled from the household's own family
list each time the agent is built — a new child, a renamed one, another
household altogether, and the examples follow.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent

#: Names used when the family has fewer people than the examples want.
_FALLBACK = ("Sam", "Noa")


@cache
def _templates() -> tuple[tuple[Path, str], ...]:
    return tuple(
        (d, (d / "SKILL.md").read_text(encoding="utf-8"))
        for d in sorted(HERE.iterdir())
        if (d / "SKILL.md").is_file()
    )


def examples(people: list[Any]) -> tuple[str, str]:
    """Two names for the examples: the children first, then anyone."""
    ordered = [p.name for p in people if getattr(p, "kind", "") == "kid"] + [
        p.name for p in people if getattr(p, "kind", "") != "kid"
    ]
    names = [*ordered, *_FALLBACK]
    return names[0], names[1] if names[1] != names[0] else _FALLBACK[1]


def load(people: list[Any] | None = None) -> list[Any]:
    """The skills, with this household's names in their examples."""
    from tulip.skills import Skill

    from luach import family

    a, b = examples(family.roster() if people is None else people)
    out = []
    for path, text in _templates():
        rendered = text.replace("{a}", a).replace("{b}", b)
        skill = Skill.from_content(rendered, path=path)
        out.append(skill)
    return out
