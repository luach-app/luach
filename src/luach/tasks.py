"""Tasks: the things the family has to do, each one somebody's.

Two kinds, one table. A *to-do* happens once: it has an optional due day and is
done when someone ticks it. A *chore* repeats on weekdays ("Noa: dishes, Tue
and Thu"): it is never finished, only done for a day, and each day it is done is
a row in ``task_done``.

Anyone in the family may tick a task — that is what the board on the kitchen
wall is for. Deciding what the tasks are is for the grown-ups: the owner, and
any adult in the family. A child ticks; a child does not assign.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from luach import db, family

WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
_NAMED: dict[str, tuple[str, ...]] = {
    "daily": WEEKDAYS,
    "every day": WEEKDAYS,
    "weekdays": WEEKDAYS[:5],
    "weekends": WEEKDAYS[5:],
}
#: How a person may write a weekday, in the household's three languages (the UI
#: passes codes; the model may pass the person's own words).
_DAY_NAMES = {
    "mo": "MO", "mon": "MO", "monday": "MO", "lun": "MO", "lunes": "MO",
    "tu": "TU", "tue": "TU", "tues": "TU", "tuesday": "TU", "mar": "TU", "martes": "TU",
    "we": "WE", "wed": "WE", "wednesday": "WE", "mie": "WE", "miercoles": "WE", "miércoles": "WE",
    "th": "TH", "thu": "TH", "thur": "TH", "thurs": "TH", "thursday": "TH", "jue": "TH",
    "jueves": "TH",
    "fr": "FR", "fri": "FR", "friday": "FR", "vie": "FR", "viernes": "FR",
    "sa": "SA", "sat": "SA", "saturday": "SA", "sab": "SA", "sabado": "SA", "sábado": "SA",
    "su": "SU", "sun": "SU", "sunday": "SU", "dom": "SU", "domingo": "SU",
    "ראשון": "SU", "שני": "MO", "שלישי": "TU", "רביעי": "WE", "חמישי": "TH", "שישי": "FR",
    "שבת": "SA",
}  # fmt: skip
#: Words around a Hebrew weekday that are not one: "יום שלישי", "בימי שני".
_HE_FILLER = {"יום", "ימי", "בימי", "ביום", "כל"}
MAX_TITLE = 200
MAX_OPEN = 500


class NotAllowed(PermissionError):
    """A child tried to decide what the tasks are."""


@dataclass(frozen=True)
class Task:
    id: int
    title: str
    person: str
    due: str
    days: tuple[str, ...]
    notes: str
    done: bool
    overdue: bool = False

    @property
    def chore(self) -> bool:
        return bool(self.days)

    def as_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "days": list(self.days), "chore": self.chore}


def parse_days(spec: str) -> tuple[str, ...]:
    """'' → a one-off; 'daily', 'weekdays', 'mon,thu', 'MO,TH' → those weekdays."""
    spec = spec.strip().lower()
    if not spec or spec in {"none", "once", "-"}:
        return ()
    if spec in _NAMED:
        return _NAMED[spec]
    if spec in {"כל יום", "כל הימים", "todos los dias", "todos los días", "diario"}:
        return WEEKDAYS
    out: list[str] = []
    for part in spec.replace(";", ",").replace(" and ", ",").replace(" ", ",").split(","):
        part = part.strip().rstrip(".")
        if not part or part in _HE_FILLER or part in {"y", "and", "ו"}:
            continue
        code = _DAY_NAMES.get(part)
        if code is None and part.startswith("ו"):  # "ושלישי": and Tuesday
            code = _DAY_NAMES.get(part[1:])
        if code is None:
            raise ValueError(
                f"{part!r} is not a weekday; say e.g. 'mon,thu', 'weekdays' or 'daily'"
            )
        if code not in out:
            out.append(code)
    return tuple(sorted(out, key=WEEKDAYS.index))


#: Days a person names in passing ("by Friday", "para el lunes", "עד יום שלישי").
#: Full names only: "mar", "sun" and "sat" are also just words.
_FULL_DAYS = {
    "monday": "MO", "tuesday": "TU", "wednesday": "WE", "thursday": "TH", "friday": "FR",
    "saturday": "SA", "sunday": "SU", "lunes": "MO", "martes": "TU", "miercoles": "WE",
    "miércoles": "WE", "jueves": "TH", "viernes": "FR", "sabado": "SA", "sábado": "SA",
    "domingo": "SU",
}  # fmt: skip
#: Hebrew weekday names are also ordinals ("שני" is "second"), so only after these.
_HE_DAY_LEAD = {"יום", "ביום", "עד", "ליום"}
_HE_DAYS = {k: v for k, v in _DAY_NAMES.items() if not k.isascii()}
_RELATIVE = {"today": 0, "hoy": 0, "היום": 0, "tomorrow": 1, "mañana": 1, "manana": 1, "מחר": 1}


def due_in_words(text: str, today: str) -> str:
    """The one day a person's own words give a to-do, or "".

    The model leaves `due` out for "by Friday" far more often than it fills it
    in — 6 turns in 9 saved no day while the answer said "due
    Friday". What the person said is the fact; this reads it. More than one day
    named, or none, and it says nothing rather than guess.
    """
    start = date.fromisoformat(today)
    words = re.findall(r"[^\W\d_]+", text.lower())
    found: set[str] = set()
    for i, w in enumerate(words):
        if w in _RELATIVE:
            found.add((start + timedelta(days=_RELATIVE[w])).isoformat())
        code = _FULL_DAYS.get(w) or (
            _HE_DAYS.get(w) if i and words[i - 1] in _HE_DAY_LEAD else None
        )
        if code:
            ahead = (WEEKDAYS.index(code) - start.weekday()) % 7
            found.add((start + timedelta(days=ahead)).isoformat())
    return found.pop() if len(found) == 1 else ""


def _day(value: str) -> str:
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError as exc:
        raise ValueError("a day is YYYY-MM-DD") from exc


def may_assign(user_id: int | None) -> bool:
    """The owner, or an adult of the family. Not a child, and not the board."""
    if user_id is None:
        return False
    if user_id == db.owner_id():
        return True
    person = family.of_user(user_id)
    return person is None or person.kind != "kid"


def _check(user_id: int | None) -> None:
    if not may_assign(user_id):
        raise NotAllowed("only a grown-up in the family decides the tasks; a child can tick them")


def _person(key: str) -> str:
    key = (key or "").strip()
    if key and family.get(key) is None:
        raise ValueError("that is not someone in the family")
    return key


def _view(row: db.Task, day: str, done_days: set[str]) -> Task:
    days = tuple(d for d in row.days.split(",") if d)
    if days:
        done = day in done_days
        overdue = False
    else:
        done = row.done_at is not None
        overdue = not done and bool(row.due) and row.due < day
    return Task(
        id=row.id,
        title=row.title,
        person=row.person,
        due=row.due,
        days=days,
        notes=row.notes,
        done=done,
        overdue=overdue,
    )


def _done_days(s: Any, ids: list[int], day: str) -> dict[int, set[str]]:
    out: dict[int, set[str]] = {i: set() for i in ids}
    if ids:
        for task_id, d in s.execute(
            select(db.TaskDone.task_id, db.TaskDone.day).where(
                db.TaskDone.task_id.in_(ids), db.TaskDone.day == day
            )
        ):
            out[task_id].add(d)
    return out


def for_day(day: str, person: str = "") -> list[Task]:
    """What is on a day: the chores that fall on it, and every to-do still open
    by then (undated, due that day, or overdue), plus those ticked that day so
    a finished list still shows what was finished."""
    day = _day(day)
    weekday = WEEKDAYS[date.fromisoformat(day).weekday()]
    with db.session() as s:
        q = select(db.Task).order_by(db.Task.position, db.Task.id)
        if person:
            # Someone who is not in the family is a mistake, as it is when
            # adding a task for them — not an empty list.
            q = q.where(db.Task.person == _person(person))
        rows = [
            r
            for r in s.execute(q).scalars()
            if (
                weekday in r.days.split(",")
                if r.days
                else (
                    (r.done_at is None and (not r.due or r.due <= day))
                    or (r.done_at is not None and r.done_on == day)
                )
            )
        ]
        done = _done_days(s, [r.id for r in rows if r.days], day)
        return [_view(r, day, done.get(r.id, set())) for r in rows]


def every(today: str) -> list[Task]:
    """All of them, for the grown-ups' list: open to-dos, future ones, chores."""
    today = _day(today)
    with db.session() as s:
        rows = list(
            s.execute(
                select(db.Task)
                .where(db.Task.done_at.is_(None))
                .order_by(db.Task.position, db.Task.id)
            ).scalars()
        )
        done = _done_days(s, [r.id for r in rows if r.days], today)
        return [_view(r, today, done.get(r.id, set())) for r in rows]


def get(task_id: int, day: str) -> Task | None:
    with db.session() as s:
        row = s.get(db.Task, task_id)
        if row is None:
            return None
        return _view(row, _day(day), _done_days(s, [row.id], _day(day)).get(row.id, set()))


def add(
    title: str,
    *,
    by: int | None,
    person: str = "",
    due: str = "",
    days: str | tuple[str, ...] = "",
    notes: str = "",
    today: str = "",
) -> Task:
    _check(by)
    title = title.strip()
    if not title or len(title) > MAX_TITLE:
        raise ValueError(f"a task is 1–{MAX_TITLE} characters")
    weekdays = parse_days(days) if isinstance(days, str) else tuple(days)
    if any(d not in WEEKDAYS for d in weekdays):
        raise ValueError("days are MO, TU, WE, TH, FR, SA, SU")
    with db.session() as s:
        if len(s.execute(select(db.Task.id).where(db.Task.done_at.is_(None))).all()) >= MAX_OPEN:
            raise ValueError(f"there are already {MAX_OPEN} open tasks; finish some first")
        row = db.Task(
            title=title,
            person=_person(person),
            due=_day(due) if due else "",
            days=",".join(weekdays),
            notes=notes.strip()[:2000],
            created_by=by,
        )
        s.add(row)
        s.flush()
        task_id = row.id
    t = get(task_id, today or date.today().isoformat())
    assert t is not None
    return t


def update(task_id: int, *, by: int | None, today: str, **fields: Any) -> Task:
    _check(by)
    with db.session() as s:
        row = s.get(db.Task, task_id)
        if row is None:
            raise KeyError(task_id)
        if "title" in fields:
            title = str(fields["title"]).strip()
            if not title or len(title) > MAX_TITLE:
                raise ValueError(f"a task is 1–{MAX_TITLE} characters")
            row.title = title
        if "person" in fields:
            row.person = _person(str(fields["person"] or ""))
        if "due" in fields:
            row.due = _day(str(fields["due"])) if fields["due"] else ""
        if "days" in fields:
            spec = fields["days"]
            row.days = ",".join(
                parse_days(spec) if isinstance(spec, str) else parse_days(",".join(spec or []))
            )
        if "notes" in fields:
            row.notes = str(fields["notes"] or "").strip()[:2000]
    t = get(task_id, today)
    assert t is not None
    return t


def remove(task_id: int, *, by: int | None) -> None:
    _check(by)
    with db.session() as s:
        row = s.get(db.Task, task_id)
        if row is None:
            raise KeyError(task_id)
        s.delete(row)


def tick(task_id: int, day: str, *, done: bool = True, by: str = "") -> Task:
    """Mark a task done — or not — for a day. Anyone may: it is a tick, not a decision."""
    day = _day(day)
    with db.session() as s:
        row = s.get(db.Task, task_id)
        if row is None:
            raise KeyError(task_id)
        if row.days:
            existing = s.get(db.TaskDone, (task_id, day))
            if done and existing is None:
                s.add(db.TaskDone(task_id=task_id, day=day, by=by[:64]))
            elif not done and existing is not None:
                s.delete(existing)
        else:
            row.done_at = db.utcnow() if done else None
            row.done_on = day if done else ""
            row.done_by = by[:64] if done else ""
    t = get(task_id, day)
    assert t is not None
    return t
