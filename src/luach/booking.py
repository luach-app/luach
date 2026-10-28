"""Meetings people book with a member.

A member publishes weekly hours and a link. The page behind that link offers
only the slots where the household's calendars are free, never more than
``max_per_day`` bookings in one day, and never inside the notice period. A
booking writes a normal calendar event — on whichever of the household's
calendars the member chose — with the visitor and the member's "also notify"
addresses as attendees, so both sides get the invitation.

Settings live in the ``settings`` table, one row per member; the bookings
themselves are rows in ``bookings`` so the per-day cap survives a restart.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from luach import busy, db, household, mail_templates, meetings
from luach.agent.control import trail
from luach.auth import users
from luach.auth.tokens import new_token, token_hash
from luach.calendar import times
from luach.calendar.client import Draft, get_calendar

KEY_PREFIX = "booking."
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

logger = logging.getLogger(__name__)

MAX_HORIZON_DAYS = 120
MAX_SLOT_MINUTES = 480

DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "slug": "",
    "slot_minutes": 30,
    "max_per_day": 2,
    "buffer_minutes": 15,
    "lead_hours": 12,
    "horizon_days": 21,
    "calendar_id": "",  # "" = the household's default
    "notify_host": True,  # mail the member each time someone books
    "conferencing": "none",  # none | zoom — a Zoom link created per booking
    "title": "Meeting with {name}",
    "location": "",
    "note": "",
    "hours": {
        "mon": [["09:00", "17:00"]],
        "tue": [["09:00", "17:00"]],
        "wed": [["09:00", "17:00"]],
        "thu": [["09:00", "17:00"]],
        "fri": [["09:00", "17:00"]],
        "sat": [],
        "sun": [],
    },
}


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime

    def as_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


def _key(user_id: int) -> str:
    return f"{KEY_PREFIX}{user_id}"


def settings_for(user_id: int) -> dict[str, Any]:
    """What this member published, defaults filled in."""
    with db.session() as s:
        row = s.get(db.Setting, _key(user_id))
        stored = db.loads(row.value, {}) if row else {}
    out = {**DEFAULTS, "hours": {d: list(DEFAULTS["hours"][d]) for d in DAYS}}
    if isinstance(stored, dict):
        for k, v in stored.items():
            if k == "hours" and isinstance(v, dict):
                out["hours"] = {d: _clean_ranges(v.get(d, [])) for d in DAYS}
            elif k in DEFAULTS:
                out[k] = v
    if not out["slug"]:
        member = users.member(user_id)
        out["slug"] = member.username if member else ""
    return out


def _clean_ranges(raw: Any) -> list[list[str]]:
    out: list[list[str]] = []
    if not isinstance(raw, list):
        return out
    for pair in raw:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError('each window is a [start, end] pair like ["09:00", "17:00"]')
        a, b = str(pair[0]).strip(), str(pair[1]).strip()
        if not HHMM.match(a) or not HHMM.match(b):
            raise ValueError(f"{a or '?'}–{b or '?'} is not a HH:MM window")
        if b <= a:
            raise ValueError(f"the window {a}–{b} ends before it starts")
        out.append([a, b])
    return sorted(out)


def _int(value: Any, name: str, low: int, high: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a whole number") from exc
    if not low <= n <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return n


def update(user_id: int, changes: dict[str, Any]) -> dict[str, Any]:
    """Validate and store; returns the whole setting."""
    current = settings_for(user_id)
    for key, value in changes.items():
        if key == "enabled":
            current["enabled"] = bool(value)
        elif key == "slug":
            slug = str(value).strip().lower()
            if not SLUG.match(slug):
                raise ValueError("the link name is 2-40 chars: letters, digits and dashes")
            taken = by_slug(slug)
            if taken and taken[0] != user_id:
                raise ValueError("another member already uses that link name")
            current["slug"] = slug
        elif key == "slot_minutes":
            current["slot_minutes"] = _int(value, "the meeting length", 5, MAX_SLOT_MINUTES)
        elif key == "max_per_day":
            current["max_per_day"] = _int(value, "meetings per day", 1, 20)
        elif key == "buffer_minutes":
            current["buffer_minutes"] = _int(value, "the gap around meetings", 0, 240)
        elif key == "lead_hours":
            current["lead_hours"] = _int(value, "the notice period", 0, 720)
        elif key == "horizon_days":
            current["horizon_days"] = _int(value, "how far ahead", 1, MAX_HORIZON_DAYS)
        elif key == "conferencing":
            choice = str(value).strip().lower() or "none"
            if choice not in ("none", "zoom"):
                raise ValueError("conferencing is 'none' or 'zoom'")
            current["conferencing"] = choice
        elif key == "notify_host":
            current["notify_host"] = bool(value)
        elif key == "calendar_id":
            cid = str(value).strip()
            if cid and cid not in household.calendar_ids():
                raise ValueError("that calendar is not one of the household's")
            current["calendar_id"] = cid
        elif key in ("title", "location", "note"):
            current[key] = str(value).strip()[: 200 if key != "note" else 500]
        elif key == "hours":
            if not isinstance(value, dict):
                raise ValueError("hours is a map of weekday to windows")
            # A day that was not a list used to read as "no hours" and wipe it.
            for d, windows in value.items():
                if d not in DAYS:
                    raise ValueError(f"{d} is not a weekday; use {', '.join(DAYS)}")
                if not isinstance(windows, list):
                    raise ValueError(f'{d} is a list of windows like [["09:00", "17:00"]]')
            current["hours"] = {
                d: _clean_ranges(value.get(d, current["hours"].get(d, []))) for d in DAYS
            }
        else:
            raise ValueError(f"unknown setting {key!r}")
    if current["enabled"] and not any(current["hours"][d] for d in DAYS):
        raise ValueError("set at least one window of hours before publishing the link")
    with db.session() as s:
        row = s.get(db.Setting, _key(user_id))
        if row is None:
            s.add(db.Setting(key=_key(user_id), value=db.dumps(current), enabled=True))
        else:
            row.value = db.dumps(current)
            row.enabled = True
    return current


def by_slug(slug: str) -> tuple[int, dict[str, Any]] | None:
    slug = slug.strip().lower()
    if not slug:
        return None
    with db.session() as s:
        rows = s.execute(select(db.Setting).where(db.Setting.key.like(f"{KEY_PREFIX}%"))).scalars()
        candidates = [(int(r.key[len(KEY_PREFIX) :]), db.loads(r.value, {})) for r in rows]
    for user_id, stored in candidates:
        if isinstance(stored, dict) and str(stored.get("slug", "")).lower() == slug:
            return user_id, settings_for(user_id)
    # A member who never picked a link name is reachable by their username.
    found = users.member_by_username(slug)
    if found is not None:
        conf = settings_for(found.id)
        if conf["slug"] == slug:
            return found.id, conf
    return None


def link_for(slug: str) -> str:
    from luach import config

    return f"{config.app_url()}/book/{slug}"


# --- availability ----------------------------------------------------------


def _busy_from_feeds(user_id: int, day: date, tz: str) -> list[tuple[datetime, datetime]]:
    """What the member's read-only calendars say is taken — the work calendar
    luach cannot see into, but can see the shape of."""
    return busy.busy_spans(user_id, day, tz)


def _busy(
    day_start: datetime, day_end: datetime, skip: str = ""
) -> list[tuple[datetime, datetime]]:
    """Timed events on any of the household's calendars. All-day entries do not
    block: "Sara's birthday" is not a reason to refuse a meeting."""
    spans: list[tuple[datetime, datetime]] = []
    for ev in get_calendar().list_events(day_start, day_end):
        if ev.all_day or (skip and ev.id == skip):
            continue
        try:
            start = times.parse_when(ev.start, str(day_start.tzinfo))
            end = times.parse_when(ev.end, str(day_start.tzinfo)) if ev.end else start
        except ValueError:
            continue
        if isinstance(start, datetime) and isinstance(end, datetime):
            spans.append((start, end))
    return spans


def booked_on(user_id: int, day: str, ignoring: int | None = None) -> list[db.Booking]:
    """What still stands that day. A cancelled meeting frees its slot and stops
    counting towards the cap: calling one off must not punish the member.

    ``ignoring`` leaves one booking out — the one being moved. Without it a cap
    of one a day would mean a guest could never move their meeting to a better
    hour on the same day: it would be blocked by itself.
    """
    with db.session() as s:
        rows = (
            s.execute(
                select(db.Booking).where(
                    db.Booking.user_id == user_id,
                    db.Booking.day == day,
                    db.Booking.cancelled_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
        return [r for r in rows if ignoring is None or r.id != ignoring]


def _windows(conf: dict[str, Any], day: date, tz: str) -> list[tuple[datetime, datetime]]:
    zone = times.zone(tz)
    out = []
    for a, b in conf["hours"][DAYS[day.weekday()]]:
        ah, am = (int(x) for x in a.split(":"))
        bh, bm = (int(x) for x in b.split(":"))
        out.append(
            (
                datetime.combine(day, time(ah, am), tzinfo=zone),
                datetime.combine(day, time(bh, bm), tzinfo=zone),
            )
        )
    return out


def slots_for(
    user_id: int,
    conf: dict[str, Any] | None = None,
    *,
    ignoring: tuple[int, str] | None = None,
) -> list[dict[str, Any]]:
    """Every free slot from now to the horizon, grouped by day.

    ``ignoring`` is (booking id, event id) to leave out: the meeting being moved
    must not count against the day's cap, nor block its own hour.
    """
    conf = conf or settings_for(user_id)
    member = users.member(user_id)
    tz = member.timezone if member else "UTC"
    now = times.now_in(tz)
    earliest = now + timedelta(hours=int(conf["lead_hours"]))
    length = timedelta(minutes=int(conf["slot_minutes"]))
    gap = timedelta(minutes=int(conf["buffer_minutes"]))
    days: list[dict[str, Any]] = []
    for offset in range(int(conf["horizon_days"]) + 1):
        day = (now + timedelta(days=offset)).date()
        windows = _windows(conf, day, tz)
        if not windows:
            continue
        iso = day.isoformat()
        taken = booked_on(user_id, iso, ignoring[0] if ignoring else None)
        if len(taken) >= int(conf["max_per_day"]):
            continue
        day_start, day_end = times.day_bounds(iso, tz)
        # The household's own calendars, plus whatever the member's read-only
        # feeds say is taken — a work meeting is busy time like any other.
        occupied = _busy(
            day_start, day_end, skip=ignoring[1] if ignoring else ""
        ) + _busy_from_feeds(user_id, day, tz)
        free: list[Slot] = []
        for w_start, w_end in windows:
            cursor = w_start
            while cursor + length <= w_end:
                slot = Slot(cursor, cursor + length)
                if slot.start >= earliest and not _clashes(slot, occupied, gap):
                    free.append(slot)
                cursor += length
        if free:
            days.append({"day": iso, "slots": [s.as_dict() for s in free]})
    return days


def _clashes(slot: Slot, busy: list[tuple[datetime, datetime]], gap: timedelta) -> bool:
    return any(slot.start - gap < end and slot.end + gap > start for start, end in busy)


# --- booking ---------------------------------------------------------------


def public_view(slug: str) -> dict[str, Any] | None:
    found = by_slug(slug)
    if found is None:
        return None
    user_id, conf = found
    if not conf["enabled"]:
        return None
    member = users.member(user_id)
    if member is None:
        return None
    return {
        "host": member.display_name or member.username,
        "slug": conf["slug"],
        "timezone": member.timezone,
        "slot_minutes": conf["slot_minutes"],
        "note": conf["note"],
        "location": conf["location"],
        "days": slots_for(user_id, conf),
    }


def book(
    slug: str, start: str, name: str, email: str, note: str = "", timezone: str = ""
) -> dict[str, Any]:
    """Take a slot. Raises ValueError when it is no longer free."""
    found = by_slug(slug)
    if found is None:
        raise KeyError("no such booking page")
    user_id, conf = found
    if not conf["enabled"]:
        raise KeyError("no such booking page")
    member = users.member(user_id)
    if member is None:
        raise KeyError("no such booking page")
    email = email.strip().lower()
    name = name.strip()[:120]
    if not EMAIL.match(email):
        raise ValueError("that is not an email address")
    if not name:
        raise ValueError("tell them who you are")
    tz = member.timezone
    when = times.parse_when(start, tz)
    if not isinstance(when, datetime):
        raise ValueError("pick a time, not a whole day")
    day = when.date().isoformat()
    offered = {s["start"] for d in slots_for(user_id, conf) if d["day"] == day for s in d["slots"]}
    if when.isoformat() not in offered:
        raise ValueError("that time has just been taken; pick another")

    span = times.span(when.isoformat(), None, tz, default_minutes=int(conf["slot_minutes"]))
    title = str(conf["title"] or "Meeting with {name}").replace("{name}", name)[:200]
    description = f"Booked by {name} <{email}> through luach."
    if note:
        description += f"\n\n{note.strip()[:500]}"

    # Where to meet: a fresh Zoom link when the member asked for one, otherwise
    # whatever they wrote. A Zoom that will not answer costs the link, not the
    # booking, so the written location is the fallback rather than an error.
    where = conf["location"]
    zoom_id = ""
    if conf.get("conferencing") == "zoom":
        meeting = meetings.create_meeting(title, when, int(conf["slot_minutes"]), tz)
        if meeting is not None:
            where = meeting.join_url
            zoom_id = meeting.id
            description += f"\n\nZoom: {meeting.join_url}"
            if meeting.passcode:
                description += f" (passcode {meeting.passcode})"
        else:
            logger.warning("booking: no Zoom link for %s; falling back to the location", slug)
    draft = Draft(
        title=title,
        span=span,
        location=where,
        description=description,
        calendar_id=conf["calendar_id"] or household.default_calendar_id(),
        attendees=household.with_member([email], user_id),
    )
    event = get_calendar().insert(draft, tz)
    token = new_token()
    with db.session() as s:
        s.add(
            db.Booking(
                user_id=user_id,
                event_id=event.id,
                calendar_id=event.calendar_id,
                day=day,
                start=when.isoformat(),
                name=name,
                email=email,
                note=note.strip()[:500],
                token_hash=token_hash(token),
                zoom_id=zoom_id,
                timezone=_their_zone(timezone),
            )
        )
    from luach.agent.control import trail

    trail().record(
        "booking.created",
        {
            "id": event.id,
            "host": member.username,
            "by": f"{name} <{email}>",
            "start": event.start,
            "calendar": event.calendar_id,
            "door": "booking",
        },
    )
    confirmed = _confirm(
        member,
        event.start,
        tz,
        name,
        email,
        {**conf, "location": where},
        manage_link(slug, token),
        their_zone=_their_zone(timezone),
        invited=not event.invite_error,
    )
    return {
        "booked": True,
        "start": event.start,
        "end": event.end,
        "when": times.describe(span.start, span.end, tz),
        "host": member.display_name or member.username,
        "invite_error": event.invite_error,
        # The slot is taken either way; say so when the mail did not go, so the
        # page can tell the visitor rather than promise an inbox that stays empty.
        "confirmation_sent": confirmed,
        # What the visitor uses to move or call it off. Shown once, on the page
        # that took the booking, and mailed to them.
        "manage": manage_link(conf["slug"], token),
    }


def _their_zone(timezone: str) -> str:
    """Trust the browser's zone only if it names one we know."""
    name = timezone.strip()[:64]
    if not name:
        return ""
    try:
        ZoneInfo(name)
    except Exception:
        return ""
    return name


def manage_link(slug: str, token: str) -> str:
    from luach import config

    return f"{config.app_url()}/book/{slug}?manage={token}"


def _mailable(url: str) -> str:
    """A link fit for a mail: absolute, or none. Without LUACH_APP_URL the page
    still works from a relative link, but a mail client opens nothing."""
    from luach import config

    return url if config.app_url() else ""


def _confirm(
    member: users.Member,
    start: str,
    tz: str,
    name: str,
    email: str,
    conf: dict[str, Any],
    manage: str = "",
    their_zone: str = "",
    *,
    invited: bool = True,
) -> bool:
    """Tell both sides, each in their own hours. Returns whether the visitor's
    confirmation went out, and records a failure: a booking nobody was told
    about is worth knowing."""
    from luach import mailer

    if not mailer.configured():
        return False
    host = member.display_name or member.username
    when = times.describe(times.parse_when(start, tz), None, tz)
    # The visitor reads it where they live; the host's hours follow on a line of
    # their own when the two differ, so neither has to do the arithmetic.
    guest_zone = their_zone or tz
    guest_when = times.describe(times.parse_when(start, guest_zone), None, guest_zone)
    text, html = mail_templates.booking_confirmed(
        host,
        guest_when,
        guest_zone,
        conf["location"],
        _mailable(manage),
        host_when=f"{when} ({tz})" if guest_zone != tz else "",
        invited=invited,
    )
    sent = mailer.send(email, f"Confirmed: {guest_when} with {host}", text, html)
    told_host = True
    if conf.get("notify_host", True):
        text, html = mail_templates.booking_host_notice(
            "Booked",
            f"{name} booked {when}",
            f"{name} <{email}>",
            f"{when} ({tz})",
            conf["location"],
        )
        told_host = mailer.send(member.email, f"Booked: {name}, {when} ({tz})", text, html)
    if not sent or not told_host:
        trail().record(
            "booking.mail_failed",
            {"host": member.username, "guest": not sent, "host_copy": not told_host},
        )
    return sent


# --- changing one's mind ----------------------------------------------------


def _booking_by_token(token: str) -> db.Booking | None:
    with db.session() as s:
        return s.execute(
            select(db.Booking).where(db.Booking.token_hash == token_hash(token))
        ).scalar_one_or_none()


def manage_view(slug: str, token: str) -> dict[str, Any]:
    """What the visitor sees when they follow the link in their confirmation:
    the meeting as it stands, and the times it could move to."""
    row = _booking_by_token(token)
    found = by_slug(slug)
    if row is None or found is None or found[0] != row.user_id:
        raise KeyError("no such meeting")
    user_id, conf = found
    member = users.member(user_id)
    if member is None:
        raise KeyError("no such meeting")
    tz = member.timezone
    when = times.parse_when(row.start, tz)
    free = slots_for(user_id, conf, ignoring=(row.id, row.event_id))
    return {
        "host": member.display_name or member.username,
        "slug": conf["slug"],
        "timezone": tz,
        "slot_minutes": conf["slot_minutes"],
        "name": row.name,
        "start": row.start,
        "when": times.describe(when, None, tz),
        "their_timezone": row.timezone,
        "cancelled": row.cancelled_at is not None,
        "past": times.is_past(when, tz),
        # The slot it holds now is not on offer to anyone else, but it is not a
        # move either, so the list is simply what else is free.
        # Everything it could move to. Its own hour is left out: offering the
        # time they already hold as a choice reads like a mistake.
        "days": [] if row.cancelled_at else _without(free, row.start),
    }


def _without(days: list[dict[str, Any]], start: str) -> list[dict[str, Any]]:
    out = []
    for d in days:
        slots = [s for s in d["slots"] if s["start"] != start]
        if slots:
            out.append({"day": d["day"], "slots": slots})
    return out


def cancel(slug: str, token: str) -> dict[str, Any]:
    """Call it off: the calendar entry goes, the Zoom link goes, both sides hear."""
    row = _booking_by_token(token)
    found = by_slug(slug)
    if row is None or found is None or found[0] != row.user_id:
        raise KeyError("no such meeting")
    if row.cancelled_at is not None:
        return {"cancelled": True, "already": True}
    user_id, conf = found
    member = users.member(user_id)
    assert member is not None
    tz = member.timezone
    when = times.parse_when(row.start, tz)
    try:
        get_calendar().delete(row.event_id, row.calendar_id)
    except Exception:
        logger.exception("booking: could not remove the calendar entry for %s", row.event_id)
    if row.zoom_id:
        meetings.delete_meeting(row.zoom_id)
    with db.session() as s:
        live = s.get(db.Booking, row.id)
        if live is not None:
            live.cancelled_at = db.utcnow()
    _record("booking.cancelled", member, row, when, tz)
    host = member.display_name or member.username
    host_when, guest_when = _both_ways(when, tz, row, host)
    theirs = row.timezone or tz
    _tell_both(
        member,
        row,
        conf,
        subject=f"Cancelled: {guest_when} with {host}",
        guest=mail_templates.booking_cancelled(host, guest_when, theirs, by_guest=True),
        host_notice=("Cancelled", f"{row.name} cancelled {host_when}", f"{host_when} ({tz})"),
    )
    return {"cancelled": True}


def move(slug: str, token: str, start: str) -> dict[str, Any]:
    """Take a different slot, by the same rules a first booking obeys."""
    row = _booking_by_token(token)
    found = by_slug(slug)
    if row is None or found is None or found[0] != row.user_id:
        raise KeyError("no such meeting")
    if row.cancelled_at is not None:
        raise ValueError("that meeting was cancelled; book a new one")
    user_id, conf = found
    member = users.member(user_id)
    assert member is not None
    tz = member.timezone
    when = times.parse_when(start, tz)
    if not isinstance(when, datetime):
        raise ValueError("pick a time, not a whole day")
    if when.isoformat() == row.start:
        raise ValueError("that is when it already is")
    day = when.date().isoformat()
    free = slots_for(user_id, conf, ignoring=(row.id, row.event_id))
    offered = {s["start"] for d in free if d["day"] == day for s in d["slots"]}
    if when.isoformat() not in offered:
        raise ValueError("that time is not free; pick another")

    span = times.span(when.isoformat(), None, tz, default_minutes=int(conf["slot_minutes"]))
    changes: dict[str, Any] = {"start": span.start.isoformat(), "end": span.end.isoformat()}
    # A Zoom meeting moves with it rather than being replaced: the link the
    # visitor already has must keep working.
    if row.zoom_id and not meetings.move_meeting(row.zoom_id, when, int(conf["slot_minutes"]), tz):
        logger.warning("booking: the Zoom meeting for %s did not move", row.event_id)
    try:
        get_calendar().patch(row.event_id, changes, tz, row.calendar_id)
    except Exception as exc:
        raise ValueError("that meeting could not be moved") from exc
    with db.session() as s:
        live = s.get(db.Booking, row.id)
        if live is not None:
            live.start = when.isoformat()
            live.day = day
    _record("booking.moved", member, row, when, tz)
    host = member.display_name or member.username
    host_when, guest_when = _both_ways(when, tz, row, host)
    theirs = row.timezone or tz
    _tell_both(
        member,
        row,
        conf,
        subject=f"Moved: {guest_when} with {host}",
        guest=mail_templates.booking_moved(
            host, guest_when, theirs, _mailable(manage_link(slug, token))
        ),
        host_notice=("Moved", f"{row.name} moved to {host_when}", f"{host_when} ({tz})"),
    )
    return {"moved": True, "start": when.isoformat(), "when": times.describe(when, None, tz)}


def cancel_by_event(event_id: str) -> bool:
    """The member removed the meeting from the calendar themselves. Tell the
    visitor, take the Zoom link down, and stop it counting against the day."""
    with db.session() as s:
        row = s.execute(
            select(db.Booking).where(
                db.Booking.event_id == event_id, db.Booking.cancelled_at.is_(None)
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        booking_id, user_id, zoom_id = row.id, row.user_id, row.zoom_id
        name, email, start = row.name, row.email, row.start
        booked_zone = row.timezone
    member = users.member(user_id)
    if member is None:
        return False
    tz = member.timezone
    if zoom_id:
        meetings.delete_meeting(zoom_id)
    with db.session() as s:
        live = s.get(db.Booking, booking_id)
        if live is not None:
            live.cancelled_at = db.utcnow()
    from luach import mailer

    if mailer.configured():
        host = member.display_name or member.username
        theirs = booked_zone or tz
        their_when = times.describe(times.parse_when(start, theirs), None, theirs)
        mine = settings_for(user_id)
        book = _mailable(link_for(mine["slug"])) if mine.get("enabled") and mine.get("slug") else ""
        text, html = mail_templates.booking_cancelled(host, their_when, theirs, book=book)
        mailer.send(email, f"Cancelled: {their_when} with {host}", text, html)
    trail().record(
        "booking.cancelled",
        {"id": event_id, "host": member.username, "by": "host", "start": start, "guest": name},
    )
    return True


def _record(kind: str, member: users.Member, row: db.Booking, when: Any, tz: str) -> None:
    trail().record(
        kind,
        {
            "id": row.event_id,
            "host": member.username,
            "by": "guest",
            "start": when.isoformat() if hasattr(when, "isoformat") else str(when),
            "door": "booking",
        },
    )


def _tell_both(
    member: users.Member,
    row: db.Booking,
    conf: dict[str, Any],
    *,
    subject: str,
    guest: tuple[str, str],
    host_notice: tuple[str, str, str],
) -> None:
    """The host hears it in their hours, the visitor in theirs.

    `guest` is the visitor's (text, html); `host_notice` is (kicker, title, when)."""
    from luach import mailer

    if not mailer.configured():
        return
    mailer.send(row.email, subject, *guest)
    if conf.get("notify_host", True):
        kicker, title, when = host_notice
        text, html = mail_templates.booking_host_notice(
            kicker, title, f"{row.name} <{row.email}>", when, conf.get("location", "")
        )
        mailer.send(member.email, f"{kicker}: {row.name}, {when}", text, html)


def _both_ways(when: Any, host_tz: str, row: db.Booking, host: str) -> tuple[str, str]:
    """(what the host reads, what the visitor reads) for one moment in time."""
    theirs = row.timezone or host_tz
    host_line = times.describe(when, None, host_tz)
    guest_line = times.describe(times.parse_when(when.isoformat(), theirs), None, theirs)
    if theirs == host_tz:
        return host_line, host_line
    return host_line, f"{guest_line} ({theirs})"
