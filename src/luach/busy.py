"""Calendars luach may not write to, and may not even read properly — only the
shape of the time they take.

The work calendar is the case this exists for. luach cannot be given access to
Acme's, but a published iCalendar feed is enough to know *when* a member is
busy, which is all the booking page needs: it must never offer a stranger a slot
that is already a meeting. Titles are read but kept out of the household's way —
an agenda entry says "Busy", never "Quarterly review with …".

A feed is fetched on a timer rather than on demand: a booking page must not wait
on someone else's server, and a feed that goes down should cost freshness, not
availability. The blocks last fetched stay in the database and keep working.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from luach import config, db
from luach.calendar import times

logger = logging.getLogger(__name__)

#: A feed is someone else's server: cap what we will read and how long we wait.
FETCH_TIMEOUT = 20
MAX_FEED_BYTES = 8 * 1024 * 1024
#: Redirects followed by hand, each to a public address like the first.
MAX_REDIRECTS = 3
#: How far ahead blocks are kept. Bookings look at most a few months out.
HORIZON_DAYS = 180
#: Occurrences read from one feed in that window. A working week of meetings for six
#: months is a few thousand; a rule like FREQ=SECONDLY is fifteen million.
MAX_OCCURRENCES = 5000
MAX_SOURCES = 5
REFRESH_MINUTES = 15


class FeedRefused(ValueError):
    """Why a feed was not read, in luach's own words: safe to store and to show. Never
    the feed's own text, which may be another server's page (or an internal one's)."""


@dataclass(frozen=True)
class Block:
    start: datetime
    end: datetime


def _norm(url: str) -> str:
    """webcal:// is an iCalendar feed wearing a different hat."""
    url = url.strip()
    if url.lower().startswith("webcal://"):
        return "https://" + url[len("webcal://") :]
    return url


def sources_for(user_id: int) -> list[dict[str, Any]]:
    with db.session() as s:
        rows = (
            s.execute(
                select(db.BusySource)
                .where(db.BusySource.user_id == user_id)
                .order_by(db.BusySource.id)
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": r.id,
                "name": r.name,
                "url": r.url,
                "enabled": r.enabled,
                "show_in_agenda": r.show_in_agenda,
                "last_fetched": db.iso(r.last_fetched),
                "last_error": r.last_error,
                "blocks": r.block_count,
            }
            for r in rows
        ]


def _not_public(url: str) -> str | None:
    """Why ``url`` is not a public address, or None (websearch's check, shared)."""
    from luach.websearch import public_url

    return public_url(url)


def add_source(user_id: int, name: str, url: str, *, show_in_agenda: bool = True) -> dict[str, Any]:
    url = _norm(url)
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("that is not a calendar feed address")
    if _not_public(url):
        # luach's own network (the database, the model, the cluster) is no calendar.
        raise ValueError("that calendar feed is not at a public internet address")
    name = name.strip()[:80] or "Work"
    with db.session() as s:
        count = len(
            s.execute(select(db.BusySource).where(db.BusySource.user_id == user_id)).scalars().all()
        )
        if count >= MAX_SOURCES:
            raise ValueError(f"at most {MAX_SOURCES} calendars")
        s.add(
            db.BusySource(
                user_id=user_id, name=name, url=url, enabled=True, show_in_agenda=show_in_agenda
            )
        )
    refresh_for(user_id)
    return {"sources": sources_for(user_id)}


def update_source(user_id: int, source_id: int, **changes: Any) -> dict[str, Any]:
    with db.session() as s:
        row = s.get(db.BusySource, source_id)
        if row is None or row.user_id != user_id:
            raise ValueError("that calendar is not yours")
        if "enabled" in changes:
            row.enabled = bool(changes["enabled"])
        if "show_in_agenda" in changes:
            row.show_in_agenda = bool(changes["show_in_agenda"])
        if "name" in changes:
            row.name = str(changes["name"]).strip()[:80] or row.name
    return {"sources": sources_for(user_id)}


def remove_source(user_id: int, source_id: int) -> dict[str, Any]:
    with db.session() as s:
        row = s.get(db.BusySource, source_id)
        if row is None or row.user_id != user_id:
            raise ValueError("that calendar is not yours")
        for block in s.execute(
            select(db.BusyBlock).where(db.BusyBlock.source_id == source_id)
        ).scalars():
            s.delete(block)
        s.delete(row)
    return {"sources": sources_for(user_id)}


# --- fetching --------------------------------------------------------------


NOT_PUBLIC = "that address is not on the public internet"


def _public_peer(sock: Any) -> None:
    """The address actually connected to must be public too: a name that resolved to a
    public address when it was checked can resolve to an internal one a moment later."""
    import ipaddress

    peer = ipaddress.ip_address(str(sock.getpeername()[0]).split("%")[0])
    if not peer.is_global:
        sock.close()
        raise FeedRefused(NOT_PUBLIC)


def _session() -> Any:
    """requests, refusing to connect anywhere but a public address. No proxies from the
    environment: the address checked must be the one connected to."""
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.connection import HTTPConnection, HTTPSConnection
    from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

    class PublicHTTP(HTTPConnection):
        def _new_conn(self) -> Any:
            sock = super()._new_conn()
            _public_peer(sock)
            return sock

    class PublicHTTPS(HTTPSConnection):
        def _new_conn(self) -> Any:
            sock = super()._new_conn()
            _public_peer(sock)
            return sock

    class PoolHTTP(HTTPConnectionPool):
        ConnectionCls = PublicHTTP

    class PoolHTTPS(HTTPSConnectionPool):
        ConnectionCls = PublicHTTPS

    class Adapter(HTTPAdapter):
        def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
            super().init_poolmanager(*args, **kwargs)
            self.poolmanager.pool_classes_by_scheme = {"http": PoolHTTP, "https": PoolHTTPS}

    session = requests.Session()
    session.trust_env = False
    session.mount("http://", Adapter())
    session.mount("https://", Adapter())
    return session


def fetch_feed(url: str) -> bytes:
    """The feed's bytes. Only from public addresses, every redirect checked like the
    first; FeedRefused (with luach's own words) for anything that is not a feed."""
    from urllib.parse import urljoin

    import requests

    with _session() as session:
        for _ in range(MAX_REDIRECTS + 1):
            if _not_public(url):
                raise FeedRefused(NOT_PUBLIC)
            try:
                r = session.get(
                    url,
                    timeout=FETCH_TIMEOUT,
                    headers={"User-Agent": config.user_agent()},
                    stream=True,
                    allow_redirects=False,
                )
            except FeedRefused:
                raise
            except requests.RequestException as exc:
                if isinstance(exc.__context__, FeedRefused):
                    raise exc.__context__ from exc
                raise FeedRefused("the feed could not be reached") from exc
            with r:
                if r.is_redirect and r.headers.get("location"):
                    url = urljoin(url, r.headers["location"])
                    continue
                if r.status_code >= 400:
                    raise FeedRefused(f"the feed answered HTTP {r.status_code}")
                body = r.raw.read(MAX_FEED_BYTES + 1, decode_content=True) or b""
            if len(body) > MAX_FEED_BYTES:
                raise FeedRefused("that feed is larger than luach will read")
            return body
    raise FeedRefused("the feed kept redirecting")


def parse_blocks(raw: bytes, horizon_days: int = HORIZON_DAYS) -> list[Block]:
    """Every busy span in the window, recurrences expanded, all-day skipped.

    An all-day entry on a work calendar is usually a holiday marker or someone
    else's leave; treating it as eight hours of meetings would empty the week.
    """
    import icalendar
    import recurring_ical_events

    try:
        cal = icalendar.Calendar.from_ical(raw)
    except Exception as exc:
        raise FeedRefused("that is not a calendar feed") from exc
    start = datetime.now(UTC) - timedelta(days=1)
    end = start + timedelta(days=horizon_days + 1)
    out: list[Block] = []
    # One at a time, in order (``after`` is lazy; ``between`` builds the whole list
    # first), and no more than MAX_OCCURRENCES of them.
    for seen, event in enumerate(recurring_ical_events.of(cal).after(start)):
        if seen >= MAX_OCCURRENCES:
            raise FeedRefused("that feed has more events than luach will read")
        s = getattr(event.get("DTSTART"), "dt", None)
        if s is None:
            continue
        begins = s if isinstance(s, datetime) else datetime.combine(s, datetime.min.time())
        if (begins if begins.tzinfo else begins.replace(tzinfo=UTC)) >= end:
            break
        if str(event.get("STATUS", "")).upper() == "CANCELLED":
            continue
        if str(event.get("TRANSP", "")).upper() == "TRANSPARENT":
            continue  # marked "free" by whoever owns the calendar
        e = getattr(event.get("DTEND"), "dt", None) or s
        if not isinstance(s, datetime) or not isinstance(e, datetime):
            continue  # an all-day entry: a marker, not a meeting
        if s.tzinfo is None:
            s = s.replace(tzinfo=UTC)
        if e.tzinfo is None:
            e = e.replace(tzinfo=UTC)
        if e <= s:
            e = s + timedelta(minutes=30)
        out.append(Block(s.astimezone(UTC), e.astimezone(UTC)))
    return sorted(out, key=lambda b: b.start)


def refresh_for(user_id: int | None = None) -> int:
    """Re-read every enabled feed (or one member's). Returns how many were read."""
    with db.session() as s:
        q = select(db.BusySource).where(db.BusySource.enabled.is_(True))
        if user_id is not None:
            q = q.where(db.BusySource.user_id == user_id)
        rows = [(r.id, r.url) for r in s.execute(q).scalars().all()]
    done = 0
    for source_id, url in rows:
        try:
            blocks = parse_blocks(fetch_feed(url))
        except Exception as exc:  # a feed nobody can reach must not break the app
            logger.warning("busy: %s could not be read: %s", _label(url), type(exc).__name__)
            # luach's own words only: an exception's text can carry the response it
            # came from, and that response may be from a server nobody should read.
            said = str(exc) if isinstance(exc, FeedRefused) else "the feed could not be read"
            with db.session() as s:
                row = s.get(db.BusySource, source_id)
                if row is not None:
                    row.last_error = said
                    row.last_fetched = db.utcnow()
            continue
        _store(source_id, blocks)
        done += 1
    return done


def _label(url: str) -> str:
    """A feed URL is a bearer token in disguise — name it by its host and a digest."""
    host = url.split("/")[2] if "//" in url else url[:20]
    return f"{host}#{hashlib.sha256(url.encode()).hexdigest()[:8]}"


def _store(source_id: int, blocks: list[Block]) -> None:
    with db.session() as s:
        for old in s.execute(
            select(db.BusyBlock).where(db.BusyBlock.source_id == source_id)
        ).scalars():
            s.delete(old)
        s.flush()
        for b in blocks:
            s.add(
                db.BusyBlock(
                    source_id=source_id,
                    start=b.start.isoformat(),
                    end=b.end.isoformat(),
                )
            )
        row = s.get(db.BusySource, source_id)
        if row is not None:
            row.last_fetched = db.utcnow()
            row.last_error = ""
            row.block_count = len(blocks)


# --- reading ---------------------------------------------------------------


def blocks_between(
    user_id: int, start: datetime, end: datetime, *, agenda_only: bool = False
) -> list[Block]:
    """Busy spans that overlap the window, from this member's feeds."""
    with db.session() as s:
        q = (
            select(db.BusyBlock)
            .join(db.BusySource, db.BusySource.id == db.BusyBlock.source_id)
            .where(db.BusySource.user_id == user_id, db.BusySource.enabled.is_(True))
        )
        if agenda_only:
            q = q.where(db.BusySource.show_in_agenda.is_(True))
        rows = s.execute(q).scalars().all()
    lo, hi = start.astimezone(UTC), end.astimezone(UTC)
    out: list[Block] = []
    for r in rows:
        try:
            bs = datetime.fromisoformat(r.start)
            be = datetime.fromisoformat(r.end)
        except ValueError:
            continue
        if bs < hi and be > lo:
            out.append(Block(bs, be))
    return sorted(out, key=lambda b: b.start)


def as_events(user_id: int, start: datetime, end: datetime, tz: str) -> list[dict[str, Any]]:
    """Busy spans shaped like calendar events, for the agenda. No titles: the
    household sees that the time is taken, not what it is taken by."""
    out = []
    for b in blocks_between(user_id, start, end, agenda_only=True):
        local_start = b.start.astimezone(times.zone(tz))
        local_end = b.end.astimezone(times.zone(tz))
        ident = hashlib.sha256(f"{b.start}{b.end}".encode()).hexdigest()[:12]
        out.append(
            {
                "id": f"busy-{ident}",
                "title": "Busy",
                "start": local_start.isoformat(),
                "end": local_end.isoformat(),
                "all_day": False,
                "location": "",
                "description": "",
                "recurrence": [],
                "recurring_event_id": "",
                "occurrence": False,
                "html_link": "",
                "creator": "",
                "updated": "",
                "calendar_id": "",
                "attendees": [],
                "invite_error": "",
                # The UI must not offer to edit or delete what it cannot change.
                "read_only": True,
            }
        )
    return out


def busy_spans(user_id: int | None, day: date, tz: str) -> list[tuple[datetime, datetime]]:
    """What the booking page subtracts, in the member's own zone."""
    if user_id is None:
        return []
    start, end = times.day_bounds(day.isoformat(), tz)
    zone = times.zone(tz)
    return [
        (b.start.astimezone(zone), b.end.astimezone(zone))
        for b in blocks_between(user_id, start, end)
    ]
