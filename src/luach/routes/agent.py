"""Talking to luach: streamed for the web, one JSON for a trusted service and mail."""

from __future__ import annotations

import asyncio
import contextvars
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from luach import config, db
from luach.agent import runtime
from luach.agent.pending import SCAN_DOOR
from luach.routes.shared import body, error, frame, require_caller, require_member, text_field

router = APIRouter(prefix="/api")

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

#: A quiet stream is a stream something in the middle will close. Between the
#: browser and this process sit a reverse proxy and often a tunnel or CDN, and
#: a turn can think, or sit inside one slow tool, for longer than any of them
#: will wait. Well under the shortest of those idle timeouts.
KEEPALIVE_SECONDS = 15

THREAD_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


async def _kept_alive(frames: AsyncIterator[dict[str, Any]]) -> AsyncIterator[str]:
    """The turn's frames, with a comment line whenever it goes quiet.

    A line beginning with ':' is an SSE comment: the browser's parser and ours
    (web/src/lib/sse.ts) both skip it, so it costs the conversation nothing and
    keeps every hop from deciding the connection is dead.
    """
    it = frames.__aiter__()
    # Every step of the turn runs in one context. A task copies the context it
    # starts in, so a task per step would each get a fresh copy, and what the turn
    # set in its first step (whose calendar, which member: agent/context.py) would
    # be gone by the step that runs a tool — every calendar tool failed that way
    # from the web chat with "no turn context", while greetings,
    # which read nothing, went on working.
    ctx = contextvars.copy_context()
    loop = asyncio.get_running_loop()

    def step() -> asyncio.Future[dict[str, Any]]:
        return loop.create_task(it.__anext__(), context=ctx)  # type: ignore[arg-type]

    nxt = step()
    try:
        while True:
            try:
                f = await asyncio.wait_for(asyncio.shield(nxt), KEEPALIVE_SECONDS)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            except StopAsyncIteration:
                return
            nxt = step()
            yield frame(f)
    finally:
        nxt.cancel()


def _turn_kwargs(data: dict) -> dict:
    c = require_caller()
    member = require_member()
    text = text_field(data, "text", max_len=8000)
    thread_id = text_field(data, "thread_id", required=False, max_len=64) or None
    # A caller may name a new conversation (an unknown id starts one), but the
    # name is an id: it goes into paths and the checkpointer's file names.
    if thread_id and not THREAD_ID.fullmatch(thread_id):
        raise error(400, "thread_id is letters, digits, - and _ (at most 64)")
    # Refused before a stream starts, so it is a status, not a 200 with an
    # error inside it.
    if thread_id and not runtime.thread_belongs(thread_id, member.id):
        raise error(403, "that thread belongs to someone else")
    return {
        "text": text,
        "user_id": member.id,
        "principal": c.principal if c.via_key else member.username,
        "timezone": member.timezone,
        "language": member.language,
        "door": c.door,
        "thread_id": thread_id,
        # Only the service key may say the human already agreed. The agent platform's
        # key never can: the platform holds its own approvals before it calls, and
        # luach's gate still decides.
        "approved": bool(data.get("approved")) and c.via_key and not c.restricted,
        "consent_by_words": not c.restricted,
        # A model the person picked from the menu; "" is the household's own.
        "model": text_field(data, "model", required=False, max_len=128),
    }


@router.post("/agent/stream")
async def agent_stream(request: Request) -> StreamingResponse:
    kwargs = _turn_kwargs(await body(request))

    return StreamingResponse(
        _kept_alive(runtime.stream_turn(**kwargs)),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/agent")
async def agent_sync(request: Request) -> dict:
    kwargs = _turn_kwargs(await body(request))
    result = await runtime.run_turn(**kwargs)
    return result.as_dict()


@router.get("/threads")
def threads(limit: int = 50, before: str = "") -> dict:
    """This member's conversations, most recently spoken to first.

    Scoped to the caller: a household shares a calendar and does
    not share what each person has been asking about it. A page at a time:
    `more` says there are older ones, and `before` (the last `updated_at`)
    fetches them. It was a silent fifty.
    """
    member = require_member()
    limit = max(1, min(limit, 200))
    # The email scan's turns are conversations nobody had: each proposal is shown under
    # Pending with its email, and a thread per message read buried the real ones.
    query = select(db.Thread).where(db.Thread.user_id == member.id, db.Thread.door != SCAN_DOOR)
    if before:
        try:
            cursor = datetime.fromisoformat(before)
        except ValueError as exc:
            raise error(400, "before must be an updated_at from the list") from exc
        if cursor.tzinfo:
            cursor = cursor.astimezone(UTC).replace(tzinfo=None)
        query = query.where(db.Thread.updated_at < cursor)
    with db.session() as s:
        rows = (
            s.execute(query.order_by(db.Thread.updated_at.desc()).limit(limit + 1)).scalars().all()
        )
        more, rows = len(rows) > limit, rows[:limit]
        # One query for the counts, and only of these threads — it counted
        # every member's turns on every page load of the rail.
        rows_counted = s.execute(
            select(db.Turn.thread_id, func.count(db.Turn.id))
            .where(db.Turn.thread_id.in_([t.id for t in rows]))
            .group_by(db.Turn.thread_id)
        ).all()
        counts: dict[str, int] = dict(rows_counted)  # type: ignore[arg-type]
    return {
        "threads": [
            {
                "id": t.id,
                "title": t.title or "New conversation",
                "door": t.door,
                "turns": counts.get(t.id, 0),
                "created_at": db.iso(t.created_at),
                "updated_at": db.iso(t.updated_at),
            }
            for t in rows
        ],
        "more": more,
        "retention_days": config.thread_retention_days(),
    }


@router.get("/threads/{thread_id}")
def thread(thread_id: str) -> dict:
    member = require_member()
    with db.session() as s:
        t = s.get(db.Thread, thread_id)
        if t is None or t.user_id != member.id:
            raise error(404, "no such conversation")
        turns = (
            s.execute(select(db.Turn).where(db.Turn.thread_id == thread_id).order_by(db.Turn.id))
            .scalars()
            .all()
        )
    return {
        "id": thread_id,
        "turns": [
            {
                "role": u.role,
                "content": u.content,
                "events": db.loads(u.events_json, []),
                "created_at": db.iso(u.created_at),
            }
            for u in turns
        ],
    }


@router.delete("/threads/{thread_id}")
async def delete_thread(thread_id: str) -> dict:
    member = require_member()
    with db.session() as s:
        t = s.get(db.Thread, thread_id)
        if t is None or t.user_id != member.id:
            raise error(404, "no such conversation")
        s.delete(t)
    # The transcript and the state the model resumes from are two different
    # places. Deleting one is not deleting the conversation.
    await runtime.forget_thread(thread_id)
    return {"ok": True}


@router.patch("/threads/{thread_id}")
async def rename_thread(thread_id: str, request: Request) -> dict:
    """A conversation is found again by its name, and the first thing somebody
    typed is rarely what the conversation turned out to be about."""
    member = require_member()
    data = await body(request)
    title = runtime.thread_title(text_field(data, "title", max_len=200))
    with db.session() as s:
        t = s.get(db.Thread, thread_id)
        if t is None or t.user_id != member.id:
            raise error(404, "no such conversation")
        t.title = title
        return {"id": thread_id, "title": title}
