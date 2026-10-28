"""Datetime hygiene. The model writes ISO strings; this module makes them
honest: timezone-aware, in the member's zone, all-day detected."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil import parser as dtparser

DATE_ONLY_LEN = 10


@dataclass(frozen=True)
class Span:
    start: datetime | date
    end: datetime | date
    all_day: bool

    def as_google(self, tz: str) -> tuple[dict, dict]:
        if self.all_day:
            return {"date": self.start.isoformat()}, {"date": self.end.isoformat()}
        assert isinstance(self.start, datetime) and isinstance(self.end, datetime)
        return (
            {"dateTime": self.start.isoformat(), "timeZone": tz},
            {"dateTime": self.end.isoformat(), "timeZone": tz},
        )


def zone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except Exception:
        return ZoneInfo("America/New_York")


def now_in(tz: str) -> datetime:
    return datetime.now(zone(tz))


def parse_when(value: str, tz: str) -> datetime | date:
    """A date for ``YYYY-MM-DD``; otherwise an aware datetime in ``tz``."""
    raw = value.strip()
    if not raw:
        raise ValueError("empty date")
    if len(raw) == DATE_ONLY_LEN and raw[4] == "-" and raw[7] == "-":
        return date.fromisoformat(raw)
    dt = dtparser.isoparse(raw) if "T" in raw or raw.count(":") >= 1 else dtparser.parse(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zone(tz))
    return dt.astimezone(zone(tz))


#: An ISO datetime with an offset or a Z on the end.
_WITH_OFFSET = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)(?:Z|[+-]\d{2}(?::?\d{2})?)$"
)


def wall_clock(value: str) -> str:
    """A time a model wrote, as the wall-clock time it means: any offset dropped.

    The tools take local times and apply the member's zone. A model copies the
    offset of an event it read earlier in the conversation, though, and on a day
    past a clock change that offset is wrong by an hour: "move it to Sunday, same
    time" from Saturday 12:00 (-04:00) was written as Sunday 11:00, the first
    day of winter time.
    """
    m = _WITH_OFFSET.match(value.strip())
    return m.group(1) if m else value


def span(start: str, end: str | None, tz: str, default_minutes: int = 60) -> Span:
    """Resolve start/end strings into a Span; end defaults to +60 min or +1 day."""
    s = parse_when(start, tz)
    if isinstance(s, date) and not isinstance(s, datetime):
        e = parse_when(end, tz) if end else s + timedelta(days=1)
        if isinstance(e, datetime):
            e = e.date()
        if e <= s:
            e = s + timedelta(days=1)
        return Span(s, e, True)
    e_dt: datetime
    parsed = parse_when(end, tz) if end else None
    e_dt = parsed if isinstance(parsed, datetime) else s + timedelta(minutes=default_minutes)
    if e_dt <= s:
        raise ValueError("end must be after start")
    return Span(s, e_dt, False)


def day_bounds(day: str, tz: str) -> tuple[datetime, datetime]:
    """Aware datetimes for the start and end of a YYYY-MM-DD day in ``tz``."""
    d = parse_when(day.strip()[:DATE_ONLY_LEN], tz)
    if isinstance(d, datetime):
        d = d.date()
    z = zone(tz)
    return (
        datetime.combine(d, datetime.min.time(), tzinfo=z),
        datetime.combine(d, datetime.max.time().replace(microsecond=0), tzinfo=z),
    )


def is_past(when: datetime | date, tz: str, grace_minutes: int = 5) -> bool:
    now = now_in(tz)
    if isinstance(when, datetime):
        return when < now - timedelta(minutes=grace_minutes)
    return when < now.date()


def describe(start: datetime | date, end: datetime | date | None, tz: str) -> str:
    """A short human line: 'Tue 16 Sep, 15:00–15:45' or 'Sat 20 Sep (all day)'."""
    if isinstance(start, datetime):
        s = start.astimezone(zone(tz))
        line = s.strftime("%a %d %b %Y, %H:%M")
        if isinstance(end, datetime):
            e = end.astimezone(zone(tz))
            line += "–" + (
                e.strftime("%H:%M") if e.date() == s.date() else e.strftime("%a %d %b %H:%M")
            )
        return line
    return start.strftime("%a %d %b %Y") + " (all day)"


def to_utc_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def describe_range(start: datetime, end: datetime, tz: str) -> str:
    """'Fri 11 – Thu 17 Sep 2026', or 'Fri 11 Sep 2026' for one day."""
    s = start.astimezone(zone(tz))
    e = end.astimezone(zone(tz))
    if s.date() == e.date():
        return s.strftime("%a %d %b %Y")
    if s.month == e.month and s.year == e.year:
        return f"{s.strftime('%a %d')} – {e.strftime('%a %d %b %Y')}"
    return f"{s.strftime('%a %d %b')} – {e.strftime('%a %d %b %Y')}"
