"""Direct calendar access for the UI. A person's tap IS the approval, so these
skip the model gate — but every write still lands on the audit trail."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from dateutil.rrule import rrulestr
from fastapi import APIRouter, Request

from luach import family, household
from luach.agent.control import trail
from luach.calendar import repeats, times
from luach.calendar.client import Draft, get_calendar
from luach.routes.shared import body, error, require_member, text_field

router = APIRouter(prefix="/api/calendar")

#: One request covers at most this many days; the UI pages month by month.
MAX_RANGE_DAYS = 400


@router.get("/events")
def events(start: str, end: str) -> dict:
    member = require_member()
    tz = member.timezone
    try:
        s, _ = times.day_bounds(start, tz)
        _, e = times.day_bounds(end, tz)
    except ValueError as exc:
        raise error(400, "start and end must be YYYY-MM-DD") from exc
    if e < s:
        raise error(400, "end is before start")
    if (e - s).days > MAX_RANGE_DAYS:
        raise error(400, f"ask for at most {MAX_RANGE_DAYS} days at a time and page through")
    out = get_calendar().list_events(s, e)
    people = family.roster()
    # Plus what the member's read-only feeds say is taken. They carry no title
    # and cannot be edited; the household sees the time, not the meeting.
    from luach import busy

    return {
        "events": [_with_leader(ev, people) for ev in out] + busy.as_events(member.id, s, e, tz),
        "timezone": tz,
        "start": start[:10],
        "end": end[:10],
    }


def _with_leader(ev: Any, people: list[family.Person] | None = None) -> dict[str, Any]:
    """The event, with whom it is for — `leaders` every one of them, `leader` the
    first (what clients read before an event could be several people's)."""
    d = ev.as_dict()
    found = family.leaders_for(ev, people)
    d["leaders"] = [p.key for p in found]
    d["leader"] = found[0].key if found else ""
    return d


def _leading(data: dict[str, Any]) -> bool:
    return "leaders" in data or "leader" in data


def _leader_field(data: dict[str, Any]) -> list[family.Person]:
    """`leaders: [key…]`, or `leader: "key"` (a comma list works too); none is nobody's."""
    if "leaders" in data:
        raw = data["leaders"]
        if not isinstance(raw, list) or not all(isinstance(k, str) for k in raw):
            raise error(400, "leaders must be a list of family keys")
        keys = [k.strip() for k in raw if k.strip()]
    else:
        keys = [
            k.strip() for k in text_field(data, "leader", required=False, max_len=400).split(",")
        ]
        keys = [k for k in keys if k]
    out: list[family.Person] = []
    for key in keys:
        p = family.get(key)
        if p is None:
            raise error(400, "that is not someone in the family")
        if p not in out:
            out.append(p)
    return out


def _attendees(data: dict[str, Any]) -> list[str] | None:
    """A list as given (empty means invite nobody); absent means the household default."""
    if "attendees" not in data:
        return None
    raw = data["attendees"]
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise error(400, "attendees must be a list of emails")
    # An address that is not one used to be dropped without a word, so the
    # person believed someone was invited who never was.
    for a in raw:
        if a.strip() and not household.is_email(a):
            raise error(400, f"{a.strip()} is not an email address")
    return household.resolve_attendees(raw)


def _recurrence(data: dict[str, Any], start: Any) -> list[str]:
    """``FREQ=WEEKLY;BYDAY=TU`` with or without its ``RRULE:``; "" is none.

    Or one of the words a menu offers (``daily``, ``weekly``, ``biweekly``,
    ``monthly``, ``yearly``, ``none``), made into a rule here on the event's own
    local day (``start``): clients that worked out the weekday themselves put a
    weekly all-day event on the day before, west of UTC.

    Checked here, because nothing else did: a rule Google cannot read was saved
    as given by the local calendar, and would fail at Google's insert.
    """
    rr = text_field(data, "recurrence", required=False, max_len=200)
    if not rr:
        return []
    if repeats.is_word(rr):
        return repeats.rule_for(rr, start)
    rule = rr if rr.upper().startswith("RRULE:") else f"RRULE:{rr}"
    try:
        rrulestr(rule, dtstart=datetime(2000, 1, 1))
    except (ValueError, TypeError) as exc:
        raise error(400, f"{rr} is not a repeat rule, e.g. FREQ=WEEKLY;BYDAY=TU") from exc
    return [rule]


def _scope(scope: str) -> str:
    """What a change or a delete of one occurrence acts on: ``this`` one or the ``series``."""
    s = (scope or repeats.THIS).strip().lower()
    if s not in repeats.SCOPES:
        raise error(400, "scope is this (one occurrence) or series (every occurrence)")
    return s


def _calendar_field(data: dict[str, Any]) -> str:
    cid = text_field(data, "calendar_id", required=False, max_len=200)
    if cid and cid not in household.calendar_ids():
        raise error(400, "that calendar is not one of the household's")
    return cid


def household_calendar(calendar: str) -> str:
    """A ``calendar=`` from the caller: empty (the household's default), or one of the
    household's calendars. Any other id reached a calendar the credential can see but
    the household does not use -- someone's personal one."""
    if calendar and calendar not in household.calendar_ids():
        raise error(400, "that calendar is not one of the household's")
    return calendar


@router.get("/events/{event_id}")
def event(event_id: str, calendar: str = "") -> dict:
    require_member()
    ev = get_calendar().get_event(event_id, household_calendar(calendar))
    if ev is None:
        raise error(404, "no such event")
    return _with_leader(ev)


def create_event(data: dict[str, Any], *, tz: str, user_id: int | None, by: str, door: str) -> dict:
    """An event from a form: the calendar API's, and the house board's."""
    title = text_field(data, "title", max_len=200)
    try:
        sp = times.span(
            text_field(data, "start", max_len=40),
            text_field(data, "end", required=False, max_len=40) or None,
            tz,
        )
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    draft = Draft(
        title=title,
        span=sp,
        location=text_field(data, "location", required=False, max_len=300),
        description=text_field(data, "description", required=False, max_len=2000),
        recurrence=_recurrence(data, sp.start),
        calendar_id=_calendar_field(data),
        # Absent → the household's usual people plus the member's own notify list;
        # a list is what the person saw in the form and is taken as given.
        attendees=(
            household.with_member(household.default_attendees(), user_id)
            if "attendees" not in data
            else household.resolve_attendees(_attendees(data))
        ),
    )
    family.stamp(draft, _leader_field(data))
    ev = get_calendar().insert(draft, tz)
    trail().record(
        "event.created",
        {
            "id": ev.id,
            "title": ev.title,
            "start": ev.start,
            "by": by,
            "door": door,
            "calendar": ev.calendar_id,
            "attendees": ev.attendees,
            "leader": ev.leader,
        },
    )
    return _with_leader(ev)


def _not_ours(ev: Any) -> None:
    """Refuse a change Google would refuse, in words a person can act on."""
    if not ev.read_only:
        return
    if ev.organizer:
        raise error(
            409,
            f"This is an invitation from {ev.organizer}: only they can change it. "
            "Reply to it, or change your copy, in Google Calendar.",
        )
    raise error(409, "This is on a calendar luach only reads: change it where it lives.")


def _google_said_no(exc: Exception) -> None:
    """Google's own refusal (403) is the person's answer, not a server fault."""
    from googleapiclient.errors import HttpError

    if isinstance(exc, HttpError) and exc.resp.status == 403:
        raise error(
            409, "Google would not allow that change: only the event's organizer can make it."
        ) from exc


def update_event(
    event_id: str,
    data: dict[str, Any],
    *,
    tz: str,
    calendar: str,
    by: str,
    door: str,
    scope: str = repeats.THIS,
) -> dict:
    """Change an event. On one occurrence of a repeating event, ``scope`` says whether
    the change is to that occurrence (``this``, the default) or to every one (``series``)."""
    scope = _scope(scope)
    changes: dict[str, Any] = {}
    for key in ("title", "start", "end", "location", "description"):
        if key in data:
            changes[key] = text_field(data, key, required=(key == "title"), max_len=2000)
    attendees = _attendees(data)
    if attendees is not None:
        changes["attendees"] = attendees
    leading = _leading(data)
    if not changes and not leading and "recurrence" not in data:
        raise error(400, "nothing to change")
    cal = get_calendar()
    existing = cal.get_event(event_id, household_calendar(calendar))
    if existing is None:
        raise error(404, "no such event")
    _not_ours(existing)
    if repeats.same_times(existing.start, existing.end, changes, tz):
        # A form sends the times it showed. Unchanged, they are no change: on one
        # occurrence they would pin it to its time when the series' time later moves.
        changes.pop("start", None)
        changes.pop("end", None)
    if "recurrence" in data:
        try:
            anchor = times.parse_when(changes.get("start") or existing.start, tz)
        except ValueError as exc:
            raise error(400, str(exc)) from exc
        rule = _recurrence(data, anchor)
        if existing.occurrence and scope == repeats.THIS:
            # One occurrence cannot repeat on its own. The rule it showed, or "" from a
            # client that showed an occurrence as not repeating, is no change.
            if rule and rule != existing.recurrence:
                raise error(
                    400,
                    "How an event repeats belongs to the whole series: save it for all "
                    "events (scope=series).",
                )
        elif rule != existing.recurrence:
            # Only a new rule: the rule it has, sent again, would stop a series moved
            # to another day from taking its weekdays along.
            changes["recurrence"] = rule
    if not changes and not leading:
        return _with_leader(existing)  # what was sent is what it already is
    if leading:
        people = _leader_field(data)
        changes.update(family.leading(people))
        # New leaders are invited, onto whatever list the event has (or is getting).
        invited = family.with_leader(changes.get("attendees", existing.attendees), people)
        if invited != changes.get("attendees", existing.attendees):
            changes["attendees"] = invited
    try:
        ev = cal.patch(event_id, changes, tz, existing.calendar_id, scope=scope)
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    except Exception as exc:
        _google_said_no(exc)
        raise
    record: dict[str, Any] = {"id": ev.id, "changes": changes, "by": by, "door": door}
    if existing.occurrence:
        record.update(occurrence=event_id, scope=scope)
    trail().record("event.updated", record)
    return _with_leader(ev)


def delete_event(
    event_id: str, *, calendar: str, by: str, door: str, scope: str = repeats.THIS
) -> dict:
    """Delete an event; one occurrence of a repeating event alone, or (``series``) them all."""
    scope = _scope(scope)
    cal = get_calendar()
    ev = cal.get_event(event_id, household_calendar(calendar))
    if ev is None:
        raise error(404, "no such event")
    _not_ours(ev)
    try:
        cal.delete(event_id, ev.calendar_id, scope=scope)
    except Exception as exc:
        _google_said_no(exc)
        raise
    # If this was a booking, the person who took it is owed the news — and their
    # Zoom link should stop working.
    from luach import booking

    told = booking.cancel_by_event(event_id)
    record: dict[str, Any] = {"id": event_id, "title": ev.title, "by": by, "door": door}
    if ev.occurrence:
        record.update(series=ev.recurring_event_id, scope=scope)
    trail().record("event.deleted", record)
    return {"ok": True, "guest_told": told}


@router.post("/events")
async def create(request: Request) -> dict:
    member = require_member()
    data = await body(request)
    return create_event(data, tz=member.timezone, user_id=member.id, by=member.username, door="ui")


@router.patch("/events/{event_id}")
async def update(
    event_id: str, request: Request, calendar: str = "", scope: str = repeats.THIS
) -> dict:
    member = require_member()
    data = await body(request)
    return update_event(
        event_id,
        data,
        tz=member.timezone,
        calendar=calendar,
        by=member.username,
        door="ui",
        scope=scope,
    )


@router.delete("/events/{event_id}")
def delete(event_id: str, calendar: str = "", scope: str = repeats.THIS) -> dict:
    member = require_member()
    return delete_event(event_id, calendar=calendar, by=member.username, door="ui", scope=scope)


@router.get("/identity")
def identity() -> dict:
    require_member()
    return get_calendar().identity()
