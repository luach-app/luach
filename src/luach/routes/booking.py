"""Booking: the member's own settings, and the public page behind their link.

``/api/book/*`` is the only part of the API a stranger can reach, so it is
narrow on purpose: read the free slots, take one. Both are throttled by IP,
and taking one re-checks the slot against the calendar before it writes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import select

from luach import booking, busy, db, meetings, reminders
from luach.auth import throttle
from luach.routes.shared import RowId, body, client_ip, error, require_member, text_field

router = APIRouter()

#: Reading the page is cheap and ordinary — a visitor may open it, think, and
#: come back — so it is capped far above the sign-in throttle. Taking a slot
#: writes to the calendar and sends mail, so that keeps the strict default.
MAX_PAGE_READS = 60


def _view(member: Any, conf: dict[str, Any]) -> dict[str, Any]:
    return {
        **conf,
        "link": booking.link_for(conf["slug"]),
        "timezone": member.timezone,
        # The UI offers Zoom only when the box has credentials for it.
        "zoom_ready": meetings.configured(),
    }


@router.get("/api/booking")
def mine() -> dict[str, Any]:
    """The member's own booking settings, plus the link to share."""
    member = require_member()
    return _view(member, booking.settings_for(member.id))


@router.patch("/api/booking")
async def update(request: Request) -> dict[str, Any]:
    member = require_member()
    data = await body(request)
    if not data:
        raise error(400, "nothing to change")
    data.pop("zoom_ready", None)  # the server owns that one
    try:
        conf = booking.update(member.id, data)
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    return _view(member, conf)


@router.get("/api/booking/upcoming")
def upcoming() -> dict[str, Any]:
    """What the link has booked, soonest first."""
    member = require_member()
    now = datetime.now().astimezone().isoformat()
    with db.session() as s:
        rows = (
            s.execute(
                select(db.Booking)
                .where(db.Booking.user_id == member.id, db.Booking.cancelled_at.is_(None))
                .order_by(db.Booking.start)
            )
            .scalars()
            .all()
        )
    return {
        "bookings": [
            {
                "start": r.start,
                "day": r.day,
                "name": r.name,
                "email": r.email,
                "note": r.note,
                "event_id": r.event_id,
            }
            for r in rows
            if r.start >= now[:19] or r.day >= now[:10]
        ]
    }


@router.get("/api/reminders")
def reminder_settings() -> dict[str, Any]:
    return reminders.settings_for(require_member().id)


@router.patch("/api/reminders")
async def update_reminders(request: Request) -> dict[str, Any]:
    member = require_member()
    data = await body(request)
    if not data:
        raise error(400, "nothing to change")
    try:
        return reminders.update(member.id, data)
    except ValueError as exc:
        raise error(400, str(exc)) from exc


@router.get("/api/busy")
def busy_sources() -> dict[str, Any]:
    """The read-only calendars this member has luach watch for busy time."""
    return {"sources": busy.sources_for(require_member().id)}


@router.post("/api/busy")
async def add_busy_source(request: Request) -> dict[str, Any]:
    member = require_member()
    data = await body(request)
    try:
        return busy.add_source(
            member.id,
            text_field(data, "name", required=False, max_len=80),
            text_field(data, "url", max_len=2000),
            show_in_agenda=bool(data.get("show_in_agenda", True)),
        )
    except ValueError as exc:
        raise error(400, str(exc)) from exc


@router.patch("/api/busy/{source_id}")
async def update_busy_source(source_id: RowId, request: Request) -> dict[str, Any]:
    member = require_member()
    data = await body(request)
    # Only what a person may change, and anything else is refused as the other
    # settings routes refuse it. The body used to be splatted straight into the
    # call, so `{"user_id": 1}` reached the function's own arguments — a 500.
    allowed = ("enabled", "show_in_agenda", "name")
    if unknown := sorted(set(data) - set(allowed)):
        raise error(400, f"unknown setting {unknown[0]}")
    if not data:
        raise error(400, "nothing to change")
    changes = {k: data[k] for k in allowed if k in data}
    try:
        return busy.update_source(member.id, source_id, **changes)
    except ValueError as exc:
        raise error(404, str(exc)) from exc


@router.delete("/api/busy/{source_id}")
def remove_busy_source(source_id: RowId) -> dict[str, Any]:
    member = require_member()
    try:
        return {"ok": True, **busy.remove_source(member.id, source_id)}
    except ValueError as exc:
        raise error(404, str(exc)) from exc


@router.post("/api/busy/refresh")
def refresh_busy_sources() -> dict[str, Any]:
    """Read every feed again, now, rather than waiting for the timer."""
    member = require_member()
    read = busy.refresh_for(member.id)
    return {"read": read, "sources": busy.sources_for(member.id)}


@router.get("/api/book/{slug}")
def page(slug: str, request: Request) -> dict[str, Any]:
    ip = client_ip(request)
    if throttle.locked(f"book:{slug}", ip, MAX_PAGE_READS):
        raise error(429, "too many requests; try again in a few minutes")
    throttle.failed(f"book:{slug}", ip)  # the read counts too, or the cap never fires
    view = booking.public_view(slug)
    if view is None:
        raise error(404, "there is no booking page at that link")
    return view


@router.get("/api/book/{slug}/manage/{token}")
def manage(slug: str, token: str, request: Request) -> dict[str, Any]:
    """The meeting behind a confirmation link, and where else it could go."""
    ip = client_ip(request)
    if throttle.locked(f"manage:{slug}", ip, MAX_PAGE_READS):
        raise error(429, "too many requests; try again in a few minutes")
    throttle.failed(f"manage:{slug}", ip)
    try:
        return booking.manage_view(slug, token)
    except KeyError as exc:
        raise error(404, "that link does not match a meeting") from exc


def _manage_throttle(slug: str, ip: str) -> None:
    """Moving and cancelling count apart from booking, and apart from reading the
    manage page. They shared booking's cap, so a visitor whose attempts to book
    had failed could not then cancel the meeting they did have."""
    if wait := throttle.locked(f"change:{slug}", ip):
        raise error(429, "too many changes from here; try again later", retry_after=wait)
    throttle.failed(f"change:{slug}", ip)


@router.post("/api/book/{slug}/manage/{token}/cancel")
def cancel(slug: str, token: str, request: Request) -> dict[str, Any]:
    ip = client_ip(request)
    _manage_throttle(slug, ip)
    try:
        return booking.cancel(slug, token)
    except KeyError as exc:
        raise error(404, "that link does not match a meeting") from exc


@router.post("/api/book/{slug}/manage/{token}/move")
async def move(slug: str, token: str, request: Request) -> dict[str, Any]:
    ip = client_ip(request)
    _manage_throttle(slug, ip)
    data = await body(request)
    try:
        return booking.move(slug, token, text_field(data, "start", max_len=40))
    except KeyError as exc:
        raise error(404, "that link does not match a meeting") from exc
    except ValueError as exc:
        raise error(400, str(exc)) from exc


@router.post("/api/book/{slug}")
async def take(slug: str, request: Request) -> dict[str, Any]:
    ip = client_ip(request)
    if wait := throttle.locked(f"take:{slug}", ip):
        raise error(429, "too many bookings from here; try again later", retry_after=wait)
    data = await body(request)
    throttle.failed(f"take:{slug}", ip)  # every attempt counts towards the cap
    try:
        return booking.book(
            slug,
            text_field(data, "start", max_len=40),
            text_field(data, "name", max_len=120),
            text_field(data, "email", max_len=255),
            text_field(data, "note", required=False, max_len=500),
            text_field(data, "timezone", required=False, max_len=64),
        )
    except KeyError as exc:
        raise error(404, "there is no booking page at that link") from exc
    except ValueError as exc:
        raise error(400, str(exc)) from exc
