"""The house board's own door, and the owner's list of boards.

``/api/board/*`` is open at the wall and closed here: every call but pairing
must carry a board token or a member's session. A board token opens nothing
else; a member simply sees the same board on whatever they are holding.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Request

from luach import board, config, db, family, household, tasks
from luach.agent.control import trail
from luach.auth import users
from luach.auth.current import caller
from luach.calendar import times
from luach.calendar.client import get_calendar
from luach.routes.shared import RowId, body, error, require_owner, text_field

router = APIRouter()


@dataclass(frozen=True)
class _Viewer:
    #: The paired screen's name; "" for a member looking at it on their own device.
    board: str
    #: Who a tick is recorded as.
    by: str
    member: str = ""
    #: Whether this viewer may add, change and remove — a member always, a
    #: screen when the owner left it able to.
    can_edit: bool = False
    #: Whose authority a change runs under: the member, or for a screen the owner.
    user_id: int | None = None
    timezone: str = ""
    #: The language the screen speaks; a member's own device follows its browser.
    language: str = "auto"


def _viewer(request: Request) -> _Viewer:
    b = board.authenticate(request.headers.get(board.HEADER))
    if b is not None:
        return _Viewer(
            board=b.name,
            by=f"board:{b.name}",
            can_edit=bool(b.can_edit),
            user_id=db.owner_id(),
            timezone=config.timezone(),
            language=b.language or "auto",
        )
    c = caller()
    m = users.member(c.user_id) if c else None
    if m is not None:
        return _Viewer(
            board="",
            by=m.username,
            member=m.display_name,
            can_edit=True,
            user_id=m.id,
            timezone=m.timezone or config.timezone(),
        )
    raise error(401, "this screen is not a board any more; pair it again")


def _events(day: str, tz: str, people: list[family.Person]) -> list[dict[str, Any]]:
    s, _ = times.day_bounds(day, tz)
    _, e = times.day_bounds(day, tz)
    out = []
    for ev in get_calendar().list_events(s, e):
        found = family.leaders_for(ev, people)
        out.append(
            {
                "id": ev.id,
                "title": ev.title,
                "start": ev.start,
                "end": ev.end,
                "all_day": ev.all_day,
                "location": ev.location,
                # Every one of them, so it shows in each person's column.
                "leaders": [p.key for p in found],
                "leader": found[0].key if found else "",
                # What the board needs to know before it lets a finger move it:
                # someone else's invitation stays put, and one day of a series
                # is moved in the editor, not by dragging.
                "read_only": ev.read_only,
                "organizer": ev.organizer,
                "recurring": bool(ev.recurring_event_id or ev.recurrence),
                "calendar_id": ev.calendar_id,
            }
        )
    return out


def _said(exc: KeyError) -> str:
    # str() of a KeyError is its repr, quotes and all: a screen was told
    # "'no screen is waiting with that code'".
    return str(exc.args[0]) if exc.args else "not found"


# -- the screen ---------------------------------------------------------------


@router.post("/api/board/pair")
def pair() -> dict:
    try:
        return board.start_pairing()
    except ValueError as exc:
        raise error(429, str(exc)) from exc


@router.get("/api/board/pair/{code}")
def collect(code: str, request: Request) -> dict:
    try:
        token = board.collect(code, request.headers.get(board.PAIR_HEADER, ""))
    except KeyError as exc:
        raise error(404, _said(exc)) from exc
    return {"token": token} if token else {"waiting": True}


#: How far ahead the board can be paged: a month, for "what is on next week".
AHEAD_DAYS = 30


def _day_param(day: str, tz: str) -> str:
    today = times.now_in(tz).date()
    if not day:
        return today.isoformat()
    try:
        wanted = date.fromisoformat(day[:10])
    except ValueError as exc:
        raise error(400, "day is YYYY-MM-DD") from exc
    if not today <= wanted <= today + timedelta(days=AHEAD_DAYS):
        raise error(400, f"the board shows today and the {AHEAD_DAYS} days after it")
    return wanted.isoformat()


@router.get("/api/board/today")
def today(request: Request, day: str = "") -> dict:
    """One day of the family's board: today, or `day` up to a month ahead."""
    v = _viewer(request)
    tz = config.timezone()
    now = times.now_in(tz)
    day = _day_param(day, tz)
    tomorrow = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    people = family.roster()
    return {
        "board": v.board,
        "viewer": v.member,
        "can_edit": v.can_edit,
        "language": v.language,
        "timezone": tz,
        "now": now.isoformat(),
        "today": now.date().isoformat(),
        "day": day,
        "people": [{"key": p.key, "name": p.name, "hex": p.hex, "kind": p.kind} for p in people],
        "events": _events(day, tz, people),
        "tomorrow": _events(tomorrow, tz, people),
        "tasks": [t.as_dict() for t in tasks.for_day(day)],
    }


@router.post("/api/board/tasks/{task_id}/done")
async def tick(task_id: RowId, request: Request) -> dict:
    v = _viewer(request)
    data = await body(request)
    # The day on the screen: a chore ticked on Thursday's page is Thursday's.
    day = _day_param(text_field(data, "day", required=False, max_len=10), config.timezone())
    done = data.get("done", True) is not False
    try:
        t = tasks.tick(task_id, day, done=done, by=v.by)
    except KeyError as exc:
        raise error(404, "no such task") from exc
    trail().record("task.ticked", {"id": task_id, "day": day, "done": done, "by": v.by})
    return dict(t.as_dict())


# -- changing things from the board ---------------------------------------------
# A member always may; a paired screen when the owner left it able to. A screen
# acts with the owner's authority and is named on the audit trail as itself.
# Events go through the same code as the calendar API, so nothing the board
# writes can escape a check the form makes.


def _editor(request: Request) -> _Viewer:
    v = _viewer(request)
    if not v.can_edit:
        raise error(403, "this screen only shows the day; the owner can let it change things")
    return v


def _door(v: _Viewer) -> str:
    return "board" if v.board else "ui"


def _kiosk(v: _Viewer, data: dict[str, Any], *, creating: bool) -> dict[str, Any]:
    """What a paired screen may not send. It acts with the owner's authority, so an
    invitation typed at the wall would go out from the owner's calendar to any address
    anyone standing there chose: a screen invites nobody but the family people an event
    is for (family.stamp), and leaves an event's guests as they are."""
    if not v.board:
        return data
    data = {k: val for k, val in data.items() if k != "attendees"}
    if creating:
        data["attendees"] = []
    return data


def _for_screen(v: _Viewer, event: dict[str, Any]) -> dict[str, Any]:
    """An event as a paired screen sees it: no link out to Google Calendar (there it is
    whoever last signed in to that browser) and no guests' addresses on the wall."""
    if not v.board:
        return event
    return {k: val for k, val in event.items() if k not in ("html_link", "attendees")}


@router.get("/api/board/calendars")
def board_calendars(request: Request) -> dict:
    """The calendars the household uses, for the board's own event form: the member
    API's list is closed to a screen. Only those in use, and nothing about guests."""
    _viewer(request)
    snap = household.snapshot()
    enabled = set(snap["calendars"])
    return {
        "calendars": snap["calendars"],
        "default_calendar": snap["default_calendar"],
        "default_attendees": [],
        "available": [
            dict(c.as_dict(), enabled=True, default=c.id == snap["default_calendar"])
            for c in get_calendar().calendars()
            if c.id in enabled
        ],
    }


@router.post("/api/board/events")
async def add_event(request: Request) -> dict:
    from luach.routes import calendar as calendar_routes

    v = _editor(request)
    data = _kiosk(v, await body(request), creating=True)
    return _for_screen(
        v,
        calendar_routes.create_event(
            data, tz=v.timezone, user_id=v.user_id, by=v.by, door=_door(v)
        ),
    )


@router.patch("/api/board/events/{event_id}")
async def change_event(
    event_id: str, request: Request, calendar: str = "", scope: str = "this"
) -> dict:
    from luach.routes import calendar as calendar_routes

    v = _editor(request)
    data = _kiosk(v, await body(request), creating=False)
    return _for_screen(
        v,
        calendar_routes.update_event(
            event_id, data, tz=v.timezone, calendar=calendar, by=v.by, door=_door(v), scope=scope
        ),
    )


@router.delete("/api/board/events/{event_id}")
def remove_event(event_id: str, request: Request, calendar: str = "", scope: str = "this") -> dict:
    from luach.routes import calendar as calendar_routes

    v = _editor(request)
    return calendar_routes.delete_event(
        event_id, calendar=calendar, by=v.by, door=_door(v), scope=scope
    )


@router.get("/api/board/events/{event_id}")
def one_event(event_id: str, request: Request, calendar: str = "") -> dict:
    from luach.routes import calendar as calendar_routes

    v = _viewer(request)
    ev = get_calendar().get_event(event_id, calendar_routes.household_calendar(calendar))
    if ev is None:
        raise error(404, "no such event")
    return _for_screen(v, calendar_routes._with_leader(ev))


def _task_call(v: _Viewer, fn: Any) -> Any:
    try:
        return fn()
    except tasks.NotAllowed as exc:
        raise error(403, str(exc)) from exc
    except KeyError as exc:
        raise error(404, "no such task") from exc
    except ValueError as exc:
        raise error(400, str(exc)) from exc


@router.post("/api/board/tasks")
async def add_task(request: Request) -> dict:
    from luach.routes.tasks import _fields

    v = _editor(request)
    f = _fields(await body(request))
    if not (f.get("title") or "").strip():
        raise error(400, "title is required")
    today = times.now_in(v.timezone).date().isoformat()
    t = _task_call(v, lambda: tasks.add(by=v.user_id, today=today, **f))
    trail().record("task.added", {"id": t.id, "title": t.title, "person": t.person, "by": v.by})
    return dict(t.as_dict())


@router.patch("/api/board/tasks/{task_id}")
async def change_task(task_id: RowId, request: Request) -> dict:
    from luach.routes.tasks import _fields

    v = _editor(request)
    f = _fields(await body(request))
    if not f:
        raise error(400, "nothing to change")
    today = times.now_in(v.timezone).date().isoformat()
    t = _task_call(v, lambda: tasks.update(task_id, by=v.user_id, today=today, **f))
    trail().record("task.changed", {"id": task_id, "changes": f, "by": v.by})
    return dict(t.as_dict())


@router.delete("/api/board/tasks/{task_id}")
def remove_task(task_id: RowId, request: Request) -> dict:
    v = _editor(request)
    _task_call(v, lambda: tasks.remove(task_id, by=v.user_id))
    trail().record("task.removed", {"id": task_id, "by": v.by})
    return {"ok": True}


# -- the owner's list ---------------------------------------------------------


@router.get("/api/boards")
def list_boards() -> dict:
    require_owner()
    return {"boards": board.boards()}


@router.post("/api/boards")
async def claim(request: Request) -> dict:
    owner = require_owner()
    data = await body(request)
    code = text_field(data, "code", max_len=12)
    name = text_field(data, "name", required=False, max_len=60)
    try:
        made = board.claim(code, name)
    except KeyError as exc:
        raise error(404, _said(exc)) from exc
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    trail().record("board.paired", {**made, "by": owner.username})
    return made


@router.patch("/api/boards/{board_id}")
async def change_board(board_id: RowId, request: Request) -> dict:
    owner = require_owner()
    data = await body(request)
    name = text_field(data, "name", required=False, max_len=60) or None
    can_edit = data.get("can_edit")
    if can_edit is not None and not isinstance(can_edit, bool):
        raise error(400, "can_edit is true or false")
    language = data.get("language")
    if language is not None and language not in board.LANGUAGES:
        raise error(400, f"language is one of {', '.join(board.LANGUAGES)}")
    if name is None and can_edit is None and language is None:
        raise error(400, "nothing to change")
    try:
        board.update(board_id, name=name, can_edit=can_edit, language=language)
    except KeyError as exc:
        raise error(404, "no such board") from exc
    trail().record(
        "board.changed",
        {"id": board_id, "by": owner.username, "can_edit": can_edit, "language": language},
    )
    return {"boards": board.boards()}


@router.delete("/api/boards/{board_id}")
def remove(board_id: RowId) -> dict:
    owner = require_owner()
    try:
        board.remove(board_id)
    except KeyError as exc:
        raise error(404, "no such board") from exc
    trail().record("board.removed", {"id": board_id, "by": owner.username})
    return {"ok": True}
