"""How a turn's tools run: off the event loop, and one at a time in the model's order."""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta

from tulip.tools import tool

from luach.agent import context
from luach.agent.tools import no_repeats
from luach.calendar.client import FakeCalendar

TZ = "America/New_York"


def _turn() -> context.Turn:
    turn = context.Turn(calendar=FakeCalendar(), user_id=1, principal="robin", timezone=TZ)
    context.set_turn(turn)
    return turn


async def test_a_slow_tool_does_not_hold_the_server():
    finished: dict[str, float] = {}

    @tool
    def slow_read(n: int) -> dict:
        """A read that takes a while, as a Google call does."""
        time.sleep(0.3)
        finished["read"] = time.monotonic()
        return {"n": n, "turn": context.current().principal}

    _turn()

    async def meanwhile() -> None:
        # The rest of the server: a few short waits, 0.1 s in all.
        for _ in range(5):
            await asyncio.sleep(0.02)
        finished["meanwhile"] = time.monotonic()

    result, _ = await asyncio.gather(no_repeats(slow_read).fn(n=1), meanwhile())
    # The rest of the server finished while the read was still waiting, rather
    # than after it — and the read still saw its own turn.
    assert finished["meanwhile"] < finished["read"]
    assert result == {"n": 1, "turn": "robin"}


async def test_one_replys_calls_run_one_at_a_time_in_the_order_written():
    seen: list[str] = []

    @tool
    def step(name: str) -> dict:
        """One step of a reply's several calls."""
        seen.append(f"start {name}")
        time.sleep(0.05)
        seen.append(f"end {name}")
        return {"ok": name}

    _turn()
    guarded = no_repeats(step)
    await asyncio.gather(guarded.fn(name="find"), guarded.fn(name="change"))
    assert seen == ["start find", "end find", "start change", "end change"]


async def test_weighing_a_write_does_not_hold_the_server():
    from luach.agent import tools
    from luach.calendar import times

    finished: dict[str, float] = {}

    class SlowCalendar(FakeCalendar):
        def list_events(self, *args, **kwargs):
            # The gate's duplicate check: a Google call, slow as one.
            time.sleep(0.3)
            return super().list_events(*args, **kwargs)

    turn = context.Turn(calendar=SlowCalendar(), user_id=1, principal="robin", timezone=TZ)
    context.set_turn(turn)
    create = next(t for t in tools.toolset("robin") if t.name == "create_event")
    start = (times.now_in(TZ) + timedelta(days=2)).strftime("%Y-%m-%dT15:00")

    async def write() -> dict:
        result = await create.fn(title="Dentist", start=start)
        finished["write"] = time.monotonic()
        return result

    async def meanwhile() -> None:
        for _ in range(5):
            await asyncio.sleep(0.02)
        finished["meanwhile"] = time.monotonic()

    result, _ = await asyncio.gather(write(), meanwhile())
    assert finished["meanwhile"] < finished["write"]
    # It was weighed and then done (or held) as before: the gate still decides.
    assert "created" in str(result) or "held_for_approval" in str(result)


def _the_next_clock_change(after) -> object:
    """The first day, after ``after``, on which the zone's offset is not the day before's."""
    from datetime import datetime as dt
    from zoneinfo import ZoneInfo

    day = after + timedelta(days=1)
    while True:
        noon = dt.combine(day, dt.min.time()).replace(hour=12, tzinfo=ZoneInfo(TZ))
        if noon.utcoffset() != (noon - timedelta(days=1)).utcoffset():
            return day
        day += timedelta(days=1)


async def test_a_time_is_the_members_clock_whatever_offset_was_copied_onto_it(calendar):
    # "Move it to Sunday, same time": the model copied Saturday's -04:00 onto the
    # Sunday winter time began, and noon was written as 11:00.
    from luach.agent.tools import create_event
    from luach.calendar import times

    sunday = _the_next_clock_change(times.now_in(TZ).date())
    saturday = sunday - timedelta(days=1)
    copied = times.parse_when(f"{saturday}T12:00", TZ).isoformat()[19:]  # Saturday's offset
    _turn().calendar = calendar
    context.current().approved = True
    made = await no_repeats(create_event).fn(title="Lunch", start=f"{sunday}T12:00:00{copied}")
    assert made["created"]["start"].startswith(f"{sunday}T12:00"), made
    assert times.wall_clock("2026-11-01T12:00:00Z") == "2026-11-01T12:00:00"
    assert times.wall_clock("2026-11-01") == "2026-11-01"


async def test_make_it_45_minutes_moves_only_the_end(calendar):
    # update_event with an end and no start answered "nothing to change"; the
    # model called it four more times and told the person it could not be done.
    from luach.agent.tools import create_event, update_event
    from luach.calendar import times

    day = times.now_in(TZ).date() + timedelta(days=2)
    _turn().calendar = calendar
    context.current().approved = True
    made = await no_repeats(create_event).fn(title="Swim", start=f"{day}T17:00")
    eid = made["created"]["id"]
    out = await no_repeats(update_event).fn(event_id=eid, end=f"{day}T17:45")
    assert out["updated"]["start"].startswith(f"{day}T17:00")
    assert out["updated"]["end"].startswith(f"{day}T17:45")
    assert "error" in await no_repeats(update_event).fn(event_id="nope", end=f"{day}T17:45")
