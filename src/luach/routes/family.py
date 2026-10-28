"""The family: who events and tasks belong to. Everyone may see it; the owner
decides who is in it."""

from __future__ import annotations

from fastapi import APIRouter, Request

from luach import family
from luach.agent.control import trail
from luach.routes.shared import body, error, require_member, require_owner, text_field

router = APIRouter(prefix="/api/family")

_FIELDS = ("name", "kind", "color", "email", "position")


@router.get("")
def show() -> dict:
    require_member()
    return {
        "people": [p.as_dict() for p in family.roster()],
        "colors": [{"id": k, "name": n, "hex": h} for k, (n, h) in family.COLORS.items()],
    }


@router.post("")
async def add(request: Request) -> dict:
    owner = require_owner()
    data = await body(request)
    try:
        # text_field, not str(): str() turned {"a": 1} into a person called "{'a': 1}".
        person = family.add(
            text_field(data, "name", max_len=64),
            kind=text_field(data, "kind", required=False, max_len=8) or "adult",
            color=text_field(data, "color", required=False, max_len=2),
            email=text_field(data, "email", required=False, max_len=255),
        )
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    trail().record("family.added", {"key": person.key, "name": person.name, "by": owner.username})
    return person.as_dict()


@router.patch("/{key}")
async def update(key: str, request: Request) -> dict:
    owner = require_owner()
    data = await body(request)
    fields = {k: data[k] for k in _FIELDS if k in data}
    if not fields:
        raise error(400, "nothing to change")
    try:
        person = family.update(key, **fields)
    except KeyError as exc:
        raise error(404, "nobody in the family has that key") from exc
    except (ValueError, TypeError) as exc:
        raise error(400, str(exc)) from exc
    trail().record("family.updated", {"key": key, "changes": fields, "by": owner.username})
    return person.as_dict()


@router.delete("/{key}")
def remove(key: str) -> dict:
    owner = require_owner()
    try:
        family.remove(key)
    except KeyError as exc:
        raise error(404, "nobody in the family has that key") from exc
    trail().record("family.removed", {"key": key, "by": owner.username})
    return {"ok": True}
