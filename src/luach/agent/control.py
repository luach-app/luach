"""The admission gate — control as structure, not as a sentence in the prompt.

Every write tool the model can reach is wrapped with tulip's ``gate_tool``.
A call is weighed as an ``Action`` whose labels come from the arguments and
the calendar itself, not from the model's opinion of itself:

    past                the start is already behind us
    possible-duplicate  something with the same title sits within a day
    ambiguous           the model could not pin the date or time — unless the
                        person's own words did: a time they said, on a day they
                        named or the first day of a rule they gave
    mutation-existing   changing or deleting an event, or a task, this thread did not create
    bulk                more than one event at once (never allowed)
    outside-the-house   an invitation would go to an address that is not the
                        household's (``household.household_addresses``). An
                        invitation is mail, and text a stranger wrote can ask the
                        model for one; only a tap on the held card sends it — not
                        a "yes" in chat, not the service key's ``approved``

The policy holds the tagged ones for a person. A held call becomes a
``pending_actions`` row; the web UI and the service key both read that list, and a
tap on Approve executes it on a path the model cannot reach. Every
decision — allowed, held, denied, approved, executed — lands on a
hash-chained audit trail that survives restarts.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import uuid
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from tulip.control import ApprovalBridge, AuditRecord, AuditTrail, ControlPolicy, gate_tool
from tulip.security.policy import Action

from luach import db
from luach.agent import audit_view, context
from luach.calendar import times

logger = logging.getLogger(__name__)

HOLD_FOR = frozenset(
    {
        "past",
        "possible-duplicate",
        "ambiguous",
        "mutation-existing",
        "from-your-email",
        "outside-the-house",
    }
)
#: What nothing said in a turn can clear: not the person's "yes" (it approves the
#: held cards it was shown, in the runtime), not the service key's ``approved``.
#: An invitation leaves the house with whatever the event's notes hold, so the
#: card that names who receives it is the only way through.
NEVER_CLEARED = frozenset({"outside-the-house"})
#: What a yes to "shall I add it?" settles, for the first event the turn writes:
#: the model's own doubt about the time, a past start, a look-alike nearby. Not a
#: change to something that exists, not an invitation out, not a second event.
ANSWERED_BY_YES = frozenset({"ambiguous", "past", "possible-duplicate"})
DENY_FOR = frozenset({"bulk", "midnight-unsaid", "already-there", "already-proposed", "incomplete"})

#: An email that really means midnight says so. The scan proposed "Appointment with
#: … MD" at 00:00 from one that did not, and it was approved unread.
_MIDNIGHT = re.compile(r"\b(midnight|medianoche|12:00\s*a\.?m\.?|12\s*a\.?m\.?|00:00)", re.I)

_WORD = re.compile(r"[\w']+", re.UNICODE)


def similar(a: str, b: str) -> bool:
    """Token overlap ≥ 0.6, so 'Dentist' and 'dentist appointment' collide."""
    ta = {w.lower() for w in _WORD.findall(a)}
    tb = {w.lower() for w in _WORD.findall(b)}
    if not ta or not tb:
        return False
    return len(ta & tb) / min(len(ta), len(tb)) >= 0.6


def find_duplicate(title: str, start: datetime | date, turn: context.Turn) -> str | None:
    """The id of an existing event that looks like this one, if any."""
    if isinstance(start, datetime):
        centre = start
    else:
        centre = datetime.combine(start, datetime.min.time(), tzinfo=times.zone(turn.timezone))
    try:
        candidates = turn.calendar.list_events(
            centre - timedelta(days=1), centre + timedelta(days=1)
        )
    except Exception:  # calendar hiccup must not turn into a silent allow
        logger.exception("duplicate check failed")
        return None
    for ev in candidates:
        if similar(ev.title, title) and not _asked_for_another_day(ev, start, turn):
            return ev.id
    return None


#: A message that takes back what came before it: "no, sunday", "actually
#: thursday", "en vez del sábado". A second copy on another day then is the
#: model adding where it should have moved, and stays held.
_CORRECTION = re.compile(
    r"^\W*(no\b|nope|not\b|actually|wait|sorry|oops|rather|en realidad|mejor|perd[oó]n|"
    r"לא\b|בעצם|סליחה)|\b(instead|en vez|en lugar|במקום)\b",
    re.I,
)


def _asked_for_another_day(ev: Any, start: datetime | date, turn: context.Turn) -> bool:
    """A look-alike this conversation made itself, on another day: the person
    asking for a second one, not the same one twice.

    "añade fútbol para Lily el sábado a las 10", then "y también el domingo a la
    misma hora": Sunday's was held as a duplicate of Saturday's, a day away —
    for every model. Kept held: one on the same day (a repeat), one the
    conversation did not make (someone else's, or before it began), and one
    asked for in a correction ("no, sunday" is a move).
    """
    if _CORRECTION.search(turn.text):
        return False
    if ev.id not in turn.created_event_ids and not thread_owns(turn.thread_id, ev.id):
        return False
    tz = times.zone(turn.timezone)
    try:
        theirs = times.parse_when(ev.start, turn.timezone)
    except ValueError:
        return False
    their_day = theirs.astimezone(tz).date() if isinstance(theirs, datetime) else theirs
    our_day = start.astimezone(tz).date() if isinstance(start, datetime) else start
    return their_day != our_day


_DAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
# A clock time as a person types it: 6pm, 6 pm, 18:00, 4:30, 6h, 7.30am.
_CLOCK = re.compile(
    r"(?<![\d:/.-])(\d{1,2})(?:[:.h](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.|h\b)?(?![\d/-])", re.I
)


def _said_times(text: str) -> set[tuple[int, int]]:
    """Every (hour, minute) the text names as a clock time; a bare hour the way the
    prompt tells the model to read it, 7 to 11 the morning and 12 to 6 the afternoon or
    evening. A lone number is only a time with a colon, am/pm or h after it, or "at"
    before it — "2 kids" is not two o'clock."""
    said: set[tuple[int, int]] = set()
    for m in _CLOCK.finditer(text):
        hour, minute, half = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
        before = text[: m.start()].rstrip().lower()
        if not (m.group(2) or half or before.endswith(("at", "@", "a las", "à", "um"))):
            continue
        if hour > 23 or minute > 59:
            continue
        if half.startswith("p") and hour < 12:
            said.add((hour + 12, minute))
        elif half.startswith("a"):
            said.add((hour % 12, minute))
        elif 1 <= hour <= 6:
            said.add((hour + 12, minute))  # read as the prompt reads it: "dinner at 6" is 18:00
        else:
            said.add((hour, minute))
    return said


_WEEKDAYS = {
    **{
        d: i
        for i, d in enumerate(
            ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
        )
    },
    **{
        d: i
        for i, d in enumerate(
            ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
        )
    },
    "miercoles": 2,
    "sabado": 5,
}
_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
    )
}


def _said_days(text: str, today: date) -> set[date]:
    """The days the text names beyond doubt: today, tonight, tomorrow, a weekday (the
    next one, today included), a date with its month. "Next Tuesday" is not one —
    families mean this coming one and the one after about equally."""
    low = text.lower()
    said: set[date] = set()
    if re.search(r"\b(today|tonight|hoy|esta noche)\b", low):
        said.add(today)
    if re.search(r"\btomorrow\b", low):
        said.add(today + timedelta(days=1))
    weekday = "|".join(_WEEKDAYS)
    for m in re.finditer(rf"\b(next\s+|this\s+)?({weekday})s?\b", low):
        if m.group(1) and m.group(1).startswith("next"):
            continue
        said.add(today + timedelta(days=(_WEEKDAYS[m.group(2)] - today.weekday()) % 7))
    month = "|".join(_MONTHS)
    for m in re.finditer(
        rf"\b(?:(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({month})[a-z]*"
        rf"|({month})[a-z]*\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?)\b",
        low,
    ):
        day, mon = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        for year in (today.year, today.year + 1):
            with contextlib.suppress(ValueError):
                when = date(year, _MONTHS[mon[:3]], int(day))
                if when >= today:
                    said.add(when)
                    break
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", low):
        with contextlib.suppress(ValueError):
            said.add(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
    return said


def pinned_by_their_words(
    kwargs: Mapping[str, Any], start: datetime | date, turn: context.Turn
) -> bool:
    """An event the person pinned themselves, though the model called it unsure.

    The model marks certainty="low" whenever it "inferred" the date, and it counts
    working out which day "tomorrow" or "every Thursday" is as inferring. "swimming
    every Thursday at 6pm until October" was held twice for it, and "breakfast for
    Ruby and Lily tomorrow at 7:10am" three times in a row — each read one way only.
    So a call goes through when the time is one the person's own message says, and
    the day is one it names (today, tomorrow, a weekday, a date) or — for a
    repeating event — the first of the rule's days, within the coming week. What they left open ("Saturday afternoon", "sometime next week",
    "next Tuesday") still waits for a yes.
    """
    if not isinstance(start, datetime):
        return False
    local = start.astimezone(times.zone(turn.timezone))
    if (local.hour, local.minute) not in _said_times(turn.text):
        return False
    now = times.now_in(turn.timezone)
    today = now.date()
    said = _said_days(turn.text, today)
    if local.date() in said:
        return True
    # "Thursday at 6pm", said on a Thursday after six, is next Thursday: today's six
    # o'clock has gone. Only then — while today's is still ahead, next week is a guess.
    a_week_on = local - timedelta(days=7)
    if a_week_on.date() == today and today in said and a_week_on <= now:
        return True
    rule = str(kwargs.get("recurrence") or "").upper()
    if "FREQ=DAILY" in rule:
        on_its_day = True
    elif "FREQ=WEEKLY" in rule:
        days = re.search(r"BYDAY=([A-Z,]+)", rule)
        on_its_day = days is not None and _DAYS[local.weekday()] in days.group(1).split(",")
    else:
        return False
    return on_its_day and local - times.now_in(turn.timezone) < timedelta(days=7)


def outsiders(name: str, kwargs: Mapping[str, Any], turn: context.Turn) -> list[str]:
    """Who outside the household this call would send an invitation, or a change to.

    create_event: the addresses the tool would invite (``tools.resolve_attendees``:
    those asked for, else the default invitees, and the member's notify list).
    update_event: everyone already on the event, and any it adds. Google keeps a
    guest's copy in step with ours, so new notes on a stranger's meeting are notes
    the stranger reads. A family member it is handed to is the household's.
    """
    from luach import household

    invited: list[str] = []
    if name == "create_event":
        from luach.agent.tools import resolve_attendees

        invited = resolve_attendees(str(kwargs.get("attendees") or ""), turn.user_id)
    elif name == "update_event":
        try:
            ev = turn.calendar.get_event(str(kwargs.get("event_id") or ""))
        except Exception:
            logger.exception("could not read the event to see who is on it")
            ev = None
        invited = list(ev.attendees) if ev is not None else []
        if kwargs.get("attendees"):
            spec = str(kwargs["attendees"]).replace(";", ",").split(",")
            invited += household.resolve_attendees(spec)
    if not invited:
        return []
    ours = household.household_addresses()
    out: list[str] = []
    for email in invited:
        address = str(email).strip().lower()
        if address and address not in ours and address not in out:
            out.append(address)
    return out


def labels_for(name: str, kwargs: Mapping[str, Any]) -> tuple[set[str], str]:
    """The tags a call earns, and the asset it touches."""
    turn = context.current()
    tags: set[str] = set()
    asset = ""
    if name == "create_event":
        asset = str(kwargs.get("title") or "").strip()
        try:
            sp = times.span(str(kwargs.get("start", "")), kwargs.get("end") or None, turn.timezone)
        except ValueError:
            tags.add("ambiguous")
        else:
            unsure = str(kwargs.get("certainty", "high")).lower() != "high"
            if unsure and not pinned_by_their_words(kwargs, sp.start, turn):
                tags.add("ambiguous")
            if times.is_past(sp.start, turn.timezone):
                tags.add("past")
            if find_duplicate(asset, sp.start, turn):
                tags.add("possible-duplicate")
            if (
                turn.propose_only
                and isinstance(sp.start, datetime)
                and (sp.start.hour, sp.start.minute) == (0, 0)
                and not _MIDNIGHT.search(turn.text)
            ):
                tags.add("midnight-unsaid")
    elif name in {"change_task", "remove_task"}:
        # A task this conversation did not make is someone's — maybe made by hand in the
        # app. "put it on her board" once reassigned a parent's own task, silently, because
        # tasks skipped the gate.
        task_id = str(kwargs.get("task_id") or "")
        asset = f"task:{task_id}"
        made_here = {str(t[0]) for t in turn.tasks_added}
        if task_id not in made_here and not thread_owns(turn.thread_id, asset):
            tags.add("mutation-existing")
    elif name in {"update_event", "delete_event"}:
        asset = str(kwargs.get("event_id") or "")
        if asset not in turn.created_event_ids and not thread_owns(turn.thread_id, asset):
            tags.add("mutation-existing")
        if name == "update_event" and kwargs.get("start"):
            try:
                sp = times.span(str(kwargs["start"]), kwargs.get("end") or None, turn.timezone)
                if times.is_past(sp.start, turn.timezone):
                    tags.add("past")
            except ValueError:
                tags.add("ambiguous")
    if name == "create_event" and turn.yes_to_a_question and not turn.created_event_ids:
        # "Want me to add it?" — "yes". There was no card to approve: the model
        # asked in words, and the event it then writes is the one asked about. Only
        # until one is written, so a second create rides on nothing.
        tags -= ANSWERED_BY_YES
    if name in {"create_event", "update_event"} and outsiders(name, kwargs, turn):
        tags.add("outside-the-house")
    if turn.approved:
        # The caller vouched for this turn (the service key's ``approved``); that
        # outranks the heuristics, never an invitation leaving the house.
        tags &= NEVER_CLEARED
    if turn.propose_only:
        # After the clearing, on purpose: in a turn nobody asked for there is no
        # one whose yes it could be. Approving the proposal is that yes, and it
        # runs on a turn of its own.
        tags.add("from-your-email")
        # Held before the tool runs, a call never meets the tool's own checks: the
        # mail eval put "Add “” — " in Pending twice beside the real proposal, a call
        # with no title and no day. Nobody can approve that.
        if name in {"create_event", "add_task"} and (
            not str(kwargs.get("title") or "").strip()
            or (name == "create_event" and "ambiguous" in tags and not kwargs.get("start"))
        ):
            tags.add("incomplete")
        again = _offered_already(name, kwargs, turn)
        if again:
            tags.add(again)
    return tags, asset


def _day(value: Any, tz: str) -> str:
    """The calendar day a start or a due date falls on, or ""."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        start = times.span(text, None, tz).start
    except ValueError:
        return text[:10]
    if isinstance(start, datetime):
        return start.astimezone(times.zone(tz)).date().isoformat()
    return start.isoformat()


def _offered_already(name: str, kwargs: Mapping[str, Any], turn: context.Turn) -> str:
    """Why a proposal from the email scan would be one the person has already got.

    A reminder of the dentist was proposed as the dentist, though the dentist was
    on the calendar (in the mail eval, 1 run in 3): held as a possible
    duplicate, it still landed in Pending for someone to turn down. In a chat a
    person is there to say "yes, another one"; in a scan nobody is, so it is not
    offered — nor what is already waiting for their yes, nor a task already open.
    """
    if name in {"update_event", "delete_event"}:
        # The same move or the same cancellation, from a second email about it.
        event_id = str(kwargs.get("event_id") or "")
        with db.session() as s:
            waiting = s.execute(
                select(db.PendingAction).where(
                    db.PendingAction.status == "pending",
                    db.PendingAction.door == turn.door,
                    db.PendingAction.user_id == turn.user_id,
                    db.PendingAction.tool == name,
                )
            ).scalars()
            if any(db.loads(r.args_json, {}).get("event_id") == event_id for r in waiting):
                return "already-proposed"
        return ""
    if name not in {"create_event", "add_task"}:
        return ""
    title = str(kwargs.get("title") or "").strip()
    if not title:
        return ""
    when = kwargs.get("start") if name == "create_event" else kwargs.get("due")
    day = _day(when, turn.timezone)
    if name == "create_event":
        try:
            start = times.span(str(when or ""), kwargs.get("end") or None, turn.timezone).start
        except ValueError:
            start = None
        if start is not None and (
            find_duplicate(title, start, turn) or _same_minute_kin(title, start, turn)
        ):
            return "already-there"
    elif _open_task_like(title, str(kwargs.get("for_whom") or ""), turn):
        return "already-there"
    with db.session() as s:
        waiting = s.execute(
            select(db.PendingAction).where(
                db.PendingAction.status == "pending",
                db.PendingAction.door == turn.door,
                db.PendingAction.user_id == turn.user_id,
                db.PendingAction.tool == name,
            )
        ).scalars()
        for row in waiting:
            args = db.loads(row.args_json, {})
            other = args.get("start") if name == "create_event" else args.get("due")
            if _day(other, turn.timezone) == day and similar(str(args.get("title") or ""), title):
                return "already-proposed"
    return ""


def _kin(a: str, b: str) -> bool:
    """Two titles that share a word's stem: "Dental appointment" and "Dentist — Dr.
    Stein" share none of their words and are still the same visit."""
    stems = {w.lower()[:4] for w in _WORD.findall(a) if len(w) >= 4}
    return any(w.lower()[:4] in stems for w in _WORD.findall(b) if len(w) >= 4)


def _same_minute_kin(title: str, start: datetime | date, turn: context.Turn) -> bool:
    """An event that starts at the very same minute under a kindred title.

    The loose title match missed a reminder of "Dentist — Dr. Stein" that the model
    called "Dental appointment" (in the mail eval): no word in common, and
    the same 15:00. The same minute is what makes a stem enough.
    """
    if not isinstance(start, datetime):
        return False
    try:
        nearby = turn.calendar.list_events(
            start - timedelta(minutes=1), start + timedelta(minutes=1)
        )
    except Exception:
        logger.exception("same-minute check failed")
        return False
    for ev in nearby:
        try:
            begins = times.span(ev.start, None, turn.timezone).start
        except ValueError:
            continue
        if isinstance(begins, datetime) and begins == start and _kin(ev.title, title):
            return True
    return False


def _open_task_like(title: str, for_whom: str, turn: context.Turn) -> bool:
    from luach import family, tasks

    try:
        people = {p.key for p in family.resolve_many(for_whom)} if for_whom.strip() else set()
    except ValueError:
        people = set()
    today = times.now_in(turn.timezone).date().isoformat()
    return any(
        not t.done and similar(t.title, title) and (not people or t.person in people)
        for t in tasks.every(today)
    )


def thread_owns(thread_id: str | None, event_id: str) -> bool:
    if not thread_id or not event_id:
        return False
    with db.session() as s:
        row = s.execute(
            select(db.ThreadEvent.id).where(
                db.ThreadEvent.thread_id == thread_id, db.ThreadEvent.event_id == event_id
            )
        ).first()
        return row is not None


def remember_created(thread_id: str | None, event_id: str) -> None:
    if not thread_id:
        return
    with db.session() as s:
        s.add(db.ThreadEvent(thread_id=thread_id, event_id=event_id))


def action_for(name: str, kwargs: Mapping[str, Any]) -> Action:
    tags, asset = labels_for(name, kwargs)
    return Action(
        name=name,
        asset=asset,
        blast_radius=1,
        environment="household",
        kind="mutate" if name != "create_event" else "create",
        tags=frozenset(tags),
    )


POLICY = ControlPolicy(
    require_verification_score=0.0,
    max_blast_radius=1,
    require_human_for=HOLD_FOR,
    deny_for=DENY_FOR,
)


# --- the durable trail ------------------------------------------------------


class PersistentTrail(AuditTrail):
    """tulip's hash chain, with every record also written to SQLite."""

    def record(self, event_type: str, payload: Mapping[str, Any] | None = None) -> AuditRecord:
        # The gate's records say whose turn they came from, so the audit view can show
        # each member theirs (audit_view.stamp; it reads the turn, changes nothing else).
        payload = audit_view.stamp(event_type, payload)
        try:
            return self._persist(event_type, payload)
        except IntegrityError:
            # Someone else advanced the chain: a one-off script against the same
            # file, or a second worker. Our tail is stale, so take theirs and
            # chain onto it rather than dropping the record on the floor. Without
            # this, every turn after the first clash went unrecorded while the
            # app carried on as if written.
            logger.warning("audit: chain moved under us, reloading and retrying")
            self._records = list(self.load()._records)
            try:
                return self._persist(event_type, payload)
            except Exception:
                logger.exception("audit: could not persist %s even after reload", event_type)
                return self._records[-1]

    def _persist(self, event_type: str, payload: Mapping[str, Any] | None) -> AuditRecord:
        rec = super().record(event_type, payload)
        with db.session() as s:
            s.add(
                db.AuditRow(
                    seq=rec.seq,
                    ts=rec.ts,
                    event_type=rec.event_type,
                    payload_json=db.dumps(rec.payload),
                    prev_hash=rec.prev_hash,
                    hash=rec.hash,
                )
            )
        return rec

    @classmethod
    def load(cls) -> PersistentTrail:
        trail = cls()
        with db.session() as s:
            rows = s.execute(select(db.AuditRow).order_by(db.AuditRow.seq)).scalars().all()
        trail._records = [
            AuditRecord(
                seq=r.seq,
                ts=r.ts,
                event_type=r.event_type,
                payload=db.loads(r.payload_json, {}),
                prev_hash=r.prev_hash,
                hash=r.hash,
            )
            for r in rows
        ]
        return trail


_trail: PersistentTrail | None = None


def trail() -> PersistentTrail:
    global _trail
    if _trail is None:
        _trail = PersistentTrail.load()
    return _trail


def reset_trail() -> None:
    global _trail
    _trail = None


_ADDRESS = re.compile(r"[^@\s\"\'<>]+@[^@\s\"\'<>]+\.[^@\s\"\'<>]+")


def _redact(value: Any) -> Any:
    """Hide the local part of every address: the household can read what
    happened without reading a visitor's inbox out of the record."""
    if isinstance(value, str):
        return _ADDRESS.sub(lambda m: "…@" + m.group(0).split("@", 1)[1], value)
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()}
    return value


def audit_snapshot(limit: int = 200, *, redact: bool = False) -> dict[str, Any]:
    t = trail()
    records = t.records()[-limit:]
    try:
        verified = bool(t.verify())
    except Exception:
        verified = False
    return {
        "entries": [
            {
                "seq": r.seq,
                "ts": r.ts,
                "event_type": r.event_type,
                "payload": _redact(r.payload) if redact else r.payload,
                "hash": r.hash,
            }
            for r in records
        ],
        "total": len(t),
        "chain_verified": verified,
        "head": t.head,
    }


# --- the approval bridge ----------------------------------------------------


def _event_named(event_id: str) -> Any:
    """The event a held change is about, for its name; None when it cannot be read."""
    if not event_id:
        return None
    try:
        return context.current().calendar.get_event(event_id)
    except Exception:
        return None


def _when_of(ev: Any, tz: str) -> str:
    try:
        sp = times.span(ev.start, ev.end or None, tz)
        return times.describe(sp.start, sp.end, tz)
    except Exception:
        return ""


def _said_changes(changes: Mapping[str, Any], tz: str) -> str:
    """What a change does, in words: never a dict, never an event id. Held changes
    read "{'start': '2026-10-16T09:00', …}" on the approval card."""
    said: list[str] = []
    if changes.get("start"):
        try:
            sp = times.span(str(changes["start"]), changes.get("end") or None, tz)
            said.append(f"move it to {times.describe(sp.start, sp.end, tz)}")
        except ValueError:
            said.append("move it")
    elif changes.get("end"):
        said.append("change when it ends")
    if changes.get("due"):
        said.append(f"due {changes['due']}")
    if changes.get("title"):
        said.append(f"call it “{changes['title']}”")
    if changes.get("location"):
        said.append(f"at {changes['location']}")
    if "description" in changes:
        said.append("change its notes")
    if changes.get("attendees"):
        said.append(f"invite {changes['attendees']}")
    if changes.get("for_whom"):
        said.append(f"for {changes['for_whom']}")
    if changes.get("repeats") or changes.get("recurrence"):
        said.append("change how it repeats")
    return " · ".join(said) or "small changes"


def describe_call(tool: str, args: Mapping[str, Any], tz: str) -> str:
    """One human line for a held call, shown in the UI and on WhatsApp."""
    if tool == "create_event":
        try:
            sp = times.span(str(args.get("start", "")), args.get("end") or None, tz)
            when = times.describe(sp.start, sp.end, tz)
        except ValueError:
            when = str(args.get("start", "?"))
        where = f" @ {args['location']}" if args.get("location") else ""
        extra = ""
        if args.get("calendar"):
            extra += f" · on {args['calendar']}"
        if args.get("attendees"):
            extra += f" · invite {args['attendees']}"
        if args.get("for_whom"):
            extra += f" · for {args['for_whom']}"
        return f"Add “{args.get('title', '?')}” — {when}{where}{extra}{_sent_out(tool, args)}"
    if tool == "add_task":
        extra = ""
        if args.get("for_whom"):
            extra += f" · for {args['for_whom']}"
        due = str(args.get("due") or "").strip()
        if due:
            try:
                extra += f" · by {date.fromisoformat(due).strftime('%a %-d %b')}"
            except ValueError:
                extra += f" · by {due}"
        if args.get("repeats"):
            extra += f" · every {args['repeats']}"
        return f"Add the task “{args.get('title', '?')}”{extra}"
    if tool in {"change_task", "remove_task"}:
        from luach import tasks

        found = tasks.get(int(args.get("task_id") or 0), times.now_in(tz).date().isoformat())
        name = f"“{found.title}”" if found else "a task"
        if tool == "remove_task":
            return f"Remove the task {name}"
        changes = {k: v for k, v in args.items() if k != "task_id" and v not in ("", None)}
        if set(changes) == {"for_whom"}:
            return f"Give {name} to {changes['for_whom']}"
        return f"Change the task {name}: {_said_changes(changes, tz)}"
    if tool in {"update_event", "delete_event"}:
        ev = _event_named(str(args.get("event_id") or ""))
        name = f"“{ev.title}”" if ev and ev.title else "an event"
        if tool == "delete_event":
            when = f" — {_when_of(ev, tz)}" if ev else ""
            return f"Delete {name}{when}"
        changes = {k: v for k, v in args.items() if k != "event_id" and v not in ("", None)}
        return f"Change {name}: {_said_changes(changes, tz)}{_sent_out(tool, args)}"
    return f"{tool} {dict(args)}"


def _sent_out(tool: str, args: Mapping[str, Any]) -> str:
    """Who outside the household the card would send something to, by address: the
    card is the one place a person sees it before it goes, so it says so plainly."""
    turn = context.maybe_current()
    if turn is None:
        return ""
    away = outsiders(tool, args, turn)
    if not away:
        return ""
    what = "an invitation" if tool == "create_event" else "the change"
    return f" · sends {what} outside the household to {', '.join(away)}"


class PendingBridge:
    """Held calls become rows a person can approve on a channel the model cannot reach."""

    def submit(self, principal: str, tool: str, args: Mapping[str, Any]) -> str:
        turn = context.current()
        pending_id = uuid.uuid4().hex
        summary = describe_call(tool, args, turn.timezone)
        tags, _ = labels_for(tool, args)
        with db.session() as s:
            s.add(
                db.PendingAction(
                    id=pending_id,
                    user_id=turn.user_id,
                    principal=principal,
                    door=turn.door,
                    thread_id=turn.thread_id,
                    tool=tool,
                    args_json=db.dumps(dict(args)),
                    summary=summary,
                    reason=", ".join(sorted(tags)),
                    status="pending",
                    source_json=db.dumps(turn.source) if turn.source else "",
                )
            )
        turn.held.append(
            {"id": pending_id, "tool": tool, "summary": summary, "reason": sorted(tags)}
        )
        return pending_id

    def state(self, approval_id: str) -> str | None:
        with db.session() as s:
            row = s.get(db.PendingAction, approval_id)
            return row.status if row else None


BRIDGE: ApprovalBridge = PendingBridge()


def refusal_reason(decision: Any) -> str:
    tags = sorted(decision.action.tags)
    if decision.outcome == "deny":
        if "incomplete" in tags:
            return (
                "Not proposed: it needs a title, and an event needs its day. Propose it "
                "again with both, or leave it if the email does not give them."
            )
        if "already-there" in tags:
            return (
                "Not proposed: it is already on their calendar or their list. Nothing to "
                "add for it."
            )
        if "already-proposed" in tags:
            return "Not proposed again: it is already waiting for their yes."
        if "midnight-unsaid" in tags:
            return (
                "Not proposed: the email does not say midnight. Use the time it states; "
                "if it gives no time, make it an all-day event on that date."
            )
        return "That is not allowed: one event per call, never in bulk."
    if "from-your-email" in tags:
        # Every call a scan makes is held, and the words for a chat — tell them what is
        # waiting, do not retry — read as "stop": an email with a party and the RSVP
        # before it came back with the party alone, 1 time in 3 in the mail eval.
        return (
            "Proposed: it waits for their yes. If the email holds anything else to "
            "propose — another date, something to do before it — propose that now; "
            "otherwise you are done."
        )
    why = {
        "past": "the start time is already in the past",
        "possible-duplicate": "a similar event already exists around that time",
        "ambiguous": "the date or time is not certain",
        "mutation-existing": "it changes something this conversation did not create",
        "from-your-email": "it was found in an email, and the person decides what goes on",
        "outside-the-house": (
            "it would send an invitation to someone outside the household, and only the "
            "person's tap on its card sends that"
        ),
    }
    reasons = "; ".join(why.get(t, t) for t in tags) or "policy"
    return (
        f"Held for the person's approval because {reasons}. An approval card is shown to them. "
        "Tell them exactly what is waiting and what you need from them; do not retry."
    )


def gated(tool: Any, principal: str = "luach-agent") -> Any:
    wrapped = gate_tool(
        tool,
        policy=POLICY,
        action=action_for,
        trail=trail(),
        approval=BRIDGE,
        principal=principal,
        refusal_reason=refusal_reason,
    )
    gate = wrapped.fn

    async def off_the_loop(**kwargs: Any) -> Any:
        # The gate weighs a write before it runs it, and weighing it reads the
        # calendar: find_duplicate is a Google call, made by tulip's gate on the
        # event loop, where every other member's request waited on it (the tools
        # themselves already run off the loop; this is the read the gate makes).
        # The gate holds nothing tied to a loop, so it runs whole in a thread, on
        # a loop of its own, with the turn's context.
        return await asyncio.to_thread(asyncio.run, gate(**kwargs))

    return wrapped.model_copy(update={"fn": off_the_loop})
