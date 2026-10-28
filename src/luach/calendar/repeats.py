"""Repeating events: the parts every calendar backend shares.

A repeating event is a series (one event carrying an RRULE) listed as its
occurrences, each with Google's id shape ``<series>_<original start>``. A change
to one occurrence is either to that occurrence alone (scope ``this``) or to the
whole series (scope ``series``). The series has no idea which occurrence the
person was looking at, so a change made "to all events" from one of them is
translated here into the same change to the series: moving Thursday's 16:00
practice to Friday at 17:00 moves the series' first day by one and its time to
17:00, and its ``BYDAY`` with it.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from luach.calendar import times

#: What a PATCH or a DELETE on an occurrence acts on.
THIS = "this"
SERIES = "series"
SCOPES = (THIS, SERIES)

DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]  # date.weekday() order

#: The repeats a person picks from a menu, which the server anchors to the
#: event's own day: a client that worked the weekday out itself got it wrong
#: west of UTC (``new Date('2026-09-17')`` is the 16th in New York).
WORDS: dict[str, str] = {
    "none": "",
    "daily": "FREQ=DAILY",
    "weekly": "FREQ=WEEKLY;BYDAY={day}",
    "biweekly": "FREQ=WEEKLY;INTERVAL=2;BYDAY={day}",
    "monthly": "FREQ=MONTHLY",
    "yearly": "FREQ=YEARLY",
}


def rule_for(word: str, start: date | datetime) -> list[str]:
    """``"weekly"`` as the RRULE for an event that starts at ``start`` (local)."""
    body = WORDS[word.strip().lower()]
    if not body:
        return []
    return ["RRULE:" + body.format(day=DAYS[start.weekday()])]


def is_word(value: str) -> bool:
    return value.strip().lower() in WORDS


def _day(when: date | datetime) -> date:
    return when.date() if isinstance(when, datetime) else when


def _iso(when: date | datetime) -> str:
    return when.isoformat()


def resolved_span(start: str, end: str, changes: dict[str, Any], tz: str) -> times.Span:
    """The span a change of start and/or end gives an event now at ``start``–``end``.

    A new start alone keeps the event's length (the UI's PATCH used to reset it
    to an hour); a new end alone keeps its start (which Google's PATCH could not
    do at all: it read ``changes["start"]`` and raised)."""
    new_start = changes.get("start") or start
    new_end = changes.get("end") or None
    if new_end is None and changes.get("start") and start and end:
        s0, e0 = times.parse_when(start, tz), times.parse_when(end, tz)
        s1 = times.parse_when(new_start, tz)
        if isinstance(s0, datetime) == isinstance(s1, datetime) and e0 > s0:  # type: ignore[operator]
            new_end = _iso(s1 + (e0 - s0))  # type: ignore[operator]
    return times.span(new_start, new_end, tz)


def shift_byday(rules: list[str], days: int) -> list[str]:
    """A weekly rule's days moved along with its first day: ``BYDAY=TU,TH`` by one
    day is ``BYDAY=WE,FR``. Anything else is left as it is."""
    out = []
    for rule in rules:
        upper = rule.upper()
        found = re.search(r"BYDAY=([A-Z,]+)", upper)
        if "FREQ=WEEKLY" not in upper or found is None:
            out.append(rule)
            continue
        codes = found.group(1).split(",")
        if not all(c in DAYS for c in codes):
            out.append(rule)
            continue
        moved = ",".join(DAYS[(DAYS.index(c) + days) % 7] for c in codes)
        out.append(upper[: found.start(1)] + moved + upper[found.end(1) :])
    return out


def same_times(start: str, end: str, changes: dict[str, Any], tz: str) -> bool:
    """Whether the start and end a change gives are the ones the event already has."""
    if not changes.get("start") and not changes.get("end"):
        return True
    try:
        new = resolved_span(start, end, changes, tz)
        return (new.start, new.end) == (times.parse_when(start, tz), times.parse_when(end, tz))
    except ValueError:
        return False


def series_changes(
    series_start: str,
    series_end: str,
    series_rules: list[str],
    seen_start: str,
    seen_end: str,
    changes: dict[str, Any],
    tz: str,
) -> dict[str, Any]:
    """A change made to one occurrence, as seen (``seen_*``), made to its series.

    The fields that are not times carry over as they are. A new start or end
    moves the series' own by as many days as the occurrence moved, to the time
    of day the occurrence now has; a weekly rule's days follow the first day,
    unless the change sets its own rule. For a series edited directly, the
    occurrence seen is the series itself.
    """
    out = {k: v for k, v in changes.items() if k not in ("start", "end")}
    if not changes.get("start") and not changes.get("end"):
        return out
    new = resolved_span(seen_start, seen_end, changes, tz)
    s_seen, e_seen = times.parse_when(seen_start, tz), times.parse_when(seen_end, tz)
    if (new.start, new.end) == (s_seen, e_seen):
        # The times as they were: a form sends them whether or not they changed, and
        # an occurrence moved on its own must not drag the series to its new time.
        return out
    s_series, e_series = times.parse_when(series_start, tz), times.parse_when(series_end, tz)

    def moved(series_when: date | datetime, seen_when: date | datetime, new_when: date | datetime):
        day = _day(series_when) + (_day(new_when) - _day(seen_when))
        if isinstance(new_when, datetime):
            return datetime.combine(day, new_when.timetz())
        return day

    start = moved(s_series, s_seen, new.start)
    end = moved(e_series, e_seen, new.end)
    out["start"], out["end"] = _iso(start), _iso(end)
    shift = (_day(start) - _day(s_series)).days
    if shift % 7 and "recurrence" not in changes:
        shifted = shift_byday(series_rules, shift)
        if shifted != series_rules:
            out["recurrence"] = shifted
    return out
