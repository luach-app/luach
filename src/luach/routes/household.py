"""What the household shares: its calendars, the default one, and who is
invited to everything. Anyone may read; the owner decides."""

from __future__ import annotations

from fastapi import APIRouter, Request

from luach import household
from luach.agent.control import trail
from luach.calendar.client import get_calendar
from luach.routes.shared import body, error, require_member, require_owner

router = APIRouter(prefix="/api/household")


@router.get("")
def show() -> dict:
    require_member()
    return household.snapshot()


@router.get("/calendars")
def calendars() -> dict:
    """Every calendar the credential can see, flagged with what the household uses.
    Only the owner, who chooses them, sees the ones the household does not use: the
    credential's other calendars (a personal one, say) are not the household's."""
    member = require_member()
    snap = household.snapshot()
    enabled = set(snap["calendars"])
    return {
        "available": [
            dict(c.as_dict(), enabled=c.id in enabled, default=c.id == snap["default_calendar"])
            for c in get_calendar().calendars()
            if member.is_owner or c.id in enabled
        ],
        **snap,
    }


def _visible(fields: dict) -> None:
    """A calendar the household does not already use must be one the credential
    can see. Any id used to be stored, and new events then went to a calendar
    no listing reads — they vanished. Ids already in use stay allowed, so a
    calendar that is briefly missing from Google's list does not lock the
    owner out of their own settings."""
    wanted = [*fields.get("calendars", []), fields.get("default_calendar", "")]
    new = {c.strip() for c in wanted if c.strip()} - set(household.calendar_ids())
    if not new:
        return
    try:
        seen = {c.id for c in get_calendar().calendars()}
    except Exception as exc:
        raise error(502, "could not reach the calendar to check that one") from exc
    unknown = sorted(new - seen)
    if unknown:
        raise error(400, f"luach cannot see a calendar called {unknown[0]}")


@router.patch("")
async def update(request: Request) -> dict:
    owner = require_owner()
    data = await body(request)
    fields: dict = {}
    for key in ("calendars", "default_attendees"):
        if key in data:
            if not isinstance(data[key], list) or not all(isinstance(x, str) for x in data[key]):
                raise error(400, f"{key} must be a list of strings")
            fields[key] = data[key]
    if "default_calendar" in data:
        if not isinstance(data["default_calendar"], str):
            raise error(400, "default_calendar must be a string")
        fields["default_calendar"] = data["default_calendar"]
    if not fields:
        raise error(400, "nothing to change")
    _visible(fields)
    try:
        snap = household.update(**fields)
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    trail().record("household.updated", {"by": owner.username, "changes": fields})
    return snap
