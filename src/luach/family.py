"""The family: the people events and tasks belong to.

A person is not an account. Noa and Sam are children; they may or may not
sign in, and the calendar still has to say which of Tuesday's things are
theirs. A person may be linked to the account they sign in with, found by the
address both share, but nothing here depends on it.

An event's person is its *leader* — the one it is for. It rides on the Google
event itself (``extendedProperties.shared.luach_leader`` plus that person's
``colorId``), so the family calendar in Google shows the same colours luach
does, and the leader is invited, so it lands in their own calendar too.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select

from luach import db

#: Google Calendar's own event colours, by colorId. A person's colour is one of
#: these because Google cannot show any other on an event.
COLORS: dict[str, tuple[str, str]] = {
    "1": ("Lavender", "#7986cb"),
    "2": ("Sage", "#33b679"),
    "3": ("Grape", "#8e24aa"),
    "4": ("Flamingo", "#e67c73"),
    "5": ("Banana", "#f6bf26"),
    "6": ("Tangerine", "#f4511e"),
    "7": ("Peacock", "#039be5"),
    "8": ("Graphite", "#616161"),
    "9": ("Blueberry", "#3f51b5"),
    "10": ("Basil", "#0b8043"),
    "11": ("Tomato", "#d50000"),
}
#: The order new people are handed colours in: distinct from each other first.
_COLOR_ORDER = ("7", "6", "2", "3", "5", "4", "10", "9", "1", "11", "8")
KINDS = ("adult", "kid")
#: The leader of an event someone said is nobody's in particular. Stored rather
#: than left empty so the guess from its invitees does not bring one back.
NOBODY = "-"
MAX_PEOPLE = 20


@dataclass(frozen=True)
class Person:
    key: str
    name: str
    color: str
    kind: str
    email: str
    user_id: int | None
    position: int

    @property
    def hex(self) -> str:
        return COLORS.get(self.color, ("", ""))[1]

    def as_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "hex": self.hex}


def _slug(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:32] or "person"


def _fold(text: str) -> str:
    """Accents off, case off — the letters kept. It used to keep only ASCII, which
    folded every Hebrew name to "": nobody called נועה could be found by name."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _view(row: db.Person, user_email: str = "") -> Person:
    return Person(
        key=row.key,
        name=row.name,
        color=row.color,
        kind=row.kind,
        email=row.email or user_email,
        user_id=row.user_id,
        position=row.position,
    )


def _seed(s: Any) -> None:
    """An empty family starts as the accounts the box already has."""
    users = s.execute(select(db.User).order_by(db.User.id)).scalars().all()
    for i, u in enumerate(users):
        s.add(
            db.Person(
                key=_unique_key(s, u.display_name or u.username),
                name=u.display_name or u.username,
                color=_COLOR_ORDER[i % len(_COLOR_ORDER)],
                kind="adult",
                user_id=u.id,
                position=i,
            )
        )
    s.flush()


def welcome(user_id: int, name: str) -> None:
    """The first account joins the family it finds.

    An empty family starts as the accounts the box has (_seed), but a box whose
    family came from LUACH_FAMILY before anyone signed up was never empty when
    the owner registered — so the owner was nobody in their own family, and
    "for Robin" had no one to mean. Someone of that name is linked; otherwise the
    owner is added.
    """
    roster()  # seed first, so an empty box is not seeded twice
    with db.session() as s:
        if s.execute(select(db.Person.id).where(db.Person.user_id == user_id)).first():
            return
        folded = _fold(name)
        for row in s.execute(select(db.Person).where(db.Person.user_id.is_(None))).scalars():
            if _fold(row.name) == folded:
                row.user_id = user_id
                return
    try:
        p = add(name, kind="adult")
    except ValueError:
        return  # a full family, or a clash: the owner can sort it out in Settings
    with db.session() as s:
        row = s.execute(select(db.Person).where(db.Person.key == p.key)).scalar_one()
        row.user_id = user_id


def _unique_key(s: Any, name: str) -> str:
    base = _slug(name)
    key, n = base, 2
    while s.execute(select(db.Person.id).where(db.Person.key == key)).first():
        key, n = f"{base}-{n}", n + 1
    return key


def _link(s: Any, row: db.Person) -> None:
    """A person with an address and no account yet is linked to the account that
    signs in with it, once there is one."""
    if row.user_id is not None or not row.email:
        return
    email = row.email.lower()
    uid = s.execute(select(db.User.id).where(func.lower(db.User.email) == email)).scalar()
    if uid is None:
        uid = s.execute(
            select(db.UserEmail.user_id).where(
                func.lower(db.UserEmail.email) == email, db.UserEmail.verified_at.is_not(None)
            )
        ).scalar()
    if uid is not None:
        row.user_id = uid


def roster() -> list[Person]:
    with db.session() as s:
        # Once only: a family the owner has since emptied stays empty.
        if s.get(db.Setting, "family.seeded") is None:
            if s.execute(select(db.Person.id).limit(1)).first() is None:
                _seed(s)
            s.add(db.Setting(key="family.seeded", value="1"))
            s.flush()
        rows = s.execute(select(db.Person).order_by(db.Person.position, db.Person.id)).scalars()
        out = []
        for row in rows:
            _link(s, row)
            user = s.get(db.User, row.user_id) if row.user_id else None
            out.append(_view(row, user.email if user else ""))
        return out


def get(key: str) -> Person | None:
    return next((p for p in roster() if p.key == key), None)


def find(name: str) -> Person | None:
    """The person someone meant: their key, their name, or the start of it.

    One person only. "Ruby and Lily" starts with "Ruby", and read as her it
    gave a task for both girls to Ruby alone; a phrase that
    names more than one is nobody here, and resolve_many is what reads it.
    """
    want = _fold(name.strip())
    if not want:
        return None
    if len([n for n in _JOIN.split(name.strip()) if n.strip()]) > 1:
        return None
    people = roster()
    for p in people:
        if want in (p.key, _fold(p.name)):
            return p
    hits = [p for p in people if _fold(p.name).startswith(want) or want.startswith(_fold(p.name))]
    return hits[0] if len(hits) == 1 else None


def resolve(name: str) -> Person:
    """Like find, but a name nobody has is an error that lists who there is."""
    p = find(name)
    if p is None:
        if len(_names(name)) > 1:
            raise ValueError(f"{name!r} is more than one person; this takes one")
        names = ", ".join(x.name for x in roster()) or "nobody yet"
        raise ValueError(f"nobody in the family is called {name!r}; the family is: {names}")
    return p


#: Between names: "Noa and Sam", "Noa, Sam", "Noa y Sam", "Noa & Sam".
_JOIN = re.compile(r"\s*(?:,|&|\+|/)\s*|\s+(?:and|y|e)\s+", re.IGNORECASE)


def _names(text: str) -> list[str]:
    parts: list[str] = []
    for chunk in _JOIN.split(text.strip()):
        chunk = chunk.strip()
        if not chunk:
            continue
        # Hebrew joins with a letter: "נועה ודנה" is "Noa" and "Sam".
        words = chunk.split()
        if len(words) > 1 and not _exact(chunk):
            for w in words:
                parts.append(w[1:] if w.startswith("ו") and not _exact(w) and _exact(w[1:]) else w)
        else:
            parts.append(chunk)
    return parts


def _exact(name: str) -> Person | None:
    want = _fold(name.strip())
    return next((p for p in roster() if want in (p.key, _fold(p.name))), None)


def resolve_many(text: str) -> list[Person]:
    """Everyone a phrase names, in order: "Noa and Sam" is both of them.

    One person per event was all there was, so "breakfast for Noa and Sam"
    had nowhere to go but the title, and it showed in neither of their columns
    on the board. A name nobody has is an error that lists
    who there is.
    """
    # Not find() on the whole phrase: it matches the start of a name, and
    # "Noa and Sam" would be Noa alone.
    out: list[Person] = []
    for name in _names(text):
        p = resolve(name)
        if p not in out:
            out.append(p)
    return out


def of_user(user_id: int) -> Person | None:
    return next((p for p in roster() if p.user_id == user_id), None)


def leader_of(
    leader: str, attendees: list[str], people: list[Person] | None = None
) -> Person | None:
    """Whom an event is for, from its marked leader or its one family invitee."""
    found = _leaders(people, leader, attendees)
    return found[0] if found else None


def leader_for(ev: Any, people: list[Person] | None = None) -> Person | None:
    """The first of leaders_for: whom an event is for, when one answer will do."""
    found = leaders_for(ev, people)
    return found[0] if found else None


def leaders_for(ev: Any, people: list[Person] | None = None) -> list[Person]:
    """Whom an event is for, however it was said — in luach or in Google.

    In order: the leader luach marked (or "nobody's", which is final); the
    person whose colour it wears; the person its title names ("Noa: football",
    "Football (Noa)", "Noa's football"); the one family member invited.
    A family made in Google Calendar on a phone needs no luach at all: pick
    Noa's colour, or start the title with "Noa:".
    """
    return _leaders(
        people,
        getattr(ev, "leader", ""),
        list(getattr(ev, "attendees", []) or []),
        color_id=getattr(ev, "color_id", ""),
        title=getattr(ev, "title", ""),
    )


def _named_in(title: str, people: list[Person]) -> list[Person]:
    folded = _fold(title).strip()
    # "Noa and Sam: breakfast" — everyone named before the colon.
    head = re.match(r"^(.+?)\s*[:\-–—]\s*\S", folded)
    if head:
        names = [n.strip() for n in _JOIN.split(head.group(1)) if n.strip()]
        group = [p for n in names for p in people if _fold(p.name) == n]
        if len(names) > 1 and len(group) == len(names):
            return group
    hits = []
    for p in people:
        name = re.escape(_fold(p.name))
        if (
            re.match(rf"^{name}\s*[:\-–—]\s*\S", folded)
            or re.match(rf"^{name}[’']s\s", folded)
            or re.search(rf"\(\s*{name}\s*\)", folded)
        ):
            hits.append(p)
    return hits if len(hits) == 1 else []


def mentioned(text: str) -> list[Person]:
    """Everyone in the family the text names, as a whole word ("Ruby's" counts)."""
    folded = _fold(text)
    return [
        p
        for p in roster()
        if p.name.strip() and re.search(rf"(?<!\w){re.escape(_fold(p.name))}(?!\w)", folded)
    ]


def title_without(title: str, people: list[Person]) -> str:
    """The title with its owner's name taken off the front — "Ruby's soccer practice",
    "Ruby has soccer", "Ruby: soccer" are "Soccer…" once for_whom says it is Ruby's.
    Anything else is left as the person wrote it."""
    for p in people:
        name = re.escape(p.name.strip())
        m = re.match(
            rf"^\s*{name}(?:[’']s\s+|\s+has\s+(?:an?\s+)?|\s*[:\-–—]\s*)(\S.*)$", title, re.I
        )
        if m:
            rest = m.group(1).strip()
            return rest[:1].upper() + rest[1:]
    return title


def _leaders(
    people: list[Person] | None,
    leader: str,
    attendees: list[str],
    *,
    color_id: str = "",
    title: str = "",
) -> list[Person]:
    people = roster() if people is None else people
    if leader == NOBODY:
        return []
    if leader:
        # One key, or several: "noa,sam".
        by_key = {p.key: p for p in people}
        return [by_key[k] for k in leader.split(",") if k in by_key]
    if color_id:
        # Only a colour that is one person's: two sharing it says nothing.
        wearing = [p for p in people if p.color == color_id]
        if len(wearing) == 1:
            return wearing
    if title:
        named = _named_in(title, people)
        if named:
            return named
    # The one family member invited. Not every one: a household that invites
    # a parent to everything would otherwise make everything theirs.
    invited = {a.lower() for a in attendees}
    hits = [p for p in people if p.email and p.email.lower() in invited]
    return hits if len(hits) == 1 else []


Leaders = Person | list[Person] | None


def _as_list(who: Leaders) -> list[Person]:
    return [] if who is None else [who] if isinstance(who, Person) else list(who)


def with_leader(attendees: list[str], who: Leaders) -> list[str]:
    """The leaders are invited: that is how it reaches their own calendars."""
    out = list(attendees)
    for person in _as_list(who):
        if person.email and person.email.lower() not in {a.lower() for a in out}:
            out.append(person.email)
    return out


def stamp(draft: Any, who: Leaders) -> None:
    """Mark a draft as these people's: leaders, colour, and their invitations.
    Google gives an event one colour; with several people it wears the first's,
    and the marked leaders — not the colour — say whose it is."""
    people = _as_list(who)
    draft.leader = ",".join(p.key for p in people)
    draft.color_id = people[0].color if people else ""
    draft.attendees = with_leader(list(draft.attendees), people)


def leading(who: Leaders) -> dict[str, str]:
    """The changes that hand an existing event to these people, or to nobody."""
    people = _as_list(who)
    return {
        "leader": ",".join(p.key for p in people) if people else NOBODY,
        "color_id": people[0].color if people else "",
    }


def describe() -> str:
    """One line for the model: who the family is."""
    return ", ".join(f"{p.name} ({p.kind})" if p.kind == "kid" else p.name for p in roster())


# -- the owner's changes -------------------------------------------------------


def _clean(fields: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "name" in fields:
        if not isinstance(fields["name"], str):
            raise ValueError("a name is text")
        name = fields["name"].strip()
        if not name or len(name) > 64:
            raise ValueError("a name is 1–64 characters")
        out["name"] = name
    if "color" in fields:
        if fields["color"] not in COLORS:
            raise ValueError("color must be one of Google's event colours, 1–11")
        out["color"] = fields["color"]
    if "kind" in fields:
        if fields["kind"] not in KINDS:
            raise ValueError("kind is adult or kid")
        out["kind"] = fields["kind"]
    if "email" in fields:
        email = str(fields["email"] or "").strip().lower()
        if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            raise ValueError("that is not an email address")
        out["email"] = email
    if "position" in fields:
        out["position"] = int(fields["position"])
    return out


def add(name: str, kind: str = "adult", color: str = "", email: str = "") -> Person:
    roster()  # an empty family is seeded first, so the owner is never lost
    fields = _clean(
        {"name": name, "kind": kind, "email": email, **({"color": color} if color else {})}
    )
    with db.session() as s:
        count = s.execute(select(func.count(db.Person.id))).scalar() or 0
        if count >= MAX_PEOPLE:
            raise ValueError(f"a family here has at most {MAX_PEOPLE} people")
        if s.execute(
            select(db.Person.id).where(func.lower(db.Person.name) == fields["name"].lower())
        ).first():
            raise ValueError(f"there is already someone called {fields['name']}")
        if fields.get("color"):
            _colour_free(s, fields["color"])
        used = set(s.execute(select(db.Person.color)).scalars())
        row = db.Person(
            key=_unique_key(s, fields["name"]),
            name=fields["name"],
            color=fields.get("color")
            or next((c for c in _COLOR_ORDER if c not in used), _COLOR_ORDER[count % 11]),
            kind=fields["kind"],
            email=fields["email"],
            position=count,
        )
        s.add(row)
        s.flush()
        _link(s, row)
        key = row.key
    person = get(key)
    assert person is not None
    return person


def _colour_free(s: Any, color: str, key: str = "") -> None:
    """A colour is one person's: in Google, the colour is how an event says whose it is."""
    other = s.execute(
        select(db.Person.name).where(db.Person.color == color, db.Person.key != key)
    ).scalar()
    if other:
        raise ValueError(f"{other} already has {COLORS[color][0]}; pick another colour")


def update(key: str, **fields: Any) -> Person:
    changes = _clean(fields)
    with db.session() as s:
        row = s.execute(select(db.Person).where(db.Person.key == key)).scalar()
        if row is None:
            raise KeyError(key)
        if "color" in changes:
            _colour_free(s, changes["color"], key)
        for k, v in changes.items():
            setattr(row, k, v)
        if "email" in changes:
            row.user_id = None
            _link(s, row)
    person = get(key)
    assert person is not None
    return person


def remove(key: str) -> None:
    with db.session() as s:
        row = s.execute(select(db.Person).where(db.Person.key == key)).scalar()
        if row is None:
            raise KeyError(key)
        s.delete(row)


def ensure(spec: str) -> list[str]:
    """Make sure these people are in the family: ``"Dana; Noa:kid; Sam:kid"``,
    optionally ``Name:kind:email``. Adds whoever is missing by name and never
    changes or removes anyone, so it is safe to run at every start. Returns the
    names it added."""
    have = {_fold(p.name) for p in roster()}
    added = []
    for part in spec.replace(",", ";").split(";"):
        name, _, rest = part.strip().partition(":")
        kind, _, email = rest.partition(":")
        name = name.strip()
        if not name or _fold(name) in have:
            continue
        add(name, kind=(kind.strip() or "adult"), email=email.strip())
        have.add(_fold(name))
        added.append(name)
    return added
