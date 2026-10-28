""" "Try it": a dozen of luach's own cases, to see whether a model can run luach.

The owner adds a model; before it joins the members' menu, luach asks it what a
family asks — read the week, add an event, a correction, a follow-up, a change
the gate holds, small talk in three languages — and scores what it *did*: which
tool each turn reached for, and what ended up on the calendar. No judge (see
``evals``: the judge is the model under test).

This module is the child half. ``luach.model_trials`` starts it as its own
process (``python -m luach.agent.trial_evals``) with an environment it builds:
a throwaway database or schema, ``LUACH_CALENDAR=fake``, no search, no memory,
no Google, mail or push credentials, and ``LUACH_MODEL`` the model on trial. It
cannot reach the household's calendar or its data: the setup below refuses to
start on anything else. It prints one JSON line per case, then a summary.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from luach.agent.chat_evals import TZ, Say, World, _seed, one, when

logger = logging.getLogger(__name__)

MEMBER = "robin"

Check = Callable[[World, list[Any]], list[str]]


@dataclass(frozen=True)
class Case:
    name: str
    about: str
    turns: tuple[Say, ...]
    #: Per turn, the tools of which at least one must run.
    wants: tuple[frozenset[str], ...]
    check: Check | None = None
    seed: Callable[[World], None] | None = None
    #: Approve what the gate holds, as a person would; False scores the hold itself.
    approve: bool = True
    tags: tuple[str, ...] = field(default_factory=tuple)


CHAT = frozenset({"just_talking"})
READ = frozenset({"list_events"})
WRITES = frozenset({"create_event", "update_event", "delete_event", "add_task"})


def _seed_week(w: World) -> None:
    tomorrow = w.today + timedelta(days=1)
    _seed(w, "Orthodontist", tomorrow, "09:00", 45)
    _seed(w, "Team meeting", tomorrow, "14:00")
    _seed(w, "Haircut", tomorrow + timedelta(days=1), "11:00", 30)


def _check_dentist(w: World, _held: list[Any]) -> list[str]:
    return one(w, ("dentist",), w.day(1), "15:00", "dentist")


def _check_swim(w: World, _held: list[Any]) -> list[str]:
    found = w.events("swim")
    if len(found) != 1:
        return [f"swim: {len(found)} events, wanted 1"]
    day, hhmm = when(found[0])
    out = (
        [] if day.weekday() == 3 and hhmm == "17:00" else [f"swim: {day} {hhmm}, wanted Thu 17:00"]
    )
    if found[0].leader != "ruby":
        out.append(f"swim: for {found[0].leader!r}, wanted ruby")
    return out


def _seed_lunch(w: World) -> None:
    _seed(w, "Lunch with Maya", w.day(5), "12:00")


def _check_held(w: World, held: list[Any]) -> list[str]:
    out = []
    if not held:
        out.append("the cancellation was not held for a yes")
    if len(w.events("maya")) != 1:
        out.append("lunch with Maya is gone without anyone approving it")
    return out


def _check_futbol(w: World, _held: list[Any]) -> list[str]:
    found = w.events("fútbol", "futbol", "football", "soccer")
    out = one(w, ("fútbol", "futbol", "football", "soccer"), w.day(5), "10:00", "fútbol")
    out += [f"fútbol: for {e.leader!r}, wanted lily" for e in found if e.leader != "lily"]
    return out


CASES: tuple[Case, ...] = (
    Case("greeting", "a greeting is a conversation", (Say("hello"),), (CHAT,)),
    Case("small_talk", "small talk reads nobody's week", (Say("whats up buddy"),), (CHAT,)),
    Case("thanks", "thanks is not a calendar question", (Say("thanks!"),), (CHAT,)),
    Case("hebrew_chat", "small talk in Hebrew", (Say("מה קורה"),), (CHAT,)),
    Case("the_week", "reading the week", (Say("what's on this week?"),), (READ,), seed=_seed_week),
    Case("tomorrow_es", "reading a day, in Spanish", (Say("¿qué hay mañana?"),), (READ,)),
    Case(
        "free_at",
        "is a time free",
        (Say("am I free Friday at 4?"),),
        (frozenset({"check_availability"}),),
    ),
    Case(
        "add_event",
        "adding an event",
        (Say("add a dentist appointment for me on tuesday at 3pm"),),
        (frozenset({"create_event"}),),
        check=_check_dentist,
    ),
    Case(
        "correction",
        "an event, then 'no, thursday'",
        (Say("add swim for Ruby on wednesday at 5pm"), Say("no, thursday")),
        (frozenset({"create_event"}), frozenset({"update_event", "create_event", "delete_event"})),
        check=_check_swim,
    ),
    Case(
        "follow_up",
        "a follow-up that means something only after the turn before",
        (Say("what's on tomorrow?"), Say("and the day after?")),
        (READ, READ),
        seed=_seed_week,
    ),
    Case(
        "held",
        "cancelling an event this conversation did not make waits for a yes",
        (Say("cancel lunch with Maya on saturday"),),
        (frozenset({"delete_event"}),),
        check=_check_held,
        seed=_seed_lunch,
        approve=False,
    ),
    Case(
        "add_es",
        "adding an event for a child, in Spanish",
        (Say("añade fútbol para Lily el sábado a las 10"),),
        (frozenset({"create_event"}),),
        check=_check_futbol,
    ),
)


def problems_of(case: Case, tools: list[list[str]], errors: list[str]) -> list[str]:
    """What each turn did wrong by which tools it reached for."""
    out = [f"turn {n}: {e}" for n, e in enumerate(errors, 1) if e]
    for n, (wanted, used) in enumerate(zip(case.wants, tools, strict=False), 1):
        if wanted and not wanted & set(used):
            out.append(f"turn {n}: {used or 'no tool'}, wanted {' or '.join(sorted(wanted))}")
        wrote = WRITES & set(used)
        if wrote and not wanted & WRITES:
            out.append(f"turn {n}: wrote ({', '.join(sorted(wrote))}) when nothing was asked")
    return out


async def run_case(case: Case, user_id: int) -> dict[str, Any]:
    from luach.agent import pending, runtime
    from luach.calendar import client, times

    cal = client.FakeCalendar()
    client.set_calendar(cal)
    world = World(calendar=cal, today=times.now_in(TZ).date())
    if case.seed:
        case.seed(world)
    tools: list[list[str]] = []
    errors: list[str] = []
    held: list[Any] = []
    thread: str | None = None
    try:
        for step in case.turns:
            result = await runtime.run_turn(
                step.text,
                user_id=user_id,
                principal=MEMBER,
                timezone=TZ,
                thread_id=thread,
                calendar=cal,
                door="trial",
            )
            thread = result.thread_id
            tools.append([c.get("tool", "") for c in result.tool_calls])
            errors.append(result.error or "")
            held += result.held
            if case.approve:
                for h in result.held:
                    if "possible-duplicate" in h.get("reason", []):
                        pending.deny(h["id"], by=MEMBER, viewer_id=user_id)
                    else:
                        pending.approve(
                            h["id"], by=MEMBER, timezone=TZ, calendar=cal, viewer_id=user_id
                        )
    except Exception as exc:  # a broken turn is a failed case, not a crashed run
        logger.exception("trial case %s failed", case.name)
        errors.append(f"{type(exc).__name__}")
    found = problems_of(case, tools, errors)
    if case.check and not any(errors):
        found += case.check(world, held)
    return {
        "case": case.name,
        "about": case.about,
        "ok": not found,
        "problems": found[:6],
        "tools": tools,
        "error": next((e for e in errors if e), ""),
    }


def _refuse_unless_isolated() -> None:
    """Never against a household: the parent builds this environment, and a run
    started any other way stops here."""
    if os.environ.get("LUACH_TRIAL") != "1" or os.environ.get("LUACH_CALENDAR") != "fake":
        raise SystemExit("trial_evals runs only as luach.model_trials starts it")
    for name in os.environ:
        if name.startswith(("LUACH_GOOGLE", "LUACH_MAIL_OAUTH", "LUACH_VAPID", "RESEND")):
            raise SystemExit(f"trial_evals refuses to run with {name} set")
    if os.environ.get("LUACH_MEMORY_DSN") or os.environ.get("CREDENTIALS_DIRECTORY"):
        raise SystemExit("trial_evals refuses to run with a memory store or credentials")


def setup() -> int:
    """Its own schema, brought to head, with one grown-up and two children."""
    from luach import db, family, migrate
    from luach.agent import control
    from luach.auth import users

    url = os.environ["LUACH_DATABASE_URL"]
    migrate.upgrade(url)
    db.reset_engine()
    db.init_db(url)
    control.reset_trail()
    member = users.create_user(
        MEMBER, "robin@example.com", "a long trial password", display_name="Robin"
    )
    family.add("Ruby", kind="kid")
    family.add("Lily", kind="kid")
    return int(member.id)


async def run(only: str = "") -> list[dict[str, Any]]:
    user_id = setup()
    picked = [c for c in CASES if only in c.name]
    results = []
    for case in picked:
        result = await run_case(case, user_id)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    print(
        json.dumps(
            {"summary": True, "passed": sum(r["ok"] for r in results), "total": len(results)}
        ),
        flush=True,
    )
    return results


def main(argv: list[str] | None = None) -> int:
    _refuse_unless_isolated()
    logging.basicConfig(level=logging.ERROR, stream=sys.stderr)
    args = argv if argv is not None else sys.argv[1:]
    asyncio.run(run(args[0] if args else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
