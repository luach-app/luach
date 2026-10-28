"""What luach remembers about you — yours to read, add to and take away.

Memory was reached only through the model's `remember` tool, so nobody could see
what luach believed about them, or remove a line that had stopped being true
short of arguing with the chat. These are the member's own facts only: the
tenant is their id (memory.py), the same boundary the tool uses.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from luach import memory
from luach.agent.control import trail
from luach.routes.shared import body, error, require_member, text_field

router = APIRouter(prefix="/api/memory")


def _available() -> None:
    if not memory.configured():
        raise error(503, "luach has no memory configured here")


def _listing(found: dict[str, Any]) -> dict[str, Any]:
    return {
        "facts": [
            {k: f.get(k, "") for k in ("key", "topic", "fact", "saved_at")}
            for f in found.get("facts", [])
        ]
    }


@router.get("")
async def mine() -> dict[str, Any]:
    member = require_member()
    _available()
    try:
        return _listing(await memory.everything(member.id, member.username))
    except memory.MemoryUnavailable as exc:
        raise error(503, f"luach's memory did not answer: {exc}") from exc


@router.post("")
async def add(request: Request) -> dict[str, Any]:
    member = require_member()
    _available()
    data = await body(request)
    fact = text_field(data, "fact", max_len=memory.MAX_FACT)
    topic = text_field(data, "topic", required=False, max_len=60)
    try:
        await memory.remember(member.id, member.username, fact, topic)
        found = await memory.everything(member.id, member.username)
    except memory.MemoryUnavailable as exc:
        raise error(503, f"luach's memory did not answer: {exc}") from exc
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    trail().record("memory.saved", {"by": member.username, "door": "ui"})
    return _listing(found)


@router.delete("/{key:path}")
async def remove(key: str) -> dict[str, Any]:
    member = require_member()
    _available()
    try:
        gone = await memory.forget(member.id, member.username, key)
        found = await memory.everything(member.id, member.username)
    except memory.MemoryUnavailable as exc:
        raise error(503, f"luach's memory did not answer: {exc}") from exc
    if not gone:
        raise error(404, "luach does not remember that")
    trail().record("memory.forgotten", {"key": key, "by": member.username, "door": "ui"})
    return {"ok": True, **_listing(found)}
