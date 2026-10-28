"""Conversations of several turns, scored by what ends up on the calendar.

A family does not talk to luach in single messages. It says "add the dentist
Tuesday at 3", then "thanks", then "actually move it to 4:30": a correction, a
pronoun, a fact said three turns ago, a preference said yesterday in another
conversation. The register suite (``evals.py``) asks one question per thread and
cannot see any of that. These conversations go through the real turn path
(``runtime.run_turn``, one thread each, a second thread where the case says so)
against a fake calendar, a throwaway database and a memory store of their own,
and are scored by fact: which events exist afterwards, on which day and at what
time, which facts are remembered, and a few words a reply must or must not hold.
No judge.

Run it against whichever model the environment points at::

    LUACH_MODEL=… OPENAI_BASE_URL=… OPENAI_API_KEY=… python -m luach.agent.chat_evals

``--only <name>`` runs the conversations whose name contains it; ``--repeat N``
runs each N times (a single pass of a sampled model is an anecdote);
``--memory-dsn`` points memory at a pgvector Postgres (``hatch run`` users: a
``pgvector/pgvector:pg16`` container), and without it facts live in tulip's
in-memory store, whose recall is a substring match rather than semantic.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

TZ = "America/New_York"
MEMBER = "robin"
#: A second grown-up, for the edge between members.
OTHER = "ana"


@dataclass(frozen=True)
class Say:
    """One message in a conversation."""

    text: str
    #: Start a new thread here: "the next day, in another conversation".
    new_thread: bool = False
    #: Who says it (MEMBER unless the case is about another member).
    member: str = MEMBER
    #: Checked on this turn's reply, case-folded: a pattern it must match.
    reply_has: str = ""
    #: And one it must not.
    reply_lacks: str = ""


@dataclass
class World:
    """What a conversation left behind, for its checks to read."""

    calendar: Any
    today: date
    replies: list[str] = field(default_factory=list)
    tools: list[list[str]] = field(default_factory=list)
    #: Every fact each member has remembered, at the end.
    facts: dict[str, list[str]] = field(default_factory=dict)

    def events(self, *words: str) -> list[Any]:
        """Events whose title holds any of these words (case-folded)."""
        return [
            e for e in self.calendar.events.values() if any(w in e.title.casefold() for w in words)
        ]

    def day(self, weekday: int, weeks: int = 0) -> date:
        """The next ``weekday`` (Mon=0) after today, as the [context] line names it."""
        d = self.today + timedelta(days=1)
        while d.weekday() != weekday:
            d += timedelta(days=1)
        return d + timedelta(weeks=weeks)


def when(ev: Any) -> tuple[date, str]:
    """An event's local day and HH:MM."""
    from luach.calendar import times

    start = times.parse_when(ev.start, TZ)
    if not isinstance(start, datetime):
        return start, ""
    return start.date(), start.strftime("%H:%M")


def minutes(ev: Any) -> int:
    from luach.calendar import times

    start, end = times.parse_when(ev.start, TZ), times.parse_when(ev.end, TZ)
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        return 0
    return int((end - start).total_seconds() // 60)


def one(world: World, words: tuple[str, ...], day: date, hhmm: str, what: str) -> list[str]:
    """Exactly one event with these words, at this day and time."""
    found = world.events(*words)
    if len(found) != 1:
        return [f"{what}: {len(found)} events, wanted 1 ({[when(e) for e in found]})"]
    got = when(found[0])
    if got != (day, hhmm):
        return [f"{what}: at {got[0]} {got[1]}, wanted {day} {hhmm}"]
    return []


Seed = Callable[[World], None]
Check = Callable[[World], list[str]]


@dataclass(frozen=True)
class Conversation:
    name: str
    #: What it is about, for the report.
    about: str
    turns: tuple[Say, ...]
    check: Check
    seed: Seed | None = None
    #: The harness taps Approve on every held card, as a person would. Off for a
    #: conversation about saying yes in words instead, where the card is left for
    #: the "yes" to approve.
    taps: bool = True


def _seed(world: World, title: str, day: date, hhmm: str, mins: int = 60, leader: str = "") -> None:
    from luach.calendar import times
    from luach.calendar.client import Event

    start = datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time())
    end = start + timedelta(minutes=mins)
    s, e = times.span(
        start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes"), TZ
    ).as_google(TZ)
    eid = f"seed{len(world.calendar.events)}"
    world.calendar.events[eid] = Event(
        id=eid, title=title, start=s["dateTime"], end=e["dateTime"], leader=leader
    )


# --- the conversations --------------------------------------------------------


def _check_move_it(w: World) -> list[str]:
    tue = w.day(1)
    out = one(w, ("dentist",), tue, "16:30", "dentist")
    found = w.events("dentist")
    if found and "insurance" not in (found[0].description + found[0].location).casefold():
        out.append("dentist: the insurance card note is not on it")
    out += one(w, ("piano",), tue, "17:00", "piano (untouched)")
    return out


def _seed_move_it(w: World) -> None:
    _seed(w, "Piano", w.day(1), "17:00", leader="ruby")


def _check_no_thursday(w: World) -> list[str]:
    # Said on a Wednesday, "wednesday" is next week's; "no, thursday" is either
    # tomorrow or the day after the Wednesday it corrects. Both are fair readings,
    # and the reply says which day it took.
    out = one(w, ("swim", "natación"), w.day(3), "17:00", "swim")
    if out and w.day(2) == w.today + timedelta(days=7):
        out = one(w, ("swim", "natación"), w.day(3, weeks=1), "17:00", "swim") and out
    found = w.events("swim")
    if len(found) == 1:
        if found[0].leader != "ruby":
            out.append(f"swim: for {found[0].leader!r}, wanted ruby")
        if minutes(found[0]) != 45:
            out.append(f"swim: {minutes(found[0])} minutes, wanted 45")
    return out


def _seed_the_one_with(w: World) -> None:
    sat = w.day(5)
    _seed(w, "Lunch with Maya", sat, "12:00")
    _seed(w, "Coffee with Dana", sat, "15:00")


def _check_the_one_with(w: World) -> list[str]:
    out = one(w, ("maya",), w.day(6), "12:00", "lunch with Maya (moved to Sunday)")
    if w.events("dana"):
        out.append("coffee with Dana: still there, wanted it cancelled")
    return out


def _check_said_once(w: World) -> list[str]:
    found = sorted(w.events("piano"), key=lambda e: e.start)
    mon = w.day(0)
    out: list[str] = []
    two = [when(e) for e in found] == [(mon, "16:00"), (mon + timedelta(weeks=1), "16:00")]
    # One lesson made weekly ("and the same the monday after") is as good as two.
    weekly = (
        len(found) == 1
        and when(found[0]) == (mon, "16:00")
        and any("FREQ=WEEKLY" in r for r in found[0].recurrence)
    )
    if not (two or weekly):
        out.append(f"piano: {[when(e) for e in found]}, wanted two Mondays at 16:00")
    for e in found:
        if "elm" not in (e.location + e.description).casefold():
            out.append(f"piano {when(e)[0]}: no 14 Elm Street (location {e.location!r})")
    return out


def _seed_follow_up(w: World) -> None:
    tomorrow = w.today + timedelta(days=1)
    _seed(w, "Orthodontist", tomorrow, "09:00", 45)
    _seed(w, "Team meeting", tomorrow, "14:00")
    _seed(w, "Haircut", tomorrow + timedelta(days=1), "11:00", 30)


def _check_follow_up(w: World) -> list[str]:
    tomorrow = w.today + timedelta(days=1)
    out = one(w, ("orthodont",), tomorrow + timedelta(days=1), "10:00", "orthodontist")
    out += one(w, ("team meeting",), tomorrow, "14:00", "team meeting (untouched)")
    out += one(w, ("haircut",), tomorrow + timedelta(days=1), "11:00", "haircut (untouched)")
    return out


def _check_spanish(w: World) -> list[str]:
    found = sorted(w.events("fútbol", "futbol", "football", "soccer"), key=lambda e: e.start)
    got = [when(e) for e in found]
    want = [(w.day(5), "11:00"), (w.day(6), "11:00")]
    out = [] if got == want else [f"fútbol: {got}, wanted {want}"]
    out += [f"fútbol {when(e)[0]}: for {e.leader!r}" for e in found if e.leader != "lily"]
    return out


def _check_hebrew(w: World) -> list[str]:
    return one(w, ("רופא", "שיניים", "dentist"), w.day(1), "17:00", "dentist")


def _check_long_thread(w: World) -> list[str]:
    out = one(w, ("parent", "teacher", "הורים"), w.day(3), "19:00", "parent-teacher meeting")
    out += one(w, ("yoga",), w.day(5), "09:00", "yoga (untouched)")
    return out


def _check_memory_next_day(w: World) -> list[str]:
    out = one(w, ("haircut",), w.day(2), "14:00", "haircut")
    if not any("tuesday" in f.casefold() for f in w.facts.get(MEMBER, [])):
        out.append(f"no Tuesday fact remembered: {w.facts.get(MEMBER)}")
    return out


def _check_memory_change(w: World) -> list[str]:
    out: list[str] = []
    facts = w.facts.get(MEMBER, [])
    if any(re.search(r"\bonly\b.*morning|morning.*\bonly\b", f, re.I) for f in facts):
        out.append(f"still remembers mornings-only: {facts}")
    if len(facts) > 2:
        out.append(f"over-remembered: {facts}")
    out += one(w, ("vet",), w.day(3), "15:00", "vet")
    out += one(w, ("dentist",), w.day(4), "11:00", "dentist")
    if w.facts.get(OTHER):
        out.append(f"{OTHER} has facts she never said: {w.facts[OTHER]}")
    return out


def _check_yes_to_a_card(w: World) -> list[str]:
    return one(w, ("lunch",), w.day(5), "12:00", "lunch with Ana")


def _check_yes_to_a_question(w: World) -> list[str]:
    return one(w, ("sister", "hermana", "visit"), w.day(6), "16:00", "the sister's visit")


def _seed_yes_to_a_move(w: World) -> None:
    _seed(w, "Dentist", w.day(1), "15:00")


def _check_yes_to_a_move(w: World) -> list[str]:
    return one(w, ("dentist",), w.day(2), "15:00", "dentist (moved to Wednesday)")


CONVERSATIONS: tuple[Conversation, ...] = (
    Conversation(
        "move_it",
        "an event, a detour, then 'it' and a detail",
        (
            Say("add a dentist appointment for me on tuesday at 3pm"),
            Say("thanks!"),
            Say("actually move it to 4:30"),
            Say("and add a note to bring the insurance card"),
            Say("what time is it at again?", reply_has=r"4:30|16:30"),
        ),
        _check_move_it,
        _seed_move_it,
    ),
    Conversation(
        "no_thursday",
        "a correction, then a change to what was corrected",
        (
            Say("add swim for Ruby on wednesday at 5pm"),
            Say("no, thursday"),
            Say("how long is it?"),
            Say("make it 45 minutes"),
        ),
        _check_no_thursday,
    ),
    Conversation(
        "the_one_with",
        "a list, then 'the one with Maya' and 'the other one'",
        (
            Say("what's on saturday?"),
            Say("move the one with Maya to sunday, same time"),
            Say("and cancel the other one"),
            Say("perfect, thanks"),
        ),
        _check_the_one_with,
        _seed_the_one_with,
    ),
    Conversation(
        "said_once",
        "a fact said once, needed three turns later",
        (
            Say("Ruby's piano lessons are at 14 Elm Street, with Mrs Klein"),
            Say("what's on friday?"),
            Say("lol ok"),
            Say("add a piano lesson for Ruby on monday at 4pm"),
            Say("and the same the monday after"),
        ),
        _check_said_once,
    ),
    Conversation(
        "follow_up",
        "follow-ups on an answer: 'the first one', 'that'",
        (
            Say("what's on tomorrow?"),
            Say("and the day after?"),
            Say("move the first one from tomorrow to the day after at 10am"),
            Say("does that clash with anything?", reply_lacks=r"\bclash(es)? with the haircut"),
        ),
        _check_follow_up,
        _seed_follow_up,
    ),
    Conversation(
        "spanish",
        "a correction and 'the same time' in Spanish",
        (
            Say("añade fútbol para Lily el sábado a las 10"),
            Say("no, a las 11"),
            Say("y también el domingo a la misma hora"),
            Say("gracias!"),
            Say("¿a qué hora es el del domingo?", reply_has=r"11"),
        ),
        _check_spanish,
    ),
    Conversation(
        "hebrew",
        "'move it' in Hebrew",
        (
            Say("תוסיף לי רופא שיניים ביום שלישי ב-3 אחרי הצהריים"),
            Say("תודה"),
            Say("תזיז את זה ל-5"),
        ),
        _check_hebrew,
    ),
    Conversation(
        "long_thread",
        "the first thing of a ten-turn thread, asked for at the end",
        (
            Say("add a parent-teacher meeting for me on thursday at 6pm"),
            Say("what's on tomorrow?"),
            Say("am I free friday at 4?"),
            Say("hello"),
            Say("add yoga for me on saturday at 9am"),
            Say("what's on sunday?"),
            Say("thanks"),
            Say("what about this week?"),
            Say("lol ok"),
            Say("move the first thing I added today to 7pm"),
        ),
        _check_long_thread,
    ),
    Conversation(
        "memory_next_day",
        "a rule said in one thread, needed in the next",
        (
            Say("I can never do appointments on Tuesdays, please remember that"),
            Say("thanks"),
            Say(
                "book a haircut for me next week, tuesday at 2pm",
                new_thread=True,
                reply_has=r"tuesday|martes|שלישי",
            ),
            Say("oh right, make it wednesday then"),
        ),
        _check_memory_next_day,
    ),
    Conversation(
        "memory_change",
        "a rule, a one-off change, the rule changed, another member asks",
        (
            Say("I only book appointments in the morning"),
            Say("add a dentist for me on friday at 10am"),
            Say("actually make it 11"),
            Say("I can do afternoons now too", new_thread=True),
            Say("add a vet visit for me on thursday at 3pm", new_thread=True),
            Say(
                "what do you remember about me?",
                new_thread=True,
                member=OTHER,
                reply_lacks=r"dentist|vet\b|book appointments",
            ),
        ),
        _check_memory_change,
    ),
    # A yes in words, where the harness does not tap: what a family types after
    # "shall I…?" or under a held card has to keep doing what it did.
    Conversation(
        "yes_to_a_card",
        "a held event, then 'yes'",
        (
            Say("put lunch with Ana on saturday, around noon I think"),
            Say("yes"),
            Say("thanks!", reply_lacks=r"waiting for (your )?approval"),
        ),
        _check_yes_to_a_card,
        taps=False,
    ),
    Conversation(
        "yes_to_a_question",
        "'should we put it on?', then 'yes'",
        (
            Say("my sister might come over on sunday at 4pm, should we put it on the calendar?"),
            Say("yes"),
            Say("thanks!", reply_lacks=r"waiting for (your )?approval"),
        ),
        _check_yes_to_a_question,
        taps=False,
    ),
    Conversation(
        "yes_to_a_move",
        "a held move of an event this thread did not make, then 'yes'",
        (
            Say("move my dentist to wednesday, same time"),
            Say("yes"),
            Say("thanks!", reply_lacks=r"waiting for (your )?approval"),
        ),
        _check_yes_to_a_move,
        _seed_yes_to_a_move,
        taps=False,
    ),
)


# --- running them -------------------------------------------------------------


@dataclass
class Scored:
    conversation: Conversation
    problems: list[str]
    replies: list[str]
    tools: list[list[str]]
    error: str = ""

    @property
    def passed(self) -> bool:
        return not self.problems and not self.error


def _isolate(memory_dsn: str) -> dict[str, int]:
    """A throwaway database, a fake calendar, two grown-ups and two children,
    and a memory of this run's own."""
    from luach import memory
    from luach.agent import mail_evals
    from luach.auth import users

    robin = mail_evals._isolate()
    ana = users.create_user(OTHER, "ana@example.com", "a long eval password", display_name="Ana")
    if memory_dsn:
        os.environ["LUACH_MEMORY_DSN"] = memory_dsn
        os.environ["LUACH_MEMORY_TABLE"] = f"evals_facts_{os.getpid()}"
        memory.reset()
    else:
        from tulip.memory.store import InMemoryStore

        os.environ["LUACH_MEMORY_DSN"] = "postgresql://in-memory/evals"
        memory.set_store(InMemoryStore())
    return {MEMBER: robin, OTHER: int(ana.id)}


async def _clear_facts(members: dict[str, int]) -> None:
    from luach import memory

    for name, uid in members.items():
        found = await memory.recall(uid, name)
        for f in found["facts"]:
            await memory.forget(uid, name, f["key"])


async def run_conversation(conv: Conversation, members: dict[str, int]) -> Scored:
    from luach import memory
    from luach.agent import pending, runtime
    from luach.calendar import client, times

    await _clear_facts(members)
    cal = client.FakeCalendar()
    client.set_calendar(cal)
    world = World(calendar=cal, today=times.now_in(TZ).date())
    if conv.seed:
        conv.seed(world)
    problems: list[str] = []
    thread: str | None = None
    try:
        for n, step in enumerate(conv.turns, 1):
            if step.new_thread:
                thread = None
            result = await runtime.run_turn(
                step.text,
                user_id=members[step.member],
                principal=step.member,
                timezone=TZ,
                thread_id=thread,
                calendar=cal,
            )
            thread = result.thread_id
            reply = result.reply or ""
            world.replies.append(reply)
            world.tools.append([c.get("tool", "") for c in result.tool_calls])
            # luach holds a change to an event this thread did not make, and a
            # likely duplicate, for a yes. A person taps Approve; so does this,
            # and the conversation goes on from a calendar that has it — what is
            # scored is whether the right change was proposed, not the gate.
            for held in result.held if conv.taps else []:
                if "possible-duplicate" in held.get("reason", []):
                    # A person turns down a second copy of what they just added.
                    pending.deny(held["id"], by=step.member, viewer_id=members[step.member])
                    world.tools[-1].append("denied")
                    continue
                pending.approve(
                    held["id"],
                    by=step.member,
                    timezone=TZ,
                    calendar=cal,
                    viewer_id=members[step.member],
                )
                world.tools[-1].append("approved")
            if step.reply_has and not re.search(step.reply_has, reply, re.I):
                problems.append(f"turn {n}: reply lacks /{step.reply_has}/: {reply[:120]!r}")
            if step.reply_lacks and re.search(step.reply_lacks, reply, re.I):
                problems.append(f"turn {n}: reply has /{step.reply_lacks}/: {reply[:120]!r}")
            if result.error:
                problems.append(f"turn {n}: error {result.error}")
    except Exception as exc:  # a broken turn is a failed conversation, not a crash
        logger.exception("conversation %s failed", conv.name)
        return Scored(conv, problems, world.replies, world.tools, error=repr(exc)[:200])
    for name, uid in members.items():
        found = await memory.recall(uid, name)
        world.facts[name] = [f["fact"] for f in found["facts"]]
    problems += conv.check(world)
    return Scored(conv, problems, world.replies, world.tools)


def report(results: list[Scored], verbose: bool = False) -> str:
    out: list[str] = []
    for r in results:
        out.append(f"{'PASS' if r.passed else 'FAIL'} {r.conversation.name}")
        if r.error:
            out.append(f"     error: {r.error}")
        for p in r.problems:
            out.append(f"     {p}")
        if verbose or not r.passed:
            for say, reply, tools in zip(r.conversation.turns, r.replies, r.tools, strict=False):
                out.append(f"     > {say.text}")
                out.append(f"       [{', '.join(tools)}] {reply[:160]!r}")
    out.append("")
    out.append(f"conversations {sum(r.passed for r in results)}/{len(results)} passed")
    return "\n".join(out)


async def run(
    only: str = "", repeat: int = 1, memory_dsn: str = "", verbose: bool = False
) -> list[Scored]:
    members = _isolate(memory_dsn)
    picked = [c for c in CONVERSATIONS if only in c.name]
    results = []
    for _ in range(repeat):
        for conv in picked:
            results.append(await run_conversation(conv, members))
    print(report(results, verbose))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", default="", help="run the conversations whose name holds this")
    parser.add_argument("--repeat", type=int, default=1, help="run each this many times")
    parser.add_argument("--memory-dsn", default="", help="a pgvector Postgres for memory")
    parser.add_argument("-v", "--verbose", action="store_true", help="print every turn")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    results = asyncio.run(run(args.only, args.repeat, args.memory_dsn, args.verbose))
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
