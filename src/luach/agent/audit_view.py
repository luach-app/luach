"""Who reads which audit records, and how much of each.

The chain is the household's tamper-evident record, and it is written whole: every
record's hash covers its full payload. So nothing here changes what is stored; it decides
what each reader is shown, after the chain has been verified as a whole.

- The owner reads the whole chain. A member reads only the records that are theirs: what
  they did, said, asked for, approved, or what was booked with them.
- What someone said (a turn's text, the model's reply to it, the words an event came from)
  is shown only to the members the record belongs to. Not even the owner reads another
  member's chats here: a conversation is private to whoever had it (luach's threads are),
  and the audit trail must not be the way round that.
- A proposal the email scan found in someone's own mail is private to them (pending.py),
  so its title and details are hidden from everyone else, the owner included.
- Addresses keep their local part hidden from anyone but the owner, as before.

The gate's own records (tulip's ``action-admission`` and ``approval-*``) carry no member, so
``stamp`` adds the member and door of the turn they were made in, when they are written.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from luach import db
from luach.agent import context

#: Records tulip's gate writes, which know nothing of luach's members.
GATE_RECORDS = frozenset(
    {"action-admission", "approval-requested", "approval-decision", "approval-edited"}
)

#: The door of a proposal found in a member's own mail (pending.SCAN_DOOR).
SCAN_DOOR = "email-scan"

#: What someone said, or the words a record was made from: for its own members only.
SAID = frozenset({"text", "said", "source_text", "prompt"})

#: What a proposal from someone's own mail is about: for its own members only.
SCAN_PRIVATE = frozenset(
    {
        "asset",
        "title",
        "summary",
        "start",
        "changes",
        "task",
        "requested_arguments",
        "approved_arguments",
        "context",
        "error",
    }
)

HIDDEN = "…"


def stamp(event_type: str, payload: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """The gate's records, with the member and door of the turn they were written in."""
    if event_type not in GATE_RECORDS:
        return payload
    turn = context.maybe_current()
    if turn is None:
        return payload
    out = dict(payload or {})
    out.setdefault("member", turn.user_id)
    out.setdefault("door", turn.door)
    return out


@dataclass
class _Who:
    """The lookups a record's members are worked out from, read once per request."""

    users: dict[str, int] = field(default_factory=dict)
    threads: dict[str, tuple[int, str]] = field(default_factory=dict)
    pending: dict[str, tuple[int | None, str, str]] = field(default_factory=dict)

    @classmethod
    def load(cls, payloads: Iterable[Mapping[str, Any]]) -> _Who:
        thread_ids: set[str] = set()
        pending_ids: set[str] = set()
        for p in payloads:
            if isinstance(p.get("thread"), str):
                thread_ids.add(p["thread"])
            for key in ("approval_id", "pending"):
                if isinstance(p.get(key), str):
                    pending_ids.add(p[key])
        who = cls()
        with db.session() as s:
            for uid, name in s.execute(select(db.User.id, db.User.username)):
                who.users[name] = uid
            if thread_ids:
                for tid, uid, door in s.execute(
                    select(db.Thread.id, db.Thread.user_id, db.Thread.door).where(
                        db.Thread.id.in_(thread_ids)
                    )
                ):
                    who.threads[tid] = (uid, door)
            if pending_ids:
                for pid, held_by, held_door, args in s.execute(
                    select(
                        db.PendingAction.id,
                        db.PendingAction.user_id,
                        db.PendingAction.door,
                        db.PendingAction.args_json,
                    ).where(db.PendingAction.id.in_(pending_ids))
                ):
                    title = str(db.loads(args, {}).get("title") or "")
                    who.pending[pid] = (held_by, held_door, title)
        return who

    def _member(self, value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            if value.isdigit():
                return int(value)
            return self.users.get(value.strip().lower())
        return None

    def members(self, p: Mapping[str, Any]) -> set[int]:
        """Whose record this is: who did it, whose turn or thread, whose proposal, whose
        booking. Empty when it is nobody's in particular (the owner's to read)."""
        found: set[int | None] = {
            self._member(p.get("member")),
            self._member(p.get("host")),
            # A booking's "by" is the guest, or the words "host"/"guest": its member is "host".
            None if "host" in p else self._member(p.get("by")),
            self._member(p.get("principal")),
            self._member(p.get("decided_by")),
        }
        thread = self.threads.get(str(p.get("thread") or ""))
        if thread:
            found.add(thread[0])
        for key in ("approval_id", "pending"):
            held = self.pending.get(str(p.get(key) or ""))
            if held:
                found.add(held[0])
        return {m for m in found if m is not None}

    def from_mail(self, p: Mapping[str, Any]) -> bool:
        """Whether the record is about a proposal the email scan found."""
        if p.get("door") == SCAN_DOOR:
            return True
        thread = self.threads.get(str(p.get("thread") or ""))
        if thread and thread[1] == SCAN_DOOR:
            return True
        return any(
            self.pending.get(str(p.get(key) or ""), (None, "", ""))[1] == SCAN_DOOR
            for key in ("approval_id", "pending")
        )

    def scan_titles_not_of(self, viewer_id: int) -> set[str]:
        """Titles of other members' email proposals. A gate record written before records
        were stamped names its proposal only by title: those are hidden by title."""
        with db.session() as s:
            rows = s.execute(
                select(db.PendingAction.args_json).where(
                    db.PendingAction.door == SCAN_DOOR,
                    (db.PendingAction.user_id != viewer_id) | db.PendingAction.user_id.is_(None),
                )
            ).scalars()
            return {t for t in (str(db.loads(a, {}).get("title") or "") for a in rows) if t}


def _shown(
    p: Mapping[str, Any],
    members: set[int],
    who: _Who,
    viewer_id: int,
    scan_titles: set[str],
) -> dict[str, Any]:
    if viewer_id in members:
        return dict(p)
    out = {k: (HIDDEN if k in SAID else v) for k, v in p.items()}
    if who.from_mail(p):
        out = {k: (HIDDEN if k in SCAN_PRIVATE else v) for k, v in out.items()}
    elif out.get("asset") in scan_titles:
        out["asset"] = HIDDEN
    return out


def snapshot(viewer_id: int, *, is_owner: bool, limit: int = 200) -> dict[str, Any]:
    """The audit trail as ``viewer_id`` may read it: the newest ``limit`` of their
    records (all records, for the owner), each payload cut to what is theirs to read.

    ``chain_verified`` is about the whole chain, checked on the server before anything
    is left out, so a member's shorter view says as much about tampering as the owner's.
    ``total`` counts the records this viewer may read; ``chain_total`` the whole chain.
    """
    from luach.agent import control

    t = control.trail()
    records = t.records()
    try:
        verified = bool(t.verify())
    except Exception:
        verified = False
    who = _Who.load(r.payload for r in records)
    visible = []
    for r in records:
        members = who.members(r.payload)
        if is_owner or viewer_id in members:
            visible.append((r, members))
    scan_titles = who.scan_titles_not_of(viewer_id)
    entries = []
    for r, members in visible[-limit:]:
        payload = _shown(r.payload, members, who, viewer_id, scan_titles)
        entries.append(
            {
                "seq": r.seq,
                "ts": r.ts,
                "event_type": r.event_type,
                "payload": payload if is_owner else control._redact(payload),
                "hash": r.hash,
            }
        )
    return {
        "entries": entries,
        "total": len(visible),
        "chain_total": len(t),
        "chain_verified": verified,
        "head": t.head,
        "scope": "household" if is_owner else "yours",
    }
