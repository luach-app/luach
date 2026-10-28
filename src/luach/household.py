"""Household-wide choices: which calendars luach watches, where new things
go by default, and who is invited to everything unless told otherwise.

Stored in the ``settings`` table so the owner can change them from the app;
the environment supplies the starting point (the one calendar the box was
installed with, nobody invited).
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select

from luach import config, db

KEY_CALENDARS = "household.calendars"
KEY_DEFAULT_CALENDAR = "household.default_calendar"
KEY_ATTENDEES = "household.default_attendees"

MAX_ATTENDEES = 20
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _get(key: str) -> Any:
    with db.session() as s:
        row = s.execute(select(db.Setting).where(db.Setting.key == key)).scalar_one_or_none()
        return db.loads(row.value) if row and row.enabled else None


def _put(key: str, value: Any) -> None:
    with db.session() as s:
        row = s.get(db.Setting, key)
        if row is None:
            s.add(db.Setting(key=key, value=db.dumps(value), enabled=True))
        else:
            row.value = db.dumps(value)
            row.enabled = True


def calendar_ids() -> list[str]:
    """The calendars luach reads and searches, the default first."""
    stored = _get(KEY_CALENDARS)
    ids = [str(c) for c in stored if str(c).strip()] if isinstance(stored, list) else []
    default = default_calendar_id()
    if default and default not in ids:
        ids.insert(0, default)
    return ids or ([config.google_calendar_id()] if config.google_calendar_id() else [])


def default_calendar_id() -> str:
    stored = _get(KEY_DEFAULT_CALENDAR)
    return (
        str(stored).strip()
        if isinstance(stored, str) and stored.strip()
        else (config.google_calendar_id())
    )


def default_attendees() -> list[str]:
    stored = _get(KEY_ATTENDEES)
    return [str(e) for e in stored if _EMAIL.match(str(e))] if isinstance(stored, list) else []


def snapshot() -> dict[str, Any]:
    return {
        "calendars": calendar_ids(),
        "default_calendar": default_calendar_id(),
        "default_attendees": default_attendees(),
    }


def update(
    *,
    calendars: list[str] | None = None,
    default_calendar: str | None = None,
    default_attendees: list[str] | None = None,
) -> dict[str, Any]:
    """Validate and store what was passed; return the full snapshot."""
    if default_attendees is not None:
        clean: list[str] = []
        for raw in default_attendees:
            email = str(raw).strip().lower()
            if not _EMAIL.match(email):
                raise ValueError(f"{raw!r} is not an email address")
            if email not in clean:
                clean.append(email)
        if len(clean) > MAX_ATTENDEES:
            raise ValueError(f"at most {MAX_ATTENDEES} default invitees")
        _put(KEY_ATTENDEES, clean)
    if calendars is not None:
        ids = []
        for raw in calendars:
            cid = str(raw).strip()
            if cid and cid not in ids:
                ids.append(cid)
        if not ids:
            raise ValueError("keep at least one calendar")
        _put(KEY_CALENDARS, ids)
    if default_calendar is not None:
        cid = str(default_calendar).strip()
        if not cid:
            raise ValueError("the default calendar cannot be empty")
        _put(KEY_DEFAULT_CALENDAR, cid)
        if cid not in calendar_ids():
            _put(KEY_CALENDARS, [cid, *calendar_ids()])
    return snapshot()


def is_email(raw: str) -> bool:
    return bool(_EMAIL.match(str(raw).strip().lower()))


def with_member(attendees: list[str], user_id: int | None) -> list[str]:
    """Add the addresses the acting member asked to be notified at."""
    from luach.auth import users

    out = list(attendees)
    for email in users.notify_emails(user_id):
        if email not in out:
            out.append(email)
    return out[:MAX_ATTENDEES]


def resolve_attendees(requested: list[str] | None) -> list[str]:
    """``None`` means "whoever is always invited"; a list is taken as given."""
    if requested is None:
        return default_attendees()
    out: list[str] = []
    for raw in requested:
        email = str(raw).strip().lower()
        if email and _EMAIL.match(email) and email not in out:
            out.append(email)
    return out[:MAX_ATTENDEES]


def household_addresses() -> frozenset[str]:
    """Every address the household already sends to, lower-cased: each member's own
    (the primary and the extras they confirmed), the "also notify" addresses they
    confirmed, the family's, and the people invited to everything.

    An invitation to anyone else is mail leaving the house, and text a stranger
    wrote — an event's notes, a booking note, an email, a web page — can ask the
    model for one. So the gate holds it (``outside-the-house``). Unconfirmed
    addresses are not here: an address someone typed is a claim, not a proof.
    """
    from luach import family

    out: set[str] = set(default_attendees())
    with db.session() as s:
        out.update(e for e in s.execute(select(db.User.email)).scalars() if e)
        for table in (db.UserEmail, db.NotifyEmail):
            out.update(
                s.execute(select(table.email).where(table.verified_at.is_not(None))).scalars()
            )
    out.update(p.email for p in family.roster() if p.email)
    return frozenset(e.strip().lower() for e in out if e and e.strip())
