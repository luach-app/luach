"""Calendar access. ``Calendar`` is the protocol the tools and routes use;
``GoogleCalendar`` is the real one (the owner's OAuth grant or a service
account, one or more calendars); ``FakeCalendar`` is the in-memory one tests
and the offline demo use."""

from __future__ import annotations

import logging
import ssl
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from luach import config, household
from luach.calendar import repeats, times

logger = logging.getLogger(__name__)

WRITABLE_ROLES = {"owner", "writer"}

#: Seconds before the one retry after a failed connection: long enough for a
#: DNS blip to pass, short enough that a page waiting on it does not notice.
RETRY_PAUSE = 1.0


@dataclass
class CalendarInfo:
    id: str
    name: str
    color: str = ""
    primary: bool = False
    writable: bool = True

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class Event:
    id: str
    title: str
    start: str  # ISO datetime, or YYYY-MM-DD for all-day
    end: str
    all_day: bool = False
    location: str = ""
    description: str = ""
    #: The RRULE. On one occurrence of a repeating event, its series' rule.
    recurrence: list[str] = field(default_factory=list)
    #: On one occurrence of a repeating event, the series' id.
    recurring_event_id: str = ""
    #: One occurrence of a repeating event (Google's instance), not the series itself:
    #: a change or a delete takes a scope, this one or the whole series.
    occurrence: bool = False
    html_link: str = ""
    creator: str = ""
    updated: str = ""
    calendar_id: str = ""
    attendees: list[str] = field(default_factory=list)
    #: Set when the event was saved but the invitations could not be sent.
    invite_error: str = ""
    #: The family member it is for (a luach.family key), or "".
    leader: str = ""
    #: Google's event colorId, "" when it wears its calendar's colour.
    color_id: str = ""
    #: The same on every calendar the event appears on: one the family calendar holds
    #: and also invites a member to shows up on both.
    ical_uid: str = ""
    #: Who sent it, when it is someone else's invitation ("" for the household's own).
    organizer: str = ""
    #: luach may not change it: an invitation only its organizer can edit, or an
    #: event on a calendar luach only reads (a member's own, shared read-only).
    read_only: bool = False

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

    def start_dt(self) -> datetime | date:
        return times.parse_when(self.start, config.timezone())


@dataclass
class Draft:
    title: str
    span: times.Span
    location: str = ""
    description: str = ""
    recurrence: list[str] = field(default_factory=list)
    reminders_minutes: list[int] = field(default_factory=list)
    calendar_id: str = ""
    attendees: list[str] = field(default_factory=list)
    leader: str = ""
    #: The leader's Google event colour; "" leaves the calendar's own.
    color_id: str = ""


#: Where an event's leader is kept on the Google side. ``shared`` rather than
#: ``private`` so every copy of the event carries it, not just the organiser's.
LEADER_PROPERTY = "luach_leader"


class Calendar(Protocol):
    def calendars(self) -> list[CalendarInfo]: ...
    def list_events(
        self,
        start: datetime,
        end: datetime,
        query: str = "",
        calendar_ids: list[str] | None = None,
    ) -> list[Event]: ...
    def get_event(self, event_id: str, calendar_id: str = "") -> Event | None: ...
    def insert(self, draft: Draft, tz: str) -> Event: ...
    def patch(
        self,
        event_id: str,
        changes: dict[str, Any],
        tz: str,
        calendar_id: str = "",
        scope: str = repeats.THIS,
    ) -> Event: ...
    def delete(self, event_id: str, calendar_id: str = "", scope: str = repeats.THIS) -> None: ...
    def identity(self) -> dict[str, Any]: ...


def _someone_elses(item: dict[str, Any], calendar_id: str) -> str:
    """The organizer's address when the event is an invitation from someone else."""
    org = item.get("organizer") or {}
    email = str(org.get("email") or "")
    if not email or org.get("self") or email == calendar_id or item.get("guestsCanModify"):
        return ""
    return email


def _from_google(item: dict[str, Any], calendar_id: str = "") -> Event:
    start = item.get("start", {})
    end = item.get("end", {})
    all_day = "date" in start
    return Event(
        id=item["id"],
        title=item.get("summary", "(untitled)"),
        start=start.get("dateTime") or start.get("date", ""),
        end=end.get("dateTime") or end.get("date", ""),
        all_day=all_day,
        location=item.get("location", "") or "",
        description=item.get("description", "") or "",
        recurrence=list(item.get("recurrence", []) or []),
        recurring_event_id=item.get("recurringEventId", "") or "",
        occurrence=bool(item.get("recurringEventId")),
        html_link=item.get("htmlLink", "") or "",
        creator=(item.get("creator") or {}).get("email", "") or "",
        updated=item.get("updated", "") or "",
        calendar_id=calendar_id,
        ical_uid=item.get("iCalUID", "") or "",
        organizer=_someone_elses(item, calendar_id),
        read_only=bool(_someone_elses(item, calendar_id)),
        attendees=[
            a["email"]
            for a in item.get("attendees", []) or []
            if a.get("email") and not a.get("self")
        ],
        leader=((item.get("extendedProperties") or {}).get("shared") or {}).get(LEADER_PROPERTY, "")
        or "",
        color_id=str(item.get("colorId") or ""),
    )


def _calendar_from_google(item: dict[str, Any]) -> CalendarInfo:
    return CalendarInfo(
        id=item["id"],
        name=item.get("summaryOverride") or item.get("summary") or item["id"],
        color=item.get("backgroundColor", "") or "",
        primary=bool(item.get("primary")),
        writable=item.get("accessRole", "owner") in WRITABLE_ROLES,
    )


def _body_from_draft(draft: Draft, tz: str) -> dict[str, Any]:
    start, end = draft.span.as_google(tz)
    body: dict[str, Any] = {"summary": draft.title, "start": start, "end": end}
    if draft.location:
        body["location"] = draft.location
    if draft.description:
        body["description"] = draft.description
    if draft.recurrence:
        body["recurrence"] = draft.recurrence
    if draft.reminders_minutes:
        body["reminders"] = {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": m} for m in draft.reminders_minutes],
        }
    if draft.attendees:
        body["attendees"] = [{"email": e} for e in draft.attendees]
    if draft.leader:
        body["extendedProperties"] = {"shared": {LEADER_PROPERTY: draft.leader}}
    if draft.color_id:
        body["colorId"] = draft.color_id
    return body


def _body_from_changes(changes: dict[str, Any], tz: str) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if "title" in changes:
        body["summary"] = changes["title"]
    if "location" in changes:
        body["location"] = changes["location"]
    if "description" in changes:
        body["description"] = changes["description"]
    if "start" in changes or "end" in changes:
        span = times.span(changes["start"], changes.get("end"), tz)
        start, end = span.as_google(tz)
        # A patch merges: an all-day event moved to 09:00 kept its "date" beside the
        # new "dateTime", and Google refused the pair (400).
        # Clearing the other kind makes the change either way.
        for part in (start, end):
            if "dateTime" in part:
                part.setdefault("date", None)
            else:
                part.setdefault("dateTime", None)
                part.setdefault("timeZone", None)
        body["start"], body["end"] = start, end
    if "recurrence" in changes:
        body["recurrence"] = changes["recurrence"] or []
    if "attendees" in changes:
        body["attendees"] = [{"email": e} for e in changes["attendees"] or []]
    if "leader" in changes:
        body["extendedProperties"] = {"shared": {LEADER_PROPERTY: changes["leader"] or ""}}
        # None clears it, so an event with nobody leading goes back to the
        # calendar's own colour.
        body["colorId"] = changes.get("color_id") or None
    return body


#: Said when one occurrence is asked to repeat differently from its series.
REPEAT_IS_THE_SERIES = (
    "how an event repeats belongs to its whole series: change it for all events (scope=series)"
)


def _with_span(current: Event, changes: dict[str, Any], tz: str) -> dict[str, Any]:
    """``changes`` with both a start and an end whenever either is changing: a start
    alone keeps the event's length, an end alone keeps its start."""
    if not changes.get("start") and not changes.get("end"):
        return {k: v for k, v in changes.items() if k not in ("start", "end")}
    sp = repeats.resolved_span(current.start, current.end, changes, tz)
    return {**changes, "start": sp.start.isoformat(), "end": sp.end.isoformat()}


def _series_changes(series: Event, seen: Event, changes: dict[str, Any], tz: str) -> dict[str, Any]:
    out = repeats.series_changes(
        series.start, series.end, series.recurrence, seen.start, seen.end, changes, tz
    )
    return _with_span(series, out, tz)


def _wanted(calendar_ids: list[str] | None, fallback: str) -> list[str]:
    """Explicit ids as given (an empty list means none); otherwise the
    household's, or the one the box was installed with."""
    if calendar_ids is not None:
        return list(calendar_ids)
    return household.calendar_ids() or ([fallback] if fallback else [])


class GoogleCalendar:
    """The household's calendars, through the owner's grant or a service account."""

    SCOPES = ["https://www.googleapis.com/auth/calendar"]

    def __init__(
        self,
        key_path: str,
        calendar_id: str,
        oauth_client: str = "",
        oauth_tokens: str = "",
        auth: str = "auto",
    ) -> None:
        self.key_path = key_path
        self.calendar_id = calendar_id
        self.oauth_client = oauth_client
        self.oauth_tokens = oauth_tokens
        self.auth = (
            auth
            if auth in ("oauth", "sa")
            else ("oauth" if oauth_client and oauth_tokens else "sa")
        )
        # googleapiclient builds on httplib2, whose connections are not thread
        # safe. FastAPI runs these calls in a worker thread while the email,
        # busy-feed and reminder loops run in others; sharing one service meant
        # two threads writing into the same TLS stream, which surfaces as
        # "SSL record layer failure" and a calendar that will not load. One
        # service per thread costs a handshake and removes the whole class.
        self._local = threading.local()
        #: A service handed in from outside (the tests do this). When set it is
        #: used as it is, on every thread, and nothing is built.
        self._service: Any = None

    def _credentials(self) -> Any:
        if self.auth == "oauth":
            import json

            from google.oauth2.credentials import Credentials

            with open(self.oauth_tokens) as fh:
                tokens = json.load(fh)
            with open(self.oauth_client) as fh:
                client = json.load(fh)
            return Credentials(
                token=None,
                refresh_token=tokens["refresh_token"],
                token_uri="https://oauth2.googleapis.com/token",
                client_id=client["client_id"],
                client_secret=client["client_secret"],
                scopes=self.SCOPES,
            )
        from google.oauth2.service_account import Credentials as SACredentials

        return SACredentials.from_service_account_file(self.key_path, scopes=self.SCOPES)

    def _svc(self) -> Any:
        if self._service is not None:
            return self._service
        service = getattr(self._local, "service", None)
        if service is None:
            from googleapiclient.discovery import build

            service = build(
                "calendar", "v3", credentials=self._credentials(), cache_discovery=False
            )
            self._local.service = service
        return service

    def _drop(self) -> None:
        """Forget this thread's service so the next call builds a fresh one."""
        if self._service is None:
            self._local.service = None

    def _run(self, make: Any) -> Any:
        """Execute a request, once more with a new connection if the transport
        fails. A dropped or poisoned socket is not a reason to fail a page.

        google-auth's TransportError is its own class, not an OSError: a token
        refresh that could not resolve oauth2.googleapis.com raised it past
        this retry, and the reminder pass failed four times in two days on a
        DNS blip that was gone a second later."""
        from google.auth.exceptions import TransportError

        try:
            return make(self._svc()).execute()
        except (OSError, ssl.SSLError, ConnectionError, TimeoutError, TransportError) as exc:
            logger.warning("calendar: connection failed (%s); retrying once", type(exc).__name__)
            self._drop()
            time.sleep(RETRY_PAUSE)
            return make(self._svc()).execute()

    # -- calendars ----------------------------------------------------------

    def calendars(self) -> list[CalendarInfo]:
        items: list[dict[str, Any]] = []
        page: str | None = None
        while True:
            kwargs: dict[str, Any] = {"minAccessRole": "reader", "showHidden": False}
            if page:
                kwargs["pageToken"] = page
            result = self._run(lambda svc, kw=kwargs: svc.calendarList().list(**kw))
            items.extend(result.get("items", []))
            page = result.get("nextPageToken")
            if not page:
                break
        out = [_calendar_from_google(i) for i in items if not i.get("deleted")]
        if self.calendar_id and all(c.id != self.calendar_id for c in out):
            out.append(CalendarInfo(id=self.calendar_id, name=self.calendar_id))
        return sorted(out, key=lambda c: (not c.primary, c.name.lower()))

    # -- events ---------------------------------------------------------------

    def list_events(
        self,
        start: datetime,
        end: datetime,
        query: str = "",
        calendar_ids: list[str] | None = None,
    ) -> list[Event]:
        out: list[Event] = []
        seen: set[tuple[str, str]] = set()
        for cid in _wanted(calendar_ids, self.calendar_id):
            for ev in self._list_one(cid, start, end, query):
                # An event on the family calendar that invites a member is on theirs too,
                # under the same iCalUID: shown once, from the first calendar read.
                key = (ev.ical_uid, ev.start)
                if ev.ical_uid and key in seen:
                    continue
                seen.add(key)
                out.append(ev)
        if len(out) > 1 and calendar_ids is None:
            out.sort(key=lambda e: times.to_utc_iso(_utc_start(e)))
        return out

    def _list_one(
        self, calendar_id: str, start: datetime, end: datetime, query: str
    ) -> list[Event]:
        kwargs: dict[str, Any] = {
            "calendarId": calendar_id,
            "timeMin": times.to_utc_iso(start),
            "timeMax": times.to_utc_iso(end),
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": 250,
        }
        if query:
            kwargs["q"] = query
        items: list[dict[str, Any]] = []
        page: str | None = None
        while True:
            if page:
                kwargs["pageToken"] = page
            result = self._run(lambda svc: svc.events().list(**kwargs))
            items.extend(result.get("items", []))
            page = result.get("nextPageToken")
            if not page or len(items) >= 1000:
                break
        writable = self._writable(calendar_id)
        out = [_from_google(i, calendar_id) for i in items if i.get("status") != "cancelled"]
        for ev in out:
            ev.read_only = ev.read_only or not writable
            self._with_rule(ev, calendar_id)
        return out

    #: How long the calendars' access roles are trusted before luach asks again.
    ROLES_SECONDS = 600

    def _writable(self, calendar_id: str) -> bool:
        """Whether luach may write to this calendar (its accessRole); True when unknown,
        so a failed lookup never hides an Edit button that would have worked."""
        import time

        cached = getattr(self, "_roles", None)
        if cached is None or time.monotonic() - cached[0] > self.ROLES_SECONDS:
            try:
                roles = {c.id: c.writable for c in self.calendars()}
            except Exception:
                logger.warning(
                    "calendar: could not read the calendars' access roles", exc_info=True
                )
                return True
            cached = (time.monotonic(), roles)
            self._roles = cached
        return cached[1].get(calendar_id, True)

    def get_event(self, event_id: str, calendar_id: str = "") -> Event | None:
        from googleapiclient.errors import HttpError

        for cid in [calendar_id] if calendar_id else _wanted(None, self.calendar_id):
            try:
                item = self._run(
                    lambda svc, c=cid: svc.events().get(calendarId=c, eventId=event_id)
                )
            except HttpError as exc:
                if exc.resp.status in (404, 410):
                    continue
                raise
            if item.get("status") == "cancelled":
                continue
            ev = _from_google(item, cid)
            ev.read_only = ev.read_only or not self._writable(cid)
            return self._with_rule(ev, cid)
        return None

    def insert(self, draft: Draft, tz: str) -> Event:
        from googleapiclient.errors import HttpError

        cid = draft.calendar_id or household.default_calendar_id() or self.calendar_id
        body = _body_from_draft(draft, tz)
        kwargs: dict[str, Any] = {"calendarId": cid, "body": body}
        if draft.attendees:
            kwargs["sendUpdates"] = "all"
        try:
            item = self._run(lambda svc: svc.events().insert(**kwargs))
        except HttpError as exc:
            if not draft.attendees or exc.resp.status != 403:
                raise
            # A service account may not invite anyone (Google wants domain-wide
            # delegation for that). Keep the event; say the invitations failed.
            logger.warning("calendar: %s refused attendees on %s; saving without", self.auth, cid)
            body.pop("attendees", None)
            item = self._run(lambda svc: svc.events().insert(calendarId=cid, body=body))
            ev = _from_google(item, cid)
            ev.invite_error = "invitations were not sent: this credential cannot invite people"
            return ev
        return _from_google(item, cid)

    def patch(
        self,
        event_id: str,
        changes: dict[str, Any],
        tz: str,
        calendar_id: str = "",
        scope: str = repeats.THIS,
    ) -> Event:
        """Google's own instance semantics: a PATCH to an occurrence's id changes that
        occurrence alone (Google keeps it as an exception to its series); scope
        ``series`` patches the series instead, the change translated to it."""
        current = self.get_event(event_id, calendar_id)
        if current is None:
            raise KeyError(f"no such event {event_id}")
        cid = current.calendar_id or calendar_id or self.calendar_id
        target = event_id
        if current.occurrence and scope == repeats.SERIES:
            series = self.get_event(current.recurring_event_id, cid)
            if series is None:
                raise KeyError(f"no such event {current.recurring_event_id}")
            changes = _series_changes(series, current, changes, tz)
            target = series.id
        elif current.recurrence and not current.occurrence:
            changes = _series_changes(current, current, changes, tz)
        else:
            if current.occurrence and "recurrence" in changes:
                raise ValueError(REPEAT_IS_THE_SERIES)
            changes = _with_span(current, changes, tz)
        body = _body_from_changes(changes, tz)
        kwargs: dict[str, Any] = {"calendarId": cid, "eventId": target, "body": body}
        if "attendees" in body:
            kwargs["sendUpdates"] = "all"
        item = self._run(lambda svc: svc.events().patch(**kwargs))
        self._forget_rule(cid, current.recurring_event_id or target)
        return self._with_rule(_from_google(item, cid), cid)

    def delete(self, event_id: str, calendar_id: str = "", scope: str = repeats.THIS) -> None:
        """An occurrence's id cancels that occurrence alone (Google's instance
        semantics); scope ``series`` deletes the whole series."""
        target = event_id
        if scope == repeats.SERIES or not calendar_id:
            current = self.get_event(event_id, calendar_id)
            if current is None:
                raise KeyError(f"no such event {event_id}")
            calendar_id = current.calendar_id or calendar_id or self.calendar_id
            if current.occurrence and scope == repeats.SERIES:
                target = current.recurring_event_id
        cid = calendar_id
        self._run(lambda svc: svc.events().delete(calendarId=cid, eventId=target))
        self._forget_rule(cid, target)

    # -- a series' rule, for its occurrences ------------------------------------
    # Google lists occurrences without their series' RRULE, so a form opened on one
    # said "Does not repeat", sent that back, and stopped the series. The rule is
    # read from the series, once per series per few minutes.

    #: How long a series' rule is trusted before it is read again.
    RULE_SECONDS = 300

    def _series_rule(self, calendar_id: str, series_id: str) -> list[str]:
        from googleapiclient.errors import HttpError

        cache: dict[tuple[str, str], tuple[float, list[str]]] = self.__dict__.setdefault(
            "_rules", {}
        )
        hit = cache.get((calendar_id, series_id))
        if hit is not None and time.monotonic() - hit[0] < self.RULE_SECONDS:
            return hit[1]
        try:
            item = self._run(
                lambda svc: svc.events().get(calendarId=calendar_id, eventId=series_id)
            )
            rules = list(item.get("recurrence") or [])
        except HttpError:
            logger.warning("calendar: could not read the series %s's rule", series_id)
            rules = []
        cache[(calendar_id, series_id)] = (time.monotonic(), rules)
        return rules

    def _forget_rule(self, calendar_id: str, series_id: str) -> None:
        self.__dict__.setdefault("_rules", {}).pop((calendar_id, series_id), None)

    def _with_rule(self, ev: Event, calendar_id: str) -> Event:
        if ev.occurrence and not ev.recurrence:
            ev.recurrence = self._series_rule(calendar_id, ev.recurring_event_id)
        return ev

    def _locate(self, event_id: str) -> str:
        ev = self.get_event(event_id)
        if ev is None:
            raise KeyError(f"no such event {event_id}")
        return ev.calendar_id or self.calendar_id

    def identity(self) -> dict[str, Any]:
        import json

        who = "?"
        try:
            if self.auth == "oauth":
                with open(self.oauth_client) as fh:
                    who = json.load(fh).get("client_id", "?")
            else:
                with open(self.key_path) as fh:
                    who = json.load(fh).get("client_email", "?")
        except OSError:
            pass
        return {
            "backend": "google",
            "auth": self.auth,
            "service_account": who,
            "calendar": household.default_calendar_id() or self.calendar_id,
            "calendars": _wanted(None, self.calendar_id),
        }


def _naive_local(when: date | datetime) -> datetime:
    return (
        when.replace(tzinfo=None)
        if isinstance(when, datetime)
        else datetime.combine(when, datetime.min.time())
    )


def _utc_start(e: Event) -> datetime:
    tz = config.timezone()
    when = times.parse_when(e.start, tz)
    if isinstance(when, datetime):
        return when.astimezone(UTC)
    # An all-day event belongs to its calendar day in the household's zone.
    return datetime.combine(when, datetime.min.time(), tzinfo=times.zone(tz)).astimezone(UTC)


class FakeCalendar:
    """In-memory calendars with the same surface. Tests, and `LUACH_CALENDAR=fake`."""

    def __init__(self, calendars: list[CalendarInfo] | None = None) -> None:
        self.events: dict[str, Event] = {}
        self.deleted: list[str] = []
        self.known: list[CalendarInfo] = calendars or [
            CalendarInfo(id="fake", name="Fake calendar", color="#f4b942", primary=True)
        ]

    def calendars(self) -> list[CalendarInfo]:
        return list(self.known)

    def list_events(
        self,
        start: datetime,
        end: datetime,
        query: str = "",
        calendar_ids: list[str] | None = None,
    ) -> list[Event]:
        wanted = set(_wanted(calendar_ids, ""))
        if calendar_ids is not None and not wanted:
            return []
        out = []
        for e in self.events.values():
            if wanted and e.calendar_id and e.calendar_id not in wanted:
                continue
            k = _utc_start(e)
            if start.astimezone(UTC) <= k < end.astimezone(UTC) and (
                not query or query.lower() in (e.title + " " + e.description).lower()
            ):
                out.append(e)
        return sorted(out, key=_utc_start)

    def get_event(self, event_id: str, calendar_id: str = "") -> Event | None:
        ev = self.events.get(event_id)
        if ev is not None and calendar_id and ev.calendar_id != calendar_id:
            return None
        return ev

    def insert(self, draft: Draft, tz: str) -> Event:
        start, end = draft.span.as_google(tz)
        ev = Event(
            id=uuid.uuid4().hex[:12],
            title=draft.title,
            start=start.get("dateTime") or start.get("date", ""),
            end=end.get("dateTime") or end.get("date", ""),
            all_day=draft.span.all_day,
            location=draft.location,
            description=draft.description,
            recurrence=list(draft.recurrence),
            html_link="",
            creator="fake@luach",
            updated=datetime.now(UTC).isoformat(),
            calendar_id=draft.calendar_id or household.default_calendar_id() or self.known[0].id,
            attendees=list(draft.attendees),
            leader=draft.leader,
            color_id=draft.color_id,
        )
        self.events[ev.id] = ev
        return ev

    def patch(
        self,
        event_id: str,
        changes: dict[str, Any],
        tz: str,
        calendar_id: str = "",
        scope: str = repeats.THIS,
    ) -> Event:
        ev = self.events[event_id]
        if ev.recurrence:
            # A series moved to another day takes its weekly days with it.
            changes = _series_changes(ev, ev, changes, tz)
        if "title" in changes:
            ev.title = changes["title"]
        if "location" in changes:
            ev.location = changes["location"]
        if "description" in changes:
            ev.description = changes["description"]
        if changes.get("start") or changes.get("end"):
            sp = repeats.resolved_span(ev.start, ev.end, changes, tz)
            s, e = sp.as_google(tz)
            ev.start = s.get("dateTime") or s.get("date", "")
            ev.end = e.get("dateTime") or e.get("date", "")
            ev.all_day = sp.all_day
        if "recurrence" in changes:
            ev.recurrence = list(changes["recurrence"] or [])
        if "attendees" in changes:
            ev.attendees = list(changes["attendees"] or [])
        if "leader" in changes:
            ev.leader = changes["leader"] or ""
            ev.color_id = changes.get("color_id") or ""
        ev.updated = datetime.now(UTC).isoformat()
        return ev

    def delete(self, event_id: str, calendar_id: str = "", scope: str = repeats.THIS) -> None:
        self.events.pop(event_id, None)
        self.deleted.append(event_id)

    def identity(self) -> dict[str, Any]:
        return {
            "backend": "fake",
            "auth": "none",
            "service_account": "-",
            "calendar": household.default_calendar_id() or self.known[0].id,
            "calendars": _wanted(None, self.known[0].id),
        }


@dataclass
class SeriesException:
    """One occurrence of a local series that is not as the series says: deleted, or
    changed on its own (``changes`` holds the fields it has of its own)."""

    cancelled: bool = False
    changes: dict[str, Any] = field(default_factory=dict)


class LocalCalendar(FakeCalendar):
    """The same calendar, kept in luach's own database instead of in memory.

    For an environment with nobody's Google account attached: dev, a laptop, a
    demo. Events survive a restart and a deploy, because they live on the same
    volume as the threads and the audit trail. It is the fake's behaviour with
    a write-through, so the two cannot drift apart.
    """

    def __init__(self) -> None:
        super().__init__(
            [CalendarInfo(id="local", name="luach (local)", color="#f4b942", primary=True)]
        )
        #: Per series, per occurrence key: the occurrences deleted or changed on their own.
        self.exceptions: dict[str, dict[str, SeriesException]] = {}
        self._load()

    def _load(self) -> None:
        from luach import db

        with db.session() as s:
            for row in s.query(db.LocalEvent).all():
                self.events[row.id] = Event(
                    id=row.id,
                    title=row.title,
                    start=row.start,
                    end=row.end,
                    all_day=row.all_day,
                    location=row.location,
                    description=row.description,
                    recurrence=db.loads(row.recurrence_json, []),
                    attendees=db.loads(row.attendees_json, []),
                    creator=row.creator,
                    updated=row.updated,
                    calendar_id=row.calendar_id,
                    leader=row.leader or "",
                )
            for exc in s.query(db.LocalEventException).all():
                self.exceptions.setdefault(exc.series_id, {})[exc.occurrence] = SeriesException(
                    cancelled=exc.cancelled, changes=db.loads(exc.changes_json, {})
                )

    def _save(self, ev: Event) -> None:
        from luach import db

        with db.session() as s:
            row = s.get(db.LocalEvent, ev.id) or db.LocalEvent(id=ev.id)
            row.calendar_id = ev.calendar_id
            row.title = ev.title
            row.start = ev.start
            row.end = ev.end
            row.all_day = ev.all_day
            row.location = ev.location
            row.description = ev.description
            row.recurrence_json = db.dumps(list(ev.recurrence))
            row.attendees_json = db.dumps(list(ev.attendees))
            row.creator = ev.creator
            row.updated = ev.updated
            row.leader = ev.leader
            s.add(row)

    def _save_exceptions(self, series_id: str) -> None:
        """The series' exceptions in the database exactly as they are in memory."""
        from luach import db

        mine = self.exceptions.get(series_id, {})
        with db.session() as s:
            s.query(db.LocalEventException).filter_by(series_id=series_id).delete()
            for key, exc in mine.items():
                s.add(
                    db.LocalEventException(
                        series_id=series_id,
                        occurrence=key,
                        cancelled=exc.cancelled,
                        changes_json=db.dumps(exc.changes),
                    )
                )

    def insert(self, draft: Draft, tz: str) -> Event:
        ev = super().insert(draft, tz)
        ev.creator = "local@luach"
        self._save(ev)
        return ev

    # -- repeats ---------------------------------------------------------------
    # Google lists every occurrence of a repeating event; this listed only the
    # first, so on dev "breakfast every weekday" was on Thursday and never again,
    # and the board could not be tried out for a week. Occurrences are expanded
    # here with Google's id shape (<series>_<original start, local>), and carry
    # their series' rule. As in Google, one occurrence can be deleted (an EXDATE)
    # or changed on its own (an override), and both are kept in
    # local_event_exceptions; a change or a delete with scope "series" acts on
    # the series instead.

    #: What makes an occurrence's key: its original start, in the household's zone.
    KEY = "%Y%m%dT%H%M%S"

    def _split(self, event_id: str) -> tuple[str, str] | None:
        """(series, key) when the id is one occurrence of a series this holds."""
        head, _, tail = event_id.rpartition("_")
        if tail and head in self.events and self.events[head].recurrence:
            return head, tail
        return None

    def _rule(self, e: Event) -> tuple[Any, datetime, timedelta, bool] | None:
        """The series' rule over naive local times, its first start, length, and all-day-ness."""
        from dateutil.rrule import rrulestr

        first = times.parse_when(e.start, config.timezone())
        last = times.parse_when(e.end, config.timezone())
        # Naive local time: dateutil will not mix an aware start with a date-only UNTIL.
        base = _naive_local(first)
        try:
            rule = rrulestr("\n".join(e.recurrence), dtstart=base)
        except (ValueError, TypeError):
            return None
        return rule, base, _naive_local(last) - base, not isinstance(first, datetime)

    def _occurrence(self, e: Event, when: datetime, span: timedelta, all_day: bool) -> Event:
        """The occurrence of ``e`` that starts at ``when`` (naive local), as changed on its own."""
        tz = times.zone(config.timezone())
        s0, e0 = when, when + span
        occ = replace(
            e,
            id=f"{e.id}_{when:{self.KEY}}",
            start=s0.date().isoformat() if all_day else s0.replace(tzinfo=tz).isoformat(),
            end=e0.date().isoformat() if all_day else e0.replace(tzinfo=tz).isoformat(),
            recurrence=list(e.recurrence),
            recurring_event_id=e.id,
            occurrence=True,
            attendees=list(e.attendees),
        )
        exc = self.exceptions.get(e.id, {}).get(f"{when:{self.KEY}}")
        for k, v in (exc.changes if exc else {}).items():
            setattr(occ, k, list(v) if isinstance(v, list) else v)
        return occ

    def _when(self, e: Event, key: str) -> datetime | None:
        """The key's original start when it is one of the series' occurrences."""
        found = self._rule(e)
        try:
            when = datetime.strptime(key, self.KEY)
        except ValueError:
            return None
        if found is None or not found[0].between(when, when, inc=True):
            return None
        return when

    def _occurrences(self, e: Event, start: datetime, end: datetime) -> list[Event]:
        found = self._rule(e)
        if found is None:
            return [e]
        rule, _base, span, all_day = found
        tz = times.zone(config.timezone())
        lo = start.astimezone(tz).replace(tzinfo=None) - span
        hi = end.astimezone(tz).replace(tzinfo=None)
        mine = self.exceptions.get(e.id, {})
        whens = rule.between(lo, hi, inc=True)[:500]
        # An occurrence moved in from outside the window is in it all the same.
        whens += [
            w
            for key, exc in mine.items()
            if exc.changes.get("start") and (w := self._when(e, key)) is not None
        ]
        out: dict[str, Event] = {}
        for when in whens:
            exc = mine.get(f"{when:{self.KEY}}")
            if exc is not None and exc.cancelled:
                continue
            occ = self._occurrence(e, when, span, all_day)
            out[occ.id] = occ
        return list(out.values())

    def list_events(
        self,
        start: datetime,
        end: datetime,
        query: str = "",
        calendar_ids: list[str] | None = None,
    ) -> list[Event]:
        out = [e for e in super().list_events(start, end, query, calendar_ids) if not e.recurrence]
        wanted = set(_wanted(calendar_ids, ""))
        if calendar_ids is not None and not wanted:
            return out
        for e in list(self.events.values()):
            if not e.recurrence or (wanted and e.calendar_id and e.calendar_id not in wanted):
                continue
            for occ in self._occurrences(e, start, end):
                if query and query.lower() not in (occ.title + " " + occ.description).lower():
                    continue
                if start.astimezone(UTC) <= _utc_start(occ) < end.astimezone(UTC):
                    out.append(occ)
        return sorted(out, key=_utc_start)

    def get_event(self, event_id: str, calendar_id: str = "") -> Event | None:
        split = self._split(event_id)
        if split is None:
            return super().get_event(event_id, calendar_id)
        series = super().get_event(split[0], calendar_id)
        when = self._when(series, split[1]) if series is not None else None
        exc = self.exceptions.get(split[0], {}).get(split[1])
        if series is None or when is None or (exc is not None and exc.cancelled):
            return None
        found = self._rule(series)
        assert found is not None
        return self._occurrence(series, when, found[2], found[3])

    def patch(
        self,
        event_id: str,
        changes: dict[str, Any],
        tz: str,
        calendar_id: str = "",
        scope: str = repeats.THIS,
    ) -> Event:
        split = self._split(event_id)
        if split is None:
            before = self.events[event_id].start if event_id in self.events else ""
            ev = super().patch(event_id, changes, tz, calendar_id)
            self._save(ev)
            if ev.recurrence or event_id in self.exceptions:
                self._follow(ev, before)
            return ev
        seen = self.get_event(event_id, calendar_id)
        if seen is None:
            raise KeyError(f"no such event {event_id}")
        series_id, key = split
        if scope == repeats.SERIES:
            series = self.events[series_id]
            return self.patch(
                series_id, _series_changes(series, seen, changes, tz), tz, calendar_id
            )
        if "recurrence" in changes:
            raise ValueError(REPEAT_IS_THE_SERIES)
        exc = self.exceptions.setdefault(series_id, {}).setdefault(key, SeriesException())
        for k in ("title", "location", "description"):
            if k in changes:
                exc.changes[k] = changes[k]
        if "attendees" in changes:
            exc.changes["attendees"] = list(changes["attendees"] or [])
        if "leader" in changes:
            exc.changes["leader"] = changes["leader"] or ""
            exc.changes["color_id"] = changes.get("color_id") or ""
        if changes.get("start") or changes.get("end"):
            sp = repeats.resolved_span(seen.start, seen.end, changes, tz)
            s, e = sp.as_google(tz)
            exc.changes["start"] = s.get("dateTime") or s.get("date", "")
            exc.changes["end"] = e.get("dateTime") or e.get("date", "")
            exc.changes["all_day"] = sp.all_day
        exc.changes["updated"] = datetime.now(UTC).isoformat()
        self._save_exceptions(series_id)
        moved = self.get_event(event_id, calendar_id)
        assert moved is not None
        return moved

    def _follow(self, series: Event, before: str) -> None:
        """The series' exceptions after it changed: moved with its first start, as
        Google's are, and gone where they no longer name one of its occurrences."""
        mine = self.exceptions.get(series.id, {})
        if before and before != series.start:
            tz = config.timezone()
            delta = _naive_local(times.parse_when(series.start, tz)) - _naive_local(
                times.parse_when(before, tz)
            )
            mine = {
                f"{datetime.strptime(k, self.KEY) + delta:{self.KEY}}": v for k, v in mine.items()
            }
        kept = {k: v for k, v in mine.items() if self._when(series, k) is not None}
        if kept or series.id in self.exceptions:
            self.exceptions[series.id] = kept
            self._save_exceptions(series.id)

    def delete(self, event_id: str, calendar_id: str = "", scope: str = repeats.THIS) -> None:
        from luach import db

        split = self._split(event_id)
        if split is not None and scope != repeats.SERIES:
            if self.get_event(event_id, calendar_id) is None:
                return
            self.exceptions.setdefault(split[0], {})[split[1]] = SeriesException(cancelled=True)
            self._save_exceptions(split[0])
            return
        event_id = split[0] if split is not None else event_id
        super().delete(event_id, calendar_id)
        self.exceptions.pop(event_id, None)
        with db.session() as s:
            row = s.get(db.LocalEvent, event_id)
            if row is not None:
                s.delete(row)

    def identity(self) -> dict[str, Any]:
        return {
            "backend": "local",
            "auth": "none",
            "service_account": "-",
            "calendar": household.default_calendar_id() or self.known[0].id,
            "calendars": _wanted(None, self.known[0].id),
        }


_calendar: Calendar | None = None

FAKE_WARNING = (
    "calendar: LUACH_CALENDAR=fake keeps events in memory only, and every one is LOST "
    "when luach restarts. It is for tests; a household wants LUACH_CALENDAR=local."
)


def get_calendar() -> Calendar:
    global _calendar
    if _calendar is None:
        # Never a quiet fallback to memory: the server refuses to start on a calendar it
        # cannot use (config.calendar_problem), and this refuses too if anything slips by.
        problem = config.calendar_problem()
        if problem:
            raise RuntimeError(problem)
        wanted = config.calendar_backend()
        if wanted == "local":
            logger.info("calendar: keeping events in luach's own database")
            _calendar = LocalCalendar()
        elif wanted == "fake":
            logger.warning(FAKE_WARNING)
            _calendar = FakeCalendar()
        else:
            _calendar = GoogleCalendar(
                config.google_sa_key(),
                config.google_calendar_id(),
                oauth_client=config.google_oauth_client(),
                oauth_tokens=config.google_oauth_tokens(),
                auth=config.calendar_auth(),
            )
    return _calendar


def set_calendar(cal: Calendar | None) -> None:
    global _calendar
    _calendar = cal


def window(days_back: int, days_ahead: int, tz: str) -> tuple[datetime, datetime]:
    now = times.now_in(tz)
    start = (now - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = (now + timedelta(days=days_ahead)).replace(hour=23, minute=59, second=59, microsecond=0)
    return start, end
