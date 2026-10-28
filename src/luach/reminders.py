"""Telling a member about a thing before it happens.

Two kinds, because the household asks for two: a nudge some hours ahead ("the
dentist is at three"), and the evening-before list ("tomorrow: school trip,
piano"). Both are per member — one may want the night before and nothing else,
another an hour's warning.

Anything already sent is remembered, so a restart, a second worker, or a member
opening the app twice cannot produce the same reminder again.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from luach import db, mailer, push
from luach.auth import users
from luach.calendar import times
from luach.calendar.client import Event, get_calendar

logger = logging.getLogger(__name__)

KEY = "reminders.{user_id}"
#: The loop wakes on this cadence; a lead time finer than it is pointless.
TICK_MINUTES = 5
#: How late a reminder may be sent before it is simply skipped: an alert for
#: something that already started is noise, not help.
GRACE_MINUTES = 30

DEFAULTS: dict[str, Any] = {
    # Minutes before an event to say something; 0 turns it off.
    "lead_minutes": 0,
    # Send the evening list at this hour (local), or -1 to turn it off.
    "evening_hour": -1,
    # The week ahead, on this weekday (0 = Monday, 6 = Sunday), or -1 for never.
    "weekly_day": -1,
    # ...at this hour, local.
    "weekly_hour": 18,
    # Where: push always when subscribed; email only if asked.
    "by_email": False,
}


@dataclass(frozen=True)
class Due:
    kind: str  # "event" | "evening" | "weekly"
    key: str
    title: str
    #: The push notification's one line.
    body: str
    #: For a mail: the digest's lines, one per thing ("07:10 · Breakfast").
    lines: list[str] = field(default_factory=list)
    #: For a mail about one event: when and where, each on a line of its own.
    when: str = ""
    where: str = ""


def settings_for(user_id: int) -> dict[str, Any]:
    with db.session() as s:
        row = s.get(db.Setting, KEY.format(user_id=user_id))
        stored = db.loads(row.value, {}) if row else {}
    out = dict(DEFAULTS)
    if isinstance(stored, dict):
        for k in DEFAULTS:
            if k in stored:
                out[k] = stored[k]
    return out


def update(user_id: int, changes: dict[str, Any]) -> dict[str, Any]:
    current = settings_for(user_id)
    for key, value in changes.items():
        if key == "lead_minutes":
            minutes = _int(value, "the warning", 0, 7 * 24 * 60)
            current["lead_minutes"] = minutes
        elif key == "evening_hour":
            hour = _int(value, "the evening hour", -1, 23)
            current["evening_hour"] = hour
        elif key == "weekly_day":
            current["weekly_day"] = _int(value, "the weekly day", -1, 6)
        elif key == "weekly_hour":
            current["weekly_hour"] = _int(value, "the weekly hour", 0, 23)
        elif key == "by_email":
            current["by_email"] = bool(value)
        else:
            raise ValueError(f"unknown setting {key!r}")
    with db.session() as s:
        key_name = KEY.format(user_id=user_id)
        row = s.get(db.Setting, key_name)
        if row is None:
            s.add(db.Setting(key=key_name, value=db.dumps(current), enabled=True))
        else:
            row.value = db.dumps(current)
            row.enabled = True
    return current


def _int(value: Any, name: str, low: int, high: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a whole number") from exc
    if not low <= n <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return n


def _already(key: str) -> bool:
    with db.session() as s:
        return s.get(db.SentReminder, key) is not None


def _mark(key: str) -> None:
    with db.session() as s:
        if s.get(db.SentReminder, key) is None:
            s.add(db.SentReminder(key=key))


def _events(start: datetime, end: datetime) -> list[Event]:
    try:
        return get_calendar().list_events(start, end)
    except Exception:
        logger.exception("reminders: could not read the calendar")
        return []


def due_for(member: users.Member, now: datetime | None = None) -> list[Due]:
    """What this member should be told about right now."""
    conf = settings_for(member.id)
    tz = member.timezone
    now = now or times.now_in(tz)
    out: list[Due] = []

    lead = int(conf["lead_minutes"])
    if lead:
        window_start = now + timedelta(minutes=lead - TICK_MINUTES)
        window_end = now + timedelta(minutes=lead)
        for ev in _events(now, now + timedelta(minutes=lead + TICK_MINUTES)):
            if ev.all_day:
                continue
            when = times.parse_when(ev.start, tz)
            if not isinstance(when, datetime):
                continue
            if not (window_start < when <= window_end):
                continue
            if when < now - timedelta(minutes=GRACE_MINUTES):
                continue
            key = f"event:{member.id}:{ev.id}:{ev.start}"
            if _already(key):
                continue
            out.append(
                Due(
                    kind="event",
                    key=key,
                    title=ev.title or "Something on the calendar",
                    body=times.describe(when, None, tz)
                    + (f" · {ev.location}" if ev.location else ""),
                    when=times.describe(when, None, tz),
                    where=ev.location or "",
                )
            )

    hour = int(conf["evening_hour"])
    if hour >= 0 and now.hour == hour and now.minute < TICK_MINUTES:
        tomorrow = (now + timedelta(days=1)).date()
        key = f"evening:{member.id}:{tomorrow.isoformat()}"
        if not _already(key):
            start, end = times.day_bounds(tomorrow.isoformat(), tz)
            listed = _events(start, end)
            if listed:
                lines = []
                for ev in listed[:10]:
                    when = times.parse_when(ev.start, tz)
                    stamp = when.strftime("%H:%M") if isinstance(when, datetime) else "all day"
                    lines.append(f"{stamp} · {ev.title}")
                out.append(
                    Due(
                        kind="evening",
                        key=key,
                        title=f"Tomorrow: {len(listed)} thing{'s' if len(listed) != 1 else ''}",
                        body="; ".join(lines),
                        lines=lines,
                    )
                )
    weekday = int(conf["weekly_day"])
    if (
        weekday >= 0
        and now.weekday() == weekday
        and now.hour == int(conf["weekly_hour"])
        and now.minute < TICK_MINUTES
    ):
        first = (now + timedelta(days=1)).date()
        key = f"weekly:{member.id}:{first.isoformat()}"
        if not _already(key):
            start, _ = times.day_bounds(first.isoformat(), tz)
            _, end = times.day_bounds((first + timedelta(days=6)).isoformat(), tz)
            listed = _events(start, end)
            lines = []
            for ev in listed[:25]:
                when = times.parse_when(ev.start, tz)
                stamp = (
                    when.strftime("%a %d %b, %H:%M")
                    if isinstance(when, datetime)
                    else when.strftime("%a %d %b")
                )
                lines.append(f"{stamp} · {ev.title}")
            out.append(
                Due(
                    kind="weekly",
                    key=key,
                    title=f"The week ahead: {len(listed)} thing{'s' if len(listed) != 1 else ''}",
                    body="; ".join(lines) if lines else "Nothing on the calendar yet.",
                    lines=lines,
                )
            )
    return out


def send(member: users.Member, due: Due) -> bool:
    """Push to the member's devices, and mail them when they asked for that."""
    conf = settings_for(member.id)
    sent = push.notify_user(member.id, due.title, due.body, "/") > 0
    # The week ahead is a read, not an alert: it belongs in an inbox even when
    # the shorter nudges do not.
    if (conf["by_email"] or due.kind == "weekly") and mailer.configured():
        sent = _mail(member.email, due) or sent
    _mark(due.key)
    return sent


def _mail(to: str, due: Due) -> bool:
    """One event is a card with its time and place; anything else is a list.
    The lines travel as a list: joined for the push and split again, a title
    with "; " in it came apart into lines with no time."""
    from luach import mail_templates

    if due.kind == "event":
        text, html = mail_templates.event_reminder(due.title, due.when, due.where)
        return mailer.send(to, f"{due.title}, {due.when}", text, html)
    return mailer.send_digest(to, due.title, due.lines)


def run_once(now: datetime | None = None) -> int:
    """One pass over every member. Returns how many reminders went out."""
    count = 0
    for member in users.members():
        conf = settings_for(member.id)
        if (
            not int(conf["lead_minutes"])
            and int(conf["evening_hour"]) < 0
            and int(conf["weekly_day"]) < 0
        ):
            continue
        for due in due_for(member, now):
            if send(member, due):
                count += 1
            else:
                logger.info("reminders: nothing could carry %s for %s", due.kind, member.username)
    return count


def purge(before_days: int = 30) -> None:
    """Forget what was sent long ago; the ledger only exists to stop repeats."""
    cutoff = db.utcnow() - timedelta(days=before_days)
    with db.session() as s:
        for row in s.execute(
            select(db.SentReminder).where(db.SentReminder.sent_at < cutoff)
        ).scalars():
            s.delete(row)
