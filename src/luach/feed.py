"""A member's calendar feed: the household's events in the phone's own calendar app.

A member turns it on in Settings and gets a secret link, ``/feed/<token>.ics``, which
Apple Calendar, Google Calendar or Outlook subscribes to and reads every few minutes.
It is read-only, and it is the only way into luach that is not a session, a key or a
paired screen, so it is kept narrow:

- The token is 32 random bytes. Only its SHA-256 is stored, so the link is shown once;
  a lost link is reset, which is also how a leaked one is closed. One per member.
- It is off until the member turns it on, and goes the moment they turn it off, reset
  it, or are removed (the row goes with the account).
- It says what the member could read in the app and nothing more: the household's
  events (or only theirs), with their titles, places, notes and whom they are for. No
  invitee or organizer addresses, nothing held for approval, no proposals from the email
  scan (those are never events until a person approves them), and no work calendars.

Repeating events stay repeating: a series is one VEVENT with its RRULE, cut to the
window the feed covers, with an EXDATE for every occurrence that was deleted (or that
is not the member's, in a feed of their own) and a RECURRENCE-ID override for every one
that was changed on its own. Where that cannot be said exactly (a rule luach cannot
read, a series written in another zone), the occurrences are listed one by one instead:
never a repeat that shows something the calendar does not hold.
"""

from __future__ import annotations

import hashlib
import hmac
import itertools
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from dateutil import parser as dtparser
from dateutil.rrule import rrulestr
from icalendar import Calendar as ICalendar
from icalendar import Event as IEvent
from icalendar import vDuration, vRecur
from sqlalchemy import exc as sa_exc
from sqlalchemy import select

from luach import config, db, family
from luach.auth import users
from luach.auth.tokens import new_token, token_hash
from luach.calendar import times
from luach.calendar.client import Event, get_calendar

logger = logging.getLogger(__name__)

HOUSEHOLD = "household"
MINE = "mine"
SCOPES = (HOUSEHOLD, MINE)

#: What secrets.token_urlsafe(32) gives: 32 random bytes as 43 base64url characters.
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
#: The one path the feed is served at, matched whole by the auth wall and by the route.
PREFIX = "/feed/"
PATH = re.compile(r"/feed/([A-Za-z0-9_-]{43})\.ics")

#: The window a feed covers, in days from today.
DAYS_BACK = 30
DAYS_AHEAD = 365
#: The window is read this many days at a time: Google answers one call with at most
#: 1000 events per calendar, and a cut-off listing would read as deleted occurrences.
CHUNK_DAYS = 92
#: A rule with more occurrences than this in the window is listed one by one.
MAX_OCCURRENCES = 2000

#: How long a calendar app or a cache may keep a copy, and how often to ask again.
CACHE_SECONDS = 600
REFRESH = timedelta(minutes=15)
#: last_read is written at most this often: a feed read every five minutes is not a
#: database write every five minutes.
SEEN_EVERY = timedelta(minutes=5)


class AlreadyOn(Exception):
    """The member's feed is on already: a new link is a reset, which they ask for."""


# -- the member's link ---------------------------------------------------------


def _scope(scope: str) -> str:
    s = (scope or HOUSEHOLD).strip().lower()
    if s not in SCOPES:
        raise ValueError("scope is household (everyone's events) or mine (only yours)")
    return s


def status(user_id: int) -> dict[str, Any]:
    """Whether the member's feed is on, what it holds, and when it was last read. Never the
    link: luach does not have it."""
    with db.session() as s:
        row = s.get(db.CalendarFeed, user_id)
        if row is None:
            return {"enabled": False, "scope": HOUSEHOLD, "created_at": None, "last_read": None}
        return {
            "enabled": True,
            "scope": row.scope,
            "created_at": db.iso(row.created_at),
            "last_read": db.iso(row.last_read),
        }


def turn_on(user_id: int, scope: str = HOUSEHOLD) -> str:
    """A new feed for the member; its token, which is never stored. AlreadyOn when the
    member has one: a second Turn on would quietly break the first link."""
    scope = _scope(scope)
    token = new_token()
    try:
        with db.session() as s:
            if s.get(db.CalendarFeed, user_id) is not None:
                raise AlreadyOn
            s.add(db.CalendarFeed(user_id=user_id, token_hash=token_hash(token), scope=scope))
    except sa_exc.IntegrityError as exc:  # two taps at once: the other one won
        raise AlreadyOn from exc
    return token


def reset(user_id: int) -> str:
    """A new link for the member's feed, the old one dead from now; KeyError when it is off."""
    token = new_token()
    with db.session() as s:
        row = s.get(db.CalendarFeed, user_id)
        if row is None:
            raise KeyError("the calendar feed is off")
        row.token_hash = token_hash(token)
        row.created_at = db.utcnow()
        row.last_read = None
    return token


def set_scope(user_id: int, scope: str) -> None:
    """What the member's feed holds, on the same link; KeyError when it is off."""
    scope = _scope(scope)
    with db.session() as s:
        row = s.get(db.CalendarFeed, user_id)
        if row is None:
            raise KeyError("the calendar feed is off")
        row.scope = scope


def turn_off(user_id: int) -> bool:
    """The member's feed gone, its link dead; False when there was none."""
    with db.session() as s:
        row = s.get(db.CalendarFeed, user_id)
        if row is None:
            return False
        s.delete(row)
        return True


def links(token: str, base: str) -> dict[str, str]:
    """The link, and the same one as webcal:// (which a phone opens in its calendar app)."""
    url = f"{base.rstrip('/')}{PREFIX}{token}.ics"
    return {"url": url, "webcal": re.sub(r"^https?://", "webcal://", url)}


@dataclass(frozen=True)
class Feed:
    user_id: int
    scope: str
    token_hash: str
    last_read: datetime | None


def lookup(token: str) -> Feed | None:
    """The feed this token opens, or None: not a token, nobody's, revoked, or a member
    who is gone. Looked up by the token's hash, never the token, and the hash found is
    compared again in constant time."""
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        return None
    wanted = token_hash(token)
    with db.session() as s:
        row = s.execute(
            select(db.CalendarFeed).where(db.CalendarFeed.token_hash == wanted)
        ).scalar_one_or_none()
        if row is None or not hmac.compare_digest(row.token_hash.encode(), wanted.encode()):
            return None
        if s.get(db.User, row.user_id) is None:
            return None
        return Feed(row.user_id, row.scope, row.token_hash, row.last_read)


def seen(feed: Feed, now: datetime | None = None) -> None:
    """Note that a calendar app read the feed, at most every SEEN_EVERY."""
    now = now or db.utcnow()
    if feed.last_read is not None and now - feed.last_read < SEEN_EVERY:
        return
    with db.session() as s:
        row = s.get(db.CalendarFeed, feed.user_id)
        if row is not None and row.token_hash == feed.token_hash:
            row.last_read = now


def etag(body: bytes) -> str:
    return '"' + hashlib.sha256(body).hexdigest()[:32] + '"'


def matches(if_none_match: str, tag: str) -> bool:
    """Whether an If-None-Match header names this ETag (weakly, as RFC 9110 has it for GET)."""
    for part in if_none_match.split(","):
        part = part.strip()
        if part == "*" or part.removeprefix("W/") == tag:
            return True
    return False


# -- what is in it -------------------------------------------------------------

_FOR = {"en": "For {}", "es": "Para {}", "he": "עבור {}"}
_AND = {"en": "and", "es": "y"}


def _language(member: users.Member) -> str:
    return member.language if member.language in _FOR else "en"


def join_names(names: list[str], lang: str) -> str:
    """ "Ruby and Lily", "Ruby, Lily, and Noa": as the app says it (Intl.ListFormat)."""
    if len(names) <= 1:
        return "".join(names)
    if lang == "he":
        last = names[-1]
        hebrew = bool(last) and "א" <= last[0] <= "ת"
        return f"{', '.join(names[:-1])} {'ו' if hebrew else 'ו-'}{last}"
    word = _AND.get(lang, "and")
    if len(names) == 2 or lang != "en":
        return f"{', '.join(names[:-1])} {word} {names[-1]}"
    return f"{', '.join(names[:-1])}, {word} {names[-1]}"


@dataclass(frozen=True)
class _View:
    """Who is reading, and how their feed is to be written."""

    scope: str
    me: family.Person | None
    people: list[family.Person]
    lang: str
    zone: Any
    stamp: datetime

    def leaders(self, ev: Event) -> list[family.Person]:
        return family.leaders_for(ev, self.people)

    def shows(self, ev: Event) -> bool:
        """Whether this event is in the feed. A feed of one's own holds the events that are
        theirs, and the ones that are nobody's in particular, which are everyone's."""
        if self.scope == HOUSEHOLD:
            return True
        found = self.leaders(ev)
        return not found or (self.me is not None and self.me in found)


def _read(start: datetime, end: datetime) -> list[Event]:
    """Every event the app would list from start to end, read a stretch at a time."""
    cal = get_calendar()
    out: dict[str, Event] = {}
    lo = start
    while lo < end:
        hi = min(lo + timedelta(days=CHUNK_DAYS), end)
        for ev in cal.list_events(lo, hi):
            out.setdefault(ev.id, ev)
        lo = hi
    return list(out.values())


def _naive(when: datetime | date, zone: Any) -> datetime:
    """A start as the household's wall clock, which is what a rule repeats in."""
    if isinstance(when, datetime):
        return when.astimezone(zone).replace(tzinfo=None)
    return datetime.combine(when, time.min)


def _parse(value: str, zone: Any) -> datetime | date:
    when = times.parse_when(value, str(zone))
    return when.astimezone(zone) if isinstance(when, datetime) else when


_ORIGINAL = re.compile(r"(\d{8})(?:T(\d{6})(Z?))?")


def _original(occ: Event, zone: Any) -> datetime | None:
    """An occurrence's original start (the household's wall clock), from its id: Google's
    ``<series>_20261025T130000Z`` (UTC) or ``<series>_20261025`` (all day), the local
    calendar's ``<series>_20261025T090000``."""
    head = occ.recurring_event_id + "_"
    if not occ.recurring_event_id or not occ.id.startswith(head):
        return None
    m = _ORIGINAL.fullmatch(occ.id[len(head) :])
    if m is None:
        return None
    try:
        when = datetime.strptime(m.group(1) + (m.group(2) or "000000"), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    if m.group(3):
        return when.replace(tzinfo=UTC).astimezone(zone).replace(tzinfo=None)
    return when


def _uid(event_id: str) -> str:
    return f"{event_id}@luach"


def _modified(ev: Event) -> datetime | None:
    if not ev.updated:
        return None
    try:
        when = dtparser.isoparse(ev.updated)
    except ValueError:
        return None
    return (
        (when if when.tzinfo else when.replace(tzinfo=UTC)).astimezone(UTC).replace(microsecond=0)
    )


def _at(when: datetime, all_day: bool, zone: Any) -> datetime | date:
    """A naive wall-clock start as the feed writes it: a DATE, or a time in the zone."""
    return when.date() if all_day else when.replace(tzinfo=zone)


def _describe(view: _View, ev: Event, comp: IEvent) -> None:
    """Title, place, notes, and whom it is for — no addresses, no links."""
    found = view.leaders(ev)
    names = [p.name for p in found]
    title = ev.title or "(untitled)"
    if names and view.scope == HOUSEHOLD:
        # "Ruby: Soccer" — luach's own way of saying whose an event is, and on a phone
        # with one colour for the whole calendar, the only way to see it.
        missing = [n for n in names if n.casefold() not in title.casefold()]
        if missing:
            title = f"{join_names(names, view.lang)}: {title}"
    comp.add("summary", title)
    if ev.location:
        comp.add("location", ev.location)
    notes = []
    if names:
        notes.append(_FOR[view.lang].format(join_names(names, view.lang)))
    if ev.description:
        notes.append(ev.description)
    if notes:
        comp.add("description", "\n\n".join(notes))


def _vevent(
    view: _View,
    ev: Event,
    uid: str,
    start: datetime | date,
    end: datetime | date,
) -> IEvent:
    comp = IEvent()
    comp.add("uid", uid)
    modified = _modified(ev)
    comp.add("dtstamp", modified or view.stamp)
    if modified is not None:
        comp.add("last-modified", modified)
    comp.add("dtstart", start)
    comp.add("dtend", end)
    _describe(view, ev, comp)
    comp.add("transp", "OPAQUE")
    return comp


def _single(view: _View, ev: Event, uid: str | None = None) -> IEvent:
    start = _parse(ev.start, view.zone)
    end = _parse(ev.end, view.zone) if ev.end else start
    if not isinstance(start, datetime) and isinstance(end, datetime):
        end = end.date()
    if end <= start:  # type: ignore[operator]
        end = start + timedelta(days=1) if not isinstance(start, datetime) else start
    comp = _vevent(view, ev, uid or _uid(ev.id), start, end)
    if not ev.occurrence:
        # The fake calendar lists a series once, as itself: its rule goes as it is.
        for rule in ev.recurrence:
            if rule.upper().startswith("RRULE:"):
                comp.add("rrule", vRecur.from_ical(rule[6:]))
    return comp


def _same(view: _View, occ: Event, master: Event, start: datetime, end: datetime) -> bool:
    """Whether an occurrence is exactly what its series says it is at that original start."""
    try:
        s, e = _parse(occ.start, view.zone), _parse(occ.end, view.zone)
    except ValueError:
        return False
    all_day = not isinstance(_parse(master.start, view.zone), datetime)
    want_s, want_e = _at(start, all_day, view.zone), _at(end, all_day, view.zone)
    return (
        type(s) is type(want_s)
        and s == want_s
        and e == want_e
        and (occ.title, occ.location, occ.description)
        == (
            master.title,
            master.location,
            master.description,
        )
        and [p.key for p in view.leaders(occ)] == [p.key for p in view.leaders(master)]
    )


def _series(
    view: _View, master: Event, occs: list[Event], lo: datetime, hi: datetime
) -> list[IEvent] | None:
    """A repeating event as one VEVENT and its exceptions, cut to the window [lo, hi) (the
    household's wall clock); None when that cannot be said exactly, and the occurrences are
    to be listed one by one."""
    rules = [r for r in master.recurrence if r.upper().startswith("RRULE:")]
    others = [r for r in master.recurrence if not r.upper().startswith(("RRULE:", "EXDATE"))]
    if len(rules) != 1 or others:
        return None
    try:
        first = _parse(master.start, view.zone)
        last = _parse(master.end, view.zone) if master.end else first
        base = _naive(first, view.zone)
        span = _naive(last, view.zone) - base
        recur = vRecur.from_ical(rules[0][6:])
        until = recur.get("UNTIL") or []
        if until and isinstance(until[0], datetime) and until[0].tzinfo is not None:
            # Google ends a series at a UTC instant; the rule repeats on the wall clock.
            recur["UNTIL"] = [until[0].astimezone(view.zone).replace(tzinfo=None)]
        rule = rrulestr("RRULE:" + recur.to_ical().decode(), dtstart=base)
        expected = list(
            itertools.takewhile(
                lambda w: w < hi, itertools.islice(rule.xafter(lo, inc=True), MAX_OCCURRENCES + 1)
            )
        )
    except (ValueError, TypeError, OverflowError):
        return None
    if len(expected) > MAX_OCCURRENCES:
        return None
    all_day = not isinstance(first, datetime)
    listed: dict[datetime, Event] = {}
    extras: list[Event] = []
    known = set(expected)
    for occ in occs:
        original = _original(occ, view.zone)
        if original is None:
            return None
        if original in known:
            listed[original] = occ
        elif lo <= original < hi:
            # The rule, read here, says no occurrence starts then, and the calendar says
            # one does: a series written in another zone, say. Not guessed at.
            return None
        else:
            extras.append(occ)  # moved into the window from outside it
    shown = [w for w in expected if w in listed and view.shows(listed[w])]
    out = [_single(view, occ, _uid(occ.id)) for occ in extras if view.shows(occ)]
    if not shown:
        return out
    begin, end_ = shown[0], shown[-1]
    for part in ("COUNT", "UNTIL"):
        recur.pop(part, None)
    body = recur.to_ical().decode()
    # The rule from its new first start must give exactly the occurrences it gave before.
    try:
        again = list(rrulestr(f"RRULE:{body};UNTIL={end_:%Y%m%dT%H%M%S}", dtstart=begin))
    except (ValueError, TypeError):
        return None
    if again != [w for w in expected if begin <= w <= end_]:
        return None
    recur["UNTIL"] = [end_.date() if all_day else end_.replace(tzinfo=view.zone).astimezone(UTC)]
    uid = _uid(master.id)
    comp = _vevent(
        view, master, uid, _at(begin, all_day, view.zone), _at(begin + span, all_day, view.zone)
    )
    comp.add("rrule", recur)
    skipped = [_at(w, all_day, view.zone) for w in again if w not in shown]
    if skipped:
        comp.add("exdate", skipped)
    out.insert(0, comp)
    for when in shown:
        occ = listed[when]
        if _same(view, occ, master, when, when + span):
            continue
        override = _single(view, occ, uid)
        override.add("recurrence-id", _at(when, all_day, view.zone))
        out.append(override)
    return out


def _components(view: _View, events: Iterable[Event], lo: datetime, hi: datetime) -> list[IEvent]:
    cal = get_calendar()
    singles: list[Event] = []
    series: dict[tuple[str, str], list[Event]] = {}
    for ev in events:
        if ev.occurrence and ev.recurring_event_id:
            series.setdefault((ev.calendar_id, ev.recurring_event_id), []).append(ev)
        elif view.shows(ev):
            singles.append(ev)
    out = [_single(view, ev) for ev in singles]
    for (cid, sid), occs in series.items():
        master = cal.get_event(sid, cid)
        made = _series(view, master, occs, lo, hi) if master is not None else None
        if made is None:
            made = [_single(view, occ) for occ in occs if view.shows(occ)]
        out.extend(made)
    return out


def _sort_key(comp: IEvent) -> tuple[str, str]:
    rid = comp.get("recurrence-id")
    return (str(comp.get("uid")), rid.to_ical().decode() if rid is not None else "")


def render(user_id: int, scope: str, *, now: datetime | None = None) -> bytes:
    """The member's feed as iCalendar. The same calendar gives the same bytes all day, so
    the ETag (feed.etag) only changes when something in it does, or the day does."""
    member = users.member(user_id)
    if member is None:
        raise KeyError("no such member")
    tz = config.timezone()
    zone = times.zone(tz)
    today = (now or times.now_in(tz)).astimezone(zone).date()
    start = datetime.combine(today - timedelta(days=DAYS_BACK), time.min, tzinfo=zone)
    end = datetime.combine(today + timedelta(days=DAYS_AHEAD + 1), time.min, tzinfo=zone)
    people = family.roster()
    view = _View(
        scope=_scope(scope),
        me=next((p for p in people if p.user_id == user_id), None),
        people=people,
        lang=_language(member),
        zone=zone,
        stamp=datetime.combine(today, time.min, tzinfo=UTC),
    )
    comps = _components(
        view, _read(start, end), start.replace(tzinfo=None), end.replace(tzinfo=None)
    )
    cal = ICalendar()
    cal.add("prodid", "-//luach//calendar feed//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    name = "luach" if view.scope == HOUSEHOLD else f"luach · {member.display_name}"
    cal.add("name", name)
    cal.add("x-wr-calname", name)
    cal.add("x-wr-timezone", tz)
    cal.add("refresh-interval", REFRESH, parameters={"VALUE": "DURATION"})
    cal.add("x-published-ttl", vDuration(REFRESH))
    for comp in sorted(comps, key=_sort_key):
        cal.add_component(comp)
    cal.add_missing_timezones(
        first_date=today - timedelta(days=DAYS_BACK + 366), last_date=today + timedelta(days=800)
    )
    return bytes(cal.to_ical())
