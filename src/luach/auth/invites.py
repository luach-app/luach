"""Invitations: the owner names an email, the invitee picks a password."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update

from luach import db
from luach.auth import sessions, users
from luach.auth.tokens import new_token, token_hash

INVITE_TTL_HOURS = 48


def create_invite(created_by: int, email: str) -> str:
    email = email.strip().lower()
    if not users.EMAIL.match(email):
        raise ValueError("email does not look like an address")
    if users.member_by_email(email):
        raise ValueError("that email is already a member")
    token = new_token()
    now = db.utcnow()
    with db.session() as s:
        s.add(
            db.Invite(
                token_hash=token_hash(token),
                email=email,
                created_by=created_by,
                created_at=now,
                expires_at=now + timedelta(hours=INVITE_TTL_HOURS),
            )
        )
    return token


def peek(token: str) -> dict | None:
    """What an invite link shows before the invitee commits: email + inviter."""
    with db.session() as s:
        row = s.get(db.Invite, token_hash(token))
        if row is None or row.consumed_at is not None or row.expires_at <= db.utcnow():
            return None
        inviter = s.get(db.User, row.created_by)
        return {
            "email": row.email,
            "inviter": (inviter.display_name or inviter.username) if inviter else "",
            "expires_at": db.iso(row.expires_at),
        }


def accept(
    token: str,
    username: str,
    password: str,
    display_name: str = "",
    timezone: str | None = None,
) -> str:
    """Consume the invite, create the account, return a session token. ``timezone`` is the
    one the new member's browser or phone reports; without it they start in the default.

    The invitation is claimed and the account made in one transaction: the claim is a
    conditional UPDATE, so of two accepts of one link at once the second waits on the
    first and then finds it used. It used to be read, then the account made, then marked
    used, and two at once could both get through the read."""
    now = db.utcnow()
    with db.session() as s:
        email = s.execute(
            update(db.Invite)
            .where(
                db.Invite.token_hash == token_hash(token),
                db.Invite.consumed_at.is_(None),
                db.Invite.expires_at > now,
            )
            .values(consumed_at=now)
            .returning(db.Invite.email)
        ).scalar_one_or_none()
        if email is None:
            raise ValueError("this invitation is no longer valid")
        # Fails (and so un-claims the invitation) when the name or address is taken.
        member = users.create_user(
            username, email, password, display_name=display_name, timezone=timezone, within=s
        )
    return sessions.mint_session(member.id)


def open_invites() -> list[dict]:
    with db.session() as s:
        rows = s.execute(
            select(db.Invite).where(db.Invite.consumed_at.is_(None)).order_by(db.Invite.created_at)
        ).scalars()
        now = db.utcnow()
        return [
            {
                "email": r.email,
                "created_at": db.iso(r.created_at),
                "expires_at": db.iso(r.expires_at),
                "expired": r.expires_at <= now,
            }
            for r in rows
        ]


def revoke(email: str) -> int:
    with db.session() as s:
        rows = (
            s.execute(
                select(db.Invite).where(
                    db.Invite.email == email.strip().lower(), db.Invite.consumed_at.is_(None)
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            s.delete(r)
        return len(rows)
