"""Tasks by person. Anyone in the family ticks; the grown-ups decide."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from luach import tasks
from luach.agent.control import trail
from luach.calendar import times
from luach.routes.shared import RowId, body, error, require_member

router = APIRouter(prefix="/api/tasks")


def _today(tz: str) -> str:
    return times.now_in(tz).date().isoformat()


def _fields(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("title", "person", "due", "notes"):
        if key in data:
            if data[key] is not None and not isinstance(data[key], str):
                raise error(400, f"{key} must be a string")
            out[key] = data[key] or ""
    if "days" in data:
        raw = data["days"]
        if isinstance(raw, list) and all(isinstance(d, str) for d in raw):
            out["days"] = ",".join(raw)
        elif isinstance(raw, str):
            out["days"] = raw
        else:
            raise error(400, "days is a list like ['MO','TH']")
    return out


def _guarded(fn: Any) -> Any:
    try:
        return fn()
    except tasks.NotAllowed as exc:
        raise error(403, str(exc)) from exc
    except KeyError as exc:
        raise error(404, "no such task") from exc
    except ValueError as exc:
        raise error(400, str(exc)) from exc


@router.get("")
def day(day: str = "", person: str = "") -> dict:
    member = require_member()
    when = day or _today(member.timezone)
    listed = _guarded(lambda: tasks.for_day(when, person))
    return {
        "day": when[:10],
        "tasks": [t.as_dict() for t in listed],
        "may_assign": tasks.may_assign(member.id),
    }


@router.get("/all")
def every() -> dict:
    member = require_member()
    listed = tasks.every(_today(member.timezone))
    return {"tasks": [t.as_dict() for t in listed], "may_assign": tasks.may_assign(member.id)}


@router.post("")
async def add(request: Request) -> dict:
    member = require_member()
    f = _fields(await body(request))
    t = _guarded(
        lambda: tasks.add(
            f.get("title", ""),
            by=member.id,
            person=f.get("person", ""),
            due=f.get("due", ""),
            days=f.get("days", ""),
            notes=f.get("notes", ""),
            today=_today(member.timezone),
        )
    )
    trail().record(
        "task.added", {"id": t.id, "title": t.title, "person": t.person, "by": member.username}
    )
    return dict(t.as_dict())


@router.patch("/{task_id}")
async def update(task_id: RowId, request: Request) -> dict:
    member = require_member()
    f = _fields(await body(request))
    if not f:
        raise error(400, "nothing to change")
    t = _guarded(lambda: tasks.update(task_id, by=member.id, today=_today(member.timezone), **f))
    trail().record("task.updated", {"id": task_id, "changes": f, "by": member.username})
    return dict(t.as_dict())


@router.delete("/{task_id}")
def remove(task_id: RowId) -> dict:
    member = require_member()
    _guarded(lambda: tasks.remove(task_id, by=member.id))
    trail().record("task.removed", {"id": task_id, "by": member.username})
    return {"ok": True}


@router.post("/{task_id}/done")
async def tick(task_id: RowId, request: Request) -> dict:
    member = require_member()
    data = await body(request)
    when = str(data.get("day") or _today(member.timezone))
    done = data.get("done", True) is not False
    t = _guarded(lambda: tasks.tick(task_id, when, done=done, by=member.username))
    trail().record(
        "task.ticked", {"id": task_id, "day": when[:10], "done": done, "by": member.username}
    )
    return dict(t.as_dict())
